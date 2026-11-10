# Effective configuration preview implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Print the next launch configuration and installed GSD resolution with OK / NOT OK / UNKNOWN checks, without launching or changing project state.

**Architecture:** Share pure merge preparation with normal synchronization. Query the selected installed GSD command module against a temporary configuration snapshot, bypassing its self-healing CLI bootstrap. Keep comparison/reporting separate from the resolver adapter.

**Tech Stack:** Python 3.10+, existing Click, standard library, installed Node/GSD; offline unittest fixtures.

**Spec:** `docs/nodes/2026-11-10-effective-config-preview-design.md`

## Global constraints

- No AI sessions, network calls, project writes, recovery, launch logs, or installed-file updates in preview.
- Explicit workflow/runtime; medium default; arbitrary project workflows; first `--` remains the forwarding boundary.
- Use selected-runtime installation discovery and project minimum version. No fallback to another runtime.
- Exit 1 for incomplete resolution/preparation failure; drift findings do not change exit status.
- Evidence labels never claim observed model execution. Show complete prospective JSON.

## Review focus

- Persistent lock files left by init must not make all previews unusable: distinguish held locks from idle files (task 1).
- Workstream/env-relative config paths must not silently resolve from the temporary directory (task 2).
- Resolver migration/build side effects must stay away from project and installation (task 2).
- A known mismatch combined with unknown effort must remain NOT OK (task 3).
- Forwarded arguments and terminal controls must not misrepresent requested settings (task 3).

### Task 1: Shared preparation and read-only project snapshot

**Files:** modify `gsd_cli/config.py`; extend `tests/test_config.py`.

**Interfaces:** `prepare(default: dict, working: dict | None, state: dict | None, resolved: dict) -> tuple[dict, dict, dict, list[str]]` returns working/default/state/changed paths without mutation. `preview(root: Path, policy: dict, resolved: dict) -> tuple[dict, list[str]]` reads and verifies stable inputs. `synchronize` keeps its existing signature and uses `prepare`.

- [ ] Write failing tests for preview/synchronize parity, pending capture without writes, unchanged bytes/mtime, missing working/state, merge conflicts, pending journal, occupied versus idle lock, and policy changes.
- [ ] Run `python3 -m unittest discover -s tests -p test_config.py -q`; expect new preview assertions to fail before implementation.
- [ ] Extract `prepare`; implement stable file snapshots and non-writing shared lock probe on an existing lock file. Reject a held lock or pending journal. Retain normal synchronization's exclusive lock and transaction.
- [ ] Run the targeted tests and full suite; expect all pass. Commit `Share configuration preparation with read-only previews`.

### Task 2: Query installed GSD against a disposable snapshot

**Files:** create `gsd_cli/resolver.py`, `gsd_cli/data/preview-resolver.cjs`, `tests/test_resolver.py`; modify package data in `pyproject.toml`.

**Interfaces:** `inspect(root: Path, data: dict, runtime: str, minimum: str) -> dict` returns installation details, catalog, loaded config/source, agent results, diagnostics, and `complete: bool`. Errors become explicit incomplete findings. Receives task 1's prepared `data`.

- [ ] Write failing tests using fabricated installed Node modules for runtime env/local selection, config loaded from scratch, workstream overlays, no CLI bootstrap invocation, malformed catalog/output, partial row errors, timeout/missing Node/old version, and unchanged source files/mtime.
- [ ] Run `python3 -m unittest discover -s tests -p test_resolver.py -q`; expect absent adapter failures.
- [ ] Implement selected-install checks; normalize runtime/GSD home env paths to original root. Copy workstream config as data. Reject unsupported GSD_PROJECT context and filesystem-dependent legacy sub-repo migrations explicitly. Use the installed catalog and add custom override agents.
- [ ] Implement a small packaged Node bridge calling `loadConfigResolved(..., {persist:false})` for context and exported `cmdResolveExecution` for each agent. Frame original command JSON without replacing resolver logic. Call compiled modules directly, so no bootstrap/build runs. Bound execution to 20 seconds and validate output; retain failed row diagnostics. No installation/home writes.
- [ ] Run targeted and full tests; expect all pass. Commit `Resolve preview settings with the selected GSD installation`.

### Task 3: Comparison report, Click option, and user documentation

**Files:** create `gsd_cli/preview.py`, `tests/test_preview.py`; modify `gsd_cli/cli.py`, `README.md`, `docs/LAUNCHER.md`, `MIGRATION.md`.

**Interfaces:** `render(root: Path, workflow: str, runtime: str, level: str, policy: dict, resolved: dict, data: dict, captured: list[str], argv: list[str], forwarded: list[str], inspection: dict) -> str`. CLI obtains `data` via task 1, `inspection` via task 2, prints report, and fails only if incomplete. Share `launch_arguments(runtime, resolved, secure, forwarded) -> list[str]` between launch and preview.

- [ ] Write failing tests for OK/NOT OK/UNKNOWN, mismatch precedence, inheritance/forwarded ambiguity, clamping, configured reviewers, complete JSON, custom workflows/default medium, secure argv, option boundary, unavailable resolver, terminal escaping, and no session/billing/executable requirement or writes.
- [ ] Run `python3 -m unittest discover -s tests -p test_preview.py -q`; expect missing report/option failures.
- [ ] Implement comparisons against explicit pins or launcher phase-tier mappings, retaining uncertainty when no expectation is justified. Render deterministic grouped agent rows with detail lines and Check column; session/reviewer configuration-only rows remain UNKNOWN. Display loader context and requested inputs separately from GSD resolution; mismatch notes name each field. Add Click branch before launch checks/writes.
- [ ] Add concise documentation examples, evidence/check semantics, incomplete exit behavior, and Node requirement. Mark design approved and record the occupied-lock refinement.
- [ ] Run full offline suite plus Python 3.10 suite; exercise both real installed resolvers with disposable fixtures and verify untouched project/installed agent artifacts. Inspect package resources. Commit `Add resolver-backed config previews to workflow commands`.

## Final verification

Run a fresh whole-branch code review following executing-plans, with emphasis on this feature and the review focus above. Reproduce and fix material findings with tests. Keep the feature branch available for review; do not merge or reinstall the host tool without authorization for those actions.
