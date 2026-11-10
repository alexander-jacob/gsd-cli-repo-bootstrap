"""Click front end; policy and synchronization remain independent of Click."""
import os
import shutil
import sys
from pathlib import Path

import click

from . import config, sessions
from .policy import LEVELS, RUNTIMES, PolicyError, resolve, validate
from .versions import VersionError, check_installation, format_result


def project_policy(root: Path) -> dict:
    if not (root / config.POLICY).exists():
        raise config.ConfigError("Missing project policy; run 'gsd-cli init' to migrate this GSD project")
    policy = config.read_json(root / config.POLICY)
    validate(policy)
    return policy


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
def cli():
    """Open Claude/Codex with project-owned workflow presets.

    Usage: gsd-cli WORKFLOW RUNTIME [low|medium|high] [--secure] [-- CLI_ARGS...]
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
def status_command():
    """Read effective configuration, or defaults in a fresh checkout."""
    root = config.discover()
    path = root / config.WORKING
    if not path.exists():
        path = root / config.DEFAULT
    data = config.read_json(path)
    click.echo(config.serialize({'source': str(path), 'pending_recovery': (root / config.JOURNAL).exists(),
                                 'config': data}), nl=False)


@cli.command('check')
@click.argument('runtime', type=click.Choice(RUNTIMES), required=False)
def check_command(runtime):
    """Check installed GSD against project requirements (both runtimes by default)."""
    root = config.discover()
    policy = project_policy(root)
    results = [check_installation(root, rt, policy['gsd']['min_version'])
               for rt in ((runtime,) if runtime else RUNTIMES)]
    for result in results:
        click.echo(format_result(result))
    if any(not result.ok for result in results):
        raise click.ClickException('GSD requirements not met. Update or repair the reported installation, then rerun gsd-cli check.')


@cli.command('sessions', context_settings={'ignore_unknown_options': True, 'allow_extra_args': True})
@click.argument('args', nargs=-1, type=click.UNPROCESSED)
def sessions_command(args):
    """Read recent sessions: [claude|codex] [--pick [N]]."""
    sessions.sessions_command(config.discover(), list(args))


def guard_billing(runtime: str, policy: dict, reviewers: list[str]) -> None:
    adapters = {runtime} | {policy['reviewers'][name]['cli'] for name in reviewers}
    if 'claude' in adapters and os.environ.get('ANTHROPIC_API_KEY'):
        raise config.ConfigError('Refusing to launch: ANTHROPIC_API_KEY is set; unset it to use Claude subscription authentication')
    if 'codex' in adapters and (os.environ.get('OPENAI_API_KEY') or os.environ.get('CODEX_API_KEY')):
        raise config.ConfigError('Refusing to launch: OPENAI_API_KEY/CODEX_API_KEY is set; unset it to use ChatGPT login')


def workflow_command(name: str):
    @click.command(name, help=f'Open a runtime using the {name} preset. Child options belong after --.')
    @click.argument('runtime', type=click.Choice(RUNTIMES))
    @click.argument('level', type=click.Choice(LEVELS), default='medium')
    @click.option('--secure', is_flag=True, help='Suppress the preset permission-bypass flag.')
    @click.pass_context
    def launch(ctx, runtime, level, secure):
        root = config.discover()
        policy = project_policy(root)
        resolved = resolve(policy, name, runtime, level)
        executable = shutil.which(runtime)
        if executable is None:
            raise config.ConfigError(f"Cannot find CLI '{runtime}' on PATH")
        guard_billing(runtime, policy, resolved['reviewers'])
        version = check_installation(root, runtime, policy['gsd']['min_version'])
        if not version.ok:
            raise config.ConfigError(format_result(version) +
                                     f'; launch blocked. Update or repair this installation, then run gsd-cli check {runtime}.')
        forwarded = ctx.obj.get('forwarded', [])
        data, captured = config.synchronize(root, policy, resolved)
        if captured:
            click.echo('GSD: captured persistent changes: ' + ', '.join(captured), err=True)
        if runtime == 'claude' and policy['agent_efforts']:
            click.echo('GSD: Claude agent effort also depends on installed agent frontmatter. '
                       'After policy changes, review GSD effort sync --apply (global agent files); '
                       'gsd-cli does not modify those files.', err=True)
        argv = [runtime, '--model', resolved['model']]
        argv += (['--effort', resolved['effort']] if runtime == 'claude'
                 else ['-c', 'model_reasoning_effort=' + resolved['effort']])
        if resolved['permissions'] == 'bypass' and not secure:
            argv += ['--dangerously-skip-permissions' if runtime == 'claude'
                     else '--dangerously-bypass-approvals-and-sandbox']
        argv += forwarded
        sessions.record_launch(root, runtime, f'{name}/{level}', resolved['model'], forwarded, data,
                               effort=resolved['effort'], workflow=name, level=level, policy=policy)
        click.echo(f"GSD: {name}/{runtime}/{level} | model={resolved['model']} | effort={resolved['effort']} | reviewers={','.join(resolved['reviewers'])}", err=True)
        os.chdir(root)
        os.execvpe(executable, argv, {**os.environ, 'GSD_RUNTIME': runtime})
    return launch


def main():
    args = sys.argv[1:]
    if args == ['help']:
        args = ['--help']
    forwarded = []
    if '--' in args:
        split = args.index('--')
        args, forwarded = args[:split], args[split + 1:]
        if not args or args[0] in ('init', 'status', 'sessions', 'check', 'help'):
            click.echo('Error: forwarding after -- is supported only for workflow launches', err=True)
            raise SystemExit(2)
    try:
        cli.main(args=args, prog_name='gsd-cli', obj={'forwarded': forwarded}, standalone_mode=False)
    except click.ClickException as exc:
        exc.show()
        raise SystemExit(exc.exit_code) from exc
    except (config.ConfigError, PolicyError, VersionError, OSError) as exc:
        click.echo(f'Error: {exc}', err=True)
        raise SystemExit(1) from exc
