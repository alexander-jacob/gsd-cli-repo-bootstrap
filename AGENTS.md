# Repository Guidelines

## Project Structure & Module Organization

- `gsd-cli` is the executable Python launcher. It handles configuration discovery, model profiles, reviewer selection, billing guards, and CLI execution. Its data tables drive everything: `CLAUDE_MODELS` / `CODEX_MODELS` (GSD tier → runtime model), `AGENT_TIERS` (per-agent tier pins), `REVIEWERS`, and `PROFILES` (session model, phase-tier overrides, reviewer preset).
- `tests/test_gsd_cli.py` contains subprocess-based launcher tests.
- `examples/gsd-config-example.json` illustrates the configuration merged into a target project's `.planning/config.json`.
- `README.md` explains workflows; `docs/LAUNCHER.md` provides installation and operation details.
- `tools/session_model_usage.py` is an offline, standard-library diagnostic: it reports which model each GSD agent was spawned with and its token usage from local Claude Code and Codex transcripts, and runs the real resolver (`resolve` subcommand). Use it before changing routing tables.
- `docs/superpowers/specs/` holds design and analysis documents; `docs/superpowers/plans/` holds the plans that execute them. A fresh session continuing an analysis starts from the newest spec and its plan.
- `.github/workflows/tests.yml` runs the test suite on pushes and pull requests.

## Build, Test, and Development Commands

Use Python 3.10+; the launcher requires only the standard library. No build or dependency installation is needed.

- `python3 ./gsd-cli --help`: display supported commands without launching an external CLI.
- `python3 -m unittest discover -s tests -v`: run the full offline test suite, matching CI's command. CI uses Python 3.11.
- `python3 ./gsd-cli status`: inspect configuration from a directory containing an existing `.planning/config.json`, or one of its descendants.

`init` and runtime profiles modify the target project's configuration. Runtime profiles also start an authenticated external CLI. On every launch the launcher writes `models.<phase_type>` from the profile and materializes `AGENT_TIERS` into `model_overrides` for the launched runtime; Codex launches add `-c model_reasoning_effort=<tier effort>`; every profile except Claude planning adds the runtime's permission-bypass flag unless `--secure` is given.

## Model Routing Invariants

- Claude tier entries in `CLAUDE_MODELS` must be Claude Code Agent-tool aliases (`fable`, `opus`, `sonnet`, `haiku`), never full model IDs. GSD cannot map a full ID back to an alias; it warns, resolves an empty model, and every subagent silently inherits the session model.
- Codex tier entries are full model IDs with a `reasoning_effort`; GSD passes them to `spawn_agent` verbatim, and the launcher uses the effort for the session model.
- `model_overrides` is applied by GSD verbatim and has no per-runtime translation, so never write tier words or runtime-specific IDs into it by hand: keep pins in `AGENT_TIERS` (tier-keyed) and let the launch materialize them. Override keys the launcher does not manage must survive a launch.
- Session `--model` values in `PROFILES` are CLI arguments and may be full IDs for either runtime.
- Verify routing against the real resolver, not the tables: `GSD_RUNTIME=<runtime> node ~/.claude/gsd-core/bin/gsd-tools.cjs query resolve-model <agent> --pick model` from inside a GSD project.

## Coding Style & Naming Conventions

Follow the existing Python style: four-space indentation, snake_case functions and variables, UPPER_CASE constants, and descriptive helper names. Use type annotations consistently with nearby code. Keep the launcher standard-library-only and preserve its executable entry point.

Use two-space indentation for JSON. Keep profile definitions, the example configuration, and documentation aligned when changing models or reviewers. No formatter or linter is configured.

## Testing Guidelines

Use `unittest`, with files named `test_*.py` and methods named `test_<behavior>`. Extend the existing temporary-project and stub-executable fixtures. Tests must avoid network access, real credentials, and paid model calls.

Cover configuration preservation, profile selection, forwarded arguments, runtime environment, billing guards, `model_overrides` materialization for both runtimes, the Codex effort flag, and the permission-bypass default / `--secure` opt-out when changing those behaviors. Tests assert the exact `argv` the stub CLI receives, so a change to launch arguments is expected to touch those assertions. No numerical coverage threshold is configured.

## Commit & Pull Request Guidelines

Use concise, imperative subjects such as `Fix execution profile reviewer preservation`, with a body that states the behaviour before and after and why. One behaviour change per commit.

Pull requests should describe the behavior changed, explain why, link relevant issues, and include the test command and result. Update examples and documentation for user-visible changes.

## Security & Configuration

Never commit API keys, CLI authentication files, or local `.planning/` state. Preserve subscription billing guards and atomic configuration writes. Use separate worktrees for concurrent sessions that modify project settings.

Execution, review, and Codex planning profiles bypass CLI permission prompts by default (Claude `--dangerously-skip-permissions`, Codex `--dangerously-bypass-approvals-and-sandbox`); `--secure` restores the CLI's normal permission settings. Claude planning must never receive an automatic bypass flag. Keep that split when adding profiles.
