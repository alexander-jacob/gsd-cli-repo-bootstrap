# GSD Minimum Version Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline; one final independent review. Steps use checkbox syntax for tracking.

**Goal:** Block unsupported GSD launches and expose the same check as a read-only command.

**Architecture:** A stdlib version/install module returns diagnostic results. Complete project policy supplies the minimum; Click uses the same module for launch preflight and standalone checks.

**Tech Stack:** Python 3.10+, existing Click, unittest; no new dependency.

**Spec:** [GSD version-check design](2026-11-10-gsd-version-check-design.md).

## Global Constraints

- Default `gsd.min_version` is `1.20.1`; old project policy must add it explicitly.
- Block before any project writes, recovery, logging or external CLI execution.
- Offline, read-only inspection; no update installation or bypass flag.
- Preserve the current branch/worktree and all existing launcher behavior outside the version gate.

## Review Focus

- Old/broken local installations must not be masked by newer global copies.
- Environment overrides must never select another runtime's bundle; a missing override must fail.
- Pending recovery and persistent GSD edits must remain untouched when checks fail.
- Version comparisons must handle numeric components and prerelease precedence, not lexical ordering.
- A corrupted/nonregular VERSION must fail without blocking on a FIFO or executing installation code.

### Task 1: Add version policy, discovery and CLI enforcement

**Files:** create `gsd_cli/versions.py`, `tests/test_versions.py`; modify `gsd_cli/policy.py`, `gsd_cli/cli.py`, bundled JSON, example JSON, `tests/test_gsd_cli.py`, `tests/test_policy.py`, README, launcher guide and AGENTS.

**Interfaces:**
- `parse_version(value: str) -> Version` raises `VersionError`; Version supports precedence comparison.
- `check_installation(root: Path, runtime: str, minimum: str, *, env: Mapping | None = None, home: Path | None = None) -> CheckResult`; result has runtime, directory, installed version (or None), minimum, success and diagnostic message.
- `format_result(result: CheckResult) -> str` gives stable human-readable diagnostics.
- CLI validates project policy, checks one/both runtimes and exits nonzero on any failure; launch calls the same check before synchronize.

- [x] Write behavioral tests: stable equal/newer/older; 1.9 versus 1.20; prerelease numeric identifiers; build metadata; malformed versions; missing/unreadable/incomplete/FIFO files; env/local/global discovery; runtime separation.
- [x] Write subprocess tests: `check` both/one with exact installed/required/path reporting and exit codes; blocks before all writes/logs/exec; custom floor and missing policy field; reserved name; init/help/status/sessions remain usable. Extend fake HOME with synthetic GSD installations, clear runtime override variables.
- [x] Run `python3 -m unittest discover -s tests -p 'test_*version*.py' -v` and CLI/policy tests. Expected: missing module and new command/guard assertions fail against the current branch.
- [x] Implement SemVer and bounded regular-file reading; explicit env > local bundle > global bundle; no runtime cross-fallback or subprocess execution.
- [x] Integrate required policy field, default/example, reserved command and launch preflight. Keep capture untouched on failed checks; no bypass through --secure.
- [x] Update docs with policy upgrade, path precedence, failure behavior and actual inspected version difference.
- [x] Run full suite with system Python and `.venv/bin/python` (3.10). Expected: all tests pass.
- [x] Run a temporary-project standalone check against actual installed GSD using a generated policy; expect Claude PASS 1.20.1, Codex FAIL 1.18.0, overall exit1, no writes. No model calls.
- [x] Build/install a wheel into an isolated environment; run check outside checkout against fixture installations. Expected: resource includes version floor and check command works.
- [x] Commit `Enforce project minimum GSD version before launch`.

Completion: blocking preflight, independent diagnostic command, explicit policy authority, installed-resource smoke and the full offline suite all satisfy the spec. Final independent review covers this extension's diff against `b0bdaca`.

## Verification evidence

- Full offline suite: 129 passing tests on Python 3.12 / Click 8.1.6 and Python 3.10.21 / Click 8.5.1.
- Actual-install check in a temporary project: Claude GSD 1.20.1 PASS; Codex GSD 1.18.0 FAIL; exit 1; no project files changed. No GSD code or AI CLI was executed.
- Built wheel and installed through isolated pipx outside the source checkout: bundled minimum is present; both/one runtime checks have the expected exit codes and leave project files unchanged.
- Initial shared test setup accidentally made the session reporter's resolver appear installed. Existing session tests caught this; synthetic GSD installations now belong only to launcher initialization fixtures. Production session reporting was not changed.

## Independent review and final verification

The independent review found one important issue and no critical/minor issues in this extension: forwarded Codex directory flags could select another project's old installation after the original project passed its check. Five flag forms were reproduced with failing regression assertions. The fix rejects them before any project writes; tokens after the child's own `--` still forward literally. The full suite now passes **131 tests** on both Python 3.12 and Python 3.10. No second reviewer was used.

Retained decisions: checks cover the selected bundle, not absolute paths in custom skills or every hook/agent file; those must remain aligned separately. The previously disclosed journal/unknown-option diagnostic issues are unchanged. The default 1.20.1 is a project policy choice, so projects can explicitly choose another floor. Verified Codex `-C`/`--cd` forms are rejected, requiring callers to run from the destination project; arbitrary child reconfiguration or actions after startup are not claimed to be prevented.
