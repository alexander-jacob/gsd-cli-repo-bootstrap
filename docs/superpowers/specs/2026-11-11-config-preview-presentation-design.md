# Configuration preview presentation

Date: 2026-11-11. Status: awaiting approval.

## Intent

Make `gsd-cli <workflow> <runtime> [level] --config` answer two questions quickly: which model and effort the launcher requests for the session, and which models and efforts installed GSD resolves for agents relevant to that workflow. Show the selected workflow, runtime, and level before the tables.

## Goals and boundaries

- The default preview is a compact, aligned terminal report with a session row, phase-grouped agent rows, and selected reviewers. Each agent row compares configured model and effort with GSD resolution and shows a colored check: green `✓` for a confirmed match, red `✗` for a known mismatch, and neutral `?` when evidence or an explicit expectation is missing. A short legend explains all three states.
- Agent rows cover phases in `workflows.<name>.tasks` and `workflows.<name>.task_levels`; the report calls them agents the workflow *may use*, since `--config` does not run a session. For `plan`, this includes its planning, discussion, research, and verification phase assignments; `exec` uses its own assignments. Keep configured agents in those phases even when the installed catalog lacks a resolution, so missing evidence remains visible.
- Keep the current comprehensive report available with `--config --details`, including resolver inputs, child argv, diagnostics, loader differences, reviewer data, and effective configuration JSON. `--details` requires `--config`.
- Syntax-color the JSON in the detailed report: keys, strings, numbers, booleans, and null receive distinct readable colors. Use color for headings and check symbols in the compact report. Emit ANSI color only on an interactive terminal and when `NO_COLOR` is unset; redirected output and tests remain plain text. Never let configuration values supply terminal control codes.
- Keep both preview modes read-only and preserve the current `COMPLETE` / `INCOMPLETE` behavior and exit status. A session's launch request can be shown, but its actual execution remains unknown.

## Approaches

1. **Workflow-scoped compact report plus full `--details` — selected.** Focuses the first screen on the selected workflow while retaining all evidence on demand.
2. **All registered agents in the compact report — not selected.** Complete inventory, but still too long to scan and includes unrelated workflow phases.

## Implementation direction

Build on the packaged Click CLI's existing `preview.render` and resolver inspection. Select compact rows from the policy's workflow phase assignments and the installed catalog's `phaseType`; reuse the existing comparison logic rather than recalculating checks in the formatter. Keep the existing detailed report as the detailed mode and add styling during rendering without changing the underlying evidence. Use the existing Click dependency and standard terminal output; no new formatting dependency is needed.

## Builder choices

Choose exact table widths, wrapping for narrow terminals, color shades, and the spelling of the check legend. Add offline tests for phase filtering, statuses, plain redirected output, color conditions, and `--details` retaining the current evidence and JSON. Update command help and user documentation.
