# Init on a Bare `.planning/` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `gsd-cli init` succeeds in a project whose `.planning/` contains no config file (e.g. only `.planning/codebase/` from `gsd-map-codebase`).

**Architecture:** Add an opt-in `allow_bare` flag to `config.discover()` that also accepts a `.planning/` directory as a project marker. Only `init_command` passes it. `initialize()` already treats a missing working config as `{}`.

**Tech Stack:** Python 3.10+, Click, unittest run by pytest.

**Spec:** `docs/superpowers/specs/2026-11-16-init-bare-planning-design.md`

## Global Constraints

- Strict discovery (marker files only) stays unchanged for `status`, `sessions`, `check`, `policy` and launches.
- `init` never creates `.planning/` itself.
- Nearest ancestor match wins, whether it is a marker file or a bare `.planning/` directory.
- Run tests with `python -m pytest -n auto ...`. Tests stay unittest-style.
- One behaviour change, one commit (code + tests + docs together).

## Review Focus

- `.planning` exists but is a regular file, not a directory: it must not count as a project (use `is_dir()`). Test added in Task 1.
- Init run from a subdirectory of a bare project finds the project root, not the subdirectory. Test added in Task 1.
- A nested bare `.planning/` inside a parent that has a full config: the nearest (child) wins. Test added in Task 1.
- `status` on a bare `.planning/` still reports "No GSD project found" (strict discovery unchanged). Test added in Task 1.
- After bare init, no `.planning/config.json` is written by init; the first launch creates it. Asserted in Task 1.

---

### Task 1: Init-only bare `.planning/` discovery

**Files:**
- Modify: `gsd_cli/config.py:30-35` (`discover`)
- Modify: `gsd_cli/cli.py:67-74` (`init_command`)
- Test: `tests/test_config.py` (new class `DiscoverTests`), `tests/test_gsd_cli.py` (`GsdCliTestCase`)
- Docs: `docs/LAUNCHER.md:100`, `README.md` (Install and initialize section), `CHANGELOG.md` (`## Unreleased`)

**Interfaces:**
- Produces: `discover(start: Path | None = None, allow_bare: bool = False) -> Path`. Raises `ConfigError` when nothing is found.
- Error messages (exact copy):
  - strict (unchanged): `No GSD project found: expected .planning/config.json or config.default.json`
  - `allow_bare=True`: `No GSD project found: run a GSD command such as gsd-map-codebase or gsd-new-project first to create .planning/`

- [ ] **Step 1: Write the failing tests in `tests/test_config.py`, class `DiscoverTests`** (each uses its own `tempfile.TemporaryDirectory` with real directories)

```python
def test_bare_planning_found_only_when_allowed(self):
    (root / '.planning/codebase').mkdir(parents=True)
    with self.assertRaisesRegex(config.ConfigError, 'expected .planning/config.json'):
        config.discover(root)
    self.assertEqual(config.discover(root, allow_bare=True), root.resolve())

def test_bare_planning_found_from_subdirectory(self):
    (root / '.planning').mkdir(); (root / 'src/pkg').mkdir(parents=True)
    self.assertEqual(config.discover(root / 'src/pkg', allow_bare=True), root.resolve())

def test_nearest_bare_planning_wins_over_configured_parent(self):
    (root / '.planning').mkdir(); (root / '.planning/config.json').write_text('{}\n')
    (root / 'child/.planning').mkdir(parents=True)
    self.assertEqual(config.discover(root / 'child', allow_bare=True), (root / 'child').resolve())

def test_planning_file_is_not_a_project(self):
    (root / '.planning').write_text('')
    with self.assertRaisesRegex(config.ConfigError, 'gsd-map-codebase or gsd-new-project'):
        config.discover(root, allow_bare=True)
```

The temp dir root has no `.planning` ancestor in practice. If the machine's `/tmp` ancestors had one, these tests would be flaky; that's acceptable, same as the existing tests.

- [ ] **Step 2: Write the failing CLI tests in `tests/test_gsd_cli.py`, `GsdCliTestCase`**

```python
def test_init_on_bare_planning_from_subdirectory(self):
    self.config_path.unlink()
    (self.project / '.planning/codebase').mkdir()
    (self.project / 'src').mkdir()
    result = self.run_launcher('init', cwd=self.project / 'src')
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(self.policy()['schema_version'], 1)
    self.assertTrue((self.project / '.planning/config.default.json').exists())
    self.assertTrue((self.project / '.gitignore').exists())
    self.assertFalse(self.config_path.exists())

def test_status_still_requires_config_on_bare_planning(self):
    self.config_path.unlink()
    result = self.run_launcher('status')
    self.assertNotEqual(result.returncode, 0)
    self.assertIn('expected .planning/config.json', result.stderr)
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest -n auto tests/test_config.py tests/test_gsd_cli.py -k "bare or planning_file or status_still"`
Expected: the `allow_bare` tests fail with `TypeError: discover() got an unexpected keyword argument 'allow_bare'`, the CLI init test fails with a nonzero exit, and the status test passes already.

- [ ] **Step 4: Implement `discover(start=None, allow_bare=False)` in `gsd_cli/config.py`**

In each ancestor, check the marker files, and when `allow_bare` is set, also `(root / '.planning').is_dir()`. Return the first match. Raise the error message for the current mode. Change `init_command` to call `config.discover(allow_bare=True)`. No other caller changes.

- [ ] **Step 5: Run the targeted tests, then the full suite**

Run: `python -m pytest -n auto tests`
Expected: all pass.

- [ ] **Step 6: Update the docs**

- `docs/LAUNCHER.md:100`: say that init also works where `.planning/` holds no config yet (for example right after `gsd-map-codebase`), and that it still doesn't create `.planning/`.
- `README.md` Install and initialize section: the same in one sentence.
- `CHANGELOG.md`, under `## Unreleased`, a `### Fixed` entry: "`gsd-cli init` now finds a project whose `.planning/` has no config file yet, such as one created only by `gsd-map-codebase`. Other commands still require a config file."

- [ ] **Step 7: Commit**

```bash
git add gsd_cli/config.py gsd_cli/cli.py tests/test_config.py tests/test_gsd_cli.py docs/LAUNCHER.md README.md CHANGELOG.md
git commit -m "Let init find a project with a bare .planning directory" \
  -m "Before: init failed with 'No GSD project found' when .planning/ held only gsd-map-codebase output. After: init accepts the nearest .planning/ directory; other commands keep strict discovery because they need a config file to read."
```

- [ ] **Step 8: Manual check against the real project (read-only until init)**

Run in `~/projects/ba/dpl-examples` with the branch's code: `python -m gsd_cli init` via the dev install. Expected: `Initialized /home/alex/projects/ba/dpl-examples...`. Ask the maintainer before running it, because it writes files into their project.
