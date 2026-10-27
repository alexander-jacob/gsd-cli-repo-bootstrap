# Post-execution review spend by tier: findings and options

Status: analysis in progress. Verified on machine A (Alex's laptop, 2026-10-27).
Open: replay on machine B, which ran a heavy review/fix day on 2026-10-26.
Decision pending, see "Open question" at the end.

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

## What is not yet known

- Machine B ran a heavy review/fix day on 2026-10-26. Whether `--fix`,
  `--all` or `--auto` was used there, which session profile the review ran
  in, what `models.execution` was at the time, and which model the fixer
  got, is unverified. The plan replays the same analysis there.
- The launcher commit machine B had that day. If it predates the alias fix
  (`CLAUDE_MODELS` as Agent-tool aliases), every spawn in those sessions
  carries `(inherit)` and the day is not representative of the current
  routing.
- The cost delta between `code_review_depth` `deep` and `standard` is not
  measured. Both the project config and `~/.gsd/defaults.json` on machine A
  set `deep`.

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

**E. Stop the cross-runtime leak in the launcher.** Only relevant if machine
B confirms the hypothesis above. Make every Claude profile write
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
review depth reduced (option B)? Machine B's logs should answer first whether
the premise (fixing on Fable) holds anywhere.
