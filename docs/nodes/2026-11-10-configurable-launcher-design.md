# Configurable workflow launcher design

Date: 2026-11-10. Status: proposed design, awaiting owner approval.

Research update: the subsequent [GSD performance and cost audit](2026-11-10-gsd-performance-cost-audit.md) identifies additional effort controls that must be resolved before this design is finalized: Claude session effort is supported, agent effort is independent of model level, installed Claude agent definitions require synchronization, and external review effort is configured separately per adapter. The schema below predates those findings and is not yet a complete effort-policy contract. No configuration changes from the audit have been applied.

## Intent and agreed behavior

The launcher already serves the owner's need for preconfigured Claude and Codex workflows, including important external reviewer choices. The change should remove inconsistent CLI names and routine Git changes from selecting a runtime or model. Session history is not currently used and is secondary.

The owner selected these behaviors:

- `gsd-cli <workflow> <runtime> [low|medium|high]`, with medium as the default.
- Workflow names are configurable; planning and execution are initial use cases, and names such as `ship` are possible.
- Commands configure and open the underlying CLI. They never invoke a GSD skill or command automatically.
- The level controls the session and the workflow's main task types. Other tasks can be pinned independently; reviewers retain their explicit models.
- Every workflow explicitly selects reviewers. No selection is inherited from a previous launch.
- A complete, tracked project-root `gsd-cli.config.json` owns launcher policy. It is authoritative after initialization, with no implicit built-in policy fallback.
- `.planning/config.default.json` is tracked; `.planning/config.json` is ignored and remains the file GSD uses.
- Before each launch, automatically capture changes to persistent GSD settings into the tracked default, excluding launcher-managed fields.
- Use Click for the CLI and package the application for installation through pipx, replacing the single-file copy installation. The owner accepted this dependency and packaging change.

The owner has chosen this direction, not yet approved the detailed schema or implementation decisions below. Items marked “proposed” are assistant decisions for review.

## Goals and boundaries

An ordinary model/runtime/workflow switch must leave tracked configuration unchanged. A persistent GSD setting change must become a meaningful default-file diff on the next launch. Changes arriving through Git or direct edits to the default must also reach the local working file without silently losing local edits.

Preserve Python 3.10+ support, atomic individual file replacement, billing guards, argument forwarding, and private launch logging. Click is the approved CLI dependency; the standard-library-only and single-file-install constraints are superseded by the owner's decision. Keep existing session reporting available without expanding its scope or fixing unrelated reporting defects.

This does not introduce concurrent session isolation, automatic workflow execution, model availability checks, or automatic commits of configuration changes. Independent checkouts/worktrees remain necessary for simultaneous sessions using different settings. It does not claim that the selected models are optimal.

## Approaches considered

**Complete project policy — selected by the owner.** Seed a full policy file, then resolve all models, workflow definitions, agent pins, and reviewer groups from it. Git exposes the policy and upgrading the launcher does not silently change model choices. Projects must deliberately update model definitions.

**Built-in policy with project overrides — rejected.** Smaller project files and centrally refreshed defaults, but the effective policy spans code and configuration and may change after an upgrade.

For capture, the owner selected **automatic capture before launch** over an explicit capture command. Automatic capture reduces manual bookkeeping but requires detecting independent changes to the working file and the tracked default. No extra capture command is required for this scope.

For CLI implementation and distribution, the owner selected **Click with a Python package installed through pipx** over keeping the manual parser and copying a single executable. This adds dependency management and package metadata in return for consistent parsing, help, validation errors, and CLI test support. It also permits separating configuration and synchronization logic from the CLI module.

## Click boundary and package installation

Define a `gsd-cli` console entry point in `pyproject.toml`, backed by a `gsd_cli` package. Declare Click as a runtime dependency using a version range verified to support the stated Python minimum. Select the build backend and exact compatible dependency range during implementation planning; do not depend on an unbounded latest version. Package the complete starter policy as a resource so initialization works outside a source checkout. A module entry point (`python -m gsd_cli`) supports development and subprocess testing.

Use Click for command dispatch, runtime/level choices, the medium default, `--secure`, help, and user-facing errors. Built-in commands remain `init`, `status`, `sessions`, and help. A small custom Click group resolves project-defined workflow names into the same generic launch command; workflow definitions are data, never executable Python plugins. Project lookup and help generation are read-only. Global help and `init --help` must work outside a project and despite malformed project policy; valid project policy may enrich help with available workflows. Errors about invalid policy belong to commands that need it, not to generic help.

Preserve the first literal `--` as the forwarding boundary before Click processes launch arguments. Pass the suffix unchanged as a list of tokens to the child; never reinterpret its `--help`, `--secure`, `-c`, model flags, or positional arguments. Before that boundary, validate only the launcher's documented arguments; unknown options get a clear error directing the user to put child options after `--`. Thus `gsd-cli exec claude -- --help` launches Claude with its help argument, while `gsd-cli exec --help` displays launcher workflow help without synchronization. This intentionally replaces the legacy parser's permissive forwarding before the separator.

Keep policy loading, validation, resolution, synchronization, and launch preparation independent of Click contexts and decorators. Split the package into focused modules where that improves ownership and testing; exact names are left to the builder. The CLI translates domain errors to concise messages and exit codes. Continue to use the existing exec-based child launch and subprocess tests for its observable behavior.

Install from the repository with `pipx install .`; Click and the application live in the pipx-managed environment, and `gsd-cli` is exposed on PATH. Update `task install` and documentation to this model. Document replacement of the old copied `~/.local/bin/gsd-cli`: identify that legacy file and explicitly replace it as part of the installation instructions without overwriting an unrelated executable. Do not require a global/system-Python installation of Click. Document updating an installed local build and check the installed command resolves to the intended package.

Development and CI install the package into a virtual environment before running tests, with an editable install suitable for development. Runtime tests remain offline after dependency installation. Keep `unittest`; Click's `CliRunner` can test help, dispatch, defaults, and error behavior without adding pytest. Test an installed package from a temporary directory outside the repository, including access to its starter-policy resource, to catch packaging errors hidden by source-tree imports.

Reference documentation: [Click custom groups](https://click.palletsprojects.com/en/stable/extending-click/), [Click CLI testing](https://click.palletsprojects.com/en/stable/testing/), and [pipx installation model](https://pipx.pypa.io/stable/).

## Files and ownership

| File | Git | Purpose |
| --- | --- | --- |
| `gsd-cli.config.json` | Tracked | Complete launcher policy, including models, workflows, pins, reviewer groups, and permission defaults. |
| `.planning/config.default.json` | Tracked | Persistent GSD configuration outside launcher ownership. |
| `.planning/config.json` | Ignored | Effective GSD configuration, including the selected launch policy and local transient state. |
| `.planning/.gsd-cli-sync.json` | Ignored | Proposed synchronization baseline and prior ownership metadata. |

The exact basename of the synchronization file is a proposed implementation choice. It must live with the checkout, be ignored, and use private permissions because configuration may contain secrets. Any recovery files must also be ignored and private.

The launcher owns `model_policy.provider`, both supported runtime tier maps, the explicitly declared phase model entries, declared agent override entries, declared reviewer instances, `review.default_reviewers`, and `review.parallel_lanes`. It also removes a project-level `runtime`, preserving the existing `GSD_RUNTIME` selection mechanism. Own individual keys/entries rather than deleting entire `review`, `models`, or `model_overrides` objects; preserve unrelated entries.

Exclude known transient GSD state, initially `workflow._auto_chain_active`, from capture. Preserve that state locally; do not reset it merely because the launcher runs. The initial transient-path list is explicit and documented, not an inference that all underscore-prefixed keys are transient.

Store the previous managed path set in the synchronization metadata. When policy removes a formerly managed pin or reviewer, remove its generated working value rather than capturing it as a new GSD preference. Use the union of previous and current managed paths during that transition; ownership history changes only after successful synchronization. Explicitly reject tracked defaults that contain currently managed or transient paths, naming the conflicting paths. Migration strips these paths intentionally when first creating the default file.

## Proposed complete policy schema

Use a versioned JSON schema, validated by standard-library Python helpers. The following describes fields; the shipped example must supply every required entry, not rely on the abbreviated samples below.

- `schema_version`: initially `1`.
- `runtimes`: required `claude` and `codex` entries, each with low/medium/high definitions containing `session_model`, `agent_model`, and, for Codex, `session_effort`.
- `phase_defaults`: explicit levels for planning, discuss, research, execution, and verification. These provide deterministic values even for tasks unrelated to the chosen workflow.
- `agent_levels`: explicit agent-name → level pins, initially the current `AGENT_TIERS` choices translated to low/medium/high.
- `reviewers`: named instances, each with `cli` and `model` (retaining GSD-compatible instance properties).
- `reviewer_groups`: named lists of reviewer instance names. Empty lists are valid only when explicitly declared; missing reviewer selection is an error.
- `workflows`: arbitrary names, with fields defined below.

Each workflow defines:

- `tasks`: the phase types that follow the command's selected level; may be empty for a session-only preset.
- `task_levels`: explicit phase overrides independent of the selected level. A phase cannot appear here and in `tasks` simultaneously.
- `reviewer_groups`: an explicit group name for each supported runtime.
- `parallel_reviews`: explicit boolean, initially false for the shipped presets.
- `permissions`: explicit `normal` or `bypass` for each runtime. `--secure` always suppresses automatic bypass.
- Optional `session_efforts`: runtime → level → effort overrides; primarily preserves the current Codex high execution session's medium effort. These change session effort, not GSD subagent effort.

Illustrative workflow entry:

```json
{
  "exec": {
    "tasks": ["execution"],
    "task_levels": {"verification": "high"},
    "reviewer_groups": {
      "claude": "review-codex-plan",
      "codex": "review-claude-plan"
    },
    "parallel_reviews": false,
    "permissions": {"claude": "bypass", "codex": "bypass"},
    "session_efforts": {"codex": {"high": "medium"}}
  }
}
```

These proposed execution reviewer defaults are visible, editable choices. They do not establish the original plan's author. The user can define a specifically named workflow for another reviewer selection. Do not infer authorship from the current runtime or consult the previous launch to choose reviewers.

Resolution order: explicit `phase_defaults`, then selected level for workflow `tasks`, then independent `task_levels`; agent pins override phase routing for their named agents. All phase defaults are rewritten each launch to eliminate accidental dependence on the preceding workflow. Reviewers and permissions come from the chosen workflow/runtime. The session always uses the chosen runtime/level mapping.

Translate low/medium/high to GSD's existing haiku/sonnet/opus tier keys at the boundary. Claude agent models remain aliases; session models may be full IDs. Codex agent models are full IDs. Preserve GSD's own per-agent effort resolution; do not pretend session effort controls every subagent.

Seed the current runtime mappings: Claude low Sonnet, medium Opus, high Fable; Codex low Luna, medium Sol, high Astra, with the current exact IDs and efforts from the repository. Seed `plan` with planning/discuss/research following the level and verification pinned high, explicit opposite-runtime subscription reviewers plus Grok and Gemini, and normal Claude / bypass Codex permissions. Seed `exec` as illustrated. Include an example custom `ship` definition in documentation; do not invent a mandatory ship routing policy.

Validation must reject missing runtime/level definitions, unknown levels or phases, bad field types, overlapping task assignments, unresolved group or reviewer names, reserved workflow names, and invalid permission values before any file changes. Reserve `init`, `status`, `sessions`, and help commands. No silent fallback to source-code tables on malformed or incomplete policy. Errors identify the offending field.

## Automatic capture and regeneration

Proposed approach: a three-way merge of persistent GSD settings using an ignored baseline. Define:

- B: persistent settings after the last successful synchronization.
- L: current working configuration with managed and transient paths removed.
- D: current tracked default configuration.

Compare JSON values, not whitespace. Merge recursively by object key. Treat arrays and non-object values as indivisible values, and distinguish deletion from JSON null.

- Only L changed: capture L into the result.
- Only D changed: apply D to the result.
- Both changed identically: accept the shared value.
- Both changed differently at the same value, including deleting a parent while the other side edits a child: stop with the conflicting paths and make no configuration changes.
- Changes to independent keys merge automatically.

Show a short capture summary with changed paths, not values that might contain secrets. Leave the resulting default diff for normal Git review; never auto-commit it. For conflicts, tell the user to reconcile the named values in the working and default files, then retry. The baseline stays unchanged until synchronization succeeds.

Launch sequence:

1. Parse and validate command, discover project, load and validate full policy and configuration, verify the runtime executable exists, and run billing guards using the selected reviewer instances' actual adapters.
2. Acquire a short synchronization lock for file preparation, re-read the relevant files, compute the merge and selected policy in memory. This lock does not imply session isolation.
3. Prepare the merged default, effective working config, and next baseline/ownership metadata. Keep unrelated local transient fields intact.
4. Write with atomic file replacement and recoverable bookkeeping. Do not claim multiple replacements form one atomic transaction. On interruption, the next mutating operation must finish the already prepared transaction or detect incompatible external edits and stop; it must not reinterpret a partial write as a user change. The builder may choose the journal format.
5. Release the lock, record the launch, set `GSD_RUNTIME`, and `exec` the runtime with its model, Codex session effort where applicable, permission flags, and forwarded arguments. Continue to warn rather than abort on launch-log failure.

Failure during validation, guard checking, or merge conflict detection must leave all configuration files untouched. A missing executable must no longer produce a configuration change or successful-looking launch record. Startup failures after synchronization can leave prepared configuration; no claim of child success is made.

If the working file is missing, recreate it from D and policy; do not interpret absence as deletion of all settings. A fresh checkout with D and policy but no baseline/working file can initialize local state at launch. If L and D both exist without baseline metadata, proceed only when their persistent projections match; otherwise stop and require reconciliation rather than guess which is newer. If a baseline exists but the tracked default is missing, stop with an actionable restoration error.

## Initialization and migration

Proposed interface: retain `gsd-cli init` as the explicit setup/migration operation. It may discover an existing GSD project via its working or default config. Ordinary launch discovery must also recognize a default-only fresh checkout. Resolve paths relative to the project root, including when invoked from a descendant.

For an existing legacy project:

1. Validate existing configuration and inspect Git state before modifying files. Stop if the working config has staged changes that migration would discard or if conflicting destination files exist.
2. Seed a full launcher policy if absent. Preserve existing supported runtime tier maps, known agent pins, reviewer definitions, and parallel-review preference where representable. Fill new required workflow/session choices explicitly in the generated file using the shipped template, with a summary of generated choices. Preserve custom unmanaged configuration in the default. Do not silently replace existing complete policy.
3. Create the default by projecting persistent, unmanaged settings from the working configuration; preserve the working file. Establish baseline and ownership metadata without launching a runtime.
4. Add narrow ignore rules for the working file, synchronization metadata, lock, and recovery artifacts. Preserve unrelated ignore rules. If an ancestor ignore rule hides the new tracked files, add appropriate exceptions or report the conflict; never unignore unrelated planning state wholesale.
5. In a Git worktree, stop tracking only `.planning/config.json` with an index-only removal, preserving the local file. Do not force through staged changes. This index change is part of explicit `init` migration, not an automatic side effect of an ordinary launch. Tell the user which new files and ignore changes to commit; make no commit automatically.

A legacy project encountered by ordinary launch receives an actionable instruction to run `gsd-cli init`; ordinary launch does not migrate Git tracking implicitly. In a non-Git directory, create the same files but skip Git operations.

Do not support a second runtime-first profile grammar in this initial redesign (proposed). Old invocation forms should fail with a specific replacement example. Preserve existing `status`, `sessions`, and help forms. `status` and `sessions` remain read-only: they must never trigger capture, migration, or recovery writes. Help works outside a project.

## Safety and compatibility

Subscription guards inspect the selected session runtime and reviewer adapters, including custom instance names. Preserve the existing environment-variable checks without asserting they guarantee subscription billing. No credentials are required for tests.

Keep the existing default permission split in shipped workflows: Claude planning normal, Codex planning bypass, execution bypass. New workflow definitions must explicitly state their permissions. User-supplied bypass flags after `--` remain forwarded unchanged; `--secure` only suppresses launcher-inserted flags.

Record workflow, selected level, effective session model/effort, policy snapshot or equivalent resolved policy metadata, and effective GSD config in new launch records. Keep legacy records readable. Session-history fixes are out of scope, but the move away from global `REVIEWERS` must not break reporting: use the recorded reviewer definitions for new records and a legacy compatibility mapping for old records. Retaining historical constants for old records is not a runtime-policy fallback.

## Verification requirements

Extend existing offline subprocess fixtures; no paid calls or authentication. Verify:

- Both runtimes, all three levels, omitted level default, custom workflow names, task pins, independent reviewer models, explicit reviewer selection, and exact CLI argv.
- Click help and error behavior outside projects and with malformed policy, exact forwarding after `--`, rejection of unknown launcher options before it, and no writes during help. Verify the installed console entry point and bundled policy resource outside the checkout.
- Complete policy authority: changing the project policy affects launch behavior; incomplete policy fails before writes; launcher template updates do not override existing policy.
- Capture of persistent GSD edits, zero tracked changes on profile switches, transient exclusion, preservation of custom entries, removal of previously managed entries, and fresh checkout initialization.
- Default-only edits, local-only edits, equal edits, independent edits, conflicting values, deletion versus null, parent deletion conflicts, and interrupted synchronization recovery.
- Migration preserves local data, handles staged changes and existing ignores, untracks only the intended file, and leaves reviewable Git changes without committing.
- Billing guards for custom reviewers, permission split and secure override, missing executables, private logging, and read-only status/sessions.
- Real installed GSD resolver smoke checks against temporary project configurations for both runtimes, separately from offline CI. Verify model resolution rather than only inspecting generated tables. Document installed resolver incompatibilities instead of changing routing assumptions silently.

Run the full offline suite and update README, launcher guide, examples, and repository instructions to match changed reviewer preservation and CLI behavior. CI should exercise the stated Python minimum as well as its current Python version.

## Remaining builder discretion

The builder chooses package module boundaries, JSON validation implementation, build backend, compatible Click dependency range, lock/journal mechanics, and exact error wording within these requirements. Click is approved; avoid unrelated dependencies and a general plugin framework. Implementation planning follows owner approval of this design.
