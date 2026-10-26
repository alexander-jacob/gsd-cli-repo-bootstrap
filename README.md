# GSD Core multi-CLI launcher

**Use GSD Core across Codex, Claude Code and OpenCode while prioritizing existing ChatGPT and Claude Max subscriptions over pay-as-you-go APIs.**

This repository contains a small, Python standard-library-only `gsd-cli` launcher and an example GSD project configuration. It automates runtime selection, task-specific model tiers, and independent AI reviewer presets. It does **not** replace GSD Core or the underlying coding CLIs.

## Design goals

- Use **Codex + ChatGPT subscription** for Astra-led planning, analysis, and optional execution.
- Use **Claude Code + Claude Max** for Fable-led planning and Opus/Sonnet execution.
- Run independent reviews from **Claude/Fable** or **Codex/Astra** (subscription-backed), alongside **Grok, Gemini and DeepSeek** through **OpenCode → OpenRouter** (metered).
- Switch who leads the work without changing reviewer models manually; avoid having a model independently review its *own* plan.
- Keep model tiers and reviewer definitions persistent, but select planning/execution/review presets per session.

## Architecture

```text
                         GSD Core project
                        .planning/config.json
                                 |
                              gsd-cli
                   selects profile and GSD_RUNTIME
                    /                         \
          Codex CLI                       Claude Code
       ChatGPT subscription             Claude Max subscription
      Astra / Sol / Luna             Fable / Opus / Sonnet
                    \                         /
                     \      GSD plan        /
                       review / convergence
                                |
                   +------------+-------------+
                   |                          |
        Independent subscription       Metered OpenRouter reviews
               reviewer                       via OpenCode
       Fable OR Astra (not author)      Grok / Gemini / DeepSeek
```

**Important:** GSD `opus`, `sonnet` and `haiku` are *tier labels* (high / medium / lower). They do not obligate you to run Claude Opus/Sonnet/Haiku. The mappings below intentionally use `opus → Fable`, `sonnet → Opus`, and `haiku → Sonnet` for Claude.

### Model tiers

| GSD tier | Claude runtime | Codex runtime |
|---|---|---|
| `opus` (high) | `fable` (Fable 5.1) | `gpt-6-astra` |
| `sonnet` (medium) | `opus` (Opus 5.5) | `gpt-6.1-sol` |
| `haiku` (lower) | `sonnet` (Sonnet 5.5) | `gpt-6-luna` |

The Claude entries are **Agent-tool aliases**, not full model IDs: Claude Code spawns subagents only by `fable`/`opus`/`sonnet`/`haiku` (each resolving to the latest model of that family). GSD cannot map a full ID such as `claude-opus-5-5` back to an alias; it warns, drops the value, and the subagent silently inherits the session model — so the tier mapping would have no effect.

Codex launches also pass `-c model_reasoning_effort=<effort>` for the session model's tier (Astra `high`, Sol `medium`, Luna `low`); without it Codex runs Astra at its `medium` default, which is what the orchestrator uses for discuss/plan work it does inline. GSD subagents get their own effort from the GSD profile. Claude Code has no equivalent launch flag.

A top-level CLI session model (`--model`) and the GSD subagent tier mappings are **different settings**. The launcher sets both as appropriate for each profile.

### Reviewer pool

| Name | Adapter | Pinned model | Intended billing |
|---|---|---|---|
| `fable-review` | `claude` | `claude-fable-5-1` | Claude Max |
| `astra-review` | `codex` | `gpt-6-astra` | ChatGPT subscription |
| `grok-review` | `opencode` | `openrouter/x-ai/grok-4.7` | OpenRouter API |
| `gemini-review` | `opencode` | `openrouter/google/gemini-4-argon` | OpenRouter API |
| `deepseek-review` | `opencode` | `openrouter/deepseek/deepseek-v3.2` | OpenRouter API |

All five are defined under `review.reviewer_instances`, *not* `review.models`. Their presence does not mean all five run each time: `review.default_reviewers` controls the selected subset. `deepseek-review` is defined but currently not selected by any profile.

| Who produced the plan? | Selected reviewers |
|---|---|
| **Codex / Astra** | Fable + Grok + Gemini |
| **Claude / Fable** | Astra + Grok + Gemini |

`review.parallel_lanes` stays `false`: reviews execute sequentially, which is simpler for rate limits and billing. The OpenCode reviewer instances can be expanded independently as new models become available.

## Repository contents

```text
.
├── README.md                         # This document
├── gsd-cli                           # Executable Python 3 launcher
├── examples/
│   └── gsd-config-example.json       # GSD config fragment/example
├── docs/
│   └── LAUNCHER.md                   # Detailed installation and operation
├── tests/
│   └── test_gsd_cli.py              # Python unittest tests (no dependencies)
└── .gitignore
```

## Prerequisites

- Python 3.10+ for the launcher (standard library only).
- Node.js and `npx` for the GSD Core installer.
- Installed `claude`, `codex`, and `opencode` CLIs available on `PATH`.
- Claude Code authenticated through **Claude Max**, Codex authenticated through **ChatGPT**, and OpenCode configured for **OpenRouter**.
- A target GSD project with `.planning/config.json` already created (for example using GSD's new-project or onboarding flow).

> Model IDs, CLI options, plan entitlements and GSD schema can change. Check your installed CLIs' model lists and the upstream GSD documentation before running paid review batches. This repository documents an intended configuration; it cannot guarantee provider availability or subscription billing.

## Install GSD Core in each CLI

Recommended global installation for GSD workflows in any project:

```bash
# Claude Code
npx @opengsd/gsd-core@latest --claude --global

# Codex CLI
npx @opengsd/gsd-core@latest --codex --global

# OpenCode
npx @opengsd/gsd-core@latest --opencode --global
```

Alternatively, from a project root, replace `--global` with `--local` to install under `.claude/`, `.codex/`, and `.opencode/` respectively. Restart each CLI after installation. For **external reviews only**, OpenCode merely needs to be installed/authenticated; its GSD command installation is optional.

Authenticate and check:

```bash
claude --version
codex --version
codex login status
opencode --version
opencode models openrouter
```

Inside Claude Code, `/status` should indicate subscription authentication. Avoid setting `ANTHROPIC_API_KEY` when intending to use Claude Max; likewise avoid API-key overrides when intending to use ChatGPT-backed Codex.

## Install the launcher

From this repository:

```bash
task install
```

This requires Task. To install manually:

```bash
mkdir -p ~/.local/bin
cp ./gsd-cli ~/.local/bin/gsd-cli
chmod +x ~/.local/bin/gsd-cli
```

Ensure `~/.local/bin` is on `PATH` (e.g. in `~/.bashrc`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Use `~/.local/bin`, **not the target project's root** and not `/usr/local/bin`, unless you intentionally want system-wide deployment. The launcher is global to your Linux user, but reads/writes each project's own `.planning/config.json`.

## Initialize a GSD project

Create or onboard a project with the standard GSD commands first:

```text
Claude Code: /gsd-new-project      (existing repo: /gsd-onboard)
Codex CLI:  $gsd-new-project      (existing repo: $gsd-onboard)
```

Once `.planning/config.json` exists, run from the project root (or a descendant):

```bash
cd ~/projects/my-project
gsd-cli init            # or: gsd-cli init codex
gsd-cli status
```

`init` **merges** the launcher's policy into your current project config and preserves unrelated settings:

- `model_policy.runtime_tiers`: Claude tiers as Agent-tool aliases (`fable` / `opus` / `sonnet`), Codex tiers as full IDs with reasoning effort (Astra / Sol / Luna).
- `models`: `planning`, `discuss`, `research` and `verification` on the `opus` tier, `execution` on `sonnet` — the same values the `plan` and `exec-opus` profiles set, so a project is consistent before its first launch. Existing values are kept.
- `model_overrides`: the per-agent tier pins (see below), materialized for the runtime given as argument (default `claude`). Every launch rewrites them for its own runtime.
- `review`: five reviewer instances and the initial default reviewers (Fable + OpenRouter).
- Removes an explicit top-level `runtime` so `GSD_RUNTIME` can select the runtime per session.

See [the complete example](examples/gsd-config-example.json).

This is a **configuration example/merge**, not a recommendation to replace an existing `.planning/config.json` wholesale.

## Launcher profiles

| Command | Top-level CLI model | GSD agent setting changed | Reviewer preset |
|---|---|---|---|
| `gsd-cli codex plan` | Astra | planning/discuss/research = `opus` | Fable + 3 OpenRouter |
| `gsd-cli claude plan` | Fable | planning/discuss/research = `opus` | Astra + 3 OpenRouter |
| `gsd-cli claude exec-opus` | Opus 5.5 | execution = `sonnet`, verification = `opus` | preserved |
| `gsd-cli claude exec-sonnet` | Sonnet 5.5 | execution = `haiku`, verification = `opus` | preserved |
| `gsd-cli codex exec-high` | Astra | execution = `opus` | preserved |
| `gsd-cli codex exec-medium` | Sol | execution = `sonnet` | preserved |
| `gsd-cli codex exec-low` | Luna | execution = `haiku` | preserved |
| `gsd-cli codex review-claude-plan` | Astra | none | Astra + 3 OpenRouter |
| `gsd-cli claude review-codex-plan` | Fable | none | Fable + 3 OpenRouter |

### Per-agent tier pins

GSD phase types are broad: `research` also covers the intel updater and codebase mapper, `verification` also covers the test-writing Nyquist auditor. The launcher carries a small `AGENT_TIERS` table (in `gsd-cli`) that pins such mechanical agents to a lower tier, keyed by GSD tier word:

| Agent | Tier | Claude / Codex |
|---|---|---|
| `gsd-nyquist-auditor`, `gsd-integration-checker`, `gsd-pattern-mapper`, `gsd-doc-verifier`, `gsd-research-synthesizer` | `sonnet` (medium) | Opus / Sol |
| `gsd-codebase-mapper`, `gsd-intel-updater`, `gsd-doc-classifier`, `gsd-user-profiler`, `gsd-mempalace-curator` | `haiku` (lower) | Sonnet / Luna |

Every launch materializes this table into `model_overrides` **for the launched runtime** — Claude gets Agent-tool aliases, Codex gets full model IDs — because GSD applies `model_overrides` values verbatim and has no per-runtime translation of its own. Override keys the launcher does not manage are preserved. Planners, researchers, the code reviewer and the verifier are deliberately not pinned: they follow `models.<phase_type>` and stay on the high tier.

`research` covers the phase/project researcher agents, which GSD otherwise routes to the medium tier; the plan profiles lift them to the high tier so research runs on the same model as planning. `verification` covers the GSD code reviewer and verifier agents that run after execution. The Claude execution profiles pin it to the `opus` tier so the post-execution review always runs on Fable, independent of the execution tier.

The two review profiles also work with the opposite runtime; see `gsd-cli --help` or [the launcher reference](docs/LAUNCHER.md). **The review preset follows the author of the plan, not the CLI used to run the review.**

Execution and review profiles and `gsd-cli codex plan` **skip permission prompts by default**: the launcher passes `--dangerously-skip-permissions` to Claude or `--dangerously-bypass-approvals-and-sandbox` to Codex, which also disables Codex's sandbox (see [OpenAI's approval documentation](https://learn.chatgpt.com/docs/agent-approvals-security)). This allows execution, reviews, and Codex planning to run unattended; only launch them on a repository you intend to grant that access to. Pass `--secure` before the optional `--` separator to keep the CLI's own permission prompts:

```bash
gsd-cli claude exec-opus --secure
gsd-cli codex plan --secure
gsd-cli codex exec-high --secure -- --no-alt-screen
gsd-cli codex review-codex-plan --secure
```

Claude planning keeps the CLI's normal permissions (`--secure` is accepted there and has no effect). Subscription billing guards apply in both modes. Arguments after `--` are forwarded unchanged.

### Workflow A — Astra plans, Claude executes

```bash
# Start Codex with Astra; inside Codex discuss/plan/review the phase
gsd-cli codex plan
# $gsd-discuss-phase 1
# $gsd-plan-phase 1     OR $gsd-plan-review-convergence 1

# After exiting Codex, start Claude with Opus 5.5
gsd-cli claude exec-opus
# /gsd-execute-phase 1

# Optionally verify in Codex / Astra
gsd-cli codex review-codex-plan
# $gsd-verify-work 1
```

The review subset for Codex-authored plans is Fable, Grok and Gemini. Execution preserves that subset.

### Workflow B — Fable plans, Codex executes

```bash
# Fable-led planning; selected reviewers: Astra + OpenRouter
gsd-cli claude plan
# /gsd-discuss-phase 1
# /gsd-plan-review-convergence 1

# Run implementation in Codex / Astra (or exec-medium for Sol)
gsd-cli codex exec-high
# $gsd-execute-phase 1
```

### Explicitly choose the reviewer preset later

```bash
# Reviewing a Claude/Fable-authored plan from Codex
gsd-cli codex review-claude-plan

# Reviewing a Codex/Astra-authored plan from Claude
gsd-cli claude review-codex-plan
```

Inside the CLI, invoke the appropriate GSD review command, e.g. `$gsd-review --phase 1` in Codex or `/gsd-review --phase 1` in Claude Code. GSD external review examines phase plans. A separate GSD code review is not automatically the same four-model reviewer ensemble.

## How the launcher works

1. Finds `.planning/config.json` in the current directory or an ancestor.
2. Loads project settings, merges/updates only selected fields, and atomically replaces the JSON file on changes: the profile's `models.<phase_type>` tiers, and `model_overrides` materialized from `AGENT_TIERS` for the launched runtime.
3. During `plan` selection, chooses the independent reviewer preset; during `exec-*`, **retains the current reviewer list**.
4. Refuses to start if an API-key environment variable would override subscription authentication for the runtime or a selected reviewer.
5. Sets `GSD_RUNTIME` for the child CLI process (`codex` or `claude`), rather than relying on installation markers or modifying a shared `runtime` field.
6. Starts the CLI with `--model <session-model>`, plus `-c model_reasoning_effort=<tier effort>` for Codex, plus the permission-bypass flag for every profile except Claude planning unless `--secure` was given.

Example with extra CLI options:

```bash
gsd-cli codex plan -- --help
```

The launcher currently starts Claude or Codex, **not OpenCode as an interactive primary runtime**. GSD invokes OpenCode separately for paid review lanes.

## Billing and security

- **Claude Max:** The `claude` adapter uses the local authenticated Claude Code CLI; confirm it is logged into your subscription. A model ID alone does not guarantee subscription-backed execution.
- **ChatGPT:** The `codex` adapter uses local Codex; sign in with ChatGPT and confirm `codex login status`.
- **OpenRouter:** Grok, Gemini and DeepSeek are billed per the OpenRouter account's usage and model prices.
- The launcher refuses to launch subscription-backed sessions/review presets if it detects conflicting `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or `CODEX_API_KEY` environment variables. This check is only a safety guard; inspect your CLI's active authentication settings too.
- Neither credentials nor authentication tokens are included in this repository. Never commit API keys or CLI auth files.

## Limitations / operational notes

- The launcher mutates **shared** `.planning/config.json` project settings. This is suitable for sequential handoffs. It is **not** safe to assume isolated settings for simultaneous write-capable sessions in the same checkout. Use separate worktrees/projects for that scenario.
- Atomic JSON replacement prevents partial files but does **not** implement a multi-process configuration lock or eliminate lost updates from concurrent writes.
- Every launch rewrites the runtime-specific parts of `config.json` (`models.execution`, `model_overrides`), so the file shows a diff after each runtime switch. Commit it as "whichever CLI ran last" or leave it uncommitted; it carries no information beyond the launcher's tables.
- Some GSD installations (notably OpenCode and certain Codex-generated agent definitions) use install-time/static model configuration. Changing the tier mappings may require reinstalling/syncing the relevant GSD runtime artifacts.
- Review instances reuse the same OpenCode adapter; these are separate model opinions, not four independently authenticated CLI installations.
- Do not use `/gsd-review --all` unintentionally: it may run reviewers outside the selected defaults and incur additional charges.
- Model quality rankings and provider catalogs change. This repo records **your selected preferences**, not an objective guarantee that one model is superior for every task.
- `gsd-cli init` requires an existing `.planning/config.json`; it does not bootstrap an application project from nothing.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Tests use temporary project directories and stub CLI executables. They do **not** spend API tokens, install GSD, or validate actual upstream model availability.

## Upstream documentation

- [GSD Core repository](https://github.com/open-gsd/gsd-core)
- [GSD Core configuration reference](https://github.com/open-gsd/gsd-core/blob/next/docs/CONFIGURATION.md)
- [Install GSD Core on your runtime](https://github.com/open-gsd/gsd-core/blob/next/docs/how-to/install-on-your-runtime.md)
- [Cross-AI review setup](https://github.com/open-gsd/gsd-core/blob/next/docs/how-to/set-up-cross-ai-review.md)

This repository is a personal orchestration wrapper around GSD Core, not an official GSD project.
