# Launcher guide

## Installation

Use Python 3.10 or newer on Linux/macOS. The package uses Click, Pydantic and POSIX file locking. Install pipx using its [official instructions](https://pipx.pypa.io/stable/installation/), then:

```sh
pipx install /absolute/path/to/gsd-cli-repo-bootstrap
command -v gsd-cli
gsd-cli --help
```

If `~/.local/bin/gsd-cli` is the old copied Python script, inspect it first (`ls -l` and its opening lines). After identifying it as this repository's legacy launcher, move that file to a backup location you choose, then install the package. Do not use pipx `--force` to overwrite an unidentified executable. `task install` runs `pipx install` from this checkout.

To update a local installation, use `pipx install --force /absolute/path/to/gsd-cli-repo-bootstrap` **after confirming that pipx owns the existing command** (`pipx list`). Package upgrades do not overwrite project policy. The development wrapper `./gsd-cli` requires the package source, Click and Pydantic; it is not a single-file distribution.

## Commands and forwarding

```text
gsd-cli --version
gsd-cli init
gsd-cli status [--json]
gsd-cli check [claude|codex] [--json]
gsd-cli policy [--json]
gsd-cli schema [NAME]
gsd-cli sessions [claude|codex] [--pick [N]] [--json]
gsd-cli claude|codex BLUEPRINT [--secure] [--config [--details|--json]] [-- CHILD_ARGS...]
```

Runtime and blueprint are mandatory. For a list of project-local choices, run `gsd-cli claude` or `gsd-cli codex`. Inside the session, choose the GSD skill yourself.

The first literal `--` separates launcher arguments from child arguments. Everything after it is forwarded unchanged, including another `--`, `--help`, `--secure` or `--model`. Before it, unknown options are errors. Codex directory switches (`-C`, `--cd`, including attached values) are rejected before writes because they would relocate the child after project selection; run the launcher from the destination project instead. Tokens after the child's own `--` remain literal positional arguments. `gsd-cli claude --help` is read-only launcher help; `gsd-cli claude medium -- --help` prepares config and launches Claude's help.

A forwarded model/effort argument may override the blueprint at the child CLI's discretion. `--secure` suppresses automatic bypass only; it does not remove bypass flags you explicitly forward. No credential or model-availability probe runs.

## Configuration preview

```sh
gsd-cli codex medium --config
gsd-cli claude high --secure --config
gsd-cli codex high --config --details
```

Preview calculates the prospective working config, including pending persistent edits, and queries the selected installed GSD resolver in a temporary snapshot. The compact view identifies the runtime, blueprint, session request and all inspected roles (covered or uncovered). Each role's model and effort identify their policy sources. Claude rows show prospective project agent file actions. Details include full policy paths, findings and resolver propagation fields. JSON includes the full returned resolver row.

`--config --details` retains the requested session argv, resolver inputs, diagnostics, reviewer models and efforts, and prospective JSON. It colors JSON syntax in an interactive terminal. Headings and check symbols in the compact view are colored there too. `NO_COLOR` disables color; redirected output is plain text. `--details` requires `--config`.

The **Check** column compares configured expectations with available evidence:

| Check | Meaning |
|---|---|
| `✓` | Applicable comparisons match resolver/installed-file evidence. |
| `✗` | A known mismatch exists; detailed notes name the setting and both values. |
| `?` | Evidence or an unambiguous configured expectation is missing. |

For Claude, the report distinguishes configured effort from installed agent frontmatter and session inheritance. For Codex, it shows GSD's rendered effort and propagation mechanism. A resolver-confirmed configuration is not proof of actual AI execution. The session and reviewer sections display configured requests with execution marked unknown. Agents without an explicit effort expectation also retain `UNKNOWN`; GSD's resolved default is still shown. A mismatch takes precedence over other unknown fields in the same row.

The preview never launches an AI CLI, performs journal recovery, captures changes, writes project config or launch logs, or synchronizes installed agent files. Node and compatible compiled GSD modules are required; AI CLI binaries and credentials are not. It bypasses GSD's automatic build entry point. Temporary files are removed after the query. Active workstream config is copied into the snapshot; unsupported `GSD_PROJECT` context or filesystem-dependent legacy `multiRepo` migration yields an explicit incomplete result.

Exit 0 means preparation and resolution completed, even if there are mismatches or unknown findings. An unavailable/old resolver, malformed response, timeout, or unsupported context prints known configuration, labels the report `INCOMPLETE`, and exits 1. A merge conflict, pending recovery journal, or held synchronization lock prevents a reliable preview and fails without changing files. Idle lock files are allowed.

Put `--config` before the first `--`. After that delimiter it is a child option and normal launch behavior applies. Forwarded arguments are displayed, with a warning that they may override the requested session settings. `status` continues to show the saved working config rather than calculating a prospective launch.

## GSD version checks

The complete project policy must include:

```json
"gsd": {
  "min_version": "1.21.0"
}
```

The bundled floor is an editable project requirement. For a version-two policy missing this field, add the required minimum explicitly. For a version-one policy, convert the full policy as described under [initialization and migration](#initialization-and-migration).

```sh
gsd-cli check          # report Claude and Codex
gsd-cli check codex    # one runtime
```

Each report includes PASS/FAIL, installed GSD version, required minimum, installation path and failure reason. Exit status is 0 when all requested checks pass and 1 for an unmet requirement. Check does not require Node or either AI CLI executable, access the network, run GSD code, update installations, capture changes, replay recovery or write logs.

Before the launcher opens a runtime, the same check blocks unsupported installations **before any configuration writes**, including lock/journal recovery. Only the launched runtime is gated; external reviewer CLI adapters do not themselves require that runtime's GSD installation. Help, status, sessions and init remain usable with old/missing GSD. `--secure` changes permission flags only and cannot bypass the version gate.

Discovery is runtime-specific, starting from the discovered project root:

1. Explicit `CLAUDE_CONFIG_DIR` or `CODEX_HOME` selects that runtime's config directory. A leading `~` expands to home; relative directories resolve against the project root, which is also the launched CLI's working directory.
2. Otherwise a project `.claude/gsd-core` or `.codex/gsd-core` takes precedence when present.
3. Otherwise the corresponding `~/.claude/gsd-core` or `~/.codex/gsd-core` is checked.

An explicit missing directory, malformed version, or incomplete local bundle blocks; it never borrows a global copy or the other runtime's version. The bundle must contain a readable, bounded regular `VERSION` file and regular `workflows/update.md` / `bin/gsd-tools.cjs` files. This checks the selected bundle; it does not verify every hook/agent file or absolute workflow paths embedded in custom skills. Keep custom skill paths aligned with the selected installation.

Versions use [SemVer 2.0.0 precedence](https://semver.org/spec/v2.0.0.html): numeric components compare numerically, build metadata does not affect precedence, and `1.20.1-rc.1` is below `1.20.1`. Partial versions, a `v` prefix and malformed identifiers are rejected. A newer prerelease such as `1.21.0-rc.1` satisfies a `1.20.1` floor; a minimum is not a stable-only release policy.

On failure, update or repair the **reported installation** through GSD's update workflow and rerun check. No automatic update is performed.

## Initialization and migration

Run `gsd-cli init` inside an existing GSD project or a descendant. A `.planning/` directory without any config file is enough, for example right after `gsd-map-codebase`; the nearest one wins, but a bare `.planning/` above the Git repository root or in your home directory is ignored. Init does not create `.planning/`, a GSD roadmap or requirements. Other commands still require `.planning/config.json` or `config.default.json`.

Initialization seeds a missing policy from the packaged version-two starter and validates an existing policy. Convert a version-one project policy manually before initialization or launch. [Migration walkthrough](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/blob/main/MIGRATION.md#convert-a-version-one-project-policy)

The existing `.planning/config.json` remains byte-for-byte unchanged during init. Persistent unmanaged settings seed `.planning/config.default.json`; starter `gsd_defaults` fills only missing settings, currently `workflow.compact_content=true`. Repeat initialization preserves project policy and local edits. A malformed policy is an error, never grounds to reset it to package defaults.

For Git projects, init refuses staged working-config changes. Commit or unstage those deliberately first. It removes only `.planning/config.json` from the index, preserves the disk file, and adds narrow ignore rules. When `.planning/` was entirely ignored, exceptions expose only the tracked default. A nested `.planning/.gitignore` conflict must be reconciled before migration.

Review the resulting diff, then commit the policy, default, `.gitignore` changes and index removal together. Initialization never commits. In non-Git projects, files and ignore rules are created without index changes.

## Project policy

The [configuration guide](configuration.md) describes runtime-local blueprints, the five required phase settings, per-role overrides and the runtime review block. Use `gsd-cli policy` for validation and `gsd-cli schema policy-file` for the JSON Schema.

## Effort and GSD routing

Claude receives session effort via `--effort` and Codex via `-c model_reasoning_effort=...`. Role effort goes into `effort.agent_overrides`, and reviewer effort into `review.effort`. Each control has its own policy field.

Claude launch preparation reads definitions beside the selected GSD installation and writes project copies for covered roles. It changes the model and effort frontmatter, preserving the upstream prompt body and other metadata. Review planned actions in `gsd-cli claude medium --config --details`. Installed user files stay under the control of their installer. The selected installed source and project destination must be distinct. To check installed resolver output and interpret actual discovery evidence, see [check commands](checks.md#check-installed-routing-directly).

## Automatic capture and recovery

Before each launch, persistent settings are merged using three versions: the last successful baseline, the current working config, and the tracked default. Object keys merge independently; arrays and scalar values are indivisible. Deleting a value differs from assigning null. Editing the same value differently, or deleting a parent while the other side edits a child, is a conflict.

Only persistent GSD edits change the default. The launcher excludes the managed model, effort and review paths and the known transient `workflow._auto_chain_active`. It preserves unrelated entries in shared sections. Previously managed entries are remembered so removing a pin or reviewer from policy also removes its generated working value.

Claude launches maintain exact generated paths in a marked block of the project’s `.gitignore` and store content hashes in the private sync state. An unchanged file stays in place. A later Claude launch refreshes upstream changes and removes stale owned files when their roles lose coverage. If an obsolete owned file is already absent, the launcher forgets its ownership. A Codex switch keeps the Claude files and ownership. Interrupted Claude transactions can be replayed before either runtime launches.

An existing unowned or tracked destination, edited generated bytes, duplicate project role identity, or conflicting Git ignore rule stops preparation. Preserve any custom definition before moving it outside the generated destination and resolve duplicate names. For an edited owned file, save the edits elsewhere, then restore its last generated bytes or move it out of the way before retrying. Resolve Git tracking and ignore conflicts explicitly and rerun preview. A shared ignore rule alone never authorizes overwriting another person's file.

If a new catalog covers a formerly unmanaged role, initialization-only values copied into the default can be retired when their recorded seed still matches. If either copy has changed or local ownership metadata is missing, review the named path, move the intended value into the blueprint, and remove the conflicting value from the default and working config before retrying.

The tracked default must not contain managed or transient entries; errors name the conflicting paths. To relinquish an owned setting and edit it in GSD, first ensure the selected blueprint no longer covers that setting and launch once to retire ownership, then add the unmanaged value. Do not edit generated model pins in config.json: the project policy owns them.

Default-only edits propagate locally. A missing working file is recreated. A fresh checkout can start with just policy and default. If a working file and default disagree without a baseline, reconcile their persistent contents before retrying; the launcher does not guess which is newer. A missing tracked default with an existing baseline must be restored.

Writes use individual atomic replacements and a private `.planning/.gsd-cli-journal.json`; the set of files is **not** one atomic filesystem transaction. The next mutating operation resumes an interrupted transaction only if each target still matches its recorded before/after content. If an external edit prevents replay, preserve copies of the edited files and journal, compare the target with the journal's before/after versions, and reconcile intentionally before retrying. Do not delete the journal and then let partial state masquerade as a normal edit.

The short `.gsd-cli.lock` protects preparation, not a running AI session. Use separate worktrees for simultaneous sessions with different blueprints. Help, status, check and sessions do not recover, capture or write config. `status` reports whether recovery is pending.

## Billing and history

Guards refuse `ANTHROPIC_API_KEY` when the session or selected reviewers use Claude, and `OPENAI_API_KEY`/`CODEX_API_KEY` when they use Codex. Custom reviewer names are checked through their adapters. These environment checks cannot guarantee an account's billing configuration. OpenCode/OpenRouter reviewers remain metered.

Each prepared launch records runtime, blueprint, session model and effort, forwarded arguments and policy/effective-config snapshots in a mode-0600 JSONL log. Missing executables, billing failures and merge conflicts produce no launch record. A failure after preparation may leave prepared config. The record is not proof that the child completed successfully.

New session records use the captured runtime review block. Legacy records remain readable using historical reviewer mappings. Where several selected reviewers share an adapter and logs do not identify the instance, the report avoids guessing its expected model.

## Development and validation

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest -n auto tests
python -m gsd_cli --help
```

`gsd-cli --version` reads the version from package metadata, not from `pyproject.toml`. In a development checkout that metadata can be stale:

- An editable install writes its metadata only when it is installed. After a version bump, it keeps reporting the old version until you rerun `python -m pip install -e '.[test]'`.
- `python -m gsd_cli` run from the repository root also sees a `gsd_workflow_cli.egg-info` directory left there by a package build, and may report that build's version instead.
- A checkout that was never installed prints `gsd-cli unknown`.

None of this changes behaviour. Reinstall (and delete a stale `*.egg-info`) before relying on the reported version, for example when the gsd-cli skill checks its minimum release.

Tests use temporary projects, real temporary Git indexes and stub CLIs. No credentials, external AI calls or network are needed after dependencies are installed. CI tests Python 3.10 and 3.11. Package installation must also be checked outside the source checkout so missing JSON resources cannot hide behind imports from the repository.
