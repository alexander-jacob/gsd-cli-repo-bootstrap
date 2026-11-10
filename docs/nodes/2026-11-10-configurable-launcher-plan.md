# Configurable launcher implementation plan

Spec: [approved design](2026-11-10-configurable-launcher-design.md), with the owner's subsequent approval to proceed using defaults. Audit: [cost and performance](2026-11-10-gsd-performance-cost-audit.md).

## Global constraints

Python 3.10+, Click >=8.1,<9, setuptools package with JSON resource. Offline unittest tests, no paid calls. Preserve the session reporter and authentication guards. Do not update global Claude agent files. Capture persistent changes with recoverable writes and report conflicts. Work in an isolated branch; do not publish.

Effort schema refinement: each runtime level requires session_effort; agent_efforts stores independent per-agent overrides; reviewer_efforts explicitly supplies claude/codex/opencode values. A gsd_defaults object seeds unmanaged settings only during init. Adopt the audit's proposed effort overrides, medium mapper/intel model, compact_content=true; existing persistent settings win on migration. Warn about Claude's global agent effort synchronization.

### Task 1: Package and policy

Files: pyproject.toml, gsd_cli/__init__.py, gsd_cli/policy.py, gsd_cli/data/default-config.json, tests/test_policy.py.
Interfaces: load_default() -> dict; validate(policy) -> None; resolve(policy, workflow, runtime, level) -> resolved dict with managed path/value map, model, effort, reviewers and permissions. PolicyError exposes actionable validation errors.

1. Write tests for complete resource, all runtime/level combinations, explicit reviewer groups, independent efforts and custom workflow; malformed policy rejection.
2. Run `python3 -m unittest discover -s tests -p test_policy.py -v`. Expected: failure because package is absent.
3. Implement package resource and strict schema validation, deterministic resolution with tuple paths.
4. Run full offline suite. Expected: pass, legacy behavior unchanged until Task 3.
5. Commit `Add packaged project policy and audited defaults`.
Completion: all tests pass and bundled default resolves both runtimes at every level.

### Task 2: Capture, migration and recovery

Files: gsd_cli/config.py, tests/test_config.py.
Interfaces: initialize(root) creates policy/default/baseline without replacing working file; synchronize(root, policy, resolved) returns effective config and captured paths. Shared read_json/discover helpers raise ConfigError. Reuses Task 1 path map.

1. Write tests for recursive three-way merge including deletion/null/arrays/parent conflicts; capture, default edits, transient preservation, stale ownership removal, missing baseline/working/default states; journal replay/external edits; init preservation and Git migration/staged refusal/ignore rules.
2. Run targeted tests. Expected: failures for absent config implementation.
3. Implement POSIX flock, atomic replacements, validated private recovery journal, ownership metadata and narrow Git migration. Recheck files under lock; retain recovery evidence until completion. No mutation on preflight errors.
4. Run full suite. Expected: pass.
5. Commit `Capture persistent GSD settings with recoverable synchronization`.
Completion: sync does not dirty tracked defaults on model switches, preserves independent edits and refuses conflicts.

### Task 3: Unified Click commands

Files: gsd_cli/cli.py, gsd_cli/sessions.py, gsd_cli/__main__.py, gsd-cli, tests/test_gsd_cli.py, tests/test_sessions.py.
Interfaces: console main(), dynamic Click group, policy resolve + config sync, historical session reader and launch records. Source wrapper remains for development only.

1. Replace obsolete profile assertions with new workflow-first subprocess tests; retain coverage for launch argv, billing, environment, permission split, logs, read-only commands, session mismatch flags. Add malformed help, exact -- boundary, missing runtime, custom reviewers and policy authority tests.
2. Run targeted tests. Expected: new CLI assertions fail against legacy launcher.
3. Extract session reader preserving old log compatibility; resolve reviewers from new recorded config. Implement Click commands, executable/guard preflight, capture and exec; log workflow/level/effort. Warn for Claude effort synchronization without global writes.
4. Run full suite. Expected: pass.
5. Commit `Launch configurable workflows through a unified Click CLI`.
Completion: both runtimes open correctly with medium default, no implicit workflow invocation or previous reviewer inheritance.

### Task 4: Install, document and verify

Files: README.md, docs/LAUNCHER.md, taskfile.yaml, AGENTS.md, examples/gsd-config-example.json, .github/workflows/tests.yml, docs/nodes design/status.
Interfaces: installed console script/resource, uv-built wheel and pipx isolation; docs match Tasks 1–3.

1. Update installation, migration, custom ship example, effort caveats, new command grammar and CI Python 3.10/3.11. Keep examples generated from authoritative bundled default.
2. Run full suite and build/install wheel into temporary environment, invoke init/help from outside checkout. Expected: resources available and project policy unchanged on repeat init.
3. Run installed GSD resolver read-only smoke on temporary configs for both runtimes. Expected: model/effort matches policy; document runtime limitations.
4. Commit `Document and verify packaged workflow launcher`.
Completion: all offline tests, installed-package smoke and resolver checks reported truthfully.

## Review focus

Inspect data-loss paths: ownership changes, nested deletions, conflicting defaults, journal replay after partial writes, migration Git index/ignore behavior, symlinks and invalid metadata. Inspect Click argument boundary and custom policy validation, secret-bearing file permissions, historical session compatibility, and packaging outside source checkout. Distinguish resolver output from actual Claude frontmatter behavior. No claim of model-quality benchmarking or session isolation.
