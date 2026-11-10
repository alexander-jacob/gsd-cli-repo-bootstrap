"""Read installed GSD resolution against a disposable configuration snapshot."""
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path

from . import config
from .versions import check_installation, format_result

QUERY_TIMEOUT = 20
OUTPUT_LIMIT = 4 * 1024 * 1024


def snapshot_configs(root: Path, data: dict, env: dict) -> dict[str, dict]:
    if env.get('GSD_PROJECT', '').strip():
        raise config.ConfigError('GSD_PROJECT context is not supported by this preview; resolution unavailable')
    snapshots = {'.planning/config.json': data}
    workstream = env.get('GSD_WORKSTREAM', '').strip()
    if workstream:
        if re.search(r'[/\\]|\.\.', workstream) or workstream == '.':
            raise config.ConfigError('GSD_WORKSTREAM contains invalid path characters')
        relative = f'.planning/workstreams/{workstream}/config.json'
        source = root / relative
        if source.resolve() != source.absolute():
            raise config.ConfigError('Workstream configuration uses a symlink; resolution unavailable')
        if source.exists():
            def stamp():
                st = source.stat()
                return st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns
            before = stamp()
            snapshots[relative] = config.read_json(source)
            if stamp() != before:
                raise config.ConfigError('Workstream configuration changed while reading; retry')
    for data in snapshots.values():
        if data.get('multiRepo') is True:
            raise config.ConfigError('Legacy multiRepo requires filesystem discovery; migrate it before previewing')
    return snapshots


def query_environment(root: Path, runtime: str) -> dict:
    env = dict(os.environ, GSD_RUNTIME=runtime)
    # Preserve identity/home semantics after changing cwd to the scratch project.
    for key in ('CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'GSD_HOME', 'GSD_AGENTS_DIR', 'HOME'):
        if env.get(key):
            path = Path(env[key]).expanduser()
            env[key] = str(path if path.is_absolute() else root / path)
    return env


def validate_result(value) -> bool:
    if not isinstance(value, dict):
        return False
    strings = ('model', 'profile', 'effort', 'effort_effective', 'effort_effective_source')
    if any(not isinstance(value.get(key), str) for key in strings):
        return False
    # GSD deliberately emits null when no per-agent effort parameter/channel
    # applies (for example inherit). Absence or other types remain malformed.
    for key in ('effort_propagation', 'effort_param', 'effort_rendered'):
        if key not in value or (value[key] is not None and not isinstance(value[key], str)):
            return False
    if value['effort_effective_source'] not in ('resolved', 'frontmatter', 'frontmatter-absent'):
        return False
    return (isinstance(value.get('effort_clamped'), bool)
            and 'effort_rendered' in value and 'effort_param' in value
            and isinstance(value.get('fast_mode'), bool)
            and isinstance(value.get('fast_mode_supported'), bool))


def inspect(root: Path, data: dict, runtime: str, minimum: str) -> dict:
    version = check_installation(root, runtime, minimum)
    result = {'installation': {**asdict(version), 'directory': str(version.directory)},
              'catalog': {}, 'context': {}, 'agents': {}, 'diagnostics': [], 'complete': False}
    diagnostics = result['diagnostics']
    if not version.ok:
        diagnostics.append(format_result(version))
        return result
    node = shutil.which('node')
    if not node:
        diagnostics.append('Node is unavailable; install Node to query the installed GSD resolver')
        return result
    try:
        manifest = config.read_json(version.directory / 'bin/shared/model-catalog.json')
        catalog = manifest.get('agents')
        if not isinstance(catalog, dict) or not catalog or any(
                not isinstance(k, str) or not k or not isinstance(v, dict) for k, v in catalog.items()):
            raise config.ConfigError('Installed GSD agent catalog is unavailable or malformed')
        result['catalog'] = catalog
        # GSD model-catalog.cjs derives MODEL_ALIAS_MAP from these same entries.
        runtime_tiers = manifest.get('runtimeTierDefaults', {})
        if not isinstance(runtime_tiers, dict) or not isinstance(runtime_tiers.get('claude', {}), dict):
            raise config.ConfigError('Installed GSD catalog runtime tier metadata is malformed')
        tiers = runtime_tiers.get('claude', {})
        result['aliases'] = {tier: entry['model'] for tier, entry in tiers.items()
                             if isinstance(entry, dict) and isinstance(entry.get('model'), str)}
        env = query_environment(root, runtime)
        result['workstream'] = env.get('GSD_WORKSTREAM', '').strip()
        snapshots = snapshot_configs(root, data, env)
        # This bridge deliberately never invokes gsd-tools.cjs: its bootstrap
        # can build/repair the installed library, even for a query command.
        bridge = files('gsd_cli').joinpath('data/preview-resolver.cjs').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory(prefix='gsd-cli-preview-') as temp:
            scratch = Path(temp)
            for relative, snapshot in snapshots.items():
                path = scratch / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(config.serialize(snapshot), encoding='utf-8')
            # GSD io's large-output spill/reaping, if needed, is private too.
            env.update(TMPDIR=temp, TMP=temp, TEMP=temp)
            query = {'installation': str(version.directory), 'runtime': runtime,
                     'agents': sorted(catalog)}
            completed = subprocess.run([node, '-e', bridge], input=json.dumps(query), cwd=scratch,
                                       env=env, text=True, capture_output=True, timeout=QUERY_TIMEOUT)
        if completed.stderr.strip():
            diagnostics.extend(completed.stderr.strip().splitlines())
        if completed.returncode:
            raise config.ConfigError(f'GSD resolver exited {completed.returncode}')
        if len(completed.stdout) > OUTPUT_LIMIT:
            raise config.ConfigError('GSD resolver output exceeds the preview limit')
        payload = json.loads(completed.stdout)
        if not isinstance(payload, dict) or not isinstance(payload.get('context'), dict) or not isinstance(payload.get('rows'), list):
            raise config.ConfigError('Malformed GSD resolver response')
        context = payload['context']
        if not isinstance(context.get('config'), dict) or not isinstance(context.get('source'), str):
            raise config.ConfigError('Malformed GSD configuration context')
        result['context'] = context
        errors = bool(context.get('degraded'))
        if errors:
            diagnostics.append('GSD configuration loading is degraded: ' + str(context.get('reason', 'unknown')))
        expected = set(catalog)
        for settings in (*snapshots.values(), context['config']):
            overrides = settings.get('model_overrides', {})
            effort = settings.get('effort') or {}
            if isinstance(overrides, dict):
                expected.update(overrides)
            if isinstance(effort, dict) and isinstance(effort.get('agent_overrides'), dict):
                expected.update(effort['agent_overrides'])
        seen = set()
        for row in payload['rows']:
            if not isinstance(row, dict) or not isinstance(row.get('agent'), str) or row['agent'] in seen:
                raise config.ConfigError('Malformed or duplicate GSD resolver row')
            agent = row['agent']
            seen.add(agent)
            if validate_result(row.get('result')):
                result['agents'][agent] = row['result']
            else:
                errors = True
                diagnostics.append(f'{agent}: ' + str(row.get('error', 'malformed resolver result')))
        if expected - seen:
            errors = True
            diagnostics.append('Missing resolver rows: ' + ', '.join(sorted(expected - seen)))
        result['complete'] = not errors
    except subprocess.TimeoutExpired:
        diagnostics.append(f'GSD resolver timed out after {QUERY_TIMEOUT} seconds')
    except (OSError, ValueError, TypeError) as exc:
        diagnostics.append(str(exc))
    return result
