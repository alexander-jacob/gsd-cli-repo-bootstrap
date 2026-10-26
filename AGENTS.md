# Repository Guidelines

## Project Structure & Module Organization

- `gsd-cli` is the executable Python launcher. It handles configuration discovery, model profiles, reviewer selection, billing guards, and CLI execution.
- `tests/test_gsd_cli.py` contains subprocess-based launcher tests.
- `examples/gsd-config-example.json` illustrates the configuration merged into a target project's `.planning/config.json`.
- `README.md` explains workflows; `docs/LAUNCHER.md` provides installation and operation details.
- `.github/workflows/tests.yml` runs the test suite on pushes and pull requests.

## Build, Test, and Development Commands

Use Python 3.10+; the launcher requires only the standard library. No build or dependency installation is needed.

- `python3 ./gsd-cli --help`: display supported commands without launching an external CLI.
- `python3 -m unittest discover -s tests -v`: run the full offline test suite, matching CI's command. CI uses Python 3.11.
- `python3 ./gsd-cli status`: inspect configuration from a directory containing an existing `.planning/config.json`, or one of its descendants.

`init` and runtime profiles modify the target project's configuration. Runtime profiles also start an authenticated external CLI.

## Coding Style & Naming Conventions

Follow the existing Python style: four-space indentation, snake_case functions and variables, UPPER_CASE constants, and descriptive helper names. Use type annotations consistently with nearby code. Keep the launcher standard-library-only and preserve its executable entry point.

Use two-space indentation for JSON. Keep profile definitions, the example configuration, and documentation aligned when changing models or reviewers. No formatter or linter is configured.

## Testing Guidelines

Use `unittest`, with files named `test_*.py` and methods named `test_<behavior>`. Extend the existing temporary-project and stub-executable fixtures. Tests must avoid network access, real credentials, and paid model calls.

Cover configuration preservation, profile selection, forwarded arguments, runtime environment, and billing guards when changing those behaviors. No numerical coverage threshold is configured.

## Commit & Pull Request Guidelines

Git history is unavailable in this checkout, so existing commit conventions cannot be verified. Prefer concise, imperative subjects such as `Fix execution profile reviewer preservation`.

Pull requests should describe the behavior changed, explain why, link relevant issues, and include the test command and result. Update examples and documentation for user-visible changes.

## Security & Configuration

Never commit API keys, CLI authentication files, or local `.planning/` state. Preserve subscription billing guards and atomic configuration writes. Use separate worktrees for concurrent sessions that modify project settings.
