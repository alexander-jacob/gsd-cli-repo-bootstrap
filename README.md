# GSD workflow launcher

Open Claude Code or Codex with project-owned model, effort and external reviewer presets. GSD remains responsible for running its workflows; this launcher configures the session and opens the CLI.

```sh
gsd-cli plan codex              # medium is the default
gsd-cli plan claude high
gsd-cli exec codex low
gsd-cli exec claude --secure
gsd-cli exec codex -- --resume  # child arguments go after --
gsd-cli check                  # verify both GSD installations
gsd-cli check codex            # verify only Codex GSD
```

Workflow and runtime are always explicit. You can define additional workflow names, such as `ship`, in your project policy. No GSD command is invoked automatically.

## Install and initialize

Requires Python 3.10+, a POSIX system (Linux/macOS), pipx, Git for Git migration, GSD, and the CLI you intend to launch. Click is installed inside the pipx environment.

```sh
pipx install /path/to/gsd-cli-repo-bootstrap
cd /path/to/your/gsd-project
gsd-cli init
```

For an existing project, follow the [installation, migration and first-use walkthrough](MIGRATION.md). It includes replacing the old single-file launcher. `task install` now uses pipx; copying the `gsd-cli` source wrapper alone no longer works.

`init` loads the complete [bundled JSON policy](gsd_cli/data/default-config.json) through package resources. It preserves compatible legacy model/reviewer settings and leaves the existing working config untouched. Review and commit the generated policy, default and ignore changes. For a previously tracked working config, init stages its removal from the index while keeping the local file. It makes no commit.

| File | Purpose | Git |
|---|---|---|
| `gsd-cli.config.json` | Complete project model/workflow/reviewer policy | Track |
| `.planning/config.default.json` | Persistent GSD settings outside launcher ownership | Track |
| `.planning/config.json` | Effective configuration read and modified by GSD | Ignore |
| `.planning/.gsd-cli-sync.json` | Local baseline and previous ownership | Ignore |

Before each launch, the launcher captures persistent GSD edits into the tracked default. Switching workflows, models or runtimes does not itself change that default. Changes to the default and local config merge when independent; conflicting edits stop the launch and name the affected paths. A private recovery journal protects against interpreting partially completed writes as new user changes.

## GSD minimum version

Project policy requires `"gsd": {"min_version": "1.20.1"}`. The bundled default uses 1.20.1 as an editable project requirement, not a proven technical compatibility minimum. Older project policies must add this field explicitly; upgrades never overwrite their policy.

Every workflow launch checks the selected runtime before capture, recovery or launch logging. An older, missing, unreadable or incomplete GSD installation **blocks launch**. `--secure` does not bypass this gate. `gsd-cli check [claude|codex]` reports installed version, required minimum and installation path; omitting the runtime checks both and exits nonzero if either fails.

Checks are offline and read-only. Explicit `CLAUDE_CONFIG_DIR`/`CODEX_HOME` overrides take precedence, followed by a project-local GSD bundle, then the runtime's global bundle. A broken selected installation does not fall back to another copy. Forwarded Codex `-C`/`--cd` is rejected; run the launcher from the destination project so checks and configuration target the same location. See [version checking](docs/LAUNCHER.md#gsd-version-checks) for discovery and upgrade details.

## Default policy

| Level | Claude session / agent alias | Codex session / agent model | Session effort |
|---|---|---|---|
| low | `claude-sonnet-5-5` / `sonnet` | `gpt-6-luna` | low |
| medium | `claude-opus-5-5` / `opus` | `gpt-6.1-sol` | medium |
| high | `claude-fable-5-1` / `fable` | `gpt-6-astra` | high |

Codex high execution deliberately uses medium **session** effort. Agent effort and reviewer effort are independent. Planning/discussion/research follow the selected plan level; execution follows the selected exec level. Verification stays high, and other phases reset to their explicit defaults each launch. Per-agent pins take precedence over phase levels.

The [performance/cost audit](docs/nodes/2026-11-10-gsd-performance-cost-audit.md) explains the evidence behind the defaults. Planner/checker/integration/synthesis/security reasoning gets high effort; extraction and mapping use lower or medium effort. Mapper and intel models use medium; compact GSD content is seeded on initialization. These are reasoned starting choices, not measured quality or cost guarantees.

Claude launches now pass `--effort`. **Claude subagent effort also depends on installed agent frontmatter**: project config alone does not update it. The launcher warns and never modifies your global agent definitions. See the [effort synchronization instructions](docs/LAUNCHER.md#effort-and-gsd-routing).

Each preset explicitly selects the opposite runtime's reviewer plus Grok and Gemini. DeepSeek is defined but inactive. Reviewers remain independent of the selected model level. This choice does not detect who authored an earlier plan; configure another preset if you need a different roster. OpenCode/OpenRouter reviewers are metered.

Claude planning uses normal permissions; Codex planning and both execution presets bypass approval prompts by default. `--secure` suppresses the launcher-inserted bypass. Custom workflows must state permissions explicitly. Billing guards check environment variables for both the session and selected reviewer adapters.

## Inspection and development

```sh
gsd-cli status
gsd-cli sessions [claude|codex] [--pick [N]]

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

Help, status and session reports are read-only. Launch records live in `$XDG_STATE_HOME/gsd-cli/launches.jsonl` (normally `~/.local/state/gsd-cli/launches.jsonl`), mode 0600, and contain policy/config snapshots. Log failures warn without blocking the launch.

The [launcher guide](docs/LAUNCHER.md) covers configuration, migration, recovery and custom workflows. The [project assessment](docs/nodes/2026-11-10-project-assessment.md) records strengths and weaknesses of the original version; [implementation design](docs/nodes/2026-11-10-configurable-launcher-design.md) records the agreed direction.
