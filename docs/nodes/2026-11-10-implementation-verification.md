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
