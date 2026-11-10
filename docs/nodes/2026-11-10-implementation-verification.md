# Configurable launcher verification

Implemented on `feat/configurable-launcher`, starting from `2e4933a`. The owner authorized proceeding with the proposed defaults. No external AI sessions or paid model calls were used for testing. The globally installed launcher and Claude agent definitions were not changed.

## Evidence before final review

- Full offline suite: 95 tests pass with system Python 3.12 / Click 8.1.6 and isolated Python 3.10.21 / Click 8.5.1.
- Built source distribution and wheel with `uv build`; wheel contains the actual default-policy JSON resource.
- Installed the wheel through pipx into temporary pipx home/bin/man directories. Ran help, init and status outside the checkout. Edited project policy and repeated init; the edit survived.
- Real installed GSD resolver smoke: 60 checks, both native Claude/Codex installations, plan/exec, all three levels, planner/executor/plan-checker/codebase-mapper/doc-classifier. Model and explicitly overridden effort matched the emitted configuration.
- The first smoke script incorrectly classified plan-checker as planning. Both installed `bin/shared/model-catalog.json` files classify it as verification (line 149). Correcting the test expectation made it pass; production routing did not change.

## Limits

These checks validate configuration, migration, argument handling and resolver behavior. They do not benchmark model quality, actual token spend, or successful paid reviewer execution. Actual Claude subagent effort still requires appropriate installed frontmatter; the launcher only warns and emits project effort settings. GSD workflow code and runtime spawn schemas can bypass or limit resolver settings, as documented in the audit.

Synchronization is recoverable across per-file replacements, not a multi-file atomic transaction or isolation for concurrently running AI sessions. Use separate worktrees for concurrent configurations. The ordinary runtime CLI is replaced with an offline stub in launch tests.

## Independent review and final fixes

One independent whole-branch review found no critical issues, two important issues and two minor issues. Both important findings were reproduced with failing regression tests and fixed:

1. Capture now compares JSON booleans distinctly from numbers, including nested objects/arrays, missing-baseline checks and changed-path reporting. This prevents a tracked `true` edit from being silently restored to `1` and detects genuinely conflicting typed edits.
2. Migration now evaluates effective Git exclusion, appends necessary exceptions after overriding rules, checks ignored project ancestors, and tests the proposed root/nested ignore files in a temporary Git repository before project writes. It rejects nested rules that hide tracked defaults or expose private synchronization files. Repeated init preserves stable ignore rules.

Final suite: **106 tests**, passing on Python 3.12 / Click 8.1.6 and Python 3.10.21 / Click 8.5.1. No second reviewer was dispatched; regression tests and the full suite verify the fixes.

### Retained scope decisions

- Model-quality, token-cost and paid-reviewer benchmarking are excluded. Cost of that choice: actual savings and quality remain unmeasured.
- Global Claude effort synchronization remains manual because installed agent files are shared. Cost: an explicit sync is needed to realize agent-effort changes.
- Running sessions are not isolated by the preparation lock. Cost: concurrent presets need separate worktrees.
- Unrelated historical session parsing/matching remains unchanged. Cost: the original assessment's reporting limitations remain.
- POSIX is the supported platform. Cost: Windows is unsupported.

### Deferred minor findings

- A manually malformed journal entry that omits its `before` key raises `KeyError`, instead of an actionable `ConfigError`. The journal is retained and no target files are written by that failed recovery attempt.
- Unknown launcher options produce Click's standard error. Guidance to put child arguments after `--` appears in workflow help rather than directly in that error.
