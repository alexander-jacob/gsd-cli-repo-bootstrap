"""Validate complete project policy and resolve launch-owned GSD values."""
import json
import re
from importlib.resources import files

from .versions import VersionError, parse_version

LEVELS = ('low', 'medium', 'high')
RUNTIMES = ('claude', 'codex')
PHASES = ('planning', 'discuss', 'research', 'execution', 'verification')
TIERS = dict(zip(LEVELS, ('haiku', 'sonnet', 'opus')))
RESERVED = ('init', 'status', 'sessions', 'check', 'policy', 'schema', 'help', 'claude', 'codex')
EFFORTS = ('low', 'medium', 'high', 'xhigh')
CLAUDE_EFFORTS = (*EFFORTS, 'max')
CLAUDE_AGENT_MODELS = ('fable', 'opus', 'sonnet', 'haiku')
REVIEW_ADAPTERS = (*RUNTIMES, 'opencode')
BLUEPRINT_NAME_PATTERN = r'^[a-z][a-z0-9-]*$'
AGENT_NAME_PATTERN = r'^gsd-[a-z0-9-]+$'
TRANSIENT = (('workflow', '_auto_chain_active'),)


class PolicyError(ValueError):
    """A project policy cannot be resolved safely."""


def load_default() -> dict:
    return json.loads(files('gsd_cli').joinpath('data/default-config.json').read_text(encoding='utf-8'))


def obj(value, path, required=None, optional=()):
    if not isinstance(value, dict):
        raise PolicyError(f'{path}: expected an object')
    if required is not None:
        missing = set(required) - value.keys()
        unknown = value.keys() - set(required) - set(optional)
        if missing:
            raise PolicyError(f'{path}.{min(missing)}: required')
        if unknown:
            raise PolicyError(f'{path}.{min(map(str, unknown))}: unknown field')
    return value


def choice(value, allowed, path):
    if not isinstance(value, str) or value not in allowed:
        raise PolicyError(f'{path}: expected one of {", ".join(allowed)}')


def string(value, path):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise PolicyError(f'{path}: expected a nonempty string')


def is_agent_name(name) -> bool:
    return isinstance(name, str) and re.fullmatch(AGENT_NAME_PATTERN, name) is not None


def validate_settings(settings, path, runtime, *, agent=False, partial=False):
    fields = ('model', 'effort')
    obj(settings, path, () if partial else fields, fields if partial else ())
    if not settings:
        raise PolicyError(f'{path}: expected at least one of model and effort')
    if 'model' in settings:
        model = settings['model']
        if agent and runtime == 'claude':
            choice(model, CLAUDE_AGENT_MODELS, f'{path}.model')
        elif agent and model in CLAUDE_AGENT_MODELS:
            raise PolicyError(f'{path}.model: expected a full Codex model ID, got Claude alias {model!r}')
        else:
            string(model, f'{path}.model')
    if 'effort' in settings:
        efforts = CLAUDE_EFFORTS if runtime == 'claude' else EFFORTS
        choice(settings['effort'], efforts, f'{path}.effort')


def validate_review(review, path):
    obj(review, path, ('reviewer_instances', 'default_reviewers', 'effort', 'parallel_lanes'))
    instances = obj(review['reviewer_instances'], f'{path}.reviewer_instances')
    for name, entry in instances.items():
        entry_path = f'{path}.reviewer_instances.{name}'
        string(name, entry_path)
        obj(entry, entry_path)
        choice(entry.get('cli'), REVIEW_ADAPTERS, f'{entry_path}.cli')
        string(entry.get('model'), f'{entry_path}.model')
    names = review['default_reviewers']
    if not isinstance(names, list):
        raise PolicyError(f'{path}.default_reviewers: expected a list of declared reviewer names')
    for index, name in enumerate(names):
        if not isinstance(name, str) or name not in instances:
            raise PolicyError(f'{path}.default_reviewers[{index}]: unknown reviewer {name!r}')
    if len(names) != len(set(names)):
        raise PolicyError(f'{path}.default_reviewers: duplicate reviewers')
    for adapter, effort in obj(review['effort'], f'{path}.effort', REVIEW_ADAPTERS).items():
        choice(effort, LEVELS if adapter == 'claude' else EFFORTS, f'{path}.effort.{adapter}')
    if type(review['parallel_lanes']) is not bool:
        raise PolicyError(f'{path}.parallel_lanes: expected boolean')


def validate(p: dict) -> None:
    obj(p, 'policy')
    if type(p.get('schema_version')) is int and p['schema_version'] == 1:
        raise PolicyError('schema_version: manually convert the version-one policy in gsd-cli.config.json '
                          'to version 2 (see MIGRATION.md)')
    if 'gsd' not in p:
        raise PolicyError('gsd.min_version is required; add "gsd": {"min_version": "1.21.0"} '
                          'to gsd-cli.config.json, choosing the minimum your project requires')
    if type(p.get('schema_version')) is not int or p['schema_version'] != 2:
        raise PolicyError('schema_version: expected 2')
    obj(p, 'policy', ('gsd', 'schema_version', 'runtimes', 'gsd_defaults'))
    gsd = obj(p['gsd'], 'gsd', ('min_version',))
    try:
        parse_version(gsd['min_version'])
    except VersionError as exc:
        raise PolicyError(f'gsd.min_version: {exc}') from exc

    for runtime, section in obj(p['runtimes'], 'runtimes', RUNTIMES).items():
        path = f'runtimes.{runtime}'
        obj(section, path, ('blueprints', 'review'))
        validate_review(section['review'], f'{path}.review')
        blueprints_path = f'{path}.blueprints'
        blueprints = obj(section['blueprints'], blueprints_path)
        if not blueprints:
            raise PolicyError(f'{blueprints_path}: expected at least one blueprint')
        for name, blueprint in blueprints.items():
            blueprint_path = f'{blueprints_path}.{name}'
            if not isinstance(name, str) or not re.fullmatch(BLUEPRINT_NAME_PATTERN, name):
                raise PolicyError(f'{blueprint_path}: invalid blueprint name')
            obj(blueprint, blueprint_path, ('session', 'phases'), ('agents',))
            validate_settings(blueprint['session'], f'{blueprint_path}.session', runtime)
            phases = obj(blueprint['phases'], f'{blueprint_path}.phases', PHASES)
            for phase, settings in phases.items():
                validate_settings(settings, f'{blueprint_path}.phases.{phase}', runtime, agent=True)
            for agent, settings in obj(blueprint.get('agents', {}), f'{blueprint_path}.agents').items():
                agent_path = f'{blueprint_path}.agents.{agent}'
                if not is_agent_name(agent):
                    raise PolicyError(f'{agent_path}: expected a GSD agent name')
                validate_settings(settings, agent_path, runtime, agent=True, partial=True)
    obj(p['gsd_defaults'], 'gsd_defaults')


def select_blueprint(p: dict, runtime: str, blueprint: str | None) -> dict:
    """Select a runtime-local blueprint without depending on an installation."""
    validate(p)
    choice(runtime, RUNTIMES, 'runtime')
    blueprints = p['runtimes'][runtime]['blueprints']
    if blueprint not in blueprints:
        reason = 'blueprint required' if blueprint is None else f'unknown blueprint {blueprint!r}'
        raise PolicyError(f'runtimes.{runtime}.blueprints: {reason}. Choose from {", ".join(sorted(blueprints))}')
    return blueprints[blueprint]


def resolve(p: dict, runtime: str, blueprint: str, catalog: dict) -> dict:
    """Expand blueprint settings against the validated installed manifest."""
    selected = select_blueprint(p, runtime, blueprint)
    path = f'runtimes.{runtime}.blueprints.{blueprint}'
    registered = catalog['agents']
    overrides = selected.get('agents', {})
    for name in sorted(overrides.keys() - registered.keys()):
        raise PolicyError(f'{path}.agents.{name}: role is missing from the installed {runtime} GSD catalog')

    review = p['runtimes'][runtime]['review']
    values = {('review', 'reviewer_instances', name): reviewer for name, reviewer in review['reviewer_instances'].items()}
    values.update({('review', 'effort', adapter): effort for adapter, effort in review['effort'].items()})
    values['review', 'default_reviewers'] = review['default_reviewers']
    values['review', 'parallel_lanes'] = review['parallel_lanes']
    agents = {}
    for name, metadata in registered.items():
        if not is_agent_name(name):
            raise PolicyError(f'catalog.agents.{name!r}: expected a GSD agent name')
        phase = metadata.get('phaseType')
        defaults = selected['phases'].get(phase, {})
        override = overrides.get(name, {})
        agent = {'phase': phase}
        for field in ('model', 'effort'):
            if field in override:
                agent[field] = override[field]
                agent[f'{field}_source'] = f'{path}.agents.{name}.{field}'
            elif field in defaults:
                agent[field] = defaults[field]
                agent[f'{field}_source'] = f'{path}.phases.{phase}.{field}'
            elif override:
                raise PolicyError(f'{path}.agents.{name}.{field}: required because the installed role '
                                  'has no configured phase to supply this field')
            else:
                agent[field] = None
                agent[f'{field}_source'] = None
        agents[name] = agent
        if agent['model'] is not None:
            values['model_overrides', name] = agent['model']
            values['effort', 'agent_overrides', name] = agent['effort']
    return {**selected['session'], 'values': values, 'reviewers': review['default_reviewers'],
            'review': review, 'agents': agents}
