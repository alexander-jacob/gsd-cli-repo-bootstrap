"""Offline SemVer and runtime-specific GSD installation checks.

No installed GSD code is executed. The check describes a bundle, not the state
of all hooks, agent definitions, or paths embedded in third-party skills.
"""
import os
import re
import stat
from dataclasses import dataclass
from functools import total_ordering
from pathlib import Path
from typing import Mapping

VERSION_LIMIT = 4096
SEMVER = re.compile(
    r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
    r'(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?'
    r'(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?'
)
CONFIG_ENV = {'claude': 'CLAUDE_CONFIG_DIR', 'codex': 'CODEX_HOME'}


class VersionError(ValueError):
    """A version requirement or installation cannot be interpreted."""


@total_ordering
@dataclass(frozen=True)
class Version:
    core: tuple[int, int, int]
    prerelease: tuple[str, ...]

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        if self.core != other.core:
            return self.core < other.core
        if not self.prerelease or not other.prerelease:
            return bool(self.prerelease) and not other.prerelease
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            if left.isdigit() and right.isdigit():
                return int(left) < int(right)
            if left.isdigit() != right.isdigit():
                return left.isdigit()
            return left < right
        return len(self.prerelease) < len(other.prerelease)


def parse_version(value: str) -> Version:
    if not isinstance(value, str) or len(value) > VERSION_LIMIT:
        raise VersionError('expected a SemVer string such as 1.20.1')
    match = SEMVER.fullmatch(value)
    if match is None:
        raise VersionError('expected a complete SemVer such as 1.20.1 (no v prefix)')
    prerelease = tuple(match[4].split('.')) if match[4] else ()
    if any(part.isdigit() and len(part) > 1 and part.startswith('0') for part in prerelease):
        raise VersionError('numeric prerelease identifiers cannot have leading zeroes')
    return Version(tuple(int(match[i]) for i in (1, 2, 3)), prerelease)


@dataclass(frozen=True)
class CheckResult:
    runtime: str
    directory: Path
    installed: str | None
    minimum: str
    ok: bool
    message: str


def installation_dir(root: Path, runtime: str, env: Mapping[str, str], home: Path) -> Path:
    override = env.get(CONFIG_ENV[runtime])
    if override:
        if override == '~' or override.startswith('~/'):
            config_dir = home / override[2:] if override != '~' else home
        else:
            config_dir = Path(override)
        if not config_dir.is_absolute():
            config_dir = root / config_dir
        return Path(os.path.abspath(config_dir)) / 'gsd-core'
    local = root / f'.{runtime}' / 'gsd-core'
    try:
        local.lstat()  # Includes broken symlinks: incomplete local installs block.
    except FileNotFoundError:
        return home / f'.{runtime}' / 'gsd-core'
    except OSError:
        pass  # An inaccessible local installation must not be bypassed either.
    return local


def read_version(path: Path) -> str:
    # O_NONBLOCK also prevents a race replacing a regular file with a FIFO
    # between inspection and open. fstat checks the actual opened descriptor.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise VersionError('VERSION must be a regular file')
        content = handle.read(VERSION_LIMIT + 1)
    if len(content) > VERSION_LIMIT:
        raise VersionError(f'VERSION exceeds {VERSION_LIMIT} bytes')
    return content.decode('utf-8').strip()


def check_installation(root: Path, runtime: str, minimum: str, *,
                       env: Mapping[str, str] | None = None, home: Path | None = None) -> CheckResult:
    required = parse_version(minimum)
    if runtime not in CONFIG_ENV:
        raise VersionError('expected runtime claude or codex')
    directory = installation_dir(root, runtime, os.environ if env is None else env,
                                 Path.home() if home is None else home)
    installed = None
    try:
        raw = read_version(directory / 'VERSION')
        actual = parse_version(raw)
        installed = raw
        for name in ('workflows/update.md', 'bin/gsd-tools.cjs'):
            path = directory / name
            if not path.is_file():
                raise VersionError(f'incomplete installation: {name} is missing or not a regular file')
        if actual < required:
            return CheckResult(runtime, directory, installed, minimum, False, 'below the project minimum')
    except (OSError, UnicodeError, VersionError) as exc:
        return CheckResult(runtime, directory, installed, minimum, False, f'Cannot verify GSD VERSION/install: {exc}')
    return CheckResult(runtime, directory, installed, minimum, True, 'meets the project minimum')


def format_result(result: CheckResult) -> str:
    state = 'PASS' if result.ok else 'FAIL'
    return (f'{state} {result.runtime}: GSD {result.installed or "unknown"}; '
            f'required >= {result.minimum}; path={result.directory}; {result.message}')
