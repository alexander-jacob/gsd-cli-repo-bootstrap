# `gsd-cli sessions`: effective models per session and subagent

Date: 2026-10-30

## Intent

After a GSD run, the user wants to check which model and reasoning effort the
session and every subagent it spawned **actually** ran with, and whether that
matches what the launched profile was supposed to deliver. Today this takes
hand-digging through Claude and Codex session logs. The failure this guards
against is silent: AGENTS.md documents how a bad tier entry makes every
subagent inherit the session model without any error.

## Goals

- New read-only subcommand `gsd-cli sessions`, scoped to the current GSD
  project (same project discovery as `status`).
- Covers both runtimes, Claude Code and Codex.
- Default output: the **three most recent sessions** of the project.
- A **picker** to select an older session and show it in the same format.
- Per session, a tree:
  - session line: runtime, start time, profile (if known), model, effort,
    Claude advisor model when recorded;
  - one line per subagent: agent type, requested model, actual model, effort;
    nested subagents indented under their parent.
- Two kinds of mismatch are flagged:
  1. **requested vs. actual**: the agent asked for one model and ran on
     another;
  2. **profile vs. actual**: the session or an agent did not get what the
     launching profile should have given it (session model and session
     effort, and per-agent model/effort).
- Each launch through `gsd-cli` appends one record so a session can be tied to
  its profile.

## Non-goals

- No `--json` output for now (easy to add later).
- No cross-project view; only the current project.
- No cost/token reporting.
- No live/streaming view; this is an after-the-fact check.

## Anti-goals

- Must never modify session logs or project config. (The launch log write
  happens on launch, not in `sessions`.)
- Must not add a third-party dependency; the launcher stays standard-library
  only, single executable file.
- Must not make launches fail or slow down noticeably: a launch-log write
  failure is a warning on stderr, never a launch abort.
- Must not invent a profile for a session it cannot match: unmatched sessions
  show "profile: unknown" and skip the profile comparison, rather than guess.

## Decided by the user

- Current project only.
- Three most recent sessions by default, picker for older ones.
- Profile comparison is wanted.
- Each launch writes one launch-log line (outside the repo and outside
  `.planning/`).

## Data sources (verified against real logs on 2026-10-30)

### Claude Code

- Sessions: `~/.claude/projects/<cwd with "/" → "-">/<session-id>.jsonl`.
- Every assistant record carries `message.model` (the model that actually
  ran, e.g. `claude-sonnet-5-5`), plus top-level `effort` / `perTurnEffort`
  and `advisorModel`.
- Subagents: `<session-id>/subagents/agent-<id>.jsonl` (same record shape) and
  `agent-<id>.meta.json` with `agentType`, `model` (the requested alias, e.g.
  `sonnet`), `spawnDepth`, `toolUseId`, `description`.
- Records have `cwd`, `timestamp`, `sessionId`.

### Codex

- Sessions: `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<id>.jsonl`, all
  projects mixed; filter by `session_meta.payload.cwd`.
- `session_meta.payload`: `id`, `cwd`, `timestamp`, `source`. A child
  session has `source.subagent.thread_spawn` with `parent_thread_id`,
  `depth`, `agent_role` (e.g. `gsd-plan-checker`), `agent_path`.
- `turn_context.payload`: `model`, `effort` — the actual values per turn.
- Parent `function_call` records named `spawn_agent` carry JSON arguments
  with `agent_type`, `model`, `reasoning_effort` — the requested values.
- Children are their own session files linked by `parent_thread_id`; they
  belong under their parent, not as separate top-level sessions.

## Matching a session to a profile

On every runtime-profile launch, before `exec`, the launcher appends one JSON
line to a launch log in the user state directory
(`$XDG_STATE_HOME/gsd-cli/launches.jsonl`, default
`~/.local/state/gsd-cli/launches.jsonl`) with: UTC timestamp, project root,
runtime, profile, session model, session effort (Codex), the forwarded CLI
arguments, a snapshot of the **whole** project config as written for the
launch, and the contents of `~/.gsd/defaults.json` if present. (Claude's call:
the resolver also reads `model_profile`, config-level `effort` and global
defaults, and launch records cannot be fixed after the fact, so snapshot
everything rather than a hand-picked key set.)

`sessions` matches each top-level session to the latest launch record for the
same project root and runtime whose timestamp is before the session start and
within a short window (builder's call; a few seconds to a minute). No match →
profile unknown. Match projects on the `cwd` recorded inside the logs, not on
Claude's folder name (which also rewrites `.` to `-`).

Resumed sessions (Claude's call): the profile comes from the launch that
started the session; if a later launch resumed it (`--resume` / `codex
resume` in the forwarded args), the session is marked "resumed, profile may
differ" rather than split into segments.

Overrides at launch (Claude's call): if the forwarded args set their own
`--model` or `-c model_reasoning_effort=…`, expected values stay the
profile's, and the session line is marked "overridden at launch" instead of
a plain mismatch.

## Reviewer runs (decided by the user: nested)

Cross-AI reviewer calls (`fable-review` → headless `claude -p`, Claude
`entrypoint: "sdk-cli"`; `astra-review` → `codex exec`) appear in the logs as
separate top-level sessions of the same project. They are **not** listed as
top-level sessions and do not count toward the three most recent. Each is
nested under the session that triggered it: same project `cwd`, start time
within that session's active span (first to last record). Their model is
compared against the `REVIEWERS` table (e.g. `fable-review` →
`claude-fable-5-1`, `astra-review` → `gpt-6-astra`). Recognising a reviewer
session (entrypoint, `originator`/`source`, the "Cross-AI Plan Review
Request" prompt) is left to the builder. A reviewer run that overlaps no
session is shown as its own entry marked "reviewer, unattached".

## Expected values for the profile comparison

- Session: model and effort from the launch record.
- Per agent: computed with the **real GSD resolver**, not the launcher tables
  (AGENTS.md: "Verify routing against the real resolver"), evaluated against
  the config snapshot from the launch record, not the current config (later
  launches rewrite `models` and `model_overrides`). The resolver is
  `GSD_RUNTIME=<runtime> node ~/.claude/gsd-core/bin/gsd-tools.cjs query
  resolve-model <agent> --pick model` (and `--pick effort`), run from inside a
  GSD project; one workable approach is a temporary directory holding the
  snapshot as `.planning/config.json`.
- If node or the resolver is missing or fails, show requested vs. actual only
  and print one note that the profile comparison was skipped.
- Agents the resolver reports as `unknown_agent` (`general-purpose`,
  `Explore`, `fork`, Codex `default`) get no profile comparison.
- Claude has no session-effort launch flag, so Claude session effort is shown
  but not compared.
- Codex spawn → child linking uses the parent's `spawn_agent` call id and the
  `SubAgentActivity` event carrying `agent_thread_id`, with
  `parent_thread_id` in the child as the fallback.
- Claude comparison is on the family: expected alias `opus` matches actual
  `claude-opus-*`. Codex compares full IDs.

## Calls made by Claude (not confirmed by the user)

- Name: `gsd-cli sessions`.
- Claude and Codex sessions are mixed in one list, newest first; an optional
  `claude|codex` argument limits to one runtime.
- Picker: numbered list in the terminal, choose by typing a number (stdlib
  `input()`); e.g. `gsd-cli sessions --pick`. Non-interactive stdin → print
  the list without prompting.
- Effort that varies within one session/agent: show the most common value
  and mark that it varied.
- Mismatches are marked inline (e.g. `!` plus a short reason); no colors
  required, colors only when stdout is a TTY if added at all.
- "Recent" = session start time.

## Left to the builder

- Exact output layout and column widths.
- Matching window size.
- How to batch resolver calls to keep `sessions` reasonably fast.
- Exact flag spelling for the picker.

## Testing

Per AGENTS.md: `unittest`, offline, no real credentials. Use fixture log
trees for both runtimes under a temporary `HOME`, a stub resolver for the
profile comparison, and cover: three-most-recent selection, picker selection,
nested subagents, reviewer runs nested under their session, both mismatch
kinds, unknown profile, resolver missing, and
that launches append exactly one launch-log record without changing the
launch `argv`. Update README, `docs/LAUNCHER.md`, AGENTS.md and the module
docstring.
