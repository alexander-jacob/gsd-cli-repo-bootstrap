# GSD CLI launcher — Astra / Fable / Opus / Sonnet

This launcher explicitly selects `GSD_RUNTIME` for each CLI session, sets its session model with `--model` (and, for Codex, its reasoning effort with `-c model_reasoning_effort=…`), and updates a small set of GSD project settings atomically in `.planning/config.json`.

The intended setup is:

- **Codex (ChatGPT subscription):** Astra for planning, or Astra / Sol / Luna execution tiers.
- **Claude Code (Claude Max subscription):** Fable → Opus → Sonnet for high / medium / lower-capability tiers.
- **OpenCode (OpenRouter API):** pay-as-you-go Grok, Gemini, and DeepSeek review lanes. The launcher starts Codex/Claude; GSD launches OpenCode when running those external reviewers.
- **Cross-provider review:** Codex-led plans use Fable + OpenRouter reviewers; Claude-led plans use Astra + OpenRouter reviewers.

## 1. Install GSD Core for the different CLIs

### Prerequisites

Install and authenticate the **Claude Code**, **Codex**, and **OpenCode** CLIs separately first. This README installs *GSD Core into those existing CLIs*; it does not install the CLIs themselves. You also need `node`, `npm`/`npx`, and Python 3 for the custom launcher. Node.js 22+ is a conservative choice compatible with the published installation documentation.

```bash
node --version
npm --version
python3 --version
claude --version
codex --version
opencode --version
```

### Recommended: global GSD installation for all three

Run each command once. Global scope makes GSD commands available across projects:

```bash
# Claude Code: /gsd-* commands
npx @opengsd/gsd-core@latest --claude --global

# Codex: $gsd-* skills/commands
npx @opengsd/gsd-core@latest --codex --global

# OpenCode: /gsd-* commands
npx @opengsd/gsd-core@latest --opencode --global
```

The installer adapts GSD's commands, agents and supporting files to each CLI's configuration format. **Do not manually copy** Claude command/agent files into Codex or OpenCode. Restart the respective CLI after installing or upgrading GSD.

Typical global install locations (may differ when you customize CLI config roots):

| CLI | Global configuration root | GSD invocation |
| --- | --- | --- |
| Claude Code | `~/.claude/` | `/gsd-new-project`, `/gsd-plan-phase` |
| Codex | `~/.codex/` | `$gsd-new-project`, `$gsd-plan-phase` |
| OpenCode | `~/.config/opencode/` (XDG) | `/gsd-new-project`, `/gsd-plan-phase` |

**Note:** Installing GSD into OpenCode enables *interactive GSD commands in OpenCode*. For use strictly as a paid external reviewer, the important requirements are the OpenCode binary and working OpenRouter credentials. Installing GSD there as well is convenient, but does not change OpenRouter billing.

### Alternative: project-local installation

Run these commands **from the project root** if you want GSD installed only in one repository:

```bash
npx @opengsd/gsd-core@latest --claude --local
npx @opengsd/gsd-core@latest --codex --local
npx @opengsd/gsd-core@latest --opencode --local
```

These write to `./.claude/`, `./.codex/`, and `./.opencode/` respectively. Pick global *or* local as your normal approach. If both are installed, Claude Code may prefer a global skill over a similarly named local command (see GSD's install-shadow warning).

To update an installation, rerun the appropriate `npx ...@latest --<runtime> --global` (or `--local`) command and restart the CLI. In particular, rerun the relevant GSD installer if model changes need to be propagated into static agent definitions.

### Authenticate and verify the CLIs

**Claude Max subscription** — sign in interactively using your subscription:

```bash
claude
# Inside Claude Code: /status
```

**ChatGPT subscription for Codex** — use ChatGPT login rather than an OpenAI API key:

```bash
codex login
codex login status
```

**OpenRouter for OpenCode** — configure OpenRouter as your provider and verify its model catalog:

```bash
opencode auth login
# Select the OpenRouter provider and enter its API key as prompted.
opencode models openrouter
```

Check that the intended models are listed by their CLIs. The reviewer identifiers and model availability can change across releases and providers.

Verify the GSD installation from a *new* session:

```text
Claude Code: /gsd-health
Codex:       $gsd-health
OpenCode:    /gsd-health
```

Use the CLI-specific command prefix: **`/gsd-*` for Claude/OpenCode, `$gsd-*` for Codex**. If a command does not appear, check the installer output, installation scope and CLI version, then restart the CLI.

Official reference: [GSD Core — Install on your runtime](https://github.com/open-gsd/gsd-core/blob/next/docs/how-to/install-on-your-runtime.md).

## 2. Install the custom launcher

The script `gsd-cli` is a **separate local convenience launcher**, not the official GSD installer.

Run `task install` from this repository to install it in `~/.local/bin` using Task, or install manually:

```bash
mkdir -p ~/.local/bin
cp gsd-cli ~/.local/bin/gsd-cli
chmod +x ~/.local/bin/gsd-cli
# Ensure ~/.local/bin is included in PATH.
```

On a fresh project, run `/gsd-new-project` in Claude/OpenCode or `$gsd-new-project` in Codex first, so `.planning/config.json` exists. For an existing repository, use `/gsd-onboard` or `$gsd-onboard` as appropriate. The launcher expects this project config file to exist.

## 3. Initialize project policy (once per project)

From the project root:

```bash
gsd-cli init
gsd-cli status
```

Codex launches add `-c model_reasoning_effort=<effort>` for the session: Astra `high` (plan and both review profiles), Astra `medium` (exec-high, a per-profile override in `SESSION_EFFORTS`), Sol `medium` (exec-medium), Luna `low` (exec-low). Without the flag Codex runs Astra at its `medium` default — the effort the orchestrator uses for everything it does inline, including the discuss phase. GSD subagents spawned from that session receive their own model and per-agent effort from GSD (executors `high`) and are unaffected by the session's effort. See the README for the per-profile table. Claude Code has no equivalent launch flag, so Claude profiles pass `--model` only.

Every launch also writes `model_overrides` for the launched runtime from the launcher's `AGENT_TIERS` table (mechanical agents such as `gsd-intel-updater` and `gsd-codebase-mapper` on the lower tier, `gsd-nyquist-auditor` and `gsd-pattern-mapper` on the medium tier). See the README for the full table.

`init [claude|codex]` configures the Claude tier mappings **Fable / Opus / Sonnet** (as the Agent-tool aliases `fable` / `opus` / `sonnet`, currently Fable 5.1 / Opus 5.5 / Sonnet 5.5); Codex tier mappings **Astra / Sol / Luna**; the phase tiers (`planning`, `discuss`, `research`, `verification` = `opus`, `execution` = `sonnet`); the per-agent pins in `model_overrides` for the given runtime (default `claude`); five reviewer instances; sequential review by default. It removes an explicit project-level `runtime` field so per-session `GSD_RUNTIME` can select the runtime. Existing unrelated settings are preserved.

The initial default reviewers are Fable, Grok, and Gemini. DeepSeek stays defined as a reviewer instance but is not selected by default. A Claude-led planning profile replaces Fable with Astra to avoid self-review.

## 4. Use the launcher

```bash
# Codex/Astra planning; Fable, Grok, Gemini review
gsd-cli codex plan

# Claude/Fable planning; Astra, Grok, Gemini review
gsd-cli claude plan

# Execution profiles preserve currently configured reviewer defaults
gsd-cli claude exec-opus      # execution on Opus, code review + verifier on Fable
gsd-cli claude exec-sonnet    # execution on Sonnet, code review + verifier on Fable
gsd-cli codex exec-high
gsd-cli codex exec-medium
gsd-cli codex exec-low

# Select reviewers based on the original planning environment
gsd-cli codex review-claude-plan
gsd-cli claude review-codex-plan
```

Extra CLI args can be forwarded after `--`, e.g. `gsd-cli codex plan -- --help`.

All execution and review profiles and `gsd-cli codex plan` bypass permission prompts by default: the launcher adds Claude's `--dangerously-skip-permissions` or Codex's `--dangerously-bypass-approvals-and-sandbox` (the Codex flag also disables sandboxing), allowing execution, reviews, and Codex planning to run unattended. Pass `--secure` before `--` to keep the CLI's permission prompts instead, for example:

```bash
gsd-cli claude exec-sonnet --secure
gsd-cli codex plan --secure
gsd-cli codex exec-medium --secure -- --no-alt-screen
gsd-cli codex review-codex-plan --secure
```

Either way the setting applies only to the launched CLI session and keeps the subscription billing guards active. Claude planning keeps the CLI's normal permissions; `--secure` is accepted there as a no-op. A `--secure` after `--` is forwarded literally rather than interpreted.

**Example phase handoff:** Run `gsd-cli codex plan`, discuss/plan the phase using `$gsd-*` commands, exit Codex, run `gsd-cli claude exec-opus`, and execute the phase using `/gsd-execute-phase`. The project `.planning/` artifacts serve as the handoff.

The custom launcher supports Codex and Claude profiles; OpenCode runs as an *external reviewer* through GSD. To work interactively inside OpenCode, launch `opencode` directly (assuming GSD was installed for that CLI).

### Checking what a session actually ran

`gsd-cli sessions` is a read-only report on what Claude Code and Codex really did in this project. It reads the runtimes' own session logs (`~/.claude/projects/` and `~/.codex/sessions/`), never writes to them or to the project, and shows the model and reasoning effort of each session, subagent and cross-AI reviewer run. This catches the silent failure where a bad tier entry makes every subagent inherit the session model.

```bash
gsd-cli sessions                # the three newest sessions of this project
gsd-cli sessions codex          # only Codex (or: claude)
gsd-cli sessions --pick         # list older sessions; prompts for a number on a terminal
gsd-cli sessions --pick 2       # show the 2nd older session (1 = the fourth newest)
```

The `--pick` list shows only each older session's summary line; it carries no mismatch marks, since the checks run only for the session you then pick.

Run it in the project or any subdirectory. Sample output:

```text
claude  2026-10-29 14:05  profile: exec-opus  claude-opus-5-5  medium  advisor claude-fable-5-1
  gsd-executor  asked sonnet  ran claude-sonnet-5-5/high
  gsd-verifier  asked sonnet  ran claude-opus-5-5/high  ! asked sonnet, ran claude-opus-5-5  ! profile expects sonnet
  reviewer fable-review  ran claude-opus-5-5  ! fable-review expects claude-fable-5-1
  gsd-planner  asked opus  ran claude-opus-5-5/high
codex   2026-10-28 09:30  profile: plan  gpt-6-astra  high
```

Each session line shows runtime, start time (local), the launching profile, session model, effort (`<effort> (varied)` if it changed during the session) and the Claude advisor model if one was recorded. Indented lines are subagents (`asked` is what the agent requested, `ran` is what the log recorded) and cross-AI reviewer runs, which are nested under the session that triggered them. A reviewer run that overlaps no session is listed on its own, marked `reviewer, unattached`.

Two kinds of mismatch are flagged with `!`:

- **Requested vs. actual:** `! asked sonnet, ran claude-opus-5-5`. The agent asked for one model and ran on another. Reviewers are compared against the `REVIEWERS` table (`! fable-review expects claude-fable-5-1`).
- **Profile vs. actual:** `! profile expects sonnet` or `! profile expects effort high`. The session or agent did not get what the launching profile should have given it. Expected agent values come from the real GSD resolver run against the config snapshot recorded at launch, not from the current config or the launcher tables. Claude is compared by model family; Claude session effort is shown but not compared, since Claude Code has no launch flag for it.

Other marks: `overridden at launch` (your forwarded arguments set their own `--model` or `model_reasoning_effort`, so the profile comparison is skipped) and `resumed, profile may differ` (a later launch resumed the session).

To tie a session to its profile, every runtime-profile launch appends one JSON line to `$XDG_STATE_HOME/gsd-cli/launches.jsonl` (default `~/.local/state/gsd-cli/launches.jsonl`): time, project, runtime, profile, session model and effort, forwarded arguments, a snapshot of the project config as written for the launch, and `~/.gsd/defaults.json` if present. The log is created with mode 0600, since it embeds whole configs. `sessions` matches a session to the latest launch of the same project and runtime within 60 seconds before it started (for Codex, the creation time from the rollout's `session_meta`, which can precede the first logged prompt by minutes). A Claude session started by `/clear` inside a running CLI inherits the launch of the previous session of that project, unless a newer launch of the same runtime came in between. Sessions without a match show `profile: unknown` and skip the profile comparison (requested vs. actual still runs). A failed log write only prints a warning; it never stops the launch.

If node or the GSD resolver (`~/.claude/gsd-core/bin/gsd-tools.cjs`) is missing or fails, only requested vs. actual is checked and the output ends with `note: GSD resolver not available; profile comparison skipped`.

## 5. Billing safety

Fable uses the locally authenticated Claude CLI (`claude`); Astra uses the locally authenticated Codex (`codex`). The launcher refuses to run when `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `CODEX_API_KEY` might override subscription-backed authentication for a selected runtime or reviewer. Verify `/status` in Claude Code and `codex login status` first. Grok/Gemini/DeepSeek use OpenCode with OpenRouter credentials and incur API charges.

A CLI executable name or `--model` setting **alone does not guarantee subscription billing**. Verify the authenticated accounts, account allowances and first review results before running large review batches.

## 6. Notes and limitations

- Reviewer instances are permanently configured; the `plan` and `review-*` profiles change `review.default_reviewers` as appropriate.
- `exec-*` profiles change `models.execution` and the session model, **not** reviewer defaults.
- GSD versions that bake subagent model IDs into static Codex/OpenCode agent definitions may require reinstall/sync after changing model configuration. Check the actual resolved agent models before relying on a new mapping.
- This script does not isolate a project's mutable `models.*` and reviewer defaults between simultaneously active sessions. For truly concurrent workflows, use separate worktrees or independent project configurations.
- Each runtime-profile launch appends a record to `~/.local/state/gsd-cli/launches.jsonl` (outside the repository and `.planning/`); `gsd-cli sessions` reads it. It is never pruned, and a write failure is only a warning.
- Never use `--all` for plan review unless you intend to run additional detected reviewers.
