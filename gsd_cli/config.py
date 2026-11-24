"""Project discovery, three-way capture and recoverable per-file replacements.

The POSIX lock covers preparation only. Running AI sessions are not isolated.
"""
import base64
import copy
import fcntl
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .claude_agents import (AgentError, check_agent_path, check_project_identities, check_untracked,
                           is_agent_path, plan_agents, validate_owned)
from .policy import PHASES, RUNTIMES, TRANSIENT, is_agent_name, load_default, resolve, validate
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


class CatalogError(ConfigError):
    """The selected installation cannot supply a usable blueprint catalog."""


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


def read_bytes(path: Path) -> bytes | None:
    safe_path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ConfigError(f'Expected regular file: {path}')
        return handle.read()


def read_text(path: Path) -> str | None:
    content = read_bytes(path)
    return content.decode('utf-8', errors='surrogateescape') if content is not None else None


def atomic_write(path: Path, content: str | bytes | None, *, before=MISSING, check=None) -> None:
    if isinstance(content, str):
        content = content.encode('utf-8', errors='surrogateescape')
    if before is MISSING and read_bytes(path) == content:
        return

    def check_target():
        if check:
            check(path)
        if before is not MISSING and read_bytes(path) != before:
            raise ConfigError(f'{path} was edited externally; preserve edits and reconcile the journal')

    if content is None:
        check_target()
        path.unlink()
        fsync_directory(path.parent)
        return
    fd, name = tempfile.mkstemp(prefix='.gsd-cli-tmp-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        check_target()
        if before is None:
            # Installing a new file must never replace one created after the
            # preimage check. Linking the flushed temporary inode is exclusive.
            try:
                os.link(name, path)
            except FileExistsError as exc:
                raise ConfigError(f'{path} was created externally; preserve it and reconcile the journal') from exc
            os.unlink(name)
        else:
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
    return validate_state(read_json(root / STATE))


def validate_state(state: dict) -> dict:
    if not isinstance(state, dict):
        raise ConfigError('Invalid synchronization baseline metadata')
    try:
        validate_owned(state.get('claude_agents', {}))
    except AgentError as exc:
        raise ConfigError(str(exc)) from exc
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


def journal_images(name: str, entry: dict, version: int) -> tuple[bytes | None, bytes | None]:
    if not isinstance(entry, dict) or set(entry) != {'before', 'after'}:
        raise ConfigError(f'Invalid recovery entry for {name}')
    images = []
    for field in ('before', 'after'):
        value = entry[field]
        if value is None and (field == 'before' or is_agent_path(name)):
            images.append(None)
        elif isinstance(value, str):
            try:
                images.append(value.encode() if version == 1 else base64.b64decode(value, validate=True))
            except ValueError as exc:
                raise ConfigError(f'Invalid recovery image for {name}') from exc
        else:
            raise ConfigError(f'Invalid recovery image for {name}')
    return tuple(images)


def validate_agent_recovery(root: Path, entries: dict, *, resuming: bool) -> None:
    agent_paths = {name for name in entries if is_agent_path(name)}
    if STATE in entries:
        maps = []
        for image in entries[STATE]:
            try:
                state = validate_state(json.loads(image, parse_constant=reject_constant)) if image is not None else {}
            except ValueError as exc:
                raise ConfigError(f'Invalid synchronization metadata in recovery journal: {exc}') from exc
            maps.append(state.get('claude_agents', {}))
        previous, desired = maps
    elif agent_paths:
        previous = desired = (load_state(root) or {}).get('claude_agents', {})
    else:
        return
    # Ownership transitions must be supported by a journal target. Forgetting
    # an already missing file is the sole transition with no file operation.
    changed = {name for name in previous.keys() | desired.keys() if previous.get(name) != desired.get(name)}
    for name in changed | agent_paths:
        check_agent_path(root / name)
        if name not in entries:
            if name in desired or read_bytes(root / name) is not None:
                raise ConfigError(f'Invalid ownership transition in recovery journal: {name}')
            continue
        before, after = entries[name]
        if before is not None and hashlib.sha256(before).hexdigest() != previous.get(name):
            raise ConfigError(f'Recovery preimage has no matching ownership: {name}')
        digest = hashlib.sha256(after).hexdigest() if after is not None else None
        if digest != desired.get(name) or before is None and after is None:
            raise ConfigError(f'Invalid recovery postimage or ownership: {name}')
    if not (changed or agent_paths):
        return
    check_untracked(root, changed | agent_paths)
    if resuming:
        # While the launcher was offline, a previously unchanged agent may
        # have been edited, tracked or shadowed by a newly declared identity.
        check_untracked(root, desired.keys() - (changed | agent_paths))
        check_project_identities(root, desired)
        for name in desired.keys() - entries.keys():
            content = read_bytes(root / name)
            if content is None or hashlib.sha256(content).hexdigest() != desired[name]:
                raise ConfigError(f'Cannot resume recovery: {name} was edited externally')
        current_ignore = read_bytes(root / '.gitignore') or b''
        final_ignore = entries['.gitignore'][1] if '.gitignore' in entries else current_ignore
        agent_ignore_block(final_ignore, desired, desired)
        validate_agent_ignores(root, agent_git(root), final_ignore, desired, current_ignore == final_ignore)


def recover(root: Path) -> None:
    safe_path(root / JOURNAL)
    if not (root / JOURNAL).exists():
        return
    journal = read_json(root / JOURNAL)
    files = journal.get('files')
    version = journal.get('version')
    if (type(version) is not int or version not in (1, 2) or not isinstance(files, dict)
            or not files or type(journal.get('untrack')) is not bool):
        raise ConfigError('Invalid recovery journal; inspect .planning/.gsd-cli-journal.json')
    entries = {}
    for name, entry in files.items():
        if name not in TARGETS and not (version == 2 and is_agent_path(name)):
            raise ConfigError(f'Invalid recovery path: {name}')
        entries[name] = journal_images(name, entry, version)
    apply_transaction(root, entries, version, journal['untrack'], resuming=True)


def apply_transaction(root: Path, entries: dict, version: int, untrack: bool, *,
                      resuming: bool, check_inputs=None) -> None:
    agents = {name for name in entries if is_agent_path(name)}
    index = None
    if agents:
        result = git(root, 'rev-parse', '--git-path', 'index')
        index = root / (result.stdout.rstrip('\n') if result.returncode == 0 else '.git/index')
        index_stamp = file_stamp(index)

    def check_agent_target(path):
        nonlocal index_stamp
        try:
            check_agent_path(path)
            current = file_stamp(index)
            if current != index_stamp:
                check_untracked(root, agents)
                index_stamp = current
        except AgentError as exc:
            raise ConfigError(str(exc)) from exc

    try:
        if version == 2:
            validate_agent_recovery(root, entries, resuming=resuming)
    except AgentError as exc:
        raise ConfigError(str(exc)) from exc
    # Check every target before the first write, including partially replayed
    # postimages. Version one used Python's universal-newline text reads.
    pending = []
    for name, (before, after) in entries.items():
        raw = current = read_bytes(root / name)
        if version == 1 and current is not None:
            current = current.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
        if current == after and (resuming or before == after):
            continue
        if current != before:
            if not resuming:
                raise ConfigError(f'{name} changed during preparation; retry')
            raise ConfigError(f'Cannot resume recovery: {name} was edited externally; preserve edits and reconcile the journal')
        pending.append((name, raw, after))
    if untrack and git_tracked(root):
        check_staged(root)
    if not resuming:
        files = {name: {key: base64.b64encode(image).decode('ascii') if image is not None else None
                        for key, image in zip(('before', 'after'), pair)} for name, pair in entries.items()}
        journal = serialize({'version': version, 'files': files, 'untrack': untrack})
        if check_inputs:
            check_inputs()
        if (root / JOURNAL).exists():
            raise ConfigError('Pending configuration journal; recover before starting a transaction')
        atomic_write(root / JOURNAL, journal, before=None)
    for name, before, after in pending:
        if is_agent_path(name):
            check_agent_path(root / name)
            for directory in (root / '.claude', root / '.claude/agents'):
                if not directory.exists():
                    directory.mkdir()
                    fsync_directory(directory.parent)
        atomic_write(root / name, after, before=before, check=check_agent_target if name in agents else None)
    if untrack and git_tracked(root):
        check_staged(root)
        result = git(root, 'rm', '--cached', '--', WORKING)
        if result.returncode:
            raise ConfigError(f'Cannot untrack config.json; recovery retained: {result.stderr.strip()}')
    if resuming:
        # A visible postimage may have survived an interruption between its
        # rename/unlink and its directory fsync. Persist directory creation
        # as well, even when every target already matched the journal.
        parents = {(root / name).parent for name in entries}
        if agents:
            parents.update((root, root / '.claude'))
        for parent in sorted(parents, key=lambda path: len(path.parts), reverse=True):
            if parent.is_dir():
                fsync_directory(parent)
    (root / JOURNAL).unlink()
    fsync_directory(root / '.planning')


def transaction(root: Path, contents: dict, untrack=False, *, check_inputs=None) -> None:
    entries = {}
    for name, content in contents.items():
        if is_agent_path(name):
            check_agent_path(root / name)
            if isinstance(content, tuple):
                entries[name] = content
                continue
        elif name not in TARGETS or content is None:
            raise ConfigError(f'Invalid transaction path or deletion: {name}')
        after = content.encode('utf-8', errors='surrogateescape') if isinstance(content, str) else content
        before = read_bytes(root / name)
        if before != after:
            entries[name] = (before, after)
    if not entries and not untrack:
        if check_inputs:
            check_inputs()
        return
    if not entries:
        # An index-only recovery still records the shared default precondition.
        entries[DEFAULT] = (read_bytes(root / DEFAULT),) * 2
    apply_transaction(root, entries, 2, untrack, resuming=False, check_inputs=check_inputs)


def prepare(default: dict, working: dict | None, state: dict | None,
            resolved: dict) -> tuple[dict, dict, dict, list[str]]:
    """Calculate a launch transaction without modifying inputs or files."""
    current = managed_paths(resolved)
    previous = {tuple(p) for p in state['managed']} if state else set()
    excluded = current | previous | set(TRANSIENT)
    # Init may predate the selected runtime's catalog. Release only leaves
    # copied from the old working config, with their original values intact.
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
    return data, merged, metadata, changed_paths(default, merged)


@dataclass
class AgentGit:
    toplevel: Path
    git_dir: Path
    index: Path
    exclude: Path
    global_exclude: Path

    def ancestor_ignores(self, root: Path) -> list[Path]:
        return [self.toplevel / parent / '.gitignore' for parent in root.absolute().relative_to(self.toplevel).parents]


def agent_git(root: Path) -> AgentGit | None:
    result = git(root, 'rev-parse', '--show-toplevel', '--absolute-git-dir', '--git-path', 'index',
                 '--git-path', 'info/exclude')
    if result.returncode:
        return None
    paths = [root.absolute() / path for path in result.stdout.splitlines()]
    configured = git(root, 'config', '--path', '--get', 'core.excludesFile')
    xdg = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    global_exclude = root / configured.stdout.rstrip('\n') if configured.returncode == 0 else xdg / 'git/ignore'
    return AgentGit(*paths, global_exclude)


def file_stamp(path: Path):
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def input_stamps(root: Path, runtime: str, installation: Path, repository: AgentGit | None) -> dict:
    paths = [root / name for name in (POLICY, DEFAULT, WORKING, STATE, LOCK, JOURNAL)]
    catalog = installation / 'bin/shared/model-catalog.json'
    try:
        check_agent_path(catalog)
    except AgentError as exc:
        raise CatalogError(str(exc)) from exc
    paths.append(catalog)
    if runtime == 'claude':
        paths.extend(root / name for name in ('.gitignore', '.claude/.gitignore', '.claude/agents/.gitignore'))
        # A newly added definition in any nested directory can introduce a
        # duplicate identity even when its filename does not match the role.
        for directory in (installation.parent / 'agents', root / '.claude/agents'):
            check_agent_path(directory)
            paths.append(directory)
            for current, dirs, files in os.walk(directory):
                paths.extend(Path(current) / d for d in dirs)
                paths.extend(Path(current) / f for f in files if f.endswith('.md'))
    for path in paths:
        safe_path(path)
    if repository:
        paths.extend((repository.index, repository.exclude, repository.global_exclude))
        paths.extend(repository.ancestor_ignores(root))
    return {path: file_stamp(path) for path in paths}


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


def prepare_project(root: Path, policy: dict, runtime: str, blueprint: str,
                    installation: Path, *, write: bool) -> tuple[dict, list[str], dict, dict]:
    from .resolver import load_catalog  # resolver uses config.read_json

    repository = agent_git(root) if runtime == 'claude' else None
    before = input_stamps(root, runtime, installation, repository)
    if before[root / JOURNAL] is not None:
        raise ConfigError('Pending configuration recovery; preview cannot recover or write project files')

    def check_inputs():
        if before != input_stamps(root, runtime, installation, repository):
            raise ConfigError('Project configuration or installation changed during preparation; retry')

    if not json_equal(read_json(root / POLICY), policy):
        raise ConfigError('Project policy changed during preparation; retry')
    try:
        catalog = load_catalog(installation)
    except ConfigError as exc:
        raise CatalogError(str(exc)) from exc
    resolved = resolve(policy, runtime, blueprint, catalog)
    default = read_json(root / DEFAULT)
    working = read_json(root / WORKING) if before[root / WORKING] is not None else None
    state = load_state(root) or {}
    data, merged, metadata, captured = prepare(default, working, state or None, resolved)
    contents = {DEFAULT: serialize(merged), WORKING: serialize(data)}
    changes, evidence = {}, {}
    if runtime == 'claude':
        plan = plan_agents(root, installation, resolved['agents'], state.get('claude_agents', {}))
        changes, evidence = plan.changes, plan.evidence
        metadata['claude_agents'] = plan.owned
        original = read_bytes(root / '.gitignore') or b''
        candidate = agent_ignore_block(original, state.get('claude_agents'), plan.owned)
        if candidate != original:
            contents['.gitignore'] = candidate
        validate_agent_ignores(root, repository, candidate, plan.owned, candidate == original)
    elif 'claude_agents' in state:
        metadata['claude_agents'] = state['claude_agents']
    contents[STATE] = serialize(metadata)
    if write:
        contents.update(changes)
        transaction(root, contents, check_inputs=check_inputs)
    else:
        check_inputs()
    return data, captured, resolved, evidence


def preview(root: Path, policy: dict, runtime: str, blueprint: str,
            installation: Path) -> tuple[dict, list[str], dict, dict]:
    with preview_lock(root):
        try:
            return prepare_project(root, policy, runtime, blueprint, installation, write=False)
        except AgentError as exc:
            raise ConfigError(str(exc)) from exc


def synchronize(root: Path, policy: dict, runtime: str, blueprint: str,
                installation: Path) -> tuple[dict, list[str], dict, dict]:
    with locked(root):
        recover(root)
        try:
            return prepare_project(root, policy, runtime, blueprint, installation, write=True)
        except AgentError as exc:
            raise ConfigError(str(exc)) from exc


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


AGENT_BLOCK_START = b'# BEGIN gsd-cli generated Claude agents'
AGENT_BLOCK_END = b'# END gsd-cli generated Claude agents'


def agent_ignore_block(original: bytes, previous: dict | None, desired: dict) -> bytes:
    lines = original.splitlines(keepends=True)
    slots = [(i, line.rstrip(b'\r\n')) for i, line in enumerate(lines)
             if line.rstrip(b'\r\n') in (AGENT_BLOCK_START, AGENT_BLOCK_END)]
    if slots:
        if [marker for _, marker in slots] != [AGENT_BLOCK_START, AGENT_BLOCK_END]:
            raise ConfigError('Malformed generated Claude agent block in .gitignore')
        start, end = (i for i, _ in slots)
        rules = [line.rstrip(b'\r\n').decode('ascii', errors='replace') for line in lines[start+1:end]]
        if (any(not r.startswith('/') or not is_agent_path(r[1:]) for r in rules)
                or rules != sorted(set(rules))):
            raise ConfigError('Edited generated Claude agent rules in .gitignore')
        existing = [r[1:] for r in rules]
    else:
        start = end = len(lines)
        existing = []
    if previous is not None and existing != sorted(previous):
        raise ConfigError('Edited generated Claude agent block in .gitignore; reconcile the owned path list')
    if existing == sorted(desired):
        return original
    newline = b'\r\n' if lines and lines[0].endswith(b'\r\n') else b'\n'
    block = b''
    if desired:
        block = newline.join([AGENT_BLOCK_START, *(b'/' + p.encode() for p in sorted(desired)),
                              AGENT_BLOCK_END, b''])
    prefix = b''.join(lines[:start])
    if block and prefix and not prefix.endswith(b'\n'):
        prefix += newline
    return prefix + block + b''.join(lines[end+1:])


def validate_agent_ignores(root: Path, repository: AgentGit | None, candidate: bytes, owned: dict,
                           already_present: bool) -> None:
    if not owned or repository is None:
        return

    def check(directory, *options):
        # One invocation for all roles, irrespective of catalog size.
        paths = b'\0'.join(path.encode() for path in owned) + b'\0'
        result = subprocess.run(['git', '-C', str(directory), *options, 'check-ignore', '--no-index', '-z', '--stdin'],
                                input=paths, capture_output=True)
        if result.returncode not in (0, 1):
            raise ConfigError(f'Cannot validate generated Claude agent rules: {os.fsdecode(result.stderr)}')
        hidden = {os.fsdecode(name) for name in result.stdout.split(b'\0') if name}
        exposed = sorted(owned.keys() - hidden)
        if exposed:
            raise ConfigError('Git rules expose generated Claude agents: ' + ', '.join(exposed))

    if already_present:
        check(root)
        return
    # Evaluate the proposed worktree against this repository's actual config
    # and info/exclude. A parent directory exclusion can disable nested rules.
    with tempfile.TemporaryDirectory(prefix='gsd-agent-ignore-') as directory:
        scratch = Path(directory)
        relative = root.absolute().relative_to(repository.toplevel)
        probe = scratch / relative
        (probe / '.claude/agents').mkdir(parents=True)
        (probe / '.gitignore').write_bytes(candidate)
        nested = [root.absolute() / name for name in ('.claude/.gitignore', '.claude/agents/.gitignore')]
        for path in repository.ancestor_ignores(root) + nested:
            content = read_bytes(path)
            if content is not None:
                (scratch / path.relative_to(repository.toplevel)).write_bytes(content)
        check(probe, '--git-dir', str(repository.git_dir), '--work-tree', str(scratch))



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
        (probe / '.gitignore').write_bytes(candidate.encode('utf-8', errors='surrogateescape'))
        if nested is not None:
            (probe / '.planning/.gitignore').write_bytes(nested.encode('utf-8', errors='surrogateescape'))
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
