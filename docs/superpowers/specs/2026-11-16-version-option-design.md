# `--version` option — short design

**Intent:** let users and tools see which gsd-cli release is installed without reading package metadata by hand.

**Goals:** `gsd-cli --version` and `gsd-cli -V` print `gsd-cli <version>` and exit 0, read-only, anywhere (no GSD project needed).
**Non-goals:** a JSON form or a `version` schema (the gsd-cli skill already detects 2.1.0+ via `gsd-cli schema`); reporting installed GSD versions (that is `check`).
**Anti-goals:** a second hard-coded version string that can drift from `pyproject.toml`.

**Approaches considered:**
1. Click `version_option` reading installed package metadata — **chosen**: single source of truth, standard Click behaviour.
2. A `__version__` constant in the package — rejected: duplicates `pyproject.toml`.
3. A `version` subcommand with `--json` — rejected: adds a schema nobody consumes yet.

**Design:**
- `@click.version_option` on the group with `package_name='gsd-workflow-cli'`, `prog_name='gsd-cli'`, message `%(prog)s %(version)s`, flags `-V`/`--version`.
- No installed metadata (source tree without install): print `gsd-cli unknown` instead of raising.
- `main()`: `--version`/`-V` wins over `--json`, like `--help`.
- Tests: `--version`, `-V`, outside a project, with `--json`.
- Docs: command lists in README, `docs/LAUNCHER.md`, `AGENTS.md`; CHANGELOG Unreleased "Added".

**Left to the builder:** where the metadata lookup lives (kept at the CLI boundary).
