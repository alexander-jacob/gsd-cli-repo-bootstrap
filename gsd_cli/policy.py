"""Validate complete project policy and resolve launch-owned GSD values."""
import json
import re
from importlib.resources import files

from .versions import VersionError, parse_version

LEVELS = ('low', 'medium', 'high')
RUNTIMES = ('claude', 'codex')
PHASES = ('planning', 'discuss', 'research', 'execution', 'verification')
TIERS = dict(zip(LEVELS, ('haiku', 'sonnet', 'opus')))
EFFORTS = ('low', 'medium', 'high', 'xhigh')
TRANSIENT = (('workflow', '_auto_chain_active'),)


class PolicyError(ValueError):
    """A project policy cannot be resolved safely."""


def load_default() -> dict:
    return json.loads(files('gsd_cli').joinpath('data/default-config.json').read_text(encoding='utf-8'))


def obj(value, path, required=(), optional=()):
    if not isinstance(value, dict):
        raise PolicyError(f'{path}: expected an object')
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional) if required else set()
    if missing or unknown:
        raise PolicyError(f'{path}: missing {sorted(missing)}, unknown {sorted(unknown)}')
    return value


def choice(value, allowed, path):
    if not isinstance(value, str) or value not in allowed:
        raise PolicyError(f'{path}: expected one of {", ".join(allowed)}')


def string(value, path):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise PolicyError(f'{path}: expected a nonempty string')


def validate(p: dict) -> None:
    if isinstance(p, dict) and 'gsd' not in p:
        raise PolicyError('gsd.min_version is required; add "gsd": {"min_version": "1.20.1"} '
                          'to gsd-cli.config.json, choosing the minimum your project requires')
    obj(p, 'policy', ('gsd', 'schema_version', 'runtimes', 'phase_defaults', 'agent_levels',
                     'agent_efforts', 'reviewers', 'reviewer_efforts', 'reviewer_groups', 'workflows', 'gsd_defaults'))
    gsd = obj(p['gsd'], 'gsd', ('min_version',))
    try:
        parse_version(gsd['min_version'])
    except VersionError as exc:
        raise PolicyError(f'gsd.min_version: {exc}') from exc
    if type(p['schema_version']) is not int or p['schema_version'] != 1:
        raise PolicyError('schema_version: expected 1')
    for runtime, levels in obj(p['runtimes'], 'runtimes', RUNTIMES).items():
        for level, entry in obj(levels, f'runtimes.{runtime}', LEVELS).items():
            path = f'runtimes.{runtime}.{level}'
            obj(entry, path, ('session_model', 'agent_model', 'session_effort'))
            for key in ('session_model', 'agent_model'):
                string(entry[key], f'{path}.{key}')
            if runtime == 'claude':
                choice(entry['agent_model'], ('fable', 'opus', 'sonnet', 'haiku'), f'{path}.agent_model')
            choice(entry['session_effort'], EFFORTS if runtime == 'codex' else LEVELS, f'{path}.session_effort')
    for phase, level in obj(p['phase_defaults'], 'phase_defaults', PHASES).items():
        choice(level, LEVELS, f'phase_defaults.{phase}')
    for field, allowed in [('agent_levels', LEVELS), ('agent_efforts', EFFORTS)]:
        for agent, value in obj(p[field], field).items():
            if not re.fullmatch(r'gsd-[a-z0-9-]+', agent):
                raise PolicyError(f'{field}.{agent}: expected a GSD agent name')
            choice(value, allowed, f'{field}.{agent}')
    for name, entry in obj(p['reviewers'], 'reviewers').items():
        string(name, 'reviewer name')
        obj(entry, f'reviewers.{name}')
        choice(entry.get('cli'), (*RUNTIMES, 'opencode'), f'reviewers.{name}.cli')
        string(entry.get('model'), f'reviewers.{name}.model')
    for adapter, effort in obj(p['reviewer_efforts'], 'reviewer_efforts', (*RUNTIMES, 'opencode')).items():
        choice(effort, LEVELS if adapter == 'claude' else EFFORTS, f'reviewer_efforts.{adapter}')
    for name, group in obj(p['reviewer_groups'], 'reviewer_groups').items():
        if not isinstance(group, list) or any(not isinstance(x, str) or x not in p['reviewers'] for x in group):
            raise PolicyError(f'reviewer_groups.{name}: expected a list of declared reviewer names')
        if len(group) != len(set(group)):
            raise PolicyError(f'reviewer_groups.{name}: duplicate reviewers')
    for name, w in obj(p['workflows'], 'workflows').items():
        if not re.fullmatch(r'[a-z][a-z0-9-]*', name) or name in ('init', 'status', 'sessions', 'check', 'help', 'claude', 'codex'):
            raise PolicyError(f'workflows.{name}: reserved or invalid workflow name')
        obj(w, f'workflows.{name}', ('tasks', 'task_levels', 'reviewer_groups', 'parallel_reviews', 'permissions'), ('session_efforts',))
        if not isinstance(w['tasks'], list):
            raise PolicyError(f'workflows.{name}.tasks: expected list')
        for phase in w['tasks']:
            choice(phase, PHASES, f'workflows.{name}.tasks')
        if len(set(w['tasks'])) != len(w['tasks']):
            raise PolicyError(f'workflows.{name}.tasks: duplicate task')
        for phase, level in obj(w['task_levels'], f'workflows.{name}.task_levels').items():
            choice(phase, PHASES, f'workflows.{name}.task_levels')
            choice(level, LEVELS, f'workflows.{name}.task_levels.{phase}')
            if phase in w['tasks']:
                raise PolicyError(f'workflows.{name}: overlapping task {phase}')
        for runtime, group in obj(w['reviewer_groups'], f'workflows.{name}.reviewer_groups', RUNTIMES).items():
            choice(group, tuple(p['reviewer_groups']), f'workflows.{name}.reviewer_groups.{runtime}')
        if type(w['parallel_reviews']) is not bool:
            raise PolicyError(f'workflows.{name}.parallel_reviews: expected boolean')
        for runtime, permission in obj(w['permissions'], f'workflows.{name}.permissions', RUNTIMES).items():
            choice(permission, ('normal', 'bypass'), f'workflows.{name}.permissions.{runtime}')
        for runtime, entries in obj(w.get('session_efforts', {}), f'workflows.{name}.session_efforts').items():
            choice(runtime, RUNTIMES, f'workflows.{name}.session_efforts')
            for level, effort in obj(entries, f'session_efforts.{runtime}').items():
                choice(level, LEVELS, f'session_efforts.{runtime}')
                choice(effort, EFFORTS if runtime == 'codex' else LEVELS, f'session_efforts.{runtime}.{level}')
    obj(p['gsd_defaults'], 'gsd_defaults')


def resolve(p: dict, workflow: str, runtime: str, level: str) -> dict:
    validate(p)
    choice(workflow, tuple(p['workflows']), 'workflow')
    choice(runtime, RUNTIMES, 'runtime')
    choice(level, LEVELS, 'level')
    w = p['workflows'][workflow]
    entry = p['runtimes'][runtime][level]
    phases = {**p['phase_defaults'], **dict.fromkeys(w['tasks'], level), **w['task_levels']}
    values = {('model_policy', 'provider'): 'generic'}
    for rt, levels in p['runtimes'].items():
        values[('model_policy', 'runtime_tiers', rt)] = {
            TIERS[lev]: {'model': e['agent_model'], **({'reasoning_effort': e['session_effort']} if rt == 'codex' else {})}
            for lev, e in levels.items()}
    values.update({('models', phase): TIERS[lev] for phase, lev in phases.items()})
    values.update({('model_overrides', agent): p['runtimes'][runtime][lev]['agent_model'] for agent, lev in p['agent_levels'].items()})
    values.update({('effort', 'agent_overrides', agent): effort for agent, effort in p['agent_efforts'].items()})
    values.update({('review', 'reviewer_instances', name): reviewer for name, reviewer in p['reviewers'].items()})
    values.update({('review', 'effort', adapter): effort for adapter, effort in p['reviewer_efforts'].items()})
    reviewers = p['reviewer_groups'][w['reviewer_groups'][runtime]]
    values[('review', 'default_reviewers')] = reviewers
    values[('review', 'parallel_lanes')] = w['parallel_reviews']
    return {'values': values, 'model': entry['session_model'],
            'effort': w.get('session_efforts', {}).get(runtime, {}).get(level, entry['session_effort']),
            'reviewers': reviewers, 'permissions': w['permissions'][runtime]}
