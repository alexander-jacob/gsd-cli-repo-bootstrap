# Changelog

User-visible changes are recorded here, newest first. Changes under **Unreleased**
have not been assigned to a release in this document.

## Release tracking

| Status | Version | Release date |
|---|---|---|
| Unreleased | Not yet assigned | — |

The current package version in `pyproject.toml` is `2.0.0`. No release tags exist
in the repository as of November 13, 2026; this changelog does not infer a
published release from the package version. Earlier release history has not been
backfilled.

When releasing, move the Unreleased entries into a versioned section with its
release date (`YYYY-MM-DD`), update the tracking table and package version as
appropriate, and retain an empty Unreleased section for subsequent changes.

## Unreleased

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
