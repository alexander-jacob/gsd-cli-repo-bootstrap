"""Click front end; policy and synchronization remain independent of Click."""
import importlib.metadata
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import NoReturn

import click
import pydantic

from . import config, preview, resolver, sessions
from .models import (JSON_COMMANDS, SCHEMAS, CheckData, CheckEntry, CheckEnvelope, ErrorInfo, PolicyData, PolicyEnvelope,
                     PreviewEnvelope, SessionsEnvelope, StatusData, StatusEnvelope, dump, failure)
from .policy import LEVELS, RESERVED, RUNTIMES, PolicyError, load_default, resolve, validate
from .versions import VersionError, check_installation, format_result


def project_policy(root: Path) -> dict:
    if not (root / config.POLICY).exists():
        raise config.ConfigError("Missing project policy; run 'gsd-cli init' to migrate this GSD project")
    policy = config.read_json(root / config.POLICY)
    validate(policy)
    return policy


def package_version() -> str:
    """Installed gsd-cli version from package metadata; 'unknown' when not installed."""
    try:
        return importlib.metadata.version('gsd-workflow-cli')
    except importlib.metadata.PackageNotFoundError:
        return 'unknown'


class WorkflowGroup(click.Group):
    def list_commands(self, ctx):
        names = set(super().list_commands(ctx))
        try:
            names.update(project_policy(config.discover())['workflows'])
        except (config.ConfigError, PolicyError, OSError):
            pass  # Generic help must work even when a project is broken.
        return sorted(names)

    def get_command(self, ctx, name):
        command = super().get_command(ctx, name)
        if command:
            return command
        if name in RUNTIMES:
            raise click.UsageError(f"Runtime-first syntax was replaced; use 'gsd-cli plan {name} [low|medium|high]' or 'gsd-cli exec {name} [low|medium|high]'.", ctx)
        # Generic preset help is available without reading or synchronizing policy.
        return workflow_command(name)


@click.group(cls=WorkflowGroup, context_settings={'help_option_names': ['-h', '--help']})
@click.version_option(package_version(), '-V', '--version', prog_name='gsd-cli', message='%(prog)s %(version)s')
def cli():
    """Open Claude/Codex with project-owned workflow presets.

    Usage: gsd-cli WORKFLOW RUNTIME [low|medium|high] [--secure] [--config [--details|--json]] [-- CLI_ARGS...]
    Level defaults to medium. Put all child CLI arguments after --.
    Presets open the runtime; they never invoke a GSD workflow.
    """


@cli.command('init')
def init_command():
    """Seed project policy and migrate persistent GSD defaults."""
    root = config.discover()
    config.initialize(root)
    click.echo(f'Initialized {root}. Existing project policy and working config are preserved.\n'
               'Starter workflows use medium sessions, explicit reviewers and independent agent/reviewer efforts.\n'
               'Review and commit gsd-cli.config.json, .planning/config.default.json, .gitignore, '
               'and the config.json index removal (if previously tracked).')


@cli.command('status')
@click.option('--json', 'as_json', is_flag=True, help='Print one machine-readable JSON envelope.')
def status_command(as_json):
    """Read effective configuration, or defaults in a fresh checkout."""
    root = config.discover()
    path = root / config.WORKING
    if not path.exists():
        path = root / config.DEFAULT
    data = config.read_json(path)
    pending = (root / config.JOURNAL).exists()
    if as_json:
        emit(StatusEnvelope(ok=True, data=StatusData(project=str(root.resolve()), source=str(path),
                                                      pending_recovery=pending, config=data)))
    click.echo(config.serialize({'source': str(path), 'pending_recovery': pending, 'config': data}), nl=False)


@cli.command('check')
@click.argument('runtime', type=click.Choice(RUNTIMES), required=False)
@click.option('--json', 'as_json', is_flag=True, help='Print one machine-readable JSON envelope.')
def check_command(runtime, as_json):
    """Check installed GSD against project requirements (both runtimes by default)."""
    root = config.discover()
    policy = project_policy(root)
    minimum = policy['gsd']['min_version']
    results = [check_installation(root, rt, minimum) for rt in ((runtime,) if runtime else RUNTIMES)]
    failed = any(not result.ok for result in results)
    message = 'GSD requirements not met. Update or repair the reported installation, then rerun gsd-cli check.'
    if as_json:
        data = CheckData(minimum=minimum, results=[
            CheckEntry(runtime=r.runtime, directory=str(r.directory), installed=r.installed, minimum=r.minimum,
                       ok=r.ok, reason=r.reason, message=r.message) for r in results])
        emit(CheckEnvelope(ok=not failed, data=data,
                           error=ErrorInfo(kind='requirements', message=message) if failed else None))
    for result in results:
        click.echo(format_result(result))
    if failed:
        raise click.ClickException(message)


@cli.command('policy')
@click.option('--json', 'as_json', is_flag=True, help='Print one machine-readable JSON envelope.')
def policy_command(as_json):
    """Validate project policy and show it."""
    root = config.discover()
    policy = project_policy(root)
    path = root / config.POLICY
    if as_json:
        emit(PolicyEnvelope(ok=True, data=PolicyData(
            project=str(root.resolve()), path=str(path), policy=policy,
            differs_from_shipped=config.changed_paths(load_default(), policy))))
    click.echo(f'Policy valid: {path}')


@cli.command('schema')
@click.argument('name', metavar='NAME', required=False)
def schema_command(name):
    """Print the JSON Schema of a machine-readable output."""
    if name is None:
        click.echo('\n'.join(sorted(SCHEMAS)))
    elif name in SCHEMAS:
        click.echo(json.dumps(SCHEMAS[name].model_json_schema(), indent=2, ensure_ascii=True))
    else:
        raise click.UsageError(f'unknown schema {name!r}; choose from {", ".join(sorted(SCHEMAS))}')


@cli.command('sessions', context_settings={'ignore_unknown_options': True, 'allow_extra_args': True})
@click.argument('args', nargs=-1, type=click.UNPROCESSED)
def sessions_command(args):
    """Read recent sessions: [claude|codex] [--pick [N]] [--json]."""
    root = config.discover()
    runtimes, picking, pick, as_json = sessions.parse_args(list(args))
    if as_json:
        emit(SessionsEnvelope(ok=True, data=sessions.report(root, runtimes, picking, pick)))
    sessions.sessions_command(root, list(args))


def guard_billing(runtime: str, policy: dict, reviewers: list[str]) -> None:
    adapters = {runtime} | {policy['reviewers'][name]['cli'] for name in reviewers}
    if 'claude' in adapters and os.environ.get('ANTHROPIC_API_KEY'):
        raise config.ConfigError('Refusing to launch: ANTHROPIC_API_KEY is set; unset it to use Claude subscription authentication')
    if 'codex' in adapters and (os.environ.get('OPENAI_API_KEY') or os.environ.get('CODEX_API_KEY')):
        raise config.ConfigError('Refusing to launch: OPENAI_API_KEY/CODEX_API_KEY is set; unset it to use ChatGPT login')


def guard_project_location(runtime: str, forwarded: list[str]) -> None:
    if runtime != 'codex':
        return
    for arg in forwarded:
        if arg == '--':
            break  # Subsequent tokens are literal child positional arguments.
        if arg == '--cd' or arg.startswith('--cd=') or arg.startswith('-C'):
            raise config.ConfigError('Codex -C/--cd would change the checked GSD project; '
                                     'run gsd-cli from the destination project instead of forwarding a directory switch')


def launch_arguments(runtime: str, resolved: dict, secure: bool, forwarded: list[str]) -> list[str]:
    argv = [runtime, '--model', resolved['model']]
    argv += (['--effort', resolved['effort']] if runtime == 'claude'
             else ['-c', 'model_reasoning_effort=' + resolved['effort']])
    if resolved['permissions'] == 'bypass' and not secure:
        argv += ['--dangerously-skip-permissions' if runtime == 'claude'
                 else '--dangerously-bypass-approvals-and-sandbox']
    return argv + forwarded


def workflow_command(name: str):
    @click.command(name, help=f'Open a runtime using the {name} preset. Child options belong after --.')
    @click.argument('runtime', type=click.Choice(RUNTIMES))
    @click.argument('level', type=click.Choice(LEVELS), default='medium')
    @click.option('--secure', is_flag=True, help='Suppress the preset permission-bypass flag.')
    @click.option('--config', 'show_config', is_flag=True, help='Print effective config and installed GSD model/effort checks, then exit without launching.')
    @click.option('--details', is_flag=True, help='With --config, show resolver evidence and full effective JSON.')
    @click.option('--json', 'as_json', is_flag=True, help='With --config, print one machine-readable JSON envelope.')
    @click.pass_context
    def launch(ctx, runtime, level, secure, show_config, details, as_json):
        if details and not show_config:
            raise click.UsageError('--details requires --config')
        if as_json and not show_config:
            raise click.UsageError('--json requires --config')
        if as_json and details:
            raise click.UsageError('--json and --details are mutually exclusive; JSON is always complete')
        forwarded = ctx.obj.get('forwarded', [])
        guard_project_location(runtime, forwarded)
        root = config.discover()
        policy = project_policy(root)
        resolved = resolve(policy, name, runtime, level)
        argv = launch_arguments(runtime, resolved, secure, forwarded)
        if show_config:
            data, captured = config.preview(root, policy, resolved)
            inspection = resolver.inspect(root, data, runtime, policy['gsd']['min_version'])
            if as_json:
                complete = inspection['complete']
                emit(PreviewEnvelope(ok=complete, data=preview.report(
                    root, name, runtime, level, policy, resolved, data, captured, argv, forwarded, inspection),
                    error=None if complete else ErrorInfo(
                        kind='incomplete', message='Configuration preview is incomplete; see diagnostics.')))
            color = preview.use_color(click.get_text_stream('stdout'), os.environ)
            if details:
                report = preview.render(root, name, runtime, level, policy, resolved, data,
                                        captured, argv, forwarded, inspection)
                marker = 'Launcher effective configuration:\n'
                before, raw_json = report.split(marker, 1)
                report = before + marker + preview.colorize_json(raw_json, color)
            else:
                report = preview.render_compact(root, name, runtime, level, policy, resolved,
                                                data, captured, argv, forwarded, inspection, color)
            click.echo(report, nl=False, color=color)
            if not inspection['complete']:
                raise click.ClickException('Configuration preview is incomplete; see resolver diagnostics above.')
            return
        executable = shutil.which(runtime)
        if executable is None:
            raise config.ConfigError(f"Cannot find CLI '{runtime}' on PATH")
        guard_billing(runtime, policy, resolved['reviewers'])
        version = check_installation(root, runtime, policy['gsd']['min_version'])
        if not version.ok:
            raise config.ConfigError(format_result(version) +
                                     f'; launch blocked. Update or repair this installation, then run gsd-cli check {runtime}.')
        data, captured = config.synchronize(root, policy, resolved)
        if captured:
            click.echo('GSD: captured persistent changes: ' + ', '.join(captured), err=True)
        if runtime == 'claude' and policy['agent_efforts']:
            click.echo('GSD: Claude agent effort also depends on installed agent frontmatter. '
                       'After policy changes, review GSD effort sync --apply (global agent files); '
                       'gsd-cli does not modify those files.', err=True)
        sessions.record_launch(root, runtime, f'{name}/{level}', resolved['model'], forwarded, data,
                               effort=resolved['effort'], workflow=name, level=level, policy=policy)
        click.echo(f"GSD: {name}/{runtime}/{level} | model={resolved['model']} | effort={resolved['effort']} | reviewers={','.join(resolved['reviewers'])}", err=True)
        os.chdir(root)
        os.execvpe(executable, argv, {**os.environ, 'GSD_RUNTIME': runtime})
    return launch


def emit(envelope) -> NoReturn:
    """Print one JSON envelope and exit 0 only when it reports success."""
    sys.stdout.write(dump(envelope))
    sys.stdout.flush()
    raise SystemExit(0 if envelope.ok else 1)


def json_command(args: list[str]) -> str | None:
    """Envelope command name for an invocation: a JSON command, None, or 'preview'."""
    if not args or args[0].startswith('-'):
        return None
    if args[0] in JSON_COMMANDS:
        return args[0]
    return None if args[0] in RESERVED else 'preview'


def help_or_version(args: list[str]) -> bool:
    """True when Click will print help or the version for these arguments.

    Mirrors Click's parsing: a short-flag cluster counts only when every letter is valid where it
    stands. Before the command name that is -h and -V; after it, only -h.
    """
    command = next((i for i, a in enumerate(args) if not a.startswith('-')), len(args))
    return (any(a == '--help' or re.fullmatch(r'-h+', a) for a in args)
            or any(a == '--version' or re.fullmatch(r'-[hV]+', a) for a in args[:command]))


def fail_json(args: list[str], kind: str, message: str, code: int) -> NoReturn:
    sys.stdout.write(dump(failure(json_command(args), kind, message)))
    sys.stdout.flush()
    raise SystemExit(code)


def main():
    args = sys.argv[1:]
    if args == ['help']:
        args = ['--help']
    forwarded = []
    if '--' in args:
        split = args.index('--')
        args, forwarded = args[:split], args[split + 1:]
        if not args or (args[0] in RESERVED and args[0] not in RUNTIMES):
            click.echo('Error: forwarding after -- is supported only for workflow launches', err=True)
            raise SystemExit(2)
    json_mode = '--json' in args
    if json_mode and help_or_version(args):
        args, json_mode = [a for a in args if a != '--json'], False  # Help and version win over JSON.
    try:
        cli.main(args=args, prog_name='gsd-cli', obj={'forwarded': forwarded, 'json': json_mode}, standalone_mode=False)
    except sessions.SessionsError as exc:
        if json_mode:
            fail_json(args, 'usage', str(exc), 1)
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc
    except click.ClickException as exc:
        if json_mode:
            usage = isinstance(exc, click.UsageError)
            fail_json(args, 'usage' if usage else 'config', exc.format_message(), exc.exit_code)
        exc.show()
        raise SystemExit(exc.exit_code) from exc
    except pydantic.ValidationError as exc:
        if not json_mode:
            raise
        # Values from unowned config or third-party logs that the output models cannot represent.
        problems = '; '.join(f"{'.'.join(map(str, e['loc'])) or 'value'}: {e['msg']}" for e in exc.errors())
        fail_json(args, 'config', f'Cannot represent the result as JSON: {problems}', 1)
    except (config.ConfigError, PolicyError, VersionError, OSError) as exc:
        if json_mode:
            kind = ('config' if isinstance(exc, config.ConfigError) else 'policy' if isinstance(exc, PolicyError)
                    else 'version' if isinstance(exc, VersionError) else 'os')
            fail_json(args, kind, str(exc), 1)
        click.echo(f'Error: {exc}', err=True)
        raise SystemExit(1) from exc
