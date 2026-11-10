# Repository Guidelines

## Project Structure & Module Organization

- `gsd_cli/cli.py` implements Click dispatch and launch preflight; `gsd-cli` is a development wrapper and `pyproject.toml` exposes the installed command.
- `gsd_cli/policy.py` validates complete project policy and resolves model/effort/permission/reviewer choices. `gsd_cli/data/default-config.json` is the authoritative shipped seed, loaded via package resources.
- `gsd_cli/versions.py` performs offline SemVer and runtime-specific GSD bundle checks; selected-install failures block before config synchronization.
- `gsd_cli/config.py` owns discovery, migration, three-way capture, ownership metadata, file locking and journal recovery.
- `gsd_cli/sessions.py` reads session logs and retains historical compatibility mappings only for old records.
- Tests use unittest, temporary projects, real temporary Git indexes and fabricated CLI/session logs. CI covers Python 3.10 and 3.11.
- `examples/gsd-config-example.json` mirrors the complete starter policy. It is not an effective GSD config fragment.

## Build, Test, and Development Commands

Use Python 3.10+ on POSIX, with Click installed in a virtual environment. Install with `pipx install .`; develop with `python -m pip install -e .` in a venv.

- `python -m gsd_cli --help`: read-only help, including outside a project.
- `python -m unittest discover -s tests -v`: full offline suite.
- `gsd-cli WORKFLOW claude|codex [low|medium|high] [--secure] [-- CHILD_ARGS...]`: explicit workflow/runtime, medium default. Never automatically invoke GSD skills.
- `gsd-cli check [claude|codex]`: read-only version diagnostics; check both when omitted, exit nonzero on any failure.
- `gsd-cli init`: migrate/seed complete policy and tracked defaults, preserving working config.
- `gsd-cli status` and `gsd-cli sessions [claude|codex] [--pick [N]]`: strictly read-only; no capture, recovery or log writes.

## Model Routing Invariants

- Claude agent models must be Agent-tool aliases (`fable`, `opus`, `sonnet`, `haiku`), not full IDs. Session models can be full IDs.
- Codex agent models are full IDs. Session effort, agent effort and reviewer effort are independent controls.
- Project `agent_levels` pins are runtime-independent levels, materialized into `model_overrides`. Unmanaged sibling keys survive.
- Every workflow/runtime explicitly selects a reviewer group. Never inherit previous reviewers or infer plan authorship.
- Require explicit `gsd.min_version` in project policy. Never bypass it with `--secure`, borrow the other runtime's GSD version, or fall back from a broken selected local/override installation.
- Complete project policy is authoritative after init. No runtime fallback to bundled policy, and upgrades must not overwrite it.
- Verify model and effort through the installed `query resolve-model` command. Config alone does not synchronize Claude installed agent effort frontmatter; never silently modify global agents.

## Coding and Testing Guidelines

Use four-space Python indentation, descriptive snake_case names, two-space JSON and unittest. Keep Click at the CLI boundary; domain logic must be usable without a Click context. Avoid dependencies beyond Click and the standard library.

Test argument forwarding at the first `--`, both runtime/level combinations, custom workflows, permissions, billing by adapter, missing executable preflight, logs, historical session compatibility, default stability, recursive capture conflicts, stale ownership, Git migration and interrupted-write recovery. Tests must not use real credentials or paid model calls. Use actual temporary files for persistence checks.

## Commit & Pull Request Guidelines

Use concise, imperative subjects such as `Fix execution profile reviewer preservation`, with a body that states the behaviour before and after and why. One behaviour change per commit.

Pull requests should describe the behavior changed, explain why, link relevant issues, and include the test command and result. Update examples and documentation for user-visible changes.

## Security & Configuration

Never commit API keys, CLI authentication files, or local `.planning/` state. Project policy and `.planning/config.default.json` are intentionally tracked; effective config, baseline, lock and journal are ignored. Preserve subscription billing guards and atomic configuration writes. Use separate worktrees for concurrent sessions that modify project settings.

Shipped execution and Codex planning presets bypass CLI permission prompts by default (Claude `--dangerously-skip-permissions`, Codex `--dangerously-bypass-approvals-and-sandbox`); `--secure` restores the CLI's normal permission settings. Claude planning must never receive an automatic bypass flag. Custom workflow permissions must be explicit.
