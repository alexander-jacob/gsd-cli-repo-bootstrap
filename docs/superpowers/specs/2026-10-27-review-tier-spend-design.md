# Post-execution review spend by tier: findings and options

Status: analysis complete. Verified on machine A (Alex's laptop, 2026-10-27)
and replayed on machine B (the heavy review/fix day of 2026-10-26), see
"Machine B findings". Decision pending, see "Open question" at the end.

## Intent

`gsd-cli claude exec-opus` is designed so that plan execution runs on Opus 5.5
(GSD tier `sonnet`) while the post-execution review gates run on Fable 5.1
(GSD tier `opus`). The observation that triggered this work: after execution,
a lot of Fable credit is consumed, and the suspicion was that the *fixing* of
review findings runs on Fable too, specifically through
`/gsd-code-review <phase> --fix [--all]`.

The goal is a clear, verifiable separation: review on Fable, everything that
writes code on Opus 5.5, and a way to see which model each agent actually
got, without guessing.

## What the code says (verified, machine-independent)

These facts come from the installed GSD core (version 1.19.0 on machine A)
and the real resolver, not from the launcher's tables.

- GSD routes agents by **phase type**. `gsd-code-fixer` is typed `execution`
  in GSD's agent catalog (`bin/shared/model-catalog.json`), the same as
  `gsd-executor` and `gsd-debugger`. `gsd-code-reviewer`, `gsd-verifier`,
  `gsd-ui-auditor`, `gsd-security-auditor` and `gsd-nyquist-auditor` are
  typed `verification`.
- The code-review workflow resolves `REVIEWER_MODEL` and `FIXER_MODEL`
  separately via `gsd_run query resolve-model <agent> --raw`
  (`workflows/code-review-fix.md`). With `--auto`, the loop re-reviews and
  re-fixes up to 3 iterations in total; each iteration spawns the reviewer
  again on the reviewer's model.
- Under the launcher's config (`models.execution = sonnet`,
  `models.verification = opus`, tier map opus→`fable`, sonnet→`opus`,
  haiku→`sonnet`), the resolver returns:

  | Agent | Resolved | Means |
  |---|---|---|
  | gsd-executor | `opus` | Opus 5.5 |
  | gsd-code-fixer | `opus` | Opus 5.5 |
  | gsd-code-reviewer | `fable` | Fable 5.1 |
  | gsd-verifier | `fable` | Fable 5.1 |

  Reproduce from inside any GSD project:
  `python3 tools/session_model_usage.py resolve` (uses `GSD_RUNTIME=claude`).
- The `claude plan` profile leaves `models.execution` untouched, so the fixer
  resolves to Opus 5.5 in a plan session as well. Only the orchestrator's own
  inline edits run on the session model (Fable in a plan session, Opus 5.5 in
  an exec session).
- Execute-phase does **not** pass `--fix`. Its code-review gate calls the
  review skill with the phase number only, then runs a disposition step that
  records each finding as `open` and suggests `--fix` to the user. Fixes made
  during that flow are done inline by the orchestrator.
- After a post-UAT edit touches covered files, execute-phase marks the
  verification stale and re-runs the gates (GSD #4682), which spawns the
  reviewer and the verifier a second time. No config knob for this was found.

## What the logs on machine A say

Tool: `python3 tools/session_model_usage.py claude --since 2026-10-26`
(token counts deduplicated per message id; output tokens are the cost proxy).

- Across all 1121 Claude Code sessions on machine A, `gsd-code-fixer` was
  **never spawned**, and no user prompt ran `/gsd-code-review --fix`.
- Three `/gsd-execute-phase` sessions exist (django-crud-views, phases 01, 03,
  04). Phase 04, launched with `exec-opus`:

  | Agent | Model | Runs | Output tokens |
  |---|---|---|---|
  | gsd-executor | Opus 5.5 | 3 | 129.6k |
  | gsd-verifier | Fable | 2 | 51.8k |
  | gsd-code-reviewer | Fable | 2 | 37.2k |
  | orchestrator | Opus 5.5 | 1 | 37.8k |
  | gsd-ui-auditor | Fable | 1 | 11.5k |

  The reviewer and verifier ran twice because the orchestrator's post-UAT
  doc fixes made the verification stale. The finding fixes themselves were 4
  orchestrator edits on Opus 5.5.
- Phase 01 (2026-10-26 08:09) spawned every agent with no model parameter
  (`(inherit)`), i.e. everything ran on the session model. That predates the
  alias fix in the launcher and is not representative.
- Codex logs on machine A (`python3 tools/session_model_usage.py codex`):
  one `spawn_agent gsd-code-fixer@gpt-6.1-sol` (Sol = sonnet tier) and
  `gsd-code-reviewer@gpt-6-astra`. Consistent with the Claude finding.

Conclusion on machine A: the Fable spend after execution comes from the
verification-tier agents (verifier, reviewer, UI auditor), roughly 100k
output tokens per phase versus 130k for execution, not from fixing.

## Hypothesis to test on machine B: cross-runtime leak of `models.execution`

The launcher writes `models.<phase_type>` into the project's
`.planning/config.json` on every launch, and that key is shared by both
runtimes. The Codex execution profiles write different tier words than the
Claude ones: `codex exec-high` sets `models.execution = opus`, while
`claude exec-opus` sets `sonnet`. The Claude tier map sends `opus` to
`fable`. So this sequence routes the fixer, and every executor, to Fable:

1. `gsd-cli codex exec-high` on a project (execution tier becomes `opus`).
2. Later, a Claude session on the same project that is not an exec launch:
   `gsd-cli claude plan` (leaves `execution` untouched) or a bare `claude`
   (no launcher at all).
3. `/gsd-code-review <phase> --fix` or `/gsd-execute-phase` there.

On machine A the committed history of `.planning/config.json` shows
`execution` at `sonnet` throughout, so this did not happen here. Machine B
mixes Codex and Claude sessions more, so the plan checks the config history
and the current value first. If this is the cause, the fix belongs in the
launcher: the Claude profiles must not depend on a value a Codex launch may
have left behind (for example by having every Claude profile, including
`plan`, write `execution` explicitly, or by keying the written tier words per
runtime).

## Machine B findings

Replayed on machine B on 2026-10-27 (the machine that ran the heavy day;
session cwd `/home/alex/projects/munoreqa/weaver`, the project with the
heavy day). Every number below comes from
`tools/session_model_usage.py` against machine B's own logs; nothing is
inferred from usage dashboards.

### Environment (Task 1)

- GSD core `1.19.0`. `~/.gsd/defaults.json` is
  `{"resolve_model_ids": "omit", "runtime": "opencode"}`: no `model_profile`,
  no `code_review_depth` there. The project sets `model_profile: adaptive`,
  `workflow.code_review_depth: deep`, `workflow.code_review: true`.
- `models` in the project's `.planning/config.json`:
  `planning: opus, discuss: opus, research: opus, execution: sonnet,
  verification: opus`. The committed history has exactly one change to
  `execution`: commit `bf9ef968` (2026-10-26 12:09 UTC) added
  `"execution": "sonnet"`; the key did not exist before and has not changed
  since. The only uncommitted change touches `review.default_reviewers` and
  `review.parallel_lanes`. The cross-runtime leak hypothesis is therefore
  **not** confirmed on machine B: `execution` was never `opus`. The Codex
  rollouts of that day were all planning work (planner, phase researcher, UI
  researcher, UI checker, pattern mapper), no `exec-high` launch.
- Launcher: `main` is `254be7f` (2026-10-26 17:13 UTC); the installed
  `~/.local/bin/gsd-cli` has the same timestamp. The alias fix `ca88321`
  landed at 12:02 UTC, before every session below, and every spawn in those
  sessions carries an explicit model. The day is representative.
- Resolver (`session_model_usage.py resolve`, `GSD_RUNTIME=claude`), identical
  to machine A:

  | Agent | Resolved |
  |---|---|
  | gsd-executor | `opus` |
  | gsd-code-reviewer | `fable` |
  | gsd-code-fixer | `opus` |
  | gsd-verifier | `fable` |
  | gsd-ui-auditor | `fable` |
  | gsd-security-auditor | `fable` |
  | gsd-nyquist-auditor | `opus` (project `model_overrides`) |
  | gsd-debugger | `opus` |
  | gsd-planner | `fable` |
  | gsd-phase-researcher | `fable` |

- Catalog: `gsd-code-fixer` has `phaseType: execution` (golden `opus`,
  balanced and budget `sonnet`).

### Sessions (Tasks 2 to 4)

The tool ran without a traceback on all three scans. Since 2026-10-26
machine B has 250 Claude Code sessions (`--all`, most of them claude-mem
observer sessions), of which two spawned GSD agents, both in the weaver
project; the `--since 2026-10-01` scan reports 0 sessions without a
subagent transcript. Codex: 15 rollouts on 2026-10-26, all planning, no
`gsd-code-fixer` or `gsd-code-reviewer` spawn.

**`gsd-code-fixer` never ran on Fable on machine B.** It was spawned twice,
both times with `@opus` (Opus 5.5), in the `--fix` session below. The
orchestrator of that session made zero edits, so every review fix (WR-01,
WR-02, WR-04 and the WR-05 edits) was written by the fixer on Opus 5.5.
The second fixer run outlived its orchestrator session: the orchestrator's
last record is 21:02, the fixer committed WR-04 at 21:11 and was still
working at 21:14. Its WR-05 edits stayed uncommitted until the next
morning, when session `e0813a6e` (Opus 5.5, `/gsd-next`, zero edits of its
own) committed them as `c33d4555` (2026-10-27 06:05 UTC). So `--fix --all`
did not complete inside its session.

Heaviest Fable session, `090ed207` (`/gsd-execute-phase 08.29`, session
model Opus 5.5, 16:31 to 20:33 UTC):

| Agent | Model | Runs | Output tokens |
|---|---|---|---|
| gsd-executor | Opus 5.5 | 7 | 763.0k |
| gsd-code-reviewer | Fable | 1 | 62.0k |
| gsd-verifier | Fable | 1 | 60.6k |
| orchestrator | Opus 5.5 | 1 | 49.7k |
| gsd-ui-auditor | Fable | 1 | 40.0k |
| gsd-security-auditor | Fable | 1 | 35.4k |

Timeline: seven executor spawns 16:33 to 18:51, then security auditor
19:40, UI auditor 19:48, code reviewer 19:59, verifier 20:13, two docs
commits 20:32. No `REVIEW.md` edit by the orchestrator (its two edits were
the executor brief and `SECURITY.md`); no fixer in this session. The
orchestrator's text at 20:24 says "the verifier ran a second time", but the
transcript holds one verifier spawn, resumed twice by the harness (20:22 and
20:29, same agent id) with no `SendMessage` continuation; the resumed work
is inside the 60.6k, not a second Fable spawn. The reviewer and verifier
each ran once here, unlike machine A's phase 04, because nothing was edited
after UAT: the orchestrator only ran the UAT and docs commits.

Fix session, `1d6a134a` (`/gsd-code-review 08.29 --fix` at 20:35, then
`--fix --all` at 20:52; session model Opus 5.5):

| Agent | Model | Runs | Output tokens |
|---|---|---|---|
| gsd-code-fixer | Opus 5.5 | 2 | 77.5k |
| gsd-code-reviewer | Fable | 1 | 38.1k |
| orchestrator | Opus 5.5 | 1 | 9.2k (0 edits) |

The first `--fix` skipped a new review (planning-only scope since the last
review) and went straight to the fixer; `--fix --all` ran one deep
re-review on Fable, then the fixer again (see above: that run outlived the
session). A third session, `53b37cf4`
(20:34, `--fix`), was `/clear`-ed after four turns and spawned nothing
(0.9k output tokens).

### Where machine B's Fable output went on 2026-10-26

Output tokens across all sessions of the day:

| Source | Fable output |
|---|---|
| execute-phase verification-tier agents (reviewer, verifier, UI auditor, security auditor) | 198k |
| four `fable-review` cross-AI plan-review lanes (`/gsd-review` convergence cycles 1 to 4; each a Fable session with no spawns) | 140k |
| deep re-review in `--fix --all` | 38k |
| **Fable total** | **376k** |
| Opus 5.5 total, weaver sessions of the day (executors 763k, fixer 78k, orchestrators 75k) | 915k |

(Another 9k of Fable output is the session that ran this replay.) The
plan-review lanes are a Fable source machine A did not have: the project's
`review.default_reviewers` lists `fable-review`, so each `/gsd-review`
cycle runs a full Fable session. On this day they cost about as much Fable
output as the whole execute-phase verification pass. None of the options
below touches that; it is a `review.default_reviewers` choice.

### Conclusion

The premise (fixing on Fable) does not hold on machine B either. Fable
spend after execution comes from the verification-tier agents (about 200k
output tokens for the phase, against 760k of Opus 5.5 execution), plus one
Fable re-review per `--fix --all`, plus the Fable plan-review lanes before
execution. Conclusion on machine A: **confirmed on machine B.**

Still unmeasured: the cost delta between `code_review_depth` `deep` and
`standard`.

## Options

Config-only means `.planning/config.json`, written either by hand or by the
launcher at launch.

**A. Pin the verifier (and UI auditor) to the sonnet tier (Opus 5.5), keep
the code reviewer on Fable.** One `AGENT_TIERS` entry each in `gsd-cli`;
materialized into `model_overrides` on every launch. GSD's own `quality`
profile already puts `gsd-verifier` in the sonnet column.
Pro: removes about half the Fable output per phase; config-only; follows
upstream judgement. Con: the agent that marks a phase complete loses Fable;
pins apply to every profile, including plan sessions.

**B. Lower review depth.** `workflow.code_review_depth: "standard"`, or
`workflow.code_review_depth_overrides` so only source paths get `deep`.
Pro: project config only. Con: shallower review; saving unmeasured.

**C. Pin `gsd-code-fixer` to the sonnet tier explicitly.** No behaviour change
today. Pro: documents intent, survives a future GSD catalog change. Con: one
more launcher-managed override key.

**D. Make resolution visible.** Extend `gsd-cli status` to print the
resolver's answer per key agent (what `tools/session_model_usage.py resolve`
does), or at least document that command. Pro: ends guessing. Con: one node
start per agent, so status only, never the launch banner.

**E. Stop the cross-runtime leak in the launcher.** Not needed by the
evidence: machine B did not confirm the hypothesis above. Make every Claude profile write
`models.execution` explicitly (the `plan` profile today does not), or key the
tier words written to `models` per runtime. Pro: removes a silent route of
execution work to Fable. Con: touches `PROFILES`, tests, README and the
example config; `plan` sessions would then also rewrite the execution tier.

**Not achievable via config:** suppressing the second review-and-verify pass
after post-UAT edits, and running the orchestrator's own inline fixes on a
model other than the session model. Manual rule: triage and fix post-execution
findings in the exec-opus session, not in a plan session.

## Non-goals

- Changing which models the Codex profiles use.
- Changing GSD core.

## Handoff

Branch `review-tier-spend-analysis` on `origin` carries this spec, the plan,
`tools/session_model_usage.py` and the AGENTS.md pointer. Machine B fetches
that branch and works on it; findings are committed there, not on `main`.

## Open question (for the owner)

Should the verifier move off Fable (option A), or stay on Fable with only the
review depth reduced (option B)? Both machines answered the premise: fixing
never ran on Fable. Machine B numbers per option: A removes the verifier's
61k (and the UI auditor's 40k) of the 198k Fable output per phase; B's
saving is unmeasured; C changes nothing today; D is visibility only. The
140k of Fable plan-review lanes is outside all four and is a
`review.default_reviewers` choice.
