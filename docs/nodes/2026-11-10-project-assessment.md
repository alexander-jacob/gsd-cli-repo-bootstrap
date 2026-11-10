# GSD CLI project assessment

Assessment date: 2026-11-10. Repository baseline: `6b0d7a9`.

The project is a useful, opinionated launcher for one person's sequential GSD workflow. Its strongest qualities are explicit routing policy, careful configuration writes, and meaningful offline tests. Its weakest area is the confidence conveyed by `sessions`: several classifications and historical comparisons are less reliable than the report's presentation suggests.

That judgment uses the README's stated personal-wrapper scope. The owner's clarification below changes the priority of the findings: workflow configuration and CLI consistency matter more to current use than historical reporting.

## Evidence and limits

Read the launcher, test fixtures and tests, README, installation guide, example configuration context, repository instructions, and CI configuration. Ran `python3 -m unittest discover -s tests -v`: **84 tests passed in 6.916 seconds**. Additional temporary probes exercised classification, effort checking, nested configuration types, and billing guards. No authenticated model sessions or paid reviews were launched.

This assessment does not establish current provider model availability, subscription entitlements, cost savings, or model quality. The repository tests use stub CLIs and a stub resolver. One additional probe used the installed real GSD resolver; its result and limits are recorded below. No production code was changed.

## Strengths

1. **The scope solves a concrete coordination problem.** Profiles select a session model, update phase tiers, materialize runtime-specific agent pins, and select reviewers by plan origin. Execution preserves the selected reviewers. This directly supports the documented plan-in-one-runtime, execute-in-another workflow. Evidence: `PROFILES`, `AGENT_TIERS`, and `main()` in [gsd-cli](../../gsd-cli).

2. **Routing concepts are separated explicitly.** Session models, phase tiers, per-agent pins, and session effort have distinct tables and functions. Claude aliases and Codex IDs are handled differently. This is more maintainable than scattering equivalent CLI strings across shell scripts. The distinction is also tested; it does not by itself prove compatibility with every installed GSD release.

3. **Configuration updates have useful safeguards.** `initialize()` preserves unrelated settings and additional reviewer names; launches preserve unmanaged agent overrides. `save()` writes a temporary file in the same directory, preserves permissions, flushes and synchronizes the file, and atomically replaces the target. This protects against partially written JSON. It does not serialize concurrent updates.

4. **Tests exercise observable behavior.** [Launcher tests](../../tests/test_gsd_cli.py) run subprocesses against stub executables and inspect actual arguments, environment, working directory, configuration, and launch records. [Session tests](../../tests/test_sessions.py) cover nested agents, malformed JSON lines, launch matching, missing resolver behavior, and read-only reporting. The suite is fast enough to run routinely and requires no paid services.

5. **Observability addresses a real routing failure mode.** Launch records capture configuration and forwarded arguments; `sessions` compares requested and recorded models and uses a resolver for agent expectations. The private log permissions and warning-only logging failures are sensible operational choices. This is a valuable feature even with the accuracy limitations below.

6. **Deployment is simple and limitations are unusually explicit.** The executable uses only Python's standard library. The README clearly states that billing is not guaranteed, shared configuration is not isolated, OpenCode is an external reviewer rather than a primary launched runtime, and provider catalogs can change.

## Confirmed weaknesses

### Historical comparisons do not replay all recorded inputs

`record_launch()` stores `gsd_defaults`, but `Resolver.resolve()` writes only the project `config` into its temporary project. It runs the currently installed resolver with the current environment. Nothing reads the saved `gsd_defaults` field when comparing historical sessions. Reviewer checks similarly use today's `REVIEWERS` table, rather than the launch snapshot's reviewer definitions.

Consequently, the record is not sufficient for an exact historical replay. Resolver upgrades or relevant global settings may change expectations; changing a reviewer model in the launcher changes how old reviewer runs are judged. The latter follows directly from `check()` reading `REVIEWERS`.

A temporary real-resolver probe varied global model overrides while keeping the launch snapshot fixed. Both runs returned `gpt-5.6-terra`; it **did not demonstrate** a change caused by those global overrides. The proven finding is that recorded defaults are unused, not that this particular installed resolver accepted those overrides. Evidence: `Resolver.resolve()` at line 466, `check()` at line 510, and `record_launch()` at line 715.

### Codex reviewer identification is too broad

`read_codex_runs()` classifies every root log with `source == "exec"` as a reviewer. Unlike the Claude reader, it does not require a review prompt. A fabricated Codex log containing session metadata and turn contexts, with no review request, was classified as `reviewer`.

The report can therefore label a non-review exec session as `astra-review` and compare it against the review model. The existing `test_codex_reader_marks_exec_as_reviewer` tests this classification rule, so passing tests do not resolve the semantic problem. Evidence: `read_codex_runs()` at line 319 and `reviewer_name()` at line 505.

### Requested effort differences can be silently missed

The readers populate `requested_effort`, and rendering displays it. However, `check()` compares requested versus actual **model**, not requested versus actual **effort**. It checks effort only against a resolved profile expectation when a suitable launch and agent type are available.

A temporary `Run` with requested effort `high`, actual effort `low`, matching model IDs, and no launch produced no mismatch marks. This narrows the usefulness of reporting for sessions started outside this launcher. Evidence: `check()` at line 510.

### Configuration validation stops too early

`load()` checks that the top level is a JSON object. Nested structures are then assumed to have the expected types. Calling `initialize()` with `{"models": []}` or `{"review": null}` raised `AttributeError` in both cases.

This is an error-handling defect, not evidence of data loss: these probes failed before saving. Users editing their own JSON should receive an actionable field-specific error rather than a traceback. Evidence: `load()`, `initialize()`, and nested dictionary access in `main()`.

### Billing guards rely on built-in reviewer names

`guard_subscription_billing()` recognizes Claude reviewers by the literal name `fable-review` and Codex reviewers by `astra-review`. It does not inspect the selected instance's configured `cli` value, although initialization preserves additional reviewer instances.

A direct probe with runtime `codex`, reviewer name `custom-claude-review`, and a dummy `ANTHROPIC_API_KEY` passed the guard. If that custom instance uses Claude, it is outside the guard's detection. Likewise, changing the adapter behind a built-in name can make detection inaccurate. This demonstrates a coverage gap, not an observed charge. Evidence: `guard_subscription_billing()` at line 754.

### Documentation already contains policy drift

The README profile table says “Fable + 3 OpenRouter” or “Astra + 3 OpenRouter.” `OTHER_REVIEWERS` contains two names, Grok and Gemini; the selected preset has three reviewers total. The README also refers to a “four-model reviewer ensemble.” Other sections correctly describe three reviewers.

This matters because the number of paid reviewers affects expectations about review runs. Evidence: [README](../../README.md), lines 188–196 and 297; `OTHER_REVIEWERS` at launcher line 72.

## Tradeoffs and limitations

| Area | Observed behavior | Implication |
| --- | --- | --- |
| Concurrent work | Launches rewrite shared project configuration without a lock or per-session isolation. | Suitable for documented sequential handoffs; simultaneous sessions can observe another session's policy. Atomic replacement alone does not prevent lost updates. |
| Permission defaults | All profiles except Claude planning add permission bypass flags unless `--secure` is supplied. | Supports unattended work but assumes a trusted operator and environment. This is deliberate, documented policy, not an accidental bug. |
| Launch failure | `main()` saves configuration and records the launch before `os.execvpe()` discovers a missing CLI. | A failed start can still change project settings and leave a record that looks like a launch attempt without an explicit failure status. |
| Session attribution | `link()` uses a 60-second launch window and time overlap to attach reviewers. | Useful heuristics, but concurrent or delayed starts can make attribution ambiguous. There is no process/session identifier handshake. |
| Historical model changes | Readers summarize the most common model and discard whether models varied; only effort variation is retained. | A minority of turns using a different model may disappear from the summary. |
| Compatibility | Resolver lookup is fixed to `~/.claude/gsd-core/bin/gsd-tools.cjs`; session roots are fixed under `~/.claude` and `~/.codex`. | Alternative installation locations need handling or explicit exclusion. CI currently exercises Python 3.11 on Ubuntu, while documentation promises Python 3.10+. |
| Review visibility | Session readers cover Claude and Codex, not OpenCode. | The report does not validate the actual Grok/Gemini paid reviewer runs despite their central role in presets. |
| Growth | Codex discovery opens every matching rollout header and fully reads matching project logs; Claude reads all top-level project logs before selecting recent sessions. | Work grows with retained history. No performance measurements were taken, so this is a scaling characteristic rather than a measured slowdown. |
| Retention | Launch records contain full configuration and arguments and are never pruned. | Mode 0600 limits access, but sensitive configuration or arguments can accumulate indefinitely. |
| Maintenance | Policy, launching, parsing, attribution, resolution, and rendering share an 848-line executable. | Single-file installation is convenient; parser changes now share a module with launch behavior. Splitting it is a tradeoff, not automatically an improvement. |

## Initial priorities before owner clarification

These are review priorities, not an agreed implementation plan.

1. **Make reporting claims precise.** Distinguish confirmed reviewer identity from inference; compare requested effort; use historical reviewer definitions; decide whether historical defaults and resolver versions must be replayed or merely disclosed.
2. **Close configuration and guard gaps.** Validate nested fields and derive reviewer billing checks from selected instance adapters. Consider checking executable availability before changing configuration.
3. **Correct documentation drift.** Align reviewer counts with the actual selected lists. Keep a focused consistency check around policy duplicated in examples and documentation.
4. **Test the compatibility boundary.** Keep the offline suite, but add a separately runnable check against the installed real resolver for both runtimes. Stub tests establish launcher behavior, not upstream resolver compatibility. A Python 3.10 CI job would test the stated minimum.
5. **Let intended use determine larger changes.** Shared use may justify isolated session policy and configurable installation roots. A personal sequential tool may benefit more from a small set of accuracy fixes than from a general configuration framework.

## Owner clarification and revised priorities

The owner wants preconfigured models for different workflows across Codex and Claude. External reviewers are important. The launcher currently serves those needs; session history is not currently used. Reporting defects remain valid findings, but they should not drive the next work ahead of the owner's actual friction.

The two reported annoyances are inconsistent command naming (`exec-high` / `exec-medium` for Codex versus `exec-opus` / `exec-sonnet` for Claude) and launch-time edits to a tracked `.planning/config.json`. The latter cause GSD to complain about modified files unrelated to the phase.

The owner proposed a tracked `.planning/config.default.json` with an ignored `.planning/config.json`. They also suggested a possible project-root `gsd-cli.config.json` containing task intelligence levels and external reviewer configuration currently embedded in the executable. These are proposals under discussion, not an approved implementation design.

Revised priorities:

1. Unify workflow vocabulary across both runtimes using intelligence levels.
2. Separate versioned defaults from mutable local GSD configuration so routine launches do not dirty tracked configuration.
3. Explore moving model, task-level, and reviewer policy into a configuration file.
4. Keep session reporting improvements secondary to the current workflow needs.

Code constraints relevant to the discussion:

- The current Claude tier map is high → Fable, medium → Opus, low → Sonnet. A consistent `exec-high` would therefore introduce Fable execution; `exec-medium` and `exec-low` would correspond to the current Opus and Sonnet execution choices. This mapping is a possible interpretation, not yet an owner decision.
- `project_config()` currently discovers a project only through an existing `.planning/config.json`. A fresh checkout containing only the default file would require discovery and creation support.
- Ignoring an already tracked file does not remove it from Git's index. Migration must preserve the local file while ending tracking.
- Existing launches preserve unrelated GSD settings and execution preserves reviewer selection from planning. Rebuilding from defaults on every launch could discard these changes unless persistence is explicitly designed.
- The proposed launcher policy file and GSD default file need clear ownership of overlapping fields; otherwise users could have two competing sources for model and reviewer settings.

The next question is whether changes made by GSD to the local `config.json` should survive subsequent launches, or whether it should be regenerated from the tracked defaults each time. That choice determines whether the default file is a starting template or the continuing source of truth.

### Verified GSD writes relevant to that choice

The owner does not recall GSD changing this file. Inspection of the installed Claude GSD workflows confirms write paths, but does not establish that they ran in the owner's projects:

- `workflows/settings.md` writes user-selected settings through `config-set`.
- `workflows/plan-phase.md:163` persists `workflow.tdd_mode = true` when invoked with `--tdd`.
- `workflows/plan-phase/steps/auto-advance-check.md` sets or clears `workflow._auto_chain_active` depending on invocation flags; `workflows/execute-phase.md:194` clears it on manual invocation without `--auto`.
- `bin/lib/config.cjs`, function `setConfigValue()`, writes these values to the workstream-aware planning `config.json` under a planning lock.

These are specific settings and workflow-state writes. They do not imply that GSD routinely replaces the launcher's model and reviewer policy. The launcher's own writes remain the direct explanation for the owner's reported launch-time Git changes. Preserving local GSD configuration between launches is a possible conservative design, not yet an agreed requirement.

### Owner proposal to capture meaningful configuration changes

The owner proposes a function that copies the local `config.json` into tracked `config.default.json` while excluding launcher-managed settings. This would let changes to persistent GSD settings appear as meaningful Git diffs while runtime model and reviewer switches remain local.

This reframes the tracked file as a maintained record of persistent GSD settings, rather than merely an initialization template. The owner selected automatic capture after being offered automatic capture before each launch versus an explicit capture command.

Design considerations identified in response:

- Exclude exact launcher-owned keys or entries, preserving unrelated entries in shared objects such as `model_overrides` and `review.reviewer_instances`.
- GSD's transient `workflow._auto_chain_active` flag is not launcher-owned, but copying it would reintroduce routine workflow noise. Persistent settings and transient state need separate treatment.
- A diff establishes that unmanaged local settings changed; it does not prove whether GSD or a human changed them.
- If tracked defaults have been edited or updated by Git since the working config was created, blindly copying the older working file over them could undo those changes. Automatic capture needs baseline comparison/conflict handling; explicit export should make the proposed diff reviewable.
- Automatic capture after the child CLI exits would require changing the launch lifecycle: the current launcher uses `os.execvpe()` and does not remain running to perform an after-exit step.

The chosen direction is automatic capture before each launch. The overall implementation design is still under discussion. A local synchronization baseline, merging non-conflicting edits, and stopping on conflicting edits to the same setting are assistant proposals for preserving both local changes and changes to tracked defaults; the owner has not yet reviewed a complete design. An additional explicit capture command has not been requested.

### Unified CLI decisions

The owner wants intelligence levels available for both planning and execution, with workflow names left open to extension, such as `ship`. They selected workflow-first syntax:

```text
gsd-cli <workflow> <runtime> <level>
gsd-cli plan codex high
gsd-cli exec claude medium
gsd-cli ship codex high
```

The owner explicitly rejected automatically invoking a GSD workflow because it would feel restrictive. A workflow name selects a configuration preset and opens the underlying CLI. The user remains free to invoke any GSD command inside that session.

Configurable workflow definitions and runtime-specific mappings for `low`, `medium`, and `high` are the proposed mechanism. Exact schema, level effects on individual task types, shipped workflow presets, reviewer selection semantics, and handling of legacy CLI names remain to be settled. The owner's `ship` example establishes extensibility; it does not yet define a ship preset's routing policy.

### Explicit reviewer selection

The owner chose always-explicit reviewer selection. Each preset must declare its reviewer selection; execution and custom presets must not inherit it from the previous launch. This intentionally replaces the current execution behavior that preserves the previous reviewer list. The schema may reuse named groups, but must make the selected group explicit for each applicable preset/runtime combination. Whether to ship an explicit empty group is not yet discussed.

An implication is that reviewer independence from a plan's original author cannot be inferred from the currently selected runtime: the user may plan in Codex and execute in Claude. Preset definitions must express the intended reviewer selection rather than assume the current runtime authored the plan.

### Intelligence level semantics and default

The owner accepted the proposed level behavior: the selected level controls the session model and the preset's main task types; the preset can explicitly pin other task types, such as verification, to different levels. External reviewers retain their explicitly configured models. The owner also identified `medium` as a good default; the proposed command syntax therefore makes the final level optional and uses `medium` when omitted:

```text
gsd-cli <workflow> <runtime> [low|medium|high]
gsd-cli exec claude        # equivalent to exec claude medium
```

For example, medium Claude execution can select Opus for the session and execution while explicitly keeping verification on Fable. This example demonstrates independent task pins; final shipped preset definitions remain to be written and reviewed.

### Complete project policy selected

The owner selected complete project configuration over built-in defaults plus project overrides. The project-root `gsd-cli.config.json` is to contain the complete model mappings, workflow definitions, and reviewer policy. A shipped template seeds it; launcher upgrades must not silently replace that policy.

A proposed detailed design is recorded in [Configurable workflow launcher design](2026-11-10-configurable-launcher-design.md). It separates owner decisions from proposed schema, synchronization, migration, and compatibility choices. Implementation has not started.

### Click and package installation selected

The owner prefers Click for CLI maintainability and explicitly accepted replacing the single-file installation with a Python package installed through pipx. This supersedes the earlier standard-library-only and single-file distribution constraints for the redesign. Click handles the CLI boundary; configuration, synchronization, and runtime logic remain ordinary Python modules. The revised design includes package metadata, bundled starter configuration, isolated dependency installation, and tests of the installed entry point and argument-forwarding boundary. The full design is still awaiting approval; acceptance of Click and pipx is not recorded as approval to implement everything.

### Performance and price investigation

The owner requested a careful code/documentation-grounded audit of GSD configuration options and agent reasoning needs before implementation. The [performance and cost audit](2026-11-10-gsd-performance-cost-audit.md) contains task and switch matrices, real resolver results, a candidate settings fragment, and caveats about actual runtime effort delivery. This research adds effort-policy requirements to the pending design; it does not authorize changing active settings or claim benchmark-proven optimal models.
