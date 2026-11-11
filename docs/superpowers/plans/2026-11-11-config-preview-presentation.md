# Configuration Preview Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `--config` a concise workflow-scoped model comparison, with the existing evidence dump and colored JSON available through `--details`.

**Architecture:** Keep resolver inspection and `preview.compare` as the evidence source. Add a compact renderer in `gsd_cli/preview.py`, retain the current renderer for details, and select between them from Click. Styling is applied only after escaping untrusted values.

**Tech Stack:** Python 3.10+, Click, standard library, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-11-config-preview-presentation-design.md`

## Global Constraints

- Preview remains read-only and keeps existing `COMPLETE` / `INCOMPLETE` exit behavior.
- Include phases from `workflows.<name>.tasks` and `workflows.<name>.task_levels` in the compact agent table.
- `--details` requires `--config` and retains all current evidence and effective JSON.
- ANSI only for interactive terminals when `NO_COLOR` is unset; untrusted values cannot inject controls.

## Review Focus

- A workflow with a custom `task_levels` phase must include that phase's agents; test in Task 1.
- An agent configured for a selected phase but absent from the catalog must remain visible as unknown; test in Task 1.
- A configured model mismatch must show a red `✗`, while absent expectation shows `?`; test in Task 1.
- A redirected preview or `NO_COLOR` terminal must contain no ANSI; test in Task 2.
- `--details` with the forwarding separator must remain a child argument, while `--config --details` must be read-only; test in Task 2.

---

### Task 1: Compact workflow report

**Files:**
- Modify: `gsd_cli/preview.py`
- Test: `tests/test_preview.py`

**Interfaces:**
- Consumes: `expectations(data, agent, meta, runtime)` and `compare(model, effort, result, runtime, session_effort, forwarded, aliases)`.
- Produces: `render_compact(root: Path, workflow: str, runtime: str, level: str, policy: dict, resolved: dict, data: dict, captured: list[str], argv: list[str], forwarded: list[str], inspection: dict) -> str`.

- [ ] Write failing tests for header before tables, session request and unknown execution, selected phases only, custom `task_levels`, configured unknown agents, three check states, selected reviewers, and incomplete diagnostics.
- [ ] Run `python3 -m unittest discover -s tests -p test_preview.py -v`; confirm new tests fail.
- [ ] Implement `render_compact` with aligned, phase-grouped columns. Reuse `compare`; show model and effort as configured → GSD resolved. Keep a brief legend and `--config --details` hint. Preserve escaped values through `display`.
- [ ] Run `python3 -m unittest discover -s tests -p test_preview.py -v`; confirm pass.
- [ ] Commit with subject `Add workflow scoped config preview`.

### Task 2: Detail switch and terminal color

**Files:**
- Modify: `gsd_cli/cli.py`, `gsd_cli/preview.py`
- Test: `tests/test_preview.py`
- Modify: `README.md`, `docs/LAUNCHER.md`

**Interfaces:**
- Consumes: Task 1 `render_compact(...)` and existing `render(...)` detailed report.
- Produces: `preview.colorize_json(text: str, enabled: bool) -> str` and a `--details` Click option on workflow commands.

- [ ] Write failing CLI tests: compact is default; `--config --details` retains resolver evidence and parseable JSON when redirected; `--details` alone errors; forwarded `--details` reaches the child; TTY color and `NO_COLOR` behavior; malicious value escaping.
- [ ] Run `python3 -m unittest discover -s tests -p test_preview.py -v`; confirm new tests fail.
- [ ] Add the Click option and mode selection. Determine color from stdout TTY and `NO_COLOR`. Apply style only to trusted headings/check tokens and JSON syntax; preserve raw JSON text when color is disabled. Keep detailed report's diagnostic and effective config sections.
- [ ] Run `python3 -m unittest discover -s tests -p test_preview.py -v`; confirm pass.
- [ ] Update help and docs with the two commands and check meanings.
- [ ] Run `python3 -m unittest discover -s tests -v` and `python3 -m gsd_cli --help`; confirm pass.
- [ ] Commit with subject `Add detailed colored config preview`.
