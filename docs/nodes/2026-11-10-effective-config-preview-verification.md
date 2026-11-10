# Configuration preview verification

Implementation is on `feat/configurable-launcher` in the existing isolated worktree. The host's pipx installation has not been replaced by this feature work.

## Automated checks

- `python3 -m unittest discover -s tests -q`: 157 tests pass on Python 3.12.
- `.venv/bin/python -m unittest discover -s tests -q`: 157 tests pass on Python 3.10.
- `uv build --offline --wheel --out-dir /tmp/gsd-preview-wheel`: succeeds using cached declared build dependencies; the wheel contains `gsd_cli/data/preview-resolver.cjs`.
- Targeted tests first failed for missing preparation/adapter/report functionality, then passed. Additional regression tests cover explicit installed `inherit` effort and malformed nested catalog metadata.

The tests cover preparation/launch parity, pending capture without writes, held and idle locks, journal/conflict errors, input changes, selected runtime and relative environment paths, workstream overlays, missing Node, malformed/incomplete results, timeout, check labels and precedence, argument boundaries, custom workflows, secure arguments, terminal escaping, and no AI CLI execution.

## Installed resolver integration

Both local installations reported GSD 1.20.1 on 2026-11-10. Zipped-wheel previews used disposable initialized projects and the bundled `plan/medium` policy, querying the real installed resolver for each runtime. No AI session was started.

| Runtime | Agent rows | OK | NOT OK | UNKNOWN |
|---|---:|---:|---:|---:|
| Codex | 35 | 15 | 0 | 20 |
| Claude | 35 | 1 | 14 | 20 |

Unknown rows generally have no explicit effort expectation in the launcher policy; resolved GSD defaults remain visible. Claude differences reflect installed effort settings compared with configured expectations. For example, `gsd-plan-checker` requests `high` but its installed Claude frontmatter reports `low`. The same Codex role resolves `high` and passes its comparisons. These counts describe this installation and fixture policy, not actual model executions or every project.

File sets, sizes, and modification times remained unchanged across the temporary project's original files and both runtimes' installed agents/GSD bundles. Unit/CLI tests additionally compare original file bytes and modification times. No global agent-effort synchronization was performed.

## Implementation rulings

- Preview rejects an occupied lock, not an idle lock file. Init and launch retain that file; rejecting its mere presence would block normal projects.
- The adapter calls compiled GSD command exports directly to avoid the public CLI's automatic build behavior. Missing exports produce an incomplete report.
- GSD_PROJECT context and legacy `multiRepo` filesystem discovery are explicitly unsupported in the snapshot. The report retains the prospective launcher config and exits 1 rather than claiming faithful resolution.
- Node is needed for resolution, but AI CLI binaries and billing credentials are not. Setting drift does not change exit status; incomplete resolution does.

## Independent review

A fresh reviewer found one important issue and no critical/minor issues: GSD legitimately returns null effort propagation for inherited effort, but the adapter rejected it as malformed. Reproduced against the real installed Codex resolver; added adapter and CLI regression tests that failed before the fix. The adapter now accepts the documented nullable effort fields while retaining type/presence validation.

Both final full suites pass (157 tests each). Real `exec --config` previews with an unmanaged `gsd-executor=inherit` effort setting complete successfully for Codex and Claude without project changes. Inheritance remains visible and comparisons remain conservative; Claude still reports a mismatch if installed effort differs from the requested inherited session effort. The wheel was rebuilt successfully after the fix.

The reviewer set aside already-reviewed earlier launcher features beyond preview integration, the two previously deferred unrelated minor issues, and actual provider execution/future resolver versions. Those boundaries stand: normal launch regression tests remain green, prior findings are unchanged, and this feature reports configuration evidence rather than actual AI execution. No new deferred findings remain.
