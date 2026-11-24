# Machine-readable output

Use `--json` before the first `--`. Each inspection writes one JSON document to stdout. Every envelope carries integer `schema_version: 2`, a command name, `ok`, `data`, and `error`. Inspect both the exit code and the payload. A failed check or incomplete preview can return useful data with its error. Paths below are normalized from a temporary project using fixture GSD bundles.

```sh
gsd-cli status --json
gsd-cli check codex --json
gsd-cli policy --json
gsd-cli claude medium --secure --config --json
gsd-cli sessions codex --json
gsd-cli schema preview
```

## Check

A successful fixture-backed `gsd-cli check codex --json` produced this envelope.

```json
{
  "schema_version": 2,
  "command": "check",
  "ok": true,
  "data": {
    "minimum": "1.21.0",
    "results": [
      {
        "runtime": "codex",
        "directory": "/tmp/example/home/.codex/gsd-core",
        "installed": "1.21.0",
        "minimum": "1.21.0",
        "ok": true,
        "reason": "ok",
        "message": "meets the project minimum"
      }
    ]
  },
  "error": null
}
```

Each result's `reason` is `ok`, `below_minimum`, or `unverifiable`. Omit the runtime to inspect both. Any failed requirement sets `ok` to false and returns exit 1.

## Status and policy

Status returns `project`, `source`, `pending_recovery` and the saved `config`. Policy returns `project`, `path`, the complete validated `policy`, and paths in `differs_from_shipped`. The packaged starter serves as a comparison. Runtime launch decisions come from the project policy.

## Preview

`gsd-cli RUNTIME BLUEPRINT --config --json` reports the selected runtime and blueprint, requested session and reviewer settings, the selected installation, per-role evidence, GSD context, prospective config, pending capture and diagnostics. `--details` selects the text view and cannot be combined with JSON.

For example, the fixture-backed Claude command above reports this `data.session` object.

```json
{
  "model": "claude-opus-5-5",
  "effort": "medium",
  "permissions": "normal",
  "argv": [
    "claude",
    "--model",
    "claude-opus-5-5",
    "--effort",
    "medium"
  ],
  "forwarded": []
}
```

For the executor, the following projection shows the source of both requested values and the prospective file action. The complete agent object also contains raw `resolved` GSD fields, `check` and `findings`.

```json
{
  "agent": "gsd-executor",
  "phase": "execution",
  "covered": true,
  "project_definition": {
    "source": "/tmp/example/home/.claude/agents/gsd-executor.md",
    "destination": ".claude/agents/gsd-executor.md",
    "action": "create",
    "model": "opus",
    "effort": "medium"
  },
  "expected": {
    "model": "opus",
    "effort": "medium",
    "model_source": "runtimes.claude.blueprints.medium.phases.execution.model",
    "effort_source": "runtimes.claude.blueprints.medium.phases.execution.effort"
  }
}
```

A project definition can be created, updated, unchanged, removed or forgotten. Codex rows have a null `project_definition`. The row’s `check` is `mismatch` if any known mismatch exists, otherwise `unknown` if evidence is missing, otherwise `ok`. A complete comparison exits 0 even if a row reports a difference. An unavailable installation or catalog can produce an incomplete preview with session/reviewer settings, no agent rows and a null effective config. Later resolver failures retain the configuration already calculated.

### Finding codes

| Code | Severity | Raised when |
|---|---|---|
| `model_mismatch` | `mismatch` | The resolved model differs from the configured one. |
| `effort_mismatch` | `mismatch` | The resolved effort differs from the configured one. |
| `effort_clamped` | `mismatch` | The runtime clamped the requested effort. |
| `installed_effort_mismatch` | `mismatch` | Effort drift: Claude's installed agent frontmatter effort differs from the configured effort. |
| `installed_effort_differs` | `note` | Installed Claude frontmatter differs from the proposed project definition. |
| `project_effort_unverified` | `unknown` | Actual Claude effort for the project definition is unobserved. |
| `model_unknown` | `unknown` | The model expectation or the resolution is missing. |
| `effort_unknown` | `unknown` | The effort expectation or the resolution is missing. |
| `forwarded_may_override` | `unknown` | Forwarded child arguments may override inherited session effort. |
| `installed_effort_unknown` | `unknown` | The resolver supplied no installed-file evidence for Claude effort. |
| `inherit_depends_on_forwarded` | `unknown` | A requested inherited effort depends on forwarded session options. |
| `propagation_unknown` | `unknown` | Codex effort propagation is unsupported or unknown. |
| `unregistered_agent` | `unknown` | The agent is not in the installed GSD catalog. |
| `alias_equivalent` | `note` | A Claude model alias was confirmed equivalent by the installed catalog. |
| `inherits_session_effort` | `note` | The installed agent inherits the session effort. |

## sessions

```sh
gsd-cli sessions [claude|codex] [--pick [N]] --json
```

Payload: `project`, `resolver_available`, `sessions` and `older`.

- Default: `sessions` holds the newest three sessions with their children,
  checked as the text command does; `older` is empty.
- `--pick N --json`: `sessions` holds that one older session.
- `--pick --json` without a number: `sessions` is empty and `older` lists older
  top-level sessions without children, numbered as the text listing numbers
  them (index 0 is pick 1). Listing entries are not checked: their `marks`
  hold only what the text listing shows (such as `reviewer, unattached`), so
  `mismatch` is false. It never prompts or reads stdin.
- Each run has `kind` (`session`, `agent` or `reviewer`), actual `model` and
  `effort`, human-readable `marks`, `mismatch` (true when any mark starts with
  `!`), a `launch` summary (without the embedded `config`, `policy` and
  `gsd_defaults`; `null` when no launch record matched) and nested `children`.
- No sessions is success with empty lists. Bad arguments and a missing session
  number exit 1 with error kind `usage`.

`sessions` compares what each agent ran with what the installed GSD would have
resolved. It asks through the same non-mutating resolver bridge as `--config`
and never runs `gsd-tools.cjs`. A runtime whose selected installation is not
usable (Node plus `bin/lib/commands.cjs`), or whose bridge call fails, skips
only its own comparisons. `resolver_available` is `false`, and the text command
prints its "profile comparison skipped" note, only when no checked runtime was
usable.

The `launch.blueprint` field identifies new launches. Older records may carry `workflow`, `level` or `profile`. Reviewer comparison uses captured review settings when available. If several active reviewers share an adapter, the report can compare adapter effort without guessing the instance-specific model.

## Errors

For example, `gsd-cli init --json` emits this usage error. An invocation with no JSON command has a null `command`.

```json
{
  "schema_version": 2,
  "command": null,
  "ok": false,
  "data": null,
  "error": {
    "kind": "usage",
    "message": "No such option '--json'."
  }
}
```

### Error kinds

| `error.kind` | Meaning |
|---|---|
| `usage` | Bad arguments or options, including `sessions` errors such as `--pick 9` for a missing session (exit 1) and Click usage errors (exit 2). |
| `config` | Project discovery, a missing `gsd-cli.config.json`, working-config conflicts, pending recovery or a held lock. Also a value from the working config or a session log that the output schema cannot represent (exit 1). |
| `policy` | `gsd-cli.config.json` is invalid; the message starts with the offending path. |
| `version` | A GSD version or `gsd.min_version` value could not be parsed. |
| `os` | A file or process error. |
| `requirements` | A `check` failed. `data` still lists every result. |
| `incomplete` | A configuration preview could not collect all resolver evidence. `data` is still complete for what was found. |

Message wording is not part of the contract; branch on `kind`, `reason`, `code`
and `severity`.

## schema

```sh
gsd-cli schema          # list the names, one per line
gsd-cli schema status   # print one JSON Schema, not enveloped
```

It works outside a project. Names: `status`, `check`, `policy`, `preview`,
`sessions`, `error` (the envelope whose `command` is `null`) and `policy-file`
(`gsd-cli.config.json` itself). An unknown name is a usage error. Schemas are
generated from the same Pydantic models that produce the output, so they cannot
drift from it.

### Editor support for the policy file

Save the schema and map it to the policy file in your editor's JSON Schema
settings:

```sh
gsd-cli schema policy-file > gsd-cli.config.schema.json
```

Map that file to `gsd-cli.config.json`. The policy file itself must not contain
`$schema`: policy validation rejects unknown top-level keys. The schema covers
structure and allowed values; `gsd-cli policy` stays the validator and also
checks cross-references such as reviewer names in each runtime roster.

## Guarantees

- **Read-only.** JSON mode never writes: no working config, baseline, journal,
  lock or launch-log change, and no recovery or capture.
- **Exit codes** equal the text-mode exit codes of the same invocation, and `ok`
  is `true` exactly when the exit code is 0. The one exception is a value the
  output schema cannot represent, which text mode can still display: JSON mode
  then exits 1 with error kind `config` instead of printing a traceback.
- **Only stdout.** JSON mode writes nothing to stderr beyond what a child
  process cannot be prevented from emitting.
- **Compatibility.** Within `schema_version` 2, fields may be added; consumers
  must ignore fields they do not know. Removing or retyping a field, or
  changing its meaning, bumps `schema_version`. The published schemas set
  `additionalProperties: false`, so a consumer that validates output should
  fetch them from the installed tool (`gsd-cli schema NAME`) rather than cache
  old copies, which would reject newly added fields.
