# `--version` Option Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `gsd-cli --version` / `-V` prints `gsd-cli <version>` and exits 0.

**Architecture:** Click `version_option` on the top-level group, version read from the installed `gsd-workflow-cli` metadata; `main()` lets `--version` win over `--json` the way `--help` does.

**Tech Stack:** Python 3.10+, Click 8, `importlib.metadata`, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-16-version-option-design.md`

## Global Constraints

- Output exactly `gsd-cli <version>\n` on stdout, exit 0; no project needed; nothing written.
- The version comes only from installed package metadata (`gsd-workflow-cli`); no hard-coded version string. Missing metadata prints `gsd-cli unknown`.
- Text output and exit codes of every other invocation are unchanged. No new JSON schema.

## Review Focus

- `--version --json` (either order): text version line, exit 0, never a usage envelope. Test in Task 1.
- Run outside any GSD project: works. Test in Task 1.
- `-V` short flag: same output. Test in Task 1.
- `--version` after a workflow name (`plan --version`): not a version request; behaviour unchanged (Click treats it as an unknown option). No test needed beyond the suite.

---

### Task 1: `--version` option

**Files:**
- Modify: `gsd_cli/cli.py` (group decorator at line 46, `main()` help/json rule at line 274)
- Test: `tests/test_json_output.py` (class `JsonErrorTests`, next to `test_help_wins_over_json`)
- Docs: `README.md` (command list near line 76), `docs/LAUNCHER.md` (command list near line 22), `AGENTS.md` (command list near line 21), `CHANGELOG.md` (Unreleased → Added)

**Interfaces:**
- Produces: `cli.package_version() -> str` — installed version of `gsd-workflow-cli`, or `'unknown'` on `importlib.metadata.PackageNotFoundError`.

- [ ] **Step 1: Write failing tests**

```python
def test_version_prints_installed_version(self):
    expected = f"gsd-cli {importlib.metadata.version('gsd-workflow-cli')}\n"
    for args in (('--version',), ('-V',), ('--version', '--json'), ('--json', '--version')):
        with self.subTest(args):
            result = self.run_launcher(*args, cwd=self.root)   # outside any project
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ''))

def test_package_version_without_metadata(self):
    with mock.patch('importlib.metadata.version', side_effect=importlib.metadata.PackageNotFoundError):
        self.assertEqual(cli.package_version(), 'unknown')
```

- [ ] **Step 2: Run** `.venv/bin/python -m unittest tests.test_json_output -v` — expect the two new tests to fail.

- [ ] **Step 3: Implement.** `package_version()` in `cli.py`; `@click.version_option(package_version(), '-V', '--version', prog_name='gsd-cli', message='%(prog)s %(version)s')` on `cli` (pass the version explicitly so Click never raises on missing metadata). In `main()`, extend the help-wins rule to `('-h', '--help', '-V', '--version')` and update its comment.

- [ ] **Step 4: Run** the new tests, then the full suite `.venv/bin/python -m unittest discover -s tests` — all pass.

- [ ] **Step 5: Docs.** Add `gsd-cli --version` to the three command lists; CHANGELOG Unreleased gets `### Added` with "`gsd-cli --version` (`-V`) prints the installed gsd-cli version."

- [ ] **Step 6: Commit** — `Add a --version option`, body stating before (no way to print the installed version) and after.
