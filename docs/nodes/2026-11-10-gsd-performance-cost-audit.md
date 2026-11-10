# GSD performance and cost configuration audit

Date: 2026-11-10. Launcher baseline: `0b4623e` (implementation unchanged from the original assessment). Goal: preserve useful independent review and strong reasoning where mistakes are expensive, while reducing unnecessary reasoning and repeated context elsewhere.

**The strongest starting improvement is to rebalance reasoning effort by agent responsibility.** Current routing spends extra-high effort on planning and user profiling, but low effort on plan checking, integration checking, research synthesis, and behavioral-test auditing. Those latter jobs are not merely mechanical checks. Model choice alone does not correct that imbalance.

These are source-grounded recommendations for an evaluation baseline, not measured optimal settings. No paid model calls, live configuration changes, or model-quality benchmarks were performed.

## Scope and evidence

There is no `.planning/config.json` in this repository. The audit covers the launcher's generated configuration, the example, and the installed GSD machinery. A different project's additional settings can change the outcome. The inspected global defaults contain `resolve_model_ids: "omit"` and no explicit effort/workflow overrides; the project configurations used here take precedence for routing.

Installed GSD versions differ: Claude **1.20.1**, Codex **1.18.0**. I evaluated all **35 registered agents × 11 launcher profiles × 2 installations = 770 resolver results**, in temporary projects initialized using the launcher's own functions. Models, effort, routing class, and fast-mode results matched between the two installations for these configurations. This establishes routing agreement, not equality of all workflow implementations.

The native-install subset is saved as [385 routing rows](2026-11-10-resolved-routing.csv). The public `query resolve-model` command was also checked for the plan checker in both runtimes. The matrix describes resolved policy, not proof that a particular past session honored it. Each profile was evaluated after fresh initialization; custom settings and prior profile history are not represented.

I inspected agent duties, actual switch consumers, installed agent definitions, effort propagation, and official provider documentation. Proposed switch setters were checked with `config-set --dry-run` in temporary projects. Actual usage, subscription allowances, and reviewer bills were not available.

## Model level and reasoning effort are separate

The launcher's high/medium/low labels map to Fable/Opus/Sonnet for Claude and Astra/Sol/Luna for Codex. These are the owner's routing choices, not independently proven capability rankings. Claude subagent entries are family aliases; they need not resolve to the exact generation pinned for the main session.

The model resolver considers managed agent pins and phase models. The effort resolver separately uses invocation overrides, `effort.agent_overrides`, the agent's built-in routing class, and finally defaults. A low-cost model can therefore receive `xhigh` effort; a flagship model can receive `low`.

Two temporary probes illustrate ineffective shortcuts:

- Setting `model_profile: "budget"` left planner/checker/executor models unchanged because explicit phase routing already selected them.
- Setting only `effort.default: "medium"` left their efforts at xhigh/low/high because their routing-class defaults won.

Likewise, `model_policy.budget` is a named-provider preset selector, not a dollar budget. The current explicit runtime tier maps resolve before it, so it is not an effective cost knob for this launcher's routing. [Policy resolver](/home/alex/.claude/gsd-core/bin/lib/model-resolver.cjs:326).

Use explicit per-agent effort settings for consequential exceptions. Evidence: [model resolution](/home/alex/.claude/gsd-core/bin/lib/model-resolver.cjs:491), [effort resolution](/home/alex/.claude/gsd-core/bin/lib/model-resolver.cjs:873), and the [canonical effort defaults](/home/alex/.claude/gsd-core/bin/shared/config-defaults.manifest.json:91).

OpenAI recommends lower effort for extraction/classification, medium or high for diagnosis/planning/code reasoning, and xhigh/max only when representative evaluations justify their cost and latency. Anthropic similarly distinguishes routine scoped engineering from verification-heavy work and cautions that effort scales differ across models. These support selective allocation, not a universal best setting. [OpenAI guidance](https://developers.openai.com/api/docs/guides/deployment-checklist), [Claude Code effort guidance](https://code.claude.com/docs/en/model-config#choose-an-effort-level).

## Task allocation matrix

Current model levels below are the shared planning / medium-execution baseline: Claude `plan` or `exec-opus`, Codex `plan` or `exec-medium`, after fresh init. Execution-shaped agents follow the chosen execution profile in other rows of the CSV. Recommended allocations are starting hypotheses based on responsibilities and error consequences.

| Task or agent | Current level / effort | Recommended starting point | Basis and escalation condition |
| --- | --- | --- | --- |
| Planner, roadmapper | High / xhigh | High / high | Dependency and goal decomposition affect all downstream work. Reserve xhigh for difficult constraints, architecture, or failed high-effort attempts. |
| Plan checker | High / low | High / high | Checks temporal coupling, cross-plan contracts, completeness, and wiring—not just formatting. First effort increase to try. |
| Executor, code fixer | Medium / high | Medium / high; trial medium effort on bounded routine changes | Handles unexpected bugs, deviations, and security/correctness requirements. Raise model level for concurrency, migrations, auth, or difficult algorithms. |
| Debugger, debug-session manager | Medium / xhigh | Medium / high for localized bugs; high / high for ambiguous failures | Hypothesis testing needs reasoning. Currently follows execution tier, including economy under low execution. Consider an independent model pin for difficult debugging. |
| Verifier, code reviewer | High / high | Keep high / high for substantial changes | Independent reasoning about actual behavior, edge cases, and claimed completion is valuable. Workhorse model is a possible trial on small, low-risk diffs. |
| Integration checker | Medium / low | Medium / high; high model for broad integration | Traces full data flow, consumers, invocation sites and failure states. Raise effort before paying for a larger model universally. |
| Nyquist auditor | Medium / low | Medium / high | Designs behavioral tests and diagnoses whether failures come from tests or implementation. Current model pin is plausible; low effort is the questionable part. |
| Research synthesizer | Medium / low | Medium / high | Reconciles findings and derives dependency-aware roadmap structure. Escalate the model for conflicting research. |
| Phase/project researchers | High / high | Medium / medium for known-stack lookups; high / high for consequential uncertainty | Separating factual retrieval from architectural judgment saves more plausibly than lowering all research uniformly. |
| Pattern mapper | Medium / low | Medium / medium | Chooses analogs by responsibility and data flow. High effort is justified for mixed paradigms or security-sensitive patterns. |
| Codebase mapper | Low / low | Medium / medium if using one static pin | The same role covers inventory, architecture, quality, and concerns. Economy/low is reasonable for inventory alone; architecture/concerns deserve more reasoning. |
| Intel updater | Low / low | Medium / medium for full refresh; low / low–medium for partial updates | Full refresh synthesizes architecture; partial refresh explicitly omits architecture/stack analysis. A single static pin cannot distinguish them. |
| Doc verifier | Medium / low | Trial low / medium on bounded factual claims | Mostly checks files, routes, symbols and dependencies; does not execute documented commands. Retain medium model for broad implicit claims. |
| Doc classifier | Low / low | Keep low / low | Fixed taxonomy and structured extraction; uncertain classifications should remain explicit rather than invented. |
| Doc synthesizer | High / high | Medium / high for coherent inputs; high / high for conflicts | Semantic contradictions, locked decisions, precedence and cycles require judgment. |
| User profiler | Low / xhigh | Low / medium | Rubric scoring and conflicting evidence need some judgment, but xhigh is a weak default use of reasoning budget compared with correctness gates. |
| MemPalace curator | Low / low | Keep for routine updates; medium effort for semantic supersession | Mostly structured persistence, provenance and idempotence, with occasional meaningful judgment. |
| Security auditor | High / xhigh | High / high; selective xhigh | Audit depth ranges from presence checks to end-to-end bypass analysis. Do not use the cheapest setting for L2/L3 boundary reasoning. |
| Eval planner / assumptions analyzer / framework selector | High / xhigh | High / high; selective xhigh | Choices and evaluation criteria shape subsequent work. Extra-high is an escalation candidate rather than an evidence-proven universal default. |
| UI checker/auditor, DOM verifier | High / low | Task-dependent: medium/medium for explicit criteria; high/high for substantive UX judgment | Current routing alone cannot establish that every visual/DOM check deserves flagship inference. Inspect acceptance-criteria ambiguity before reducing it. |

Evidence for the reasoning-heavy gates: [planner](/home/alex/.claude/gsd-core/agents/gsd-planner.md:457), [plan checker](/home/alex/.claude/gsd-core/agents/gsd-plan-checker.md:220), [executor](/home/alex/.claude/gsd-core/agents/gsd-executor.md:178), [integration checker](/home/alex/.claude/gsd-core/agents/gsd-integration-checker.md:20), [Nyquist auditor](/home/alex/.claude/gsd-core/agents/gsd-nyquist-auditor.md:65), [research synthesizer](/home/alex/.claude/gsd-core/agents/gsd-research-synthesizer.md:103), and [security audit depths](/home/alex/.claude/gsd-core/agents/gsd-security-auditor.md:74).

Evidence for mixed/mechanical work: [mapper responsibilities](/home/alex/.claude/gsd-core/agents/gsd-codebase-mapper.md:17), [full versus partial intel updates](/home/alex/.claude/gsd-core/agents/gsd-intel-updater.md:253), [doc verifier constraints](/home/alex/.claude/gsd-core/agents/gsd-doc-verifier.md:58), [classifier](/home/alex/.claude/gsd-core/agents/gsd-doc-classifier.md:23), [doc synthesis](/home/alex/.claude/gsd-core/agents/gsd-doc-synthesizer.md:145), and [profiler rubric](/home/alex/.claude/gsd-core/agents/gsd-user-profiler.md:78).

## Important effort delivery findings

**The repository's claim that Claude has no session effort flag is outdated.** The installed `claude --help` lists `--effort <level>`, and official documentation supports it. Add explicit Claude session effort to the redesigned policy: medium for routine interactive work, high when doing architecture/diagnosis directly in the main session. This is separate from subagent settings. [Claude session effort](https://code.claude.com/docs/en/model-config#set-the-effort-level).

**Claude GSD agents currently have installed effort frontmatter.** The inspected planner is xhigh; checker/integration/synthesis/Nyquist are low; executor is high. Merely editing project effort configuration changes resolver output but does not rewrite these installed definitions. GSD documents `effort sync --apply` for that synchronization. Preview it first; applying to a global installation affects shared agent definitions, not just one project. No sync was applied in this audit. [Installed planner](/home/alex/.claude/agents/gsd-planner.md:12), [checker](/home/alex/.claude/agents/gsd-plan-checker.md:6), [GSD effort explanation](/home/alex/.claude/gsd-core/references/model-profiles.md:229).

**Codex follows a different path.** The inspected agent TOML headers have no model/effort pins. The installed skill adapter instructs GSD to resolve each agent's effort and pass `reasoning_effort` when the tool supports it. Current Codex effort-sync code removes obsolete/orphaned pins rather than blindly inserting effort everywhere. An older paragraph in GSD's model-profile reference still says Codex always pins effort at install time; current code and installed files are stronger evidence. [Skill dispatch instructions](/home/alex/.agents/skills/gsd-plan-phase/SKILL.md:52), [Codex sync implementation](/home/alex/.claude/gsd-core/bin/lib/commands.cjs:1021). Verify the actual spawn channel before treating resolver results as observed runtime effort.

**A resolved agent pin can also be bypassed by a workflow's chosen model argument.** Both installed plan-phase workflows pass `researcher_model` to the pattern mapper, rather than resolving the pattern mapper's own model. The matrix's medium/low row is its resolver policy; this particular spawn receives the high research model under the audited baseline. Changing only the pattern-mapper model pin does not correct that call site. [Claude dispatch](/home/alex/.claude/gsd-core/workflows/plan-phase.md:690), [Codex dispatch](/home/alex/.codex/gsd-core/workflows/plan-phase.md:690).

Automatic drift-triggered codebase remapping similarly omits an explicit model argument, unlike normal map-codebase dispatch. Its economy model pin is therefore not established by that call site. Also, the installed agent contract states that no standard Markdown workflow currently spawns `gsd-intel-updater`: tuning that role only matters when it is actually invoked. [Auto-remap dispatch](/home/alex/.claude/gsd-core/workflows/execute-phase/steps/codebase-drift-gate.md:89), [intel agent contract](/home/alex/.claude/gsd-core/references/agent-contracts.md:44).

## Configuration switches missing from the example

These settings are absent from the launcher example, not necessarily from another project's config. Most already have defaults; writing them explicitly makes policy stable, but does not itself save tokens. Defaults below are from the inspected Claude 1.20.1 manifest and consumers, with important cross-runtime caveats noted.

| Setting / current default | Recommendation | Verified effect and limit |
| --- | --- | --- |
| `effort.agent_overrides` / empty | Add explicit role-based overrides | Directly fixes the mismatched reasoning allocations above. Runtime delivery still needs the checks described earlier. |
| `workflow.compact_content` / false | First context-saving experiment: true | Uses compact workflow fragments/templates and some compact agent payloads. Does not uniformly shrink every named Claude agent or source file. No measured savings percentage. |
| `workflow.auto_prune_state` / false | Consider true for long-lived projects | Prunes completed-phase state with three recent phases retained; durable decisions should live in durable artifacts. |
| `workflow.pattern_mapper` / true | Consider false for this small, already-understood launcher; retain for unfamiliar repositories | Removes a separate analogy-discovery step. This trades explicit pattern discovery for fewer calls. |
| `workflow.research` / true | Keep; reuse existing research and selectively use `--skip-research` | Interactive planning may still ask when false. Existing RESEARCH.md is reused unless research is forced. |
| `workflow.plan_check` / true | Keep for substantial plans | This consumer really gates the checker; skipping cheap validation can increase later repair work. |
| `workflow.nyquist_validation` / true | Keep for behavioral changes | Planning's validation strategy is also skipped when research is disabled. These settings are coupled. |
| `workflow.verifier` / true | Keep; do not sell false as a proven saving | The inspected execute-phase verifier step dispatches unconditionally despite the available setting. Both installed variants show this inconsistency. |
| `workflow.inline_plan_threshold` / 2 | Keep initially | Inline handling of small plans is implemented in execute-plan; do not assume it controls execute-phase's direct executor fan-out. |
| `parallelization` / true | Keep where plans are independent | Primarily reduces elapsed time; more agents can duplicate context. No inherent cost discount. |
| `workflow.context_guard_mode` / warn | Keep warn; consider auto for long runs with checkpoint/resume | Attempts to avoid work under degraded context. Turning it off is not an established optimization. |
| `workflow.node_repair_budget` / 2 | Keep bounded; lower only if retries fail repeatedly | Repair retries may save intervention time but incur additional work. |
| `context_window` / 200000 | Match actual runtime; do not inflate as an optimization | Workflows include richer historical context at ≥500000, increasing prompt input. This is not a universal context-budget saving switch. |
| `plan_review.source_grounding` / true | Keep explicitly true | Source evidence can prevent unsupported reviewer objections from driving expensive rework. |
| `review.effort.<adapter>` / high | Make explicit; trial medium for routine metered reviews | Separate from session and subagent effort. See review matrix below. |

Sources: [canonical defaults](/home/alex/.claude/gsd-core/bin/shared/config-defaults.manifest.json:29), [compact content](/home/alex/.claude/gsd-core/references/compact-content-gate.md:11), [state pruning](/home/alex/.claude/gsd-core/bin/lib/phase.cjs:6933), [research selection](/home/alex/.claude/gsd-core/workflows/plan-phase.md:354), [Nyquist dependency](/home/alex/.claude/gsd-core/workflows/plan-phase.md:439), [checker gate](/home/alex/.claude/gsd-core/workflows/plan-phase.md:976), [verifier dispatch](/home/alex/.claude/gsd-core/workflows/execute-phase/steps/verify-phase-goal.md:128), [inline execution](/home/alex/.claude/gsd-core/workflows/execute-plan.md:96), and [context guard](/home/alex/.claude/gsd-core/references/execute-phase-context-guard.md:7).

Be precise about `fast_mode`: with no block, light agents resolve true from canonical tier defaults. In a temporary probe, explicitly setting only `fast_mode: {"enabled": false}` changed the checker to false. Existing explicit tier overrides can still take precedence. The resolver flag is not evidence that a particular host used a fast service tier, and fast service is not synonymous with lower token cost. No automatic fast-mode change is recommended here. [Resolver](/home/alex/.claude/gsd-core/bin/lib/model-resolver.cjs:941).

## External reviewer cost and quality

Keep independent external review; optimize its scope and repeated work before removing it wholesale. The current preset selects three reviewers: the other Claude/Codex reviewer plus Grok and Gemini through OpenCode. DeepSeek is defined but inactive.

| Control | Current behavior | Proposed use |
| --- | --- | --- |
| Reviewer count | Three per pass, two metered OpenRouter lanes | Retain all three for architectural/security changes. Offer a routine preset with the independent subscription-path reviewer plus one paid reviewer, selected using useful findings and actual billing. |
| Convergence cycles | Default max three; exits early on resolution | Consider invoking convergence with `--max-cycles 2` for routine work; retain three for difficult phases. This is a workflow argument, not an existing `review.max_cycles` config key. |
| Effort | Claude/Codex/OpenCode lanes default high | Keep high for difficult reviews. Trial `review.effort.opencode: "medium"` on routine phases; it affects both Grok and Gemini. |
| Parallel lanes | False | Enable when elapsed time matters and provider limits permit; it does not reduce the reviewer roster or cycles. |
| Prompt caps | `review.max_prompt_tokens` and adapter caps; context-derived defaults additionally in Claude GSD 1.20.1 | Version-sensitive: Claude 1.20.1 refuses oversized lanes; Codex 1.18.0 trims prompts and skips if the minimum set cannot fit. Neither behavior caps output tokens or total spend. |
| Timeout | Claude/Codex 1200 seconds; OpenCode 660 seconds | Tail-latency control, not a spending cap. Shortening may discard paid work and lead to repeats. |

Invocation arithmetic: three reviewers × three cycles permits **nine reviewer CLI invocations**, including **six OpenRouter-backed reviewer invocations**, before planning/replanning overhead. Two cycles would permit six/four respectively. Each source-reading reviewer can make multiple provider requests. These counts bound reviewer runs without additional retries or manual reruns, not billed API requests or actual usage.

The installed review lane code emits Claude `--effort`, Codex `-c model_reasoning_effort=…`, and OpenCode `--variant …`. OpenCode forwarding is verified; whether a given provider honors a variant is a separate concern. Per-instance reviewer schema exposes CLI/model/agent, not independent effort; the two OpenCode instances share `review.effort.opencode`. Adding an `effort` property to each reviewer instance is not a verified solution. [Effort resolution](/home/alex/.claude/gsd-core/bin/lib/review-lane-invocation.cjs:138), [instance schema](/home/alex/.claude/gsd-core/references/reviewer-instances.md:12), [convergence cycle control](/home/alex/.claude/gsd-core/workflows/plan-review-convergence.md:21), [parallel review](/home/alex/.claude/gsd-core/workflows/review.md:344), [prompt cap behavior](/home/alex/.claude/gsd-core/bin/lib/review-lane-invocation.cjs:295).

The older Codex prompt-trimming behavior is documented in its [review workflow](/home/alex/.codex/gsd-core/workflows/review.md:463) and [budget resolver](/home/alex/.codex/gsd-core/bin/lib/review-lane-invocation.cjs:292). Aligning GSD versions is advisable before comparing reviewer results across runtimes, because equal cap settings can otherwise produce different review inputs. An upgrade itself still needs verification; none was performed here.

Current public OpenRouter displayed prices are Grok 4.7 **$2 input / $6 output** per million tokens and Gemini 4 Argon **$2 input / $10 output** per million, with a discount indicator on the Gemini page. These are dated public listings, not guaranteed account/provider invoices. At hypothetical 30,000 billed input and 5,000 billed output tokens each, one two-model pass would be $0.09 + $0.11 = **$0.20**; three identical passes $0.60. This deliberately simplified illustration excludes differences in billed reasoning/output, cache accounting, source-reading turns, tools, retries, and provider pricing. Use actual billed usage for decisions. [Grok pricing](https://openrouter.ai/x-ai/grok-4.7), [Gemini pricing](https://openrouter.ai/google/gemini-4-argon).

Subscription-path calls still consume allowances and time, and cannot be priced using API rates as if they were the same bill. Claude's documentation also says Fable may consume usage credits depending on plan/seat. The launcher's API-key guard does not establish whether those calls are included in this user's plan. [Fable billing behavior](https://code.claude.com/docs/en/model-config#fable-and-usage-credits).

## Candidate changes and verification

The [candidate JSON fragment](2026-11-10-proposed-gsd-settings.json) contains selective effort overrides and compact content. It is **a merge fragment for evaluation, not a replacement configuration**. It deliberately does not change model IDs, reviewer rosters, verification gates, or active settings. The new launcher design should represent these effort choices explicitly rather than relying only on model levels.

Both installed real resolvers accepted the fragment in temporary projects: the planner/checker/integration checker resolved high, and the profiler resolved medium. Setter checks also accepted compact content, auto-pruning, pattern mapper, each reviewer adapter's effort, and review parallelism. `config-set` rejects whole-map `effort.agent_overrides` and `fast_mode.routing_tier_defaults`; individual leaves such as `effort.agent_overrides.gsd-plan-checker` and `fast_mode.routing_tier_defaults.light` succeeded in both installations. A direct JSON merge is also understood by the resolver.

Recommended order:

1. Verify dispatch actually receives the selected model and effort, particularly pattern mapping and auto-remapping. Make session, subagent, and external-review effort independently visible in policy, including Claude's supported session flag and its installed-agent synchronization boundary.
2. Trial high effort for plan checker/integration/Nyquist/synthesis and medium for profiling. Compare planner high against its existing xhigh before standardizing a reduction.
3. Trial compact content; compare plans and review findings before adopting it broadly.
4. Raise mapping/full-intel model allocation where architecture is involved; trial cheaper bounded doc verification to offset cost. Keep researcher allocation conditional on novelty.
5. Keep a quality reviewer group and add an explicit routine group. Measure useful unique findings per paid call, not just reviewer count or output length.

For evaluation, use representative routine edits, unfamiliar integration, difficult debugging, and a security/data-boundary change. Hold input tasks and acceptance criteria stable. Compare accepted correctness, defects caught/missed, repair/replan counts, elapsed time, tokens and actual metered cost. Change one dimension at a time; judge total cost per accepted result rather than only the first response's cost. This is the evidence needed to claim a best-price configuration rather than just a plausible one.

## Consequences for the pending launcher design

The design is not yet ready to freeze its effort model. It needs separate fields for session effort in both runtimes, agent-specific effort, and external-review adapter effort. It must document that changing Claude project effort alone is insufficient for installed named agents, and avoid silently mutating global agent definitions on every project launch. Capture ownership must account for whichever effort settings the launcher manages.

The current design's model-tier-only task pins remain useful, but are insufficient to achieve the owner's price/performance goal. Resolve this before implementation planning. No existing user-approved decision about CLI order, explicit reviewer selection, automatic capture, or Click/pipx needs to change.
