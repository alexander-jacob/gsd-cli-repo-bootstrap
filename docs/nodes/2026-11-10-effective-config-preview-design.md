# Effective configuration preview

Status: proposed design, builder check complete with no important unanswered questions; awaiting owner approval. Implementation has not started.

## Intent and decisions

The owner wants to inspect the configuration selected by any workflow preset, including the model and effort for GSD roles and external reviewers. They chose **print and exit** and **resolver-backed** output, and requested an **OK / NOT OK check column** to spot differences quickly. Existing choices remain: explicit workflow and runtime, optional intelligence level defaulting to medium, arbitrary project-defined workflows, and no automatic workflow invocation.

Examples:

```sh
gsd-cli plan codex --config
gsd-cli exec claude high --config
gsd-cli ship codex medium --secure --config
```

This is a bounded feature involving shared configuration preparation, a local resolver adapter, and terminal reporting. The following detailed defaults are proposals by the author, not additional choices already made by the owner.

## Approaches

1. Policy-only: show the launcher merge and configured model/effort values. Simple and independent of Node, but cannot establish GSD fallback behavior or installed Claude effort differences.
2. Resolver-backed: prepare the next configuration without committing it, then query the selected GSD installation locally. More integration work, but exposes GSD's resolution and its available evidence about effort. **Selected by the owner.**

Do not reproduce the model/effort resolution algorithm in Python. Do not run a paid session to discover actual execution.

## Command and output contract

`--config` is a flag on every dynamic workflow command, including project-defined names. It uses normal workflow/runtime/level validation. Like `--secure`, it must precede the first `--`; after that delimiter it remains an unchanged child argument. Built-in `status`, `check`, `init`, and `sessions` keep their existing behavior.

Print a deterministic, plain-text report followed by indented JSON. No pager, interactive prompt, or extra output-format option is needed initially. Include:

1. Project root, workflow, runtime, level, selected installation path/version, and the relevant policy/default/working file paths.
2. Launcher session model, requested session effort, permission mode, and assembled child argv. These are launch arguments, not observations of a running model.
3. Phase model settings and an agent matrix, grouped by phase and sorted by agent name. Columns include agent, relevant configured model/effort inputs, GSD-resolved model, requested/resolved effort, runtime-rendered effort and propagation mechanism, installed effort evidence, **Check**, and discrepancy/unknown notes. Use continuation lines when a table becomes too wide; preserve values without truncation.
4. Selected external reviewers: instance, adapter, configured model, adapter-specific configured effort or unknown. Include any resolved adapter behavior only when supported by inspected adapter code; never describe configuration alone as provider-observed behavior.
5. Persistent setting changes that a normal launch would capture, shown as pending changes without saving them. Include resolver warnings, clamping, and relevant drift such as Claude frontmatter differing from policy.
6. The entire JSON object the launcher would write to `.planning/config.json`, including non-model GSD switches. Label this **launcher effective configuration**; GSD's own built-in defaults and workstream overlays are a separate resolution layer.

The **Check** column compares expectations from the prospective configuration for this command with available resolver/installed-file evidence. Use literal text so checks remain readable without color:

- `OK`: all applicable model/effort comparisons are supported by evidence and match. Documented alias normalization or inheritance may establish equivalence; explain it in the notes rather than comparing raw strings blindly.
- `NOT OK`: at least one evidenced mismatch exists, including an effort clamp that changes the requested level or installed Claude effort that differs from the intended effort. Name the differing setting and show expected and reported values. A known mismatch takes precedence over another unknown field in the same row.
- `UNKNOWN`: no known mismatch, but evidence or an unambiguous expectation is missing for an applicable comparison. Never mark a value OK merely because the report echoes the configuration. This third state is the author's proposed handling of uncertainty.

Apply the same labels to session/reviewer comparisons where shown; configuration-only entries are `UNKNOWN` unless independent evidence supports the comparison. An agent's model can be resolver-confirmed even when installed effort remains unknown; explain field-specific results in the notes. These checks concern configuration resolution and installed-file evidence, not observed AI execution. `NOT OK` is a visible finding and does not change the exit-status contract below.

Agent rows cover the selected installation's registered agent catalog plus agent names appearing in model/effort overrides. Unknown custom agents remain visible and are labeled. Do not maintain a second hardcoded role list. All roles are shown because the launcher selects a preset rather than invoking a particular GSD workflow; a row does not imply the workflow will execute that role. Future retries, per-spawn overrides, and workflow-specific dispatch decisions cannot be predicted here.

Forwarded arguments are displayed verbatim as argv data with safe terminal escaping. If present, label session values as launcher requests that child options may override; do not guess the child's option precedence. Agent resolution remains a report of the prepared GSD configuration. Preserve the existing rejection of forwarded Codex directory changes. Inherited Claude effort is tied to the requested session effort only when no forwarded options make that inference uncertain.

## Shared preparation and read-only behavior

Extract a pure preparation operation from `config.synchronize`: accept snapshots of policy, default, working config, and synchronization metadata; apply the existing ownership projection, typed three-way merge, transient preservation, and resolved managed values; return the proposed working/default/state objects and changed paths. Normal launch retains its lock, recovery, policy-change check, and transaction around this shared operation.

Preview reads the files and calls the same operation, without creating locks, performing recovery, untracking files, invoking Git mutations, capturing changes, writing a journal, recording a launch, modifying agent files, or executing an AI CLI. Temporary files outside the project may be created and must be removed on success and failure.

A pending journal or existing synchronization lock blocks preview rather than presenting an uncertain snapshot. Detect changes to input files during preparation and fail with a retry message. Merge conflicts, invalid policy/configuration, and an ambiguous missing baseline are errors using the same rules as launch. Preview can use a fresh initialized checkout where working config/state are absent if normal synchronization can do so.

## Resolver adapter and evidence

Use `versions.installation_dir` / `check_installation`, so explicit runtime directories, local installs, and home installs use exactly the existing selection rules. Never silently query Claude's installation for Codex. Set `GSD_RUNTIME` to the selected runtime. Normalize relative environment paths against the original project root before changing to a temporary directory.

Use the installed `query resolve-execution <agent> --host <runtime>` contract, which includes model, profile, effort, rendered effort, propagation, clamping, fast-mode fields, and effort evidence. Choose a batched module adapter or bounded subprocess queries during implementation, based on the installed exports and side effects. Both must call GSD's resolver implementation, validate returned fields, retain diagnostics, use timeouts, and avoid invoking its automatic build/repair path. Missing compiled modules produce an incomplete-report diagnostic, never a build.

Supply a private temporary project containing the prospective root config. Copy any selected workstream config as ordinary data, preserving its overlay semantics; do not link writable paths to real project files. Preserve relevant read-only global defaults and installation identity. Inspect the selected resolver's configuration inputs during implementation: if an external planning-directory override or filesystem-dependent migration cannot be reproduced faithfully in the snapshot, report resolution as unavailable with the precise reason. Never silently ignore an active context. Report the workstream/source when applicable; the JSON section remains the prospective root config.

The adapter must verify that queries cannot trigger writes outside temporary storage through the supported code paths. GSD's loader has a `persist: false` option, but its public execution query currently calls `loadConfig` without it, so merely calling a query from the real project is insufficient. Do not globally monkey-patch the installed resolver or alter its output to disguise differences.

Interpret evidence conservatively:

- `effort_effective_source=frontmatter` is an installed-file observation, not a measured execution.
- `frontmatter-absent` establishes inheritance; display `inherit`, plus the known requested session effort if justified.
- `resolved` supplies no installed-file evidence. Show the resolved value and label the effective installed effort unknown instead of claiming it was observed.
- Preserve unknown-agent flags and runtime effort clamping/propagation fields. Report unsupported effort as unsupported, not as an invented numeric level.
- Configured keys are inputs. Do not invent a winning model-source key when the resolver does not expose provenance.

No version-specific installation model names or agent counts belong in product code.

## Failure and exit behavior

The preview does not require authenticated Claude/Codex executables or billing credentials. It does not contact providers or claim launch readiness. Node and a compatible local GSD resolver are required for a complete resolver-backed report.

Exit 0 when configuration preparation and all requested resolution queries succeed. Legitimate unknown/unsupported values, inheritance, and configuration drift are report findings, not command failures. Missing Node, a failed minimum-version check, unavailable/malformed resolver/catalog, unsupported snapshot context, or a failed/timed-out query yields exit 1, prints the known launcher configuration, and explicitly marks the report incomplete. Never substitute the Python policy prediction for a failed resolver result. Invalid invocation follows Click's normal usage exit status. Preparation failure exits 1 without claiming an effective configuration.

The project minimum remains authoritative; do not execute a resolver from a bundle that fails that gate. Help remains available without project initialization or Node. Existing normal launch behavior is unchanged.

## Grounding in current code

Repository evidence:

- `gsd_cli/cli.py:114`: generic workflow command; preparation, runtime flags, forwarding, and launch currently share one callback.
- `gsd_cli/config.py:264`: synchronization's merge and managed-value application currently run inside the writing transaction path.
- `gsd_cli/versions.py:82`: selected-runtime installation discovery. `sessions.py`'s historical resolver path must not be reused for this feature.

Installed GSD evidence inspected on 2026-11-10 (both installations now report 1.20.1):

- `~/.claude/gsd-core/bin/lib/commands.cjs:492`: `cmdResolveExecution`; effort source, rendering, host surface, and unknown-agent fields.
- `commands.cjs:88`: Claude frontmatter directory selection depends on local installation manifest or global runtime home. Show evidence from the directory GSD actually uses; do not assume it is always beside the selected bundle.
- `bin/lib/config-loader.cjs:629`: loading can persist legacy migrations; active workstream is an additional input.
- `config-loader.cjs:1094`: runtime identity is filled from `GSD_RUNTIME`/installation marker when absent. This supplies the runtime used by execution-query effort rendering; no synthetic `runtime` field needs adding to the displayed JSON.
- `bin/ensure-runtime-build.cjs`: the public CLI can rebuild missing compiled libraries, which is incompatible with preview's read-only promise.
- `bin/shared/model-catalog.json`: registered agent phase/routing metadata.

These paths describe inspected evidence, not a guarantee that every future GSD installation has the same internal structure. Implementation must validate capabilities and report unsupported installs explicitly.

## Verification and builder discretion

Use the existing Python/Click package and offline unittest fixtures. Add meaningful coverage for both runtimes and custom workflows, medium default, `--secure`, argument boundaries, forwarded override ambiguity, merge/capture parity, missing working/state files, conflicts/journal/lock/input changes, catalog/custom roles, effort evidence/inheritance/clamping, reviewer fields, runtime-specific local/env discovery, workstream context, malformed query output, timeouts, and missing Node/unsupported installations.

Assert preview leaves project contents and mtimes, launch logs, installed agent files, and installation artifacts unchanged; child CLI stubs must never run. Cover check labels for matches, model/effort mismatches, evidenced alias equivalence/inheritance, clamping, missing evidence, and mismatch precedence over unknown fields. Test preview preparation against the same normal-launch configuration on independent fixture copies. Exercise a real installed resolver on a disposable fixture as an integration check, with no AI CLI or paid requests. Run the existing offline suite to protect normal launch behavior. Update README, LAUNCHER, and MIGRATION with concise examples and the meaning of evidence labels.

Module boundaries, batching mechanics, table layout, subprocess limits, and fixture organization remain builder decisions. Any inability to preserve resolver semantics or the read-only guarantee must be surfaced before weakening either contract. This feature does not modify model policy defaults, synchronize installed frontmatter, add a session-history dependency, execute workflows, or alter pricing recommendations.
