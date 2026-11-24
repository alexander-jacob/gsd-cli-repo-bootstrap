# Repository Guidelines

## Project Structure & Module Organization

- `gsd_cli/cli.py` implements Click dispatch and launch preflight; `gsd-cli` is a development wrapper and `pyproject.toml` exposes the installed command.
- `gsd_cli/policy.py` validates complete project policy and resolves runtime blueprints against installed role catalogs. `gsd_cli/data/default-config.json` is the authoritative shipped seed, loaded via package resources.
- `gsd_cli/versions.py` performs offline SemVer and runtime-specific GSD bundle checks; selected-install failures block before config synchronization.
- `gsd_cli/config.py` owns discovery, migration, three-way capture, ownership metadata, file locking and journal recovery.
- `gsd_cli/claude_agents.py` plans project-local definitions from the selected upstream agent sources. Exact paths, Git state and content hashes guard creation, updates and removal.
- `gsd_cli/sessions.py` reads session logs, resolves expectations through the non-mutating preview bridge, and retains historical compatibility mappings only for old records.
- `gsd_cli/models.py` defines the machine-readable envelopes, payloads and `FindingCode`; `gsd_cli/policy_model.py` models `gsd-cli.config.json` for its schema only. `gsd-cli schema NAME` prints schemas generated from them.
- Tests use unittest, temporary projects, real temporary Git indexes and fabricated CLI/session logs. CI covers Python 3.10 and 3.11.
- `examples/gsd-config-example.json` mirrors the complete starter policy. It is not an effective GSD config fragment.

## Build, Test, and Development Commands

Use Python 3.10+ on POSIX, with Click and Pydantic installed in a virtual environment. Install with `pipx install .`; develop with `python -m pip install -e '.[test]'` in a venv (the `test` extra adds pytest, pytest-xdist and jsonschema).

- `python -m gsd_cli --help`: read-only help, including outside a project. `gsd-cli --version` (`-V`) prints the installed version from package metadata; an editable install keeps reporting the version from its last `pip install -e .`, and `python -m gsd_cli` from the repo root can read a leftover build `*.egg-info`, so reinstall after bumping `pyproject.toml`.
- `python -m pytest -n auto tests`: full offline suite. Always run tests with `-n auto` so they spread over all CPUs, including single test files (`python -m pytest -n auto tests/test_preview.py`). Tests stay unittest-style; pytest only runs them.
- `gsd-cli claude|codex BLUEPRINT [--secure] [-- CHILD_ARGS...]`: explicit runtime and project-local blueprint. Never automatically invoke GSD skills.
- `gsd-cli check [claude|codex]`: read-only version diagnostics; check both when omitted, exit nonzero on any failure.
- `gsd-cli init`: migrate/seed complete policy and tracked defaults, preserving working config.
- `gsd-cli status` and `gsd-cli sessions [claude|codex] [--pick [N]]`: strictly read-only; no capture, recovery or log writes.
- `gsd-cli policy [--json]`: validate the project policy; `--json` prints it. `gsd-cli schema [NAME]`: print JSON Schemas (`status`, `check`, `policy`, `preview`, `sessions`, `error`, `policy-file`).
- `--json` (before the first `--`) on `status`, `check`, `policy`, `sessions` and `RUNTIME BLUEPRINT --config` prints one envelope document; it is read-only, requires `--config` for runtime launches and is exclusive with `--details`.

## Model Routing Invariants

- Claude agent models must be Agent-tool aliases (`fable`, `opus`, `sonnet`, `haiku`), not full IDs. Session models can be full IDs.
- Codex agent models are full IDs. Session effort, agent effort and reviewer effort are independent controls.
- Resolve each model and effort independently from the installed catalog phase and the selected blueprint’s explicit role override. Materialize covered roles into `model_overrides` and `effort.agent_overrides`. Unmanaged sibling keys survive.
- Each runtime explicitly sets one review block for all its blueprints. Never inherit previous reviewers or infer plan authorship.
- Require explicit `gsd.min_version` in project policy. Never bypass it with `--secure`, borrow the other runtime's GSD version, or fall back from a broken selected local/override installation.
- Complete project policy is authoritative after init. No runtime fallback to bundled policy, and upgrades must not overwrite it.
- Verify model and effort through the installed `query resolve-model` command. Check installed execution evidence separately from Claude project discovery. Generate only project-local Claude definitions and preserve installed agents.

## Coding and Testing Guidelines

Use four-space Python indentation, descriptive snake_case names, two-space JSON and unittest. Keep Click at the CLI boundary; domain logic must be usable without a Click context. Avoid runtime dependencies beyond Click, Pydantic and the standard library; pytest, pytest-xdist and jsonschema are test-only, in the `test` extra. Pydantic defines machine-readable output and its schemas only.

Test argument forwarding at the first `--`, both runtimes, arbitrary blueprint names and partial role overrides, permissions, billing by adapter, missing executable preflight, logs, historical session compatibility, default stability, recursive capture conflicts, stale ownership, Git migration and interrupted-write recovery. Tests must not use real credentials or paid model calls. Use actual temporary files for persistence checks.

## Commit & Pull Request Guidelines

Use concise, imperative subjects such as `Fix execution profile reviewer preservation`, with a body that states the behaviour before and after and why. One behaviour change per commit.

Pull requests should describe the behavior changed, explain why, link relevant issues, and include the test command and result. Update examples and documentation for user-visible changes.

## Release Process

Follow `docs/releasing.md`. In short: one change per branch, squash-merged into `main`; documentation-only changes need no release. A gsd-cli release is a `Release version X.Y.Z` commit (version in `pyproject.toml`, `CHANGELOG.md` table, version sentence and dated section, empty `Unreleased` kept), a suite run on 3.10 and 3.11, a clean `uv build` smoke-tested from a fresh venv, an annotated `vX.Y.Z` tag, `git push origin main vX.Y.Z`, and a GitHub release with the wheel and sdist. Every gsd-cli release is followed by a skill release in `jacob-consulting/skills` that requires it, even when nothing else in the skill changes: raise its requirement there to the new version, release the plugin with `scripts/release.sh gsd-cli X.Y.Z` (minor bump), note it in the marketplace changelog, release the marketplace, push with `--follow-tags`, and update the plugin in Claude Code and Codex. Tags, pushes, releases and installs are outward-facing: do them only when the maintainer asks.

## Security & Configuration

Never commit API keys, CLI authentication files, or local `.planning/` state. Project policy and `.planning/config.default.json` are intentionally tracked; effective config, baseline, lock and journal are ignored. Preserve subscription billing guards and atomic configuration writes. Use separate worktrees for concurrent sessions that modify project settings.

All blueprints bypass CLI permission prompts by default (Claude `--dangerously-skip-permissions`, Codex `--dangerously-bypass-approvals-and-sandbox`). `--secure` omits the automatic bypass. Preserve the first `--` forwarding boundary.
