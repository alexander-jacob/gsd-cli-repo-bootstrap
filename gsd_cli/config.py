"""Project discovery, three-way capture and recoverable per-file replacements.

The POSIX lock covers preparation only. Running AI sessions are not isolated.
"""
import copy
import fcntl
import json
import os
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .policy import PHASES, RUNTIMES, TRANSIENT, is_agent_name, load_default, validate
from .versions import installation_dir

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


def discover(start: Path | None = None, allow_bare: bool = False) -> Path:
    """Find the nearest project root; allow_bare (init only) also accepts a config-less .planning/."""
    start = (start or Path.cwd()).resolve()
    roots = (start, *start.parents)
    bare = allow_bare
    if allow_bare:
        # A stray .planning/ above the repository or in $HOME must not capture init.
        toplevel = git(start, 'rev-parse', '--show-toplevel')
        stop = Path(toplevel.stdout.strip()).resolve() if toplevel.returncode == 0 else None
        home = Path.home().resolve()
    for root in roots:
        if any((root / name).exists() for name in (WORKING, DEFAULT, POLICY)):
            return root
        if bare and root != home and (root / '.planning').is_dir():
            return root
        if bare and root == stop:
            bare = False
    if allow_bare:
        raise ConfigError('No GSD project found: run a GSD command such as gsd-map-codebase '
                          'or gsd-new-project first to create .planning/')
    raise ConfigError('No GSD project found: expected .planning/config.json or config.default.json')


def safe_path(path: Path) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise ConfigError(f'Refusing symlink: {path}')


def reject_constant(name: str):
    """Python's json accepts NaN and Infinity; strict JSON, GSD and every writer here do not."""
    raise ValueError(f'{name} is not valid JSON')


def read_json(path: Path) -> dict:
    safe_path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, 'r', encoding='utf-8') as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError('expected a regular file')
            data = json.load(handle, parse_constant=reject_constant)
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
    provisional = state.get('provisional', [])
    if not isinstance(provisional, list):
        raise ConfigError('Invalid provisional entries in synchronization metadata')
    for entry in provisional:
        path = entry.get('path') if isinstance(entry, dict) else None
        if (not isinstance(path, list) or not path or not is_agent_name(path[-1])
                or path[:-1] not in (['model_overrides'], ['effort', 'agent_overrides'])
                or 'seed' not in entry):
            raise ConfigError('Invalid provisional agent path in synchronization metadata')
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
        raise ConfigError('config.default.json contains managed/transient settings: ' + ', '.join(found)
                          + '; reconcile these paths in the shared defaults before retrying')
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


def prepare(default: dict, working: dict | None, state: dict | None,
            resolved: dict) -> tuple[dict, dict, dict, list[str]]:
    """Calculate a launch transaction without modifying inputs or files."""
    current = managed_paths(resolved)
    previous = {tuple(p) for p in state['managed']} if state else set()
    excluded = current | previous | set(TRANSIENT)
    # Init may predate the selected runtime's catalog. Release only leaves
    # copied from the old working config, with their original values intact.
    original_default = default
    default = copy.deepcopy(default)
    provisional = []
    for entry in (state or {}).get('provisional', []):
        path = tuple(entry['path'])
        if path not in current:
            provisional.append(entry)
            continue
        sources = [get_path(source, path) for source in (default, working) if source is not None]
        if all(value is MISSING for value in sources):
            continue
        if any(not json_equal(value, entry['seed']) for value in sources):
            raise ConfigError(f'Configuration conflict at {".".join(path)}; remove the edited seed '
                              'from config.json and config.default.json to accept blueprint management')
        remove_path(default, path)
    reject_owned(default, excluded)
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
    if provisional:
        metadata['provisional'] = provisional
    return data, merged, metadata, changed_paths(original_default, merged)


def input_stamps(root: Path) -> dict:
    stamps = {}
    for name in (POLICY, DEFAULT, WORKING, STATE, LOCK, JOURNAL):
        path = root / name
        safe_path(path)
        try:
            st = path.stat()
            stamps[name] = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
        except FileNotFoundError:
            stamps[name] = None
    return stamps


@contextmanager
def preview_lock(root: Path):
    """Probe an existing lock without creating or modifying a lock file."""
    safe_path(root / LOCK)
    try:
        handle = (root / LOCK).open('r')
    except FileNotFoundError:
        yield
        return
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ConfigError('Another gsd-cli process is preparing configuration; retry shortly') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def preview(root: Path, policy: dict, resolved: dict) -> tuple[dict, list[str]]:
    with preview_lock(root):
        before = input_stamps(root)
        if before[JOURNAL] is not None:
            raise ConfigError('Pending configuration recovery; preview cannot recover or write project files')
        if not json_equal(read_json(root / POLICY), policy):
            raise ConfigError('Project policy changed during preparation; retry')
        default = read_json(root / DEFAULT)
        working = read_json(root / WORKING) if before[WORKING] is not None else None
        state = load_state(root)
        data, _, _, captured = prepare(default, working, state, resolved)
        if before != input_stamps(root):
            raise ConfigError('Project configuration changed during preparation; retry')
        return data, captured


def synchronize(root: Path, policy: dict, resolved: dict) -> tuple[dict, list[str]]:
    with locked(root):
        recover(root)
        if not json_equal(read_json(root / POLICY), policy):
            raise ConfigError('Project policy changed during preparation; retry')
        default = read_json(root / DEFAULT)
        working = read_json(root / WORKING) if (root / WORKING).exists() else None
        data, merged, metadata, captured = prepare(default, working, load_state(root), resolved)
        transaction(root, {DEFAULT: serialize(merged), WORKING: serialize(data), STATE: serialize(metadata)})
        return data, captured


def initial_paths(root: Path, policy: dict) -> set:
    """Classify old generated settings independently of the first launch."""
    from .resolver import load_catalog  # resolver uses config.read_json

    paths = {('runtime',), ('model_policy', 'provider'), ('review', 'default_reviewers'),
             ('review', 'parallel_lanes')}
    paths.update(('models', phase) for phase in PHASES)
    for runtime, section in policy['runtimes'].items():
        paths.add(('model_policy', 'runtime_tiers', runtime))
        review = section['review']
        paths.update(('review', 'reviewer_instances', name) for name in review['reviewer_instances'])
        paths.update(('review', 'effort', adapter) for adapter in review['effort'])
        agents = {name for blueprint in section['blueprints'].values() for name in blueprint.get('agents', {})}
        directory = installation_dir(root, runtime, os.environ, Path.home())
        try:
            catalog = load_catalog(directory)
        except ConfigError:
            # Installation validation belongs to launch. An unavailable catalog
            # leaves its unknown working-config entries provisional.
            pass
        else:
            agents.update(name for name, entry in catalog['agents'].items() if entry.get('phaseType') in PHASES)
        for name in agents:
            paths.update((('model_overrides', name), ('effort', 'agent_overrides', name)))
    return paths


def provisional_entries(baseline: dict) -> list:
    entries = []
    for prefix in (('model_overrides',), ('effort', 'agent_overrides')):
        values = get_path(baseline, prefix)
        if isinstance(values, dict):
            entries.extend({'path': [*prefix, name], 'seed': value}
                           for name, value in sorted(values.items()) if is_agent_name(name))
    return entries


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
        policy = read_json(root / POLICY) if (root / POLICY).exists() else load_default()
        validate(policy)
        existing_state = load_state(root)
        paths = ({tuple(path) for path in existing_state['managed']} if existing_state is not None
                 else initial_paths(root, policy))
        provisional = []
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
            provisional = provisional_entries(baseline)
            default = seed_settings(policy['gsd_defaults'], baseline)
            reject_owned(default, paths | set(TRANSIENT))
        state = existing_state or {'version': 1, 'baseline': baseline, 'managed': sorted(paths)}
        if provisional:
            state['provisional'] = provisional
        ignores = ignore_text(root)
        validate_ignores(root, ignores)
        contents = {POLICY: serialize(policy), DEFAULT: serialize(default), STATE: serialize(state), '.gitignore': ignores}
        transaction(root, contents, untrack=git_tracked(root))
