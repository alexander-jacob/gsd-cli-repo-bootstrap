# GSD runtime blueprint launcher

Open Claude Code or Codex with a named project configuration. A **blueprint** specifies the session model and effort, defaults for five GSD phases and optional exceptions for individual agents. Each runtime has its own blueprint names and one reviewer configuration. Start the GSD skill you want inside the session.

## Quick start

Use Python 3.10+ on Linux or macOS, the desired AI CLI and a compatible GSD installation for that runtime. Preview uses Node. Install from the launcher checkout, then initialize your GSD project.

```sh
pipx install .
cd /path/to/your/gsd-project
gsd-cli init
gsd-cli policy
gsd-cli check
```

The unqualified `gsd-cli check` checks both installed GSD bundles. If you use just one runtime, run `gsd-cli check codex` or `gsd-cli check claude`; only that runtime’s GSD installation must pass for its launch.

An existing `.planning/` directory is enough to initialize. Review the generated `gsd-cli.config.json`, `.planning/config.default.json` and `.gitignore`. If Git tracked `.planning/config.json`, init stages its removal from the index and preserves the working file. For an existing version-one policy, follow the [manual conversion walkthrough](MIGRATION.md#convert-a-version-one-project-policy).

To discover the available names, enter either runtime alone. These commands print the choices and exit 1. The starter lists `high, low, medium` for each runtime.

```sh
gsd-cli codex
gsd-cli claude
```

Preview, then open your chosen runtime. These examples use the CLI’s normal permissions. **Omitting `--secure` adds the full permission bypass on either runtime.**

```sh
gsd-cli codex medium --config --secure
gsd-cli claude medium --config --secure
gsd-cli codex medium --secure
gsd-cli claude medium --secure
```

Put child options after the first `--`. For example, `gsd-cli codex medium --secure -- --help` prepares the project and invokes Codex help. Run from the destination project because forwarded Codex directory switches are rejected.

| Starter blueprint | Claude session / phase agent | Codex session / phase agent | Session and phase effort |
|---|---|---|---|
| low | `claude-sonnet-5-5` / `sonnet` | `gpt-6-luna` | low |
| medium | `claude-opus-5-5` / `opus` | `gpt-6.1-sol` | medium |
| high | `claude-fable-5-2` / `fable` | `gpt-6-astra` | high |

An agent override can change its model, effort or both. The starter executor and verifier use their respective execution and verification phase settings. The reviewer roster stays the same across a runtime’s blueprints. OpenCode/OpenRouter reviewers are metered. [Configuration guide](docs/configuration.md)

## What a launch writes

The launcher merges persistent GSD edits into the tracked default, retaining a private local baseline for conflict detection. A Claude launch also copies covered installed agent definitions to `.claude/agents/`, sets their model and effort frontmatter and maintains exact ignore rules. Preview shows prospective creation, update and cleanup. Codex uses config overrides and leaves those Claude files in place. For conflicts and recovery, see the [launcher reference](docs/LAUNCHER.md#automatic-capture-and-recovery).

The selected GSD installation must satisfy `gsd.min_version` (shipped floor `1.21.0`). Use `gsd-cli check codex` or `gsd-cli check claude` to identify its location. Previews compare the policy to installed GSD resolution. Claude discovery has confirmed the generated project model, but actual Claude subagent effort remains unverified. [Check commands and evidence](docs/checks.md)

## Inspection and development

```sh
gsd-cli --version
gsd-cli status
gsd-cli policy --json
gsd-cli codex medium --config --details
gsd-cli sessions codex
gsd-cli schema preview

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest -n auto tests
```

The [machine-readable output guide](docs/json-output.md) describes version-two envelopes. Private launch records live in `$XDG_STATE_HOME/gsd-cli/launches.jsonl` (normally `~/.local/state/gsd-cli/launches.jsonl`). The [performance/cost audit](docs/nodes/2026-11-10-gsd-performance-cost-audit.md) records the rationale behind earlier routing choices.

## Documentation

The [user guide](docs/index.md) explains the problem, why gsd-cli helps,
configuration, check commands and best practices. The MkDocs site uses the
Read the Docs theme and search. With Task and uv installed, the docs task
automatically loads the pinned documentation dependencies in an isolated
environment; no virtualenv activation or global MkDocs installation is needed.

```sh
task docs
uv run --isolated --no-project --with-requirements docs/requirements.txt mkdocs build --strict
```

The preview runs at `http://127.0.0.1:8010`. To use another port, run
`task docs -- -a 127.0.0.1:8001`.

Tracking folders `docs/nodes/` and `docs/superpowers/` are excluded from the site
and search index. Generated output lives in the ignored `site/` directory.
