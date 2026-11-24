# Configuration details

## Files and ownership

| File | Purpose | Track in Git? |
|---|---|---|
| `gsd-cli.config.json` | Complete project policy | Yes |
| `.planning/config.default.json` | Persistent GSD settings outside launcher ownership | Yes |
| `.claude/agents/gsd-*.md` generated for covered roles | Project-local Claude model and effort | No, exact owned paths are ignored |
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

The version-two policy contains `schema_version: 2`, a required SemVer `gsd.min_version`, both `runtimes.claude` and `runtimes.codex`, and `gsd_defaults`. The latter seeds missing persistent settings during initialization only. New projects start with `workflow.compact_content` enabled.

Each runtime declares one or more entries in `blueprints` and one shared `review` block. Blueprint names begin with a lowercase letter and may contain lowercase letters, digits and hyphens. To create a name such as `fast-review`, copy a complete blueprint within the chosen runtime and edit its fields. Discover that runtime’s names with `gsd-cli codex` or `gsd-cli claude`.

| Blueprint field | Required settings |
|---|---|
| `session` | Model ID and effort for the top-level CLI |
| `phases` | Both model and effort for each of `planning`, `discuss`, `research`, `execution` and `verification` |
| `agents` (optional) | Installed role names and their model, effort or both |

Claude phase and agent models use the aliases `fable`, `opus`, `sonnet` and `haiku`. Codex uses full IDs. Both runtimes support `low`, `medium`, `high` and `xhigh` policy efforts for sessions and agents. Claude also accepts `max`. Actual runtime support depends on the installed tools and model.

## Per-agent overrides

For example, insert these entries into the existing `agents` object of your Codex blueprint:

```json
{
  "gsd-executor": {"model": "gpt-6-astra", "effort": "xhigh"},
  "gsd-verifier": {"effort": "high"}
}
```

The executor gets both explicit values. The verifier inherits its model from the phase assigned by the selected installed catalog. For a registered role with no recognized phase, supply both fields to cover it. With no override such a role stays uncovered. An explicit role missing from the selected catalog causes a preparation error. Preview identifies the policy path supplying each field.

Launch preparation writes `model_overrides.<role>` and `effort.agent_overrides.<role>` for covered roles. Unmanaged siblings survive. Claude additionally needs a readable installed Markdown definition for each covered role, in the `agents/` directory beside the selected `gsd-core/`. Its source directory must be distinct from the project's destination.

## Reviewers

Each runtime’s `review` declares named `reviewer_instances` with a `cli` and `model`, an ordered `default_reviewers` list of declared names, `effort` for all three adapters (`claude`, `codex`, `opencode`), and boolean `parallel_lanes`. An empty roster is valid. Adapter effort is shared by reviewers using that CLI. The starter selects the opposite runtime's reviewer plus Grok and Gemini, declares an inactive DeepSeek reviewer, and disables parallel lanes.

## Permissions and billing

Both runtimes launch with full permission bypass by default. Add `--secure` to omit the automatic bypass flag. Explicitly forwarded options can still affect the child. The launcher checks subscription billing environment variables for the session and selected reviewer adapters. OpenRouter-backed reviewers incur usage charges.

## Persistent changes and upgrades

Keep policy changes in `gsd-cli.config.json`. Review persistent GSD edits in `.planning/config.default.json`. Package upgrades preserve both files. The selected blueprint and installed catalog determine which paths the launcher owns during a launch. Changing the selected runtime or blueprint alone should leave the tracked default stable. See the [launcher reference](LAUNCHER.md#automatic-capture-and-recovery) for conflicts and Claude file cleanup.
