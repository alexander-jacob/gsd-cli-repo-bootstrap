"""Project discovery, three-way capture and recoverable per-file replacements.

The POSIX lock covers preparation only. Running AI sessions are not isolated.
"""
import copy
import fcntl
import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .policy import PHASES, RUNTIMES, TIERS, TRANSIENT, load_default, resolve, validate

POLICY = 'gsd-cli.config.json'
WORKING = '.planning/config.json'
DEFAULT = '.planning/config.default.json'
STATE = '.planning/.gsd-cli-sync.json'
JOURNAL = '.planning/.gsd-cli-journal.json'
LOCK = '.planning/.gsd-cli.lock'
MISSING = object()
TARGETS = (POLICY, DEFAULT, WORKING, STATE, '.gitignore')


class ConfigError(ValueError):
    """Unsafe, conflicting, or malformed project state."""


def discover(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    for root in (start, *start.parents):
        if any((root / name).exists() for name in (WORKING, DEFAULT, POLICY)):
            return root
    raise ConfigError('No GSD project found: expected .planning/config.json or config.default.json')


def safe_path(path: Path) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise ConfigError(f'Refusing symlink: {path}')


def read_json(path: Path) -> dict:
    safe_path(path)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ConfigError(f'Cannot read {path}: {exc}') from exc
    if not isinstance(data, dict):
        raise ConfigError(f'{path}: expected a JSON object')
    return data


def serialize(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n'


def read_text(path: Path) -> str | None:
    safe_path(path)
    return path.read_text(encoding='utf-8') if path.exists() else None


def atomic_write(path: Path, content: str) -> None:
    safe_path(path)
    if read_text(path) == content:
        return
    fd, name = tempfile.mkstemp(prefix='.gsd-cli-tmp-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        fsync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def locked(root: Path):
    safe_path(root / LOCK)
    with (root / LOCK).open('a') as handle:
        os.fchmod(handle.fileno(), 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ConfigError('Another gsd-cli process is preparing configuration; retry shortly') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def json_equal(left, right) -> bool:
    """Compare JSON values without Python's bool/number equivalence."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    return left == right


def merge(base, local, default, path=()):
    """Merge JSON trees, treating absent keys distinctly from null."""
    if json_equal(local, default):
        return copy.deepcopy(local) if local is not MISSING else MISSING
    if json_equal(local, base):
        return copy.deepcopy(default) if default is not MISSING else MISSING
    if json_equal(default, base):
        return copy.deepcopy(local) if local is not MISSING else MISSING
    if isinstance(local, dict) and isinstance(default, dict) and (isinstance(base, dict) or base is MISSING):
        b = {} if base is MISSING else base
        result = {}
        for key in sorted(b.keys() | local.keys() | default.keys()):
            value = merge(b.get(key, MISSING), local.get(key, MISSING), default.get(key, MISSING), (*path, key))
            if value is not MISSING:
                result[key] = value
        return result
    raise ConfigError(f'Configuration conflict at {".".join(path) or "<root>"}; reconcile config.json and config.default.json, then retry')


def get_path(data: dict, path: tuple):
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return MISSING
        current = current[key]
    return current


def remove_path(data: dict, path: tuple) -> None:
    if len(path) == 1:
        data.pop(path[0], None)
    elif path[0] in data:
        child = data[path[0]]
        if not isinstance(child, dict):
            raise ConfigError(f'{path[0]}: expected object containing managed settings')
        remove_path(child, path[1:])
        if not child:
            del data[path[0]]


def put_path(data: dict, path: tuple, value) -> None:
    for key in path[:-1]:
        if key in data and not isinstance(data[key], dict):
            raise ConfigError(f'{key}: expected object containing managed settings')
        data = data.setdefault(key, {})
    data[path[-1]] = copy.deepcopy(value)


def project(data: dict, paths) -> dict:
    result = copy.deepcopy(data)
    for path in sorted(paths):
        remove_path(result, path)
    return result


def managed_paths(resolved: dict) -> set:
    return set(resolved['values']) | {('runtime',)}


def valid_owned(path: tuple) -> bool:
    return (path == ('runtime',) or path == ('model_policy', 'provider')
            or (len(path) == 3 and path[:2] == ('model_policy', 'runtime_tiers') and path[2] in RUNTIMES)
            or (len(path) == 2 and path[0] == 'models' and path[1] in PHASES)
            or (len(path) == 2 and path[0] == 'model_overrides' and path[1].startswith('gsd-'))
            or (len(path) == 3 and path[:2] == ('effort', 'agent_overrides') and path[2].startswith('gsd-'))
            or (len(path) == 3 and path[:2] == ('review', 'reviewer_instances'))
            or (len(path) == 3 and path[:2] == ('review', 'effort') and path[2] in (*RUNTIMES, 'opencode'))
            or path in (('review', 'default_reviewers'), ('review', 'parallel_lanes')))


def load_state(root: Path):
    if not (root / STATE).exists():
        return None
    state = read_json(root / STATE)
    if state.get('version') != 1 or not isinstance(state.get('baseline'), dict) or not isinstance(state.get('managed'), list):
        raise ConfigError('Invalid synchronization baseline metadata')
    for path in state['managed']:
        if not isinstance(path, list) or not path or any(not isinstance(k, str) or not k for k in path) or not valid_owned(tuple(path)):
            raise ConfigError('Invalid managed path in synchronization metadata')
    return state


def changed_paths(before, after, prefix=()) -> list[str]:
    if json_equal(before, after):
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        return [p for k in sorted(before.keys() | after.keys())
                for p in changed_paths(before.get(k, MISSING), after.get(k, MISSING), (*prefix, k))]
    return ['.'.join(prefix)]


def reject_owned(default: dict, paths) -> None:
    found = ['.'.join(p) for p in sorted(paths) if get_path(default, p) is not MISSING]
    if found:
        raise ConfigError('config.default.json contains managed/transient settings: ' + ', '.join(found))
    # Detect a scalar replacing a container even when no leaf exists.
    project(default, paths)


def git(root: Path, *args):
    return subprocess.run(['git', '-C', str(root), *args], text=True, capture_output=True, check=False)


def git_tracked(root: Path) -> bool:
    result = git(root, 'ls-files', '--error-unmatch', '--', WORKING)
    return result.returncode == 0


def check_staged(root: Path) -> None:
    if git(root, 'diff', '--cached', '--quiet', '--', WORKING).returncode != 0:
        raise ConfigError('config.json has staged changes; commit or unstage them before init migration')


def recover(root: Path) -> None:
    if not (root / JOURNAL).exists():
        return
    journal = read_json(root / JOURNAL)
    entries = journal.get('files')
    if journal.get('version') != 1 or not isinstance(entries, dict) or not entries or not set(entries) <= set(TARGETS) or type(journal.get('untrack')) is not bool:
        raise ConfigError('Invalid recovery journal; inspect .planning/.gsd-cli-journal.json')
    # Validate every precondition before resuming any replacement.
    for name, entry in entries.items():
        if not isinstance(entry, dict) or not isinstance(entry.get('after'), str) or not (entry.get('before') is None or isinstance(entry['before'], str)):
            raise ConfigError('Invalid recovery entry')
        if read_text(root / name) not in (entry['before'], entry['after']):
            raise ConfigError(f'Cannot resume recovery: {name} was edited externally; preserve edits and reconcile the journal')
    if journal['untrack'] and git_tracked(root):
        check_staged(root)
    for name, entry in entries.items():
        atomic_write(root / name, entry['after'])
    if journal['untrack'] and git_tracked(root):
        result = git(root, 'rm', '--cached', '--', WORKING)
        if result.returncode:
            raise ConfigError(f'Cannot untrack config.json; recovery retained: {result.stderr.strip()}')
    (root / JOURNAL).unlink()
    fsync_directory(root / '.planning')


def transaction(root: Path, contents: dict, untrack=False) -> None:
    entries = {name: {'before': read_text(root / name), 'after': content} for name, content in contents.items()}
    entries = {name: e for name, e in entries.items() if e['before'] != e['after']}
    if not entries and not untrack:
        return
    # An index-only recovery still records a target precondition.
    if not entries:
        entries[DEFAULT] = {'before': read_text(root / DEFAULT), 'after': read_text(root / DEFAULT)}
    atomic_write(root / JOURNAL, serialize({'version': 1, 'files': entries, 'untrack': untrack}))
    recover(root)


def synchronize(root: Path, policy: dict, resolved: dict) -> tuple[dict, list[str]]:
    with locked(root):
        recover(root)
        if not json_equal(read_json(root / POLICY), policy):
            raise ConfigError('Project policy changed during preparation; retry')
        default = read_json(root / DEFAULT)
        state = load_state(root)
        current = managed_paths(resolved)
        previous = {tuple(p) for p in state['managed']} if state else set()
        excluded = current | previous | set(TRANSIENT)
        reject_owned(default, excluded)
        working = read_json(root / WORKING) if (root / WORKING).exists() else None
        local = project(working, excluded) if working is not None else default
        if state is None:
            if not json_equal(local, default):
                raise ConfigError('No synchronization baseline and persistent configs differ; reconcile config.json with config.default.json before retrying')
            baseline = default
        else:
            baseline = project(state['baseline'], excluded)
        merged = merge(baseline, local, default)
        data = copy.deepcopy(merged)
        if working is not None:
            for path in TRANSIENT:
                value = get_path(working, path)
                if value is not MISSING:
                    put_path(data, path, value)
        for path, value in resolved['values'].items():
            put_path(data, path, value)
        metadata = {'version': 1, 'baseline': merged, 'managed': sorted(current)}
        transaction(root, {DEFAULT: serialize(merged), WORKING: serialize(data), STATE: serialize(metadata)})
        return data, changed_paths(default, merged)


def seed_policy(working: dict) -> dict:
    policy = load_default()
    tiers = working.get('model_policy', {}).get('runtime_tiers', {})
    for runtime in RUNTIMES:
        for level, tier in TIERS.items():
            old = tiers.get(runtime, {}).get(tier)
            if old:
                entry = policy['runtimes'][runtime][level]
                entry['agent_model'] = old['model']
                if runtime == 'codex':
                    entry['session_model'] = old['model']
                    if 'reasoning_effort' in old:
                        entry['session_effort'] = old['reasoning_effort']
    for agent, model in working.get('model_overrides', {}).items():
        if agent in policy['agent_levels']:
            matches = {level for rt in policy['runtimes'].values() for level, entry in rt.items() if entry['agent_model'] == model}
            if len(matches) == 1:
                policy['agent_levels'][agent] = matches.pop()
            else:
                # A custom model cannot be converted into a runtime-independent pin.
                del policy['agent_levels'][agent]
    policy['agent_efforts'].update(working.get('effort', {}).get('agent_overrides', {}))
    review = working.get('review', {})
    policy['reviewers'].update(review.get('reviewer_instances', {}))
    policy['reviewer_efforts'].update(review.get('effort', {}))
    if 'parallel_lanes' in review:
        for workflow in policy['workflows'].values():
            workflow['parallel_reviews'] = review['parallel_lanes']
    validate(policy)
    return policy


def seed_settings(defaults: dict, existing: dict) -> dict:
    result = copy.deepcopy(defaults)
    for key, value in existing.items():
        result[key] = seed_settings(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else copy.deepcopy(value)
    return result


def ignored(root: Path, name: str) -> bool:
    # With -v, Git also prints matching NEGATED rules and returns zero.
    # -q gives the effective exclusion status needed here.
    return git(root, 'check-ignore', '-q', '--no-index', '--', name).returncode == 0


def ignore_text(root: Path) -> str:
    original = read_text(root / '.gitignore') or ''
    additions = []
    reopen = ignored(root, '.planning')
    if reopen:
        # These must follow earlier rules, even when their text already exists.
        additions += ['!/.planning/', '/.planning/*']
    for name in ('.gitignore', POLICY, DEFAULT):
        rule = '!/' + name
        if rule not in original.splitlines() or ignored(root, name) or (reopen and name == DEFAULT):
            additions.append(rule)
    for rule in ('/.planning/config.json', '/.planning/.gsd-cli-*', '/.planning/.gsd-cli.lock', '/.gsd-cli-tmp-*'):
        if rule not in original.splitlines():
            additions.append(rule)
    return original + ('\n' if original and not original.endswith('\n') else '') + ('\n# gsd-cli project configuration\n' + '\n'.join(additions) + '\n' if additions else '')


def validate_ignores(root: Path, candidate: str) -> None:
    repository = git(root, 'rev-parse', '--show-toplevel')
    if repository.returncode:
        return
    prefix = git(root, 'rev-parse', '--show-prefix').stdout.strip().rstrip('/')
    if prefix and ignored(Path(repository.stdout.strip()), prefix):
        raise ConfigError('An ignored project ancestor hides launcher configuration; unignore the project in ancestor Git rules before init')
    # Evaluate the proposed rules without writing the project or touching its
    # index. A nested ignore file may be hidden by the CURRENT parent exclusion,
    # then become authoritative after we reopen .planning. Mirror both files.
    nested = read_text(root / '.planning/.gitignore')
    with tempfile.TemporaryDirectory(prefix='gsd-ignore-check-') as directory:
        probe = Path(directory)
        result = git(probe, 'init', '-q', '--template=')
        if result.returncode:
            raise ConfigError('Cannot validate migration ignore rules: ' + result.stderr.strip())
        (probe / '.planning').mkdir()
        (probe / '.gitignore').write_text(candidate, encoding='utf-8')
        if nested is not None:
            (probe / '.planning/.gitignore').write_text(nested, encoding='utf-8')
        hidden = [name for name in (POLICY, DEFAULT, '.gitignore') if ignored(probe, name)]
        exposed = [name for name in (WORKING, STATE, JOURNAL, LOCK, '.planning/.gsd-cli-tmp-probe') if not ignored(probe, name)]
        if hidden or exposed:
            raise ConfigError('Nested .planning/.gitignore conflicts with migration: '
                              f'hidden tracked files {hidden}; exposed local files {exposed}. '
                              'Allow config.default.json and ignore local config/sync/recovery files before init')


def initialize(root: Path) -> None:
    if not (root / '.planning').is_dir():
        raise ConfigError('Initialize GSD first: .planning directory is missing')
    with locked(root):
        recover(root)
        if git_tracked(root):
            check_staged(root)
        working = read_json(root / WORKING) if (root / WORKING).exists() else {}
        try:
            policy = read_json(root / POLICY) if (root / POLICY).exists() else seed_policy(working)
        except (TypeError, KeyError, AttributeError) as exc:
            raise ConfigError(f'Malformed legacy configuration: {exc}') from exc
        validate(policy)
        # Ownership is identical across workflows and runtimes.
        values = resolve(policy, next(iter(policy['workflows'])), 'claude', 'medium') if policy['workflows'] else None
        if values is None:
            raise ConfigError('workflows: declare at least one workflow')
        paths = managed_paths(values)
        existing_state = load_state(root)
        if (root / DEFAULT).exists():
            default = read_json(root / DEFAULT)
            reject_owned(default, paths | set(TRANSIENT))
            if existing_state is None and working and not json_equal(project(working, paths | set(TRANSIENT)), default):
                raise ConfigError('Existing config.default.json differs; reconcile before init')
            baseline = existing_state['baseline'] if existing_state else default
        else:
            if existing_state:
                raise ConfigError('Restore missing config.default.json before init')
            baseline = project(working, paths | set(TRANSIENT))
            default = seed_settings(policy['gsd_defaults'], baseline)
            reject_owned(default, paths | set(TRANSIENT))
        state = existing_state or {'version': 1, 'baseline': baseline, 'managed': sorted(paths)}
        ignores = ignore_text(root)
        validate_ignores(root, ignores)
        contents = {POLICY: serialize(policy), DEFAULT: serialize(default), STATE: serialize(state), '.gitignore': ignores}
        transaction(root, contents, untrack=git_tracked(root))
