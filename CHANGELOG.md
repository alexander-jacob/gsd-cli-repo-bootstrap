# Changelog

User-visible changes are recorded here, newest first. Changes under **Unreleased**
have not been assigned to a release in this document.

## Release tracking

| Status | Version | Release date |
|---|---|---|
| Unreleased | Not yet assigned | — |
| Released | [3.0.0](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v3.0.0) | 2026-11-24 |
| Released | [2.1.5](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.1.5) | 2026-11-16 |
| Released | [2.1.4](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.1.4) | 2026-11-16 |
| Released | [2.1.3](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.1.3) | 2026-11-16 |
| Released | [2.1.2](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.1.2) | 2026-11-16 |
| Released | [2.1.1](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.1.1) | 2026-11-16 |
| Released | [2.1.0](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.1.0) | 2026-11-16 |
| Released | [2.0.1](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.0.1) | 2026-11-13 |
| Released | [2.0.0](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.0.0) | 2026-11-13 |

The current package version in `pyproject.toml` is `3.0.0`. Version 2.0.0 is the
first release tracked here. Earlier release history has not been backfilled.

When releasing, move the Unreleased entries into a versioned section with its
release date (`YYYY-MM-DD`), update the tracking table and package version as
appropriate, and retain an empty Unreleased section for subsequent changes.

## Unreleased

## [3.0.0](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v3.0.0) — 2026-11-24

- Replace workflow/level launches with explicit `gsd-cli RUNTIME BLUEPRINT` selection. Policies and JSON output now use version 2. Existing project policies require [manual conversion](MIGRATION.md#convert-a-version-one-project-policy). Historical session reports remain readable.
- Resolve phase and per-agent model and effort from the installed runtime catalog, share review settings across a runtime’s blueprints, and manage ignored Claude agent definitions in the project. Preview shows field sources, planned file actions and resolver evidence.
- Launch either runtime with full permission bypass by default. Pass `--secure` for the runtime’s normal permissions.

## [2.1.5](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.1.5) — 2026-11-16

### Fixed

- `gsd-cli init` now finds a project whose `.planning/` has no config file yet, such as one created only by `gsd-map-codebase`. Other commands still require a config file.

## [2.1.4](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.1.4) — 2026-11-16

### Added

- A `test` extra (`pip install -e '.[test]'`) with pytest and pytest-xdist. Runtime dependencies are unchanged.
- A release guide (`docs/releasing.md`) covering gsd-cli releases and the matching skill, plugin and
  marketplace releases.

### Changed

- The documented test command, the `test` task and CI run the unchanged suite with
  `python -m pytest -n auto tests`, in parallel on all CPUs.

## [2.1.3](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.1.3) — 2026-11-16

### Fixed

- Combined short flags such as `-hV` or `-Vh` now print help or the version when `--json` is
  also given, as they do without it. Before, `--json` made them a JSON usage error. Clusters that
  Click rejects, such as `-hX`, still give the usage envelope.

## [2.1.2](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.1.2) — 2026-11-16

### Fixed

- A `NaN`, `Infinity` or `-Infinity` constant in a configuration or policy file is now reported as
  a `config` error naming the file (`NaN is not valid JSON`). Before, text-mode `status`, previews and
  JSON-mode previews crashed with a traceback, and `status --json` silently printed `null` in its place.

## [2.1.1](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.1.1) — 2026-11-16

### Added

- `gsd-cli --version` (`-V`) prints the installed gsd-cli version. It works outside a project and
  wins over `--json`.

## [2.1.0](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.1.0) — 2026-11-16

### Added

- Machine-readable output: `--json` for `status`, `check`, `policy`, `sessions` and
  `WORKFLOW RUNTIME --config`. Each prints one envelope
  (`schema_version`, `command`, `ok`, `data`, `error`) and never writes.
  See `docs/json-output.md`.
- `gsd-cli policy [--json]` validates the project policy; with `--json` it prints
  the policy and its differences from the shipped starter.
- `gsd-cli schema [NAME]` prints generated JSON Schemas for each output and for
  `gsd-cli.config.json`.
- Coded findings in configuration previews (for example `installed_effort_mismatch`
  for effort drift) and a machine-readable `reason` on check results.

### Changed

- `sessions` resolves expected models and efforts through the non-mutating preview
  bridge instead of running `gsd-tools.cjs`, and honours project-local and
  overridden installations.
- New runtime dependency: `pydantic>=2,<3`.
- **Breaking:** `policy` and `schema` are now reserved workflow names; a project
  policy that defines a workflow with either name must rename it.
- Raise the starter policy `gsd.min_version` from `1.20.1` to `1.21.0`, the current
  `@opengsd/gsd-core` release. Existing project policies are not modified.

## [2.0.1](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.0.1) — 2026-11-13

### Added

- MkDocs user documentation covering the problem, solution, configuration, check
  commands and best practices, with search and strict CI builds. Internal `nodes`
  and `superpowers` tracking folders are excluded from the published site.
- `task docs` serves documentation at `http://127.0.0.1:8010`, automatically
  loading pinned documentation dependencies through uv. Additional MkDocs serve
  options can be passed after `--`.

## [2.0.0](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/releases/tag/v2.0.0) — 2026-11-13

### Changed

- Update the Claude high runtime and Fable reviewer from Fable 5.1 to 5.2,
  preserving the Claude agent alias `fable`.
- Update the Gemini reviewer from Gemini 4 Argon to Gemini 4 Carbon. Carbon
  targets demanding reviews and can use more reasoning tokens.
- Update the optional DeepSeek reviewer from V3.2 to V4.1 Flash 1017. It remains
  inactive in the default reviewer groups.
- Align the shipped starter policy, example configuration and documentation with
  these model updates. Existing project policies and historical session mappings
  are preserved.
- Present configuration previews as compact workflow-scoped model and effort
  comparisons, including task-level phases. Show full evidence and effective JSON
  with `--details`, with terminal color support and plain redirected output.

### Added

- Read-only `--config` previews for workflow commands, using the selected installed
  GSD resolver against a temporary configuration snapshot without launching AI
  sessions or modifying project configuration.
- Explicit minimum GSD version checks before launch and a read-only
  `gsd-cli check [claude|codex]` command. Broken or outdated selected installations
  block launch before configuration synchronization.
- A packaged Click CLI with pipx installation, complete project-owned policy,
  custom workflow presets and bundled defaults.
- Persistent configuration capture with three-way merging, ownership tracking,
  file locking and journal recovery, plus migration of tracked working config.
- Installation, migration and first-use documentation.

### Fixed

- Accept inherited effort in GSD preview results.
- Reject forwarded Codex directory switches that could bypass project version
  checks by changing the launch destination.
- Validate migration ignore rules before writing project files.
- Distinguish JSON booleans from numbers when detecting configuration changes.
