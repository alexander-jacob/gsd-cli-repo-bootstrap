"""Calculate project-local Claude agent updates from pristine installation files."""
import codecs
import hashlib
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .policy import CLAUDE_AGENT_MODELS, CLAUDE_EFFORTS, is_agent_name


class AgentError(ValueError):
    """An agent cannot be generated or retired safely."""


@dataclass
class AgentPlan:
    changes: dict[str, tuple[bytes | None, bytes | None]]
    owned: dict[str, str]
    evidence: dict[str, dict]


def is_agent_path(path: str) -> bool:
    if not isinstance(path, str):
        return False
    name = Path(path).stem
    return is_agent_name(name) and path == f'.claude/agents/{name}.md'


def validate_owned(owned: dict) -> None:
    if not isinstance(owned, dict):
        raise AgentError('claude_agents: expected an ownership map')
    for path, digest in owned.items():
        if not is_agent_path(path) or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise AgentError(f'claude_agents: invalid ownership record for {path!r}')


def check_agent_path(path: Path) -> None:
    for ancestor in (*reversed(path.parents), path):
        if ancestor.is_symlink():
            raise AgentError(f'Refusing symlink: {ancestor}')
        if ancestor != path and ancestor.exists() and not ancestor.is_dir():
            raise AgentError(f'Expected directory: {ancestor}')


def check_untracked(root: Path, paths) -> None:
    paths = set(paths)
    if not paths:
        return
    ancestors = {str(parent) for path in paths for parent in Path(path).parents if parent != Path('.')}
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--', *sorted(paths | ancestors)],
                            capture_output=True, env={**os.environ, 'LC_ALL': 'C'})
    if result.returncode:
        if b'not a git repository' in result.stderr:
            return
        raise AgentError(f'Cannot check Git index in {root}: {os.fsdecode(result.stderr).strip()}')
    for entry in result.stdout.split(b'\0'):
        path = os.fsdecode(entry)
        if path in paths or path in ancestors or any(str(parent) in paths for parent in Path(path).parents):
            raise AgentError(f'Refusing Git-tracked agent path: {path}')


# Only plain or quoted scalar settings can be patched without reserializing YAML.
_KEY = re.compile(rb"""(?P<quote>['"]?)(?P<key>[A-Za-z0-9_.-]+)(?P=quote)[ \t]*:(?:[ \t]+|$)(?P<value>.*)""")
_SCALAR = re.compile(rb"""(?P<quote>['"]?)(?P<token>[A-Za-z0-9_.-]+)(?P=quote)(?:[ \t]+\#.*|[ \t]*)""")


def _header(source: bytes) -> tuple[list[bytes], int]:
    lines = source.splitlines(keepends=True)
    if lines and lines[0].removeprefix(codecs.BOM_UTF8).rstrip(b'\r\n') == b'---':
        for i, line in enumerate(lines[1:], 1):
            if line.rstrip(b'\r\n') == b'---':
                return lines, i
    return lines, 0


def _header_content(lines: list[bytes], end: int) -> tuple[int, list[tuple[int, bytes]]]:
    content = [(i, lines[i].rstrip(b'\r\n')) for i in range(1, end)
               if lines[i].strip() and not lines[i].lstrip().startswith(b'#')]
    indent = min((len(line) - len(line.lstrip(b' ')) for _, line in content), default=0)
    return indent, [(i, line[indent:]) for i, line in content]


def _sequence_item(line: bytes) -> bool:
    return line == b'-' or line.startswith((b'- ', b'-\t'))


def render_definition(source: bytes, name: str, model: str, effort: str) -> bytes:
    if not is_agent_name(name) or model not in CLAUDE_AGENT_MODELS or effort not in CLAUDE_EFFORTS:
        raise AgentError(f'{name}: invalid Claude agent name, model or effort')
    lines, end = _header(source)
    if not end:
        raise AgentError(f'{name}: missing or incomplete Markdown frontmatter')
    values = {'name': name, 'model': model, 'effort': effort}
    seen = set()
    previous = None
    indent, content = _header_content(lines, end)
    for i, line in content:
        if line.startswith(b' ') or _sequence_item(line):
            if previous is None or previous in values:
                raise AgentError(f'{name}: ambiguous indented header at line {i+1}')
            continue
        match = _KEY.fullmatch(line)
        if not match:
            raise AgentError(f'{name}: ambiguous top-level frontmatter at line {i+1}')
        previous = match['key'].decode('ascii')
        if previous not in values:
            continue
        scalar = _SCALAR.fullmatch(match['value'])
        if previous in seen or not scalar:
            raise AgentError(f'{name}: duplicate or ambiguous {previous} header')
        seen.add(previous)
        if previous == 'name' and scalar['token'] != name.encode():
            raise AgentError(f'{name}: source declares another name')
        start = indent + match.start('value') + scalar.start('token')
        lines[i] = lines[i][:start] + values[previous].encode() + lines[i][start + len(scalar['token']):]
    if 'name' not in seen:
        raise AgentError(f'{name}: missing name header')
    newline = lines[0].removeprefix(codecs.BOM_UTF8)[3:]
    lines[end:end] = [b' ' * indent + f'{key}: {values[key]}'.encode() + newline
                      for key in ('model', 'effort') if key not in seen]
    return b''.join(lines)


def _read(path: Path) -> bytes:
    check_agent_path(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise AgentError(f'Expected regular agent file: {path}')
        return handle.read()


def _raise(error):
    raise error


def _declared_names(source: bytes, path: Path):
    """Scan only root mapping keys, including uniformly indented YAML headers."""
    lines, end = _header(source)
    _, content = _header_content(lines, end)
    found_name = False
    ambiguous = False
    for _, line in content:
        if line.startswith(b' ') or _sequence_item(line):
            continue
        key = _KEY.fullmatch(line)
        if key is None:
            ambiguous = True
        elif key['key'] == b'name':
            found_name = True
            scalar = _SCALAR.fullmatch(key['value'])
            if scalar:
                yield scalar['token'].decode()
            else:
                # Human-readable names cannot equal a managed role. Complex YAML
                # expressions could, so do not silently skip them.
                literal = rb"""(?:'[^']*'|"[^"\\]*"|[A-Za-z0-9_.-]+(?: +[A-Za-z0-9_.-]+)+)"""
                if not re.fullmatch(literal + rb'(?:[ \t]+\#.*|[ \t]*)', key['value']):
                    raise AgentError(f'{path}: ambiguous declared name')
    if ambiguous and not found_name:
        raise AgentError(f'{path}: cannot verify agent identity in ambiguous frontmatter')


def _definitions(directory: Path, roles: set[str]) -> dict[str, Path]:
    """Index declared names, independent of filenames and project subdirectories."""
    found = {}
    check_agent_path(directory)
    if not roles or not directory.exists():
        return found
    if not directory.is_dir():
        raise AgentError(f'Expected agent directory: {directory}')
    for current, dirs, files in os.walk(directory, onerror=_raise):
        for entry in sorted(dirs):
            check_agent_path(Path(current) / entry)
        for filename in sorted(files):
            if not filename.endswith('.md'):
                continue
            path = Path(current) / filename
            for role in _declared_names(_read(path), path):
                if role in roles:
                    if role in found:
                        raise AgentError(f'Duplicate identity {role}: {found[role]} and {path}')
                    found[role] = path
    return found


def plan_agents(root: Path, installation: Path, agents: dict, owned: dict[str, str]) -> AgentPlan:
    validate_owned(owned)
    desired = {}
    for name, settings in agents.items():
        if not is_agent_name(name):
            raise AgentError(f'Invalid catalog agent name: {name!r}')
        if settings['model'] is not None or settings['effort'] is not None:
            desired[f'.claude/agents/{name}.md'] = settings
    plan = AgentPlan({}, {}, {})
    paths = desired.keys() | owned.keys()
    if not paths:
        return plan
    source_dir = installation.parent / 'agents'
    project_dir = root / '.claude/agents'
    try:
        check_agent_path(installation)
        check_agent_path(project_dir)
        check_agent_path(source_dir)
        if project_dir.resolve() == source_dir.resolve():
            raise AgentError(f'Installed source and project agent directories coincide: {source_dir}')
        check_untracked(root, paths)
        sources = _definitions(source_dir, {Path(p).stem for p in desired})
        local = _definitions(project_dir, {Path(p).stem for p in desired})
        for rel in sorted(paths):
            path = root / rel
            role = path.stem
            try:
                before = _read(path)
            except FileNotFoundError:
                before = None
            if before is not None:
                if rel not in owned:
                    raise AgentError(f'Unowned project agent: {path}')
                if hashlib.sha256(before).hexdigest() != owned[rel]:
                    raise AgentError(f'Edited owned agent: {path}')
            source = None
            after = None
            settings = desired.get(rel, {})
            if rel in desired:
                if role in local and local[role] != path:
                    raise AgentError(f'{local[role]} already declares {role} for {path}')
                source = sources.get(role)
                if source is None:
                    raise AgentError(f'{source_dir}: missing installed source declaring {role}')
                if before is not None and path.samefile(source):
                    raise AgentError(f'{path}: destination aliases installed source {source}')
                try:
                    after = render_definition(_read(source), role, settings['model'], settings['effort'])
                except AgentError as exc:
                    raise AgentError(f'{source}: {exc}') from exc
                plan.owned[rel] = hashlib.sha256(after).hexdigest()
            if before == after:
                action = 'forget' if after is None else 'unchanged'
            else:
                plan.changes[rel] = (before, after)
                action = 'remove' if after is None else 'create' if before is None else 'update'
            plan.evidence[role] = dict(source=str(source.absolute()) if source else None,
                                       destination=rel, model=settings.get('model'),
                                       effort=settings.get('effort'), action=action)
    except OSError as exc:
        raise AgentError(f'Cannot prepare Claude agents: {exc}') from exc
    return plan
