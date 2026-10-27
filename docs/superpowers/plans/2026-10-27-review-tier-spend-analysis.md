# Review Tier Spend Analysis Plan (machine B replay)

> **For agentic workers:** this is a diagnostic plan, not a feature build. Execute it inline with superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking. Record every result in the spec, then stop at Task 6 and ask the owner the open question.

**Goal:** Establish, from machine B's own transcripts, which model performed review and fix work on 2026-10-26 and where the Fable spend came from, then let the owner choose between the options in the spec.

**Architecture:** One standard-library Python tool (`tools/session_model_usage.py`) reads Claude Code transcripts under `~/.claude/projects`, Codex rollouts under `~/.codex/sessions`, and runs the real GSD resolver. Findings are written into the spec, never kept in chat.

**Tech Stack:** Python 3.10+, node (for the installed GSD core's `gsd-tools.cjs`).

**Spec:** `docs/superpowers/specs/2026-10-27-review-tier-spend-design.md`

## Global Constraints

- Read-only on machine B's logs and projects. No launch of a paid CLI session, no `init`, no config edits until the owner decides.
- Report what the logs show. If a session did not spawn an agent, say so; do not infer from usage dashboards.
- Tool is standard library only; keep it that way.

## Review Focus

- A Claude session transcript without a `<session>/subagents/` folder: the tool prints `(no subagent transcript found)` for its spawns and still lists spawn counts (Task 2 checks this on an older session).
- Codex rollout with `source` as a string instead of an object: handled, role prints as `orchestrator`.
- A `--since` date filter that excludes everything: the summary line still prints the totals, no exception.
- GSD core missing or at another version on machine B: Task 1 records the version; `resolve` exits with a clear message if `gsd-tools.cjs` is absent.
- Logs for the heavy day living under a project folder with a different cwd than expected: Task 3 uses `--all` once to make sure no session is filtered out by the GSD-spawn filter.

---

### Task 0: Get the handoff onto machine B

- [ ] **Step 1: Fetch the analysis branch**

Run: `git fetch origin && git checkout review-tier-spend-analysis`
Expected: `docs/superpowers/specs/2026-10-27-review-tier-spend-design.md`, `docs/superpowers/plans/2026-10-27-review-tier-spend-analysis.md` and `tools/session_model_usage.py` exist. Stay on this branch for every commit in this plan.

- [ ] **Step 2: Record the launcher commit machine B used on 2026-10-26**

Run: `git log --format='%h %ad %s' --date=iso -5 main`
Expected: the newest commit before 2026-10-26 on `main`. If it predates `ca88321` (tier aliases in `CLAUDE_MODELS`), spawns from that day will show `(inherit)` and Task 5 Step 2 must say the day is not representative.

### Task 1: Confirm environment on machine B

**Files:**
- Read: `~/.claude/gsd-core/VERSION`, `~/.gsd/defaults.json`, the target project's `.planning/config.json`

- [ ] **Step 0: Check the `models.execution` history of the project (spec hypothesis "cross-runtime leak")**

From inside the project that had the heavy day:
Run: `node -e 'console.log(require("./.planning/config.json").models)'; git log --format='%h %ad' --date=iso -p -- .planning/config.json | grep -E '^[0-9a-f]{7} |^[-+] *"execution"'`
Expected: the current value and every committed change of `execution`. Any `"execution": "opus"` on or around 2026-10-26 means a Codex `exec-high` launch left the Claude side routing execution-typed agents (fixer, executor) to Fable. Record the lines in the spec. Note that launches that were never committed do not appear here, so also ask the owner which profiles they launched that day if the history is inconclusive.

- [ ] **Step 1: Record GSD version and defaults**

Run: `cat ~/.claude/gsd-core/VERSION; cat ~/.gsd/defaults.json`
Expected: a version string (machine A had `1.19.0`) and a JSON object. Note `model_profile`, `workflow.code_review_depth`, `resolve_model_ids`, `runtime`.

- [ ] **Step 2: Record the project's effective routing**

From inside the project that had the heavy day:
Run: `python3 <repo>/tools/session_model_usage.py resolve`
Expected: `gsd-code-fixer -> opus`, `gsd-code-reviewer -> fable`, `gsd-executor -> opus`, `gsd-verifier -> fable`. Any deviation is a finding; copy the whole table into the spec under a new heading "Machine B".

- [ ] **Step 3: Check the catalog phase type of the fixer**

Run: `node -e 'const c=require(require("os").homedir()+"/.claude/gsd-core/bin/shared/model-catalog.json");console.log(c.agents["gsd-code-fixer"])'`
Expected: `phaseType: 'execution'`. If it says `verification`, the premise holds on this GSD version; record it.

### Task 2: Verify the tool on machine B's logs

**Files:**
- Use: `tools/session_model_usage.py`

- [ ] **Step 1: Run the Claude scan for the heavy day**

Run: `python3 tools/session_model_usage.py claude --since 2026-10-26`
Expected: one block per session that spawned `gsd-*` agents, each with `spawn <agent>@<model> xN` lines and token usage. No traceback.

- [ ] **Step 2: Sanity-check an older session without a subagents folder**

Run: `python3 tools/session_model_usage.py claude --since 2026-10-01 | grep -c "no subagent transcript"`
Expected: a count (possibly 0). No traceback.

- [ ] **Step 3: Run the Codex scan**

Run: `python3 tools/session_model_usage.py codex --since 2026-10-26`
Expected: one line per rollout plus `spawn_agent <agent_type>@<model>` lines where present; final summary line `N rollout(s)`.

### Task 3: Find the review/fix sessions

- [ ] **Step 1: List which sessions spawned the fixer or reviewer**

Run: `python3 tools/session_model_usage.py claude --since 2026-10-26 | grep -E "^###|gsd-code-(fixer|reviewer)|prompts mentioning"`
Expected: for every session, the reviewer and fixer lines with their `@model`. Record each `gsd-code-fixer@<model>` occurrence. If the fixer never appears, say so explicitly in the spec.

- [ ] **Step 2: Make sure the GSD-spawn filter hid nothing**

Run: `python3 tools/session_model_usage.py claude --since 2026-10-26 --all | grep -E "^###|prompts mentioning" | grep -B1 -- "--fix"`
Expected: any session whose prompts mention `--fix` is listed, even if it spawned no GSD agent (which would mean the fix ran inline or in a different runtime).

- [ ] **Step 3: Check the Codex side the same way**

Run: `python3 tools/session_model_usage.py codex --since 2026-10-26 | grep -E "gsd-code-(fixer|reviewer)"`
Expected: the Codex fixer on `gpt-6.1-sol` and reviewer on `gpt-6-astra`, or a deviation to record.

### Task 4: Timeline the heaviest session

- [ ] **Step 1: Pick the session with the most Fable output**

From Task 3 output, choose the session whose `@fable` lines sum to the largest `out=` value. Note its 8-character id.

- [ ] **Step 2: Produce its timeline**

Run: `python3 tools/session_model_usage.py timeline ~/.claude/projects/<project-dir>/<id>*.jsonl`
Expected: ordered `USER`, `SPAWN`, `EDIT`, `COMMIT`, `TEXT` lines. Answer three questions and write them into the spec: who performed the edits after REVIEW.md existed (orchestrator `EDIT` lines versus `SPAWN gsd-code-fixer`), what model those spawns carried, and how many times the reviewer and verifier were spawned.

### Task 5: Write the machine B findings into the spec

**Files:**
- Modify: `docs/superpowers/specs/2026-10-27-review-tier-spend-design.md` (section "What is not yet known" becomes "Machine B findings")

- [ ] **Step 1: Add a table like the machine A one**

Columns: Agent, Model, Runs, Output tokens, for the heaviest session; plus one sentence stating whether `gsd-code-fixer` ran on Fable anywhere.

- [ ] **Step 2: Update the conclusion**

Four outcomes, pick the one the logs support:
- The fixer never ran on Fable: keep the conclusion, add "confirmed on machine B".
- The fixer ran on Fable and Task 1 Step 0 shows `execution: opus` at the time: the cross-runtime leak hypothesis is confirmed. Record the session id, the config history lines, and mark option "fix the launcher's per-runtime tier words" as the first option in the spec.
- The fixer ran on Fable with `execution: sonnet` throughout: this contradicts the resolver. Record the session id, the first `USER` line (the launch banner is not in the transcript, so note the profile if the owner remembers it), and the full resolver table from Task 1 Step 2. Do not choose an option until this is explained.
- All spawns show `(inherit)`: the day is not representative (see Task 0 Step 2); say so and stop at Task 6 with that statement.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-10-27-review-tier-spend-design.md
git commit -m "Record machine B review-spend findings"
```

### Task 6: Hand the decision back

- [ ] **Step 1: Ask the owner the spec's open question**

Present options A to D from the spec with the machine B numbers next to them. Do not implement any option in this plan; the implementation (launcher `AGENT_TIERS` change, tests, README and example config updates) is a separate plan once the owner has chosen.
