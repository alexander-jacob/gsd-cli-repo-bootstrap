# Launcher guide

## Installation

Use Python 3.10 or newer on Linux/macOS. The package uses Click and POSIX file locking. Install pipx using its [official instructions](https://pipx.pypa.io/stable/installation/), then:

```sh
pipx install /absolute/path/to/gsd-cli-repo-bootstrap
command -v gsd-cli
gsd-cli --help
```

If `~/.local/bin/gsd-cli` is the old copied Python script, inspect it first (`ls -l` and its opening lines). After identifying it as this repository's legacy launcher, move that file to a backup location you choose, then install the package. Do not use pipx `--force` to overwrite an unidentified executable. `task install` runs `pipx install` from this checkout.

To update a local installation, use `pipx install --force /absolute/path/to/gsd-cli-repo-bootstrap` **after confirming that pipx owns the existing command** (`pipx list`). Package upgrades do not overwrite project policy. The development wrapper `./gsd-cli` requires the package source and Click; it is not a single-file distribution.

## Commands and forwarding

```text
gsd-cli init
gsd-cli status
gsd-cli check [claude|codex]
gsd-cli sessions [claude|codex] [--pick [N]]
gsd-cli WORKFLOW claude|codex [low|medium|high] [--secure] [--config [--details]] [-- CHILD_ARGS...]
```

Workflow and runtime are mandatory; level defaults to medium. Old runtime-first syntax is rejected with a replacement example. No preset runs a GSD command. Start the desired GSD skill yourself after the CLI opens.

The first literal `--` separates launcher arguments from child arguments. Everything after it is forwarded unchanged, including another `--`, `--help`, `--secure` or `--model`. Before it, unknown options are errors. Codex directory switches (`-C`, `--cd`, including attached values) are rejected before writes because they would relocate the child after project selection; run the launcher from the destination project instead. Tokens after the child's own `--` remain literal positional arguments. `gsd-cli exec --help` is read-only launcher help; `gsd-cli exec claude -- --help` prepares config and launches Claude's help.

A forwarded model/effort argument may override the preset at the child CLI's discretion. `--secure` suppresses automatic bypass only; it does not remove bypass flags you explicitly forward. No credential or model-availability probe runs.

## Configuration preview

```sh
gsd-cli plan codex --config
gsd-cli exec claude high --config
gsd-cli ship codex --secure --config  # when ship is defined in project policy
gsd-cli plan codex --config --details  # full evidence and effective JSON
```

This prints and exits. It calculates the same prospective `.planning/config.json` as a normal launch, including pending persistent changes, then asks the selected installed GSD resolver about each registered/configured agent using a temporary snapshot. The default report puts the workflow and requested session model first, then compares configured and GSD-resolved model and effort for agents in the workflow's task phases and task-level phases. These are agents the workflow may use, not a record of execution. Configured agents with no installed phase metadata are counted and listed in `--details`.

`--config --details` retains the complete report: requested session argv, all registered/configured agents, resolver inputs, diagnostics, reviewer models/efforts, and the prospective JSON. It colors JSON syntax in an interactive terminal. Headings and check symbols in the compact view are colored there too. `NO_COLOR` disables color; redirected output is plain text. `--details` requires `--config`.

The **Check** column compares configured expectations with available evidence:

| Check | Meaning |
|---|---|
| `✓` (`OK` in details) | Applicable comparisons match resolver/installed-file evidence. |
| `✗` (`NOT OK` in details) | A known mismatch exists; detailed notes name the setting and both values. |
| `?` (`UNKNOWN` in details) | Evidence or an unambiguous configured expectation is missing. |

For Claude, the report distinguishes configured effort from installed agent frontmatter and session inheritance. For Codex, it shows GSD's rendered effort and propagation mechanism. A resolver-confirmed configuration is not proof of actual AI execution. Session and external reviewer rows are configuration-only and carry `UNKNOWN`. Agents without an explicit effort expectation also retain `UNKNOWN`; GSD's resolved default is still shown. A mismatch takes precedence over other unknown fields in the same row.

The preview never launches an AI CLI, performs journal recovery, captures changes, writes project config or launch logs, or synchronizes installed agent files. Node and compatible compiled GSD modules are required; AI CLI binaries and credentials are not. It bypasses GSD's automatic build entry point. Temporary files are removed after the query. Active workstream config is copied into the snapshot; unsupported `GSD_PROJECT` context or filesystem-dependent legacy `multiRepo` migration yields an explicit incomplete result.

Exit 0 means preparation and resolution completed, even if there are `NOT OK` or legitimate `UNKNOWN` findings. An unavailable/old resolver, malformed response, timeout, or unsupported context prints known configuration, labels the report `INCOMPLETE`, and exits 1. A merge conflict, pending recovery journal, or held synchronization lock prevents a reliable preview and fails without changing files. Idle lock files are allowed.

Put `--config` before the first `--`. After that delimiter it is a child option and normal launch behavior applies. Forwarded arguments are displayed, with a warning that they may override the requested session settings. `status` continues to show the saved working config rather than calculating a prospective launch.

## GSD version checks

The complete project policy must include:

```json
"gsd": {
  "min_version": "1.20.1"
}
```

This is the bundled default floor, editable for your project's requirements. It does not assert that every earlier GSD version is incompatible. If you initialized a policy before this field existed, add it to `gsd-cli.config.json` deliberately; init and launches report the missing field instead of adding a hidden default or replacing your policy.

```sh
gsd-cli check          # report Claude and Codex
gsd-cli check codex    # one runtime
```

Each report includes PASS/FAIL, installed GSD version, required minimum, installation path and failure reason. Exit status is 0 when all requested checks pass and 1 for an unmet requirement. Check does not require Node or either AI CLI executable, access the network, run GSD code, update installations, capture changes, replay recovery or write logs.

Before a workflow opens a runtime, the same check blocks unsupported installations **before any configuration writes**, including lock/journal recovery. Only the launched runtime is gated; external reviewer CLI adapters do not themselves require that runtime's GSD installation. Help, status, sessions and init remain usable with old/missing GSD. `--secure` changes permission flags only and cannot bypass the version gate.

Discovery is runtime-specific, starting from the discovered project root:

1. Explicit `CLAUDE_CONFIG_DIR` or `CODEX_HOME` selects that runtime's config directory. A leading `~` expands to home; relative directories resolve against the project root, which is also the launched CLI's working directory.
2. Otherwise a project `.claude/gsd-core` or `.codex/gsd-core` takes precedence when present.
3. Otherwise the corresponding `~/.claude/gsd-core` or `~/.codex/gsd-core` is checked.

An explicit missing directory, malformed version, or incomplete local bundle blocks; it never borrows a global copy or the other runtime's version. The bundle must contain a readable, bounded regular `VERSION` file and regular `workflows/update.md` / `bin/gsd-tools.cjs` files. This checks the selected bundle; it does not verify every hook/agent file or absolute workflow paths embedded in custom skills. Keep custom skill paths aligned with the selected installation.

Versions use [SemVer 2.0.0 precedence](https://semver.org/spec/v2.0.0.html): numeric components compare numerically, build metadata does not affect precedence, and `1.20.1-rc.1` is below `1.20.1`. Partial versions, a `v` prefix and malformed identifiers are rejected. A newer prerelease such as `1.21.0-rc.1` satisfies a `1.20.1` floor; a minimum is not a stable-only release policy.

On failure, update or repair the **reported installation** through GSD's update workflow and rerun check. No automatic update is performed. At implementation time this machine's Claude GSD reports 1.20.1 (passes the default) and Codex GSD reports 1.18.0 (blocked by the default). Both have update-check hooks; notification visibility alone does not establish why their versions differ.

## Initialization and migration

Run `gsd-cli init` inside an existing GSD project or a descendant. It does not create a GSD roadmap or requirements.

Initialization seeds complete `gsd-cli.config.json` from the packaged `data/default-config.json`. When migrating, compatible existing Claude aliases/Codex tier models, known agent pins, effort overrides, reviewer definitions and parallel-review preference are retained. New session/workflow/reviewer choices come from the explicit starter policy; inspect the generated file. An unrepresentable custom agent model remains an unmanaged GSD override rather than being guessed into a tier.

The existing `.planning/config.json` remains byte-for-byte unchanged during init. Persistent unmanaged settings seed `.planning/config.default.json`; starter `gsd_defaults` fills only missing settings, currently `workflow.compact_content=true`. Repeat initialization preserves project policy and local edits. A malformed policy is an error, never grounds to reset it to package defaults.

For Git projects, init refuses staged working-config changes. Commit or unstage those deliberately first. It removes only `.planning/config.json` from the index, preserves the disk file, and adds narrow ignore rules. When `.planning/` was entirely ignored, exceptions expose only the tracked default. A nested `.planning/.gitignore` conflict must be reconciled before migration.

Review the resulting diff, then commit the policy, default, `.gitignore` changes and index removal together. Initialization never commits. In non-Git projects, files and ignore rules are created without index changes.

## Project policy

The complete example is [examples/gsd-config-example.json](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/blob/main/examples/gsd-config-example.json), a copy of the authoritative bundled starter. Do not paste it into `.planning/config.json`; it is the schema for **`gsd-cli.config.json`**.

| Field | Contract |
|---|---|
| `schema_version` | `1` |
| `gsd.min_version` | Required complete SemVer minimum; default `1.20.1`; blocks unsupported launches |
| `runtimes` | Both runtimes; all three levels; `session_model`, `agent_model`, `session_effort` required |
| `phase_defaults` | Explicit levels for planning, discuss, research, execution and verification |
| `agent_levels` | Per-agent level pins; translated for the selected runtime |
| `agent_efforts` | Independent GSD `effort.agent_overrides` |
| `reviewers` | Named GSD reviewer instances, with `cli` and `model` |
| `reviewer_efforts` | Explicit claude/codex/opencode adapter effort; shared across instances using that adapter |
| `reviewer_groups` | Lists of declared instances; explicitly empty is allowed |
| `workflows` | Configurable presets with all fields below |
| `gsd_defaults` | Initialization-only seed for persistent unmanaged GSD settings |

Each workflow declares `tasks` following the selected level, independent `task_levels`, `reviewer_groups` for both runtimes, boolean `parallel_reviews`, and explicit `permissions` (`normal`/`bypass`) for both runtimes. Optional `session_efforts` overrides runtime/level effort for that preset. A task cannot appear in both task lists. Reserved command/runtime names cannot be workflow names.

For example, add this under `workflows` for a session-only `ship` preset with normal permissions:

```json
"ship": {
  "tasks": [],
  "task_levels": {"verification": "high"},
  "reviewer_groups": {
    "claude": "review-claude-plan",
    "codex": "review-codex-plan"
  },
  "parallel_reviews": false,
  "permissions": {"claude": "normal", "codex": "normal"}
}
```

Then `gsd-cli ship codex` opens a medium Codex session. You decide whether to invoke GSD ship, review, or another action.

Resolution: phase defaults → selected level for workflow tasks → independent task levels → named agent pins. Every launch explicitly writes all phase defaults and its selected reviewers. Previous workflow state cannot supply missing policy. Both runtime tier maps are emitted; low/medium/high become GSD haiku/sonnet/opus tier labels at the boundary. Claude agent models must be aliases (`fable`, `opus`, `sonnet`, `haiku`); session model strings can be full IDs.

## Effort and GSD routing

Session effort is passed via Claude `--effort` or Codex `-c model_reasoning_effort=...`. GSD agent effort is written separately to `effort.agent_overrides`. Reviewer effort is written to `review.effort.<adapter>`. Increasing one does not automatically increase the others.

The installed Claude GSD agent Markdown files contain effort frontmatter. After launching once to materialize the intended config, preview synchronization from that project:

```sh
GSD_RUNTIME=claude node ~/.claude/gsd-core/bin/gsd-tools.cjs effort sync --dry-run
```

If the preview is appropriate, the same command with `--apply` writes installed agent files. Those files may be global and shared by other projects. The launcher never performs this operation. In the inspected Codex installation, agent TOMLs have no static effort pins; runtime workflows resolve effort per agent where the spawn schema supports it. See [check commands](checks.md) for ways to inspect installed behavior and session evidence.

To check actual resolver output without making model calls:

```sh
GSD_RUNTIME=claude node ~/.claude/gsd-core/bin/gsd-tools.cjs query resolve-model gsd-plan-checker
GSD_RUNTIME=codex node ~/.codex/gsd-core/bin/gsd-tools.cjs query resolve-model gsd-codebase-mapper
```

Other GSD features, such as dynamic routing or workflow code that reuses a research model, can affect actual spawns. The launcher preserves unmanaged GSD settings. Resolver output alone does not prove which model/effort a running agent used. The read-only `sessions` report can help inspect runtime logs.

## Automatic capture and recovery

Before each workflow launch, persistent settings are merged using three versions: the last successful baseline, the current working config, and the tracked default. Object keys merge independently; arrays and scalar values are indivisible. Deleting a value differs from assigning null. Editing the same value differently, or deleting a parent while the other side edits a child, is a conflict.

Only persistent GSD edits change the default. The launcher excludes its generated model/provider/phase/pin/reviewer/effort entries and the known transient `workflow._auto_chain_active`. It preserves unrelated entries in shared sections. Previously managed entries are remembered so removing a pin or reviewer from policy also removes its generated working value.

The tracked default must not contain managed or transient entries; errors name the conflicting paths. To relinquish an owned setting and edit it in GSD, first remove its policy entry and launch once to retire ownership, then add the unmanaged value. Do not edit generated model pins in config.json: the project policy owns them.

Default-only edits propagate locally. A missing working file is recreated. A fresh checkout can start with just policy and default. If a working file and default disagree without a baseline, reconcile their persistent contents before retrying; the launcher does not guess which is newer. A missing tracked default with an existing baseline must be restored.

Writes use individual atomic replacements and a private `.planning/.gsd-cli-journal.json`; the set of files is **not** one atomic filesystem transaction. The next mutating operation resumes an interrupted transaction only if each target still matches its recorded before/after content. If an external edit prevents replay, preserve copies of the edited files and journal, compare the target with the journal's before/after versions, and reconcile intentionally before retrying. Do not delete the journal and then let partial state masquerade as a normal edit.

The short `.gsd-cli.lock` protects preparation, not a running AI session. Use separate worktrees for simultaneous sessions with different presets. Help, status, check and sessions do not recover, capture or write config. `status` reports whether recovery is pending.

## Billing and history

Guards refuse `ANTHROPIC_API_KEY` when the session or selected reviewers use Claude, and `OPENAI_API_KEY`/`CODEX_API_KEY` when they use Codex. Custom reviewer names are checked through their adapters. These environment checks cannot guarantee an account's billing configuration. OpenCode/OpenRouter reviewers remain metered.

Each launch attempt records workflow, level, model, effort, forwarded arguments and policy/effective-config snapshots in a mode-0600 JSONL log. Missing executables, billing failures and merge conflicts produce no launch record. A failure after preparation may leave prepared config. The record is not proof that the child completed successfully.

New session records use the captured reviewer definitions. Legacy records remain readable using historical reviewer mappings. Where several selected reviewers share an adapter and logs do not identify the instance, the report avoids guessing its expected model.

## Development and validation

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
python -m gsd_cli --help
```

Tests use temporary projects, real temporary Git indexes and stub CLIs. No credentials, external AI calls or network are needed after dependencies are installed. CI tests Python 3.10 and 3.11. Package installation must also be checked outside the source checkout so missing JSON resources cannot hide behind imports from the repository.
