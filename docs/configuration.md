# Configuration details

## Files and ownership

| File | Purpose | Track in Git? |
|---|---|---|
| `gsd-cli.config.json` | Complete project policy | Yes |
| `.planning/config.default.json` | Persistent GSD settings outside launcher ownership | Yes |
| `.planning/config.json` | Effective working configuration | No |
| `.planning/.gsd-cli-sync.json` | Synchronization baseline and ownership | No |
| `.planning/.gsd-cli.lock` / `.gsd-cli-journal.json` | Lock and interrupted-write recovery | No |

`init` seeds policy and persistent defaults while preserving the working config.
When migrating a tracked working config, it removes that file from the Git index
while keeping the local file. Review the staged change before committing.

The [complete starter policy](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/blob/main/examples/gsd-config-example.json)
is the reference for all required fields. The snippets below are edits within
that policy, not complete replacement files.

## Policy fields

| Field | Meaning |
|---|---|
| `schema_version` | Must be `1` |
| `gsd.min_version` | Explicit minimum GSD SemVer; starter value `1.20.1` |
| `runtimes` | Both runtimes and all three levels, each with session model, agent model and session effort |
| `phase_defaults` | Levels for planning, discuss, research, execution and verification |
| `agent_levels` | Named agent pins expressed as runtime-independent levels |
| `agent_efforts` | Independent per-agent reasoning effort |
| `reviewers` | Named instances with `cli` and `model` |
| `reviewer_efforts` | Effort for each of claude, codex and opencode |
| `reviewer_groups` | Lists of declared reviewer names; an empty list is allowed |
| `workflows` | Tasks, fixed task levels, reviewer groups, permissions and parallel review setting |
| `gsd_defaults` | Initialization-only seed for persistent GSD settings |

## Runtime levels and effort

| Level | Claude session / agent | Codex session / agent | Session effort |
|---|---|---|---|
| low | `claude-sonnet-5-5` / `sonnet` | `gpt-6-luna` | low |
| medium | `claude-opus-5-5` / `opus` | `gpt-6.1-sol` | medium |
| high | `claude-fable-5-2` / `fable` | `gpt-6-astra` | high |

These are starter settings, not forced upgrades to existing projects. Medium is
the default launch level. The shipped high Codex execution preset overrides
**session** effort to medium.

Claude agent models must be aliases: `fable`, `opus`, `sonnet` or `haiku`.
Codex agents use full model IDs. GSD's internal haiku/sonnet/opus tier labels
represent low/medium/high; they do not force those particular Claude models.

Session effort, agent effort and reviewer effort are independent. Claude session
and reviewer effort accept low/medium/high; Codex session effort, agent overrides
and Codex/OpenCode reviewer effort also accept xhigh. Runtime support must still
be checked with the installed resolver.

## Resolution order

1. Start with every entry in `phase_defaults`.
2. Apply the requested level to the workflow's `tasks`.
3. Apply the workflow's fixed `task_levels`.
4. Apply named `agent_levels` pins for individual agents.

A phase cannot appear in both `tasks` and `task_levels`. Pins translate to the
selected runtime's agent model. Unrelated GSD keys survive synchronization.

## Reviewers

The starter roster defines Fable 5.2, GPT-6 Astra, Grok 4.7, Gemini 4 Carbon and
DeepSeek V4.1 Flash 1017. Claude workflows select Astra, Grok and Gemini; Codex
workflows select Fable, Grok and Gemini. DeepSeek is defined but inactive.

Reviewer groups are explicit choices, not automatic detection of who wrote a
plan. To enable DeepSeek, add `deepseek-review` to the desired group's list.
Reviewer effort is shared by instances using the same CLI adapter.

## Custom workflows

Add this entry under `workflows` to open a session with high verification settings
and normal permissions:

```json
"ship": {
  "tasks": [],
  "task_levels": {"verification": "high"},
  "reviewer_groups": {
    "claude": "review-claude-plan",
    "codex": "review-codex-plan"
  },
  "parallel_reviews": false,
  "permissions": {"claude": "normal", "codex": "normal"}
}
```

Preview with `gsd-cli ship codex --config`, then launch with `gsd-cli ship codex`.
This opens the CLI; it does not automatically run a shipping skill.

## Permissions and billing

Claude planning uses normal permissions. Codex planning and both execution
presets bypass approval prompts by default. Pass `--secure` to suppress the
launcher's automatic bypass. Explicitly forwarded child flags still take effect.
Custom workflows must declare permissions for both runtimes.

Billing guards reject API-key environment variables for Claude/Codex adapters
used by the session or selected reviewers. They cannot guarantee account billing
settings. OpenCode/OpenRouter reviews are metered.

## Persistent changes and upgrades

Edit model policy in `gsd-cli.config.json`, not generated working values. Edit
persistent GSD defaults in `.planning/config.default.json`, or let the next launch
capture persistent working edits. Package upgrades do not replace project policy;
`gsd_defaults` is only an initialization seed.

Arrays and scalar values merge as whole values; object keys merge independently.
If a merge conflicts, reconcile the reported path before retrying. Preserve the
journal when recovering an interrupted write. See the
[recovery reference](LAUNCHER.md#automatic-capture-and-recovery) for details.
