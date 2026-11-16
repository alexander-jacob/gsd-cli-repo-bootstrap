# Machine-readable output

Every inspection command can print one JSON document instead of text, so scripts,
editors and agent skills never have to parse prose. Add `--json` before the first
`--`; after it, `--json` is an ordinary child argument.

```sh
gsd-cli status --json
gsd-cli check [claude|codex] --json
gsd-cli policy --json
gsd-cli plan claude --config --json
gsd-cli sessions [claude|codex] [--pick [N]] --json
gsd-cli schema [NAME]
```

The examples below were captured from the tool in a throwaway project, with
absolute paths replaced by `/home/user/...` and long arrays trimmed. The preview
example used a stand-in GSD resolver, which is why its model differs from the
configured expectation.

## The envelope

JSON mode prints exactly one JSON object and a trailing newline to stdout, with
two-space indentation and ASCII-only escapes:

```json
{
  "schema_version": 1,
  "command": "check",
  "ok": false,
  "data": { },
  "error": { "kind": "requirements", "message": "..." }
}
```

| Field | Meaning |
|---|---|
| `schema_version` | Integer `1`. Bumped only for incompatible changes. |
| `command` | `status`, `check`, `policy`, `sessions` or `preview` (a workflow with `--config`). `null` when the invocation maps to none of them, for example `init --json`. |
| `ok` | `true` exactly when the exit code is 0. The exit code is the one the same invocation produces in text mode. |
| `data` | The command payload, or `null` when none could be produced. |
| `error` | `null` on success, otherwise `{kind, message}`. `data` and `error` can both be present: a failed check still reports its results. |

`--help` keeps printing help text with exit 0, with or without `--json`.

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

## status

```sh
gsd-cli status --json
```

Payload: `project`, `source` (the working config file), `pending_recovery` and
`config` (the saved working configuration).

```json
{
  "schema_version": 1,
  "command": "status",
  "ok": true,
  "data": {
    "project": "/home/user/project",
    "source": "/home/user/project/.planning/config.json",
    "pending_recovery": false,
    "config": {
      "runtime": "claude"
    }
  },
  "error": null
}
```

## check

```sh
gsd-cli check [claude|codex] --json
```

Payload: `minimum` and `results`, one entry per runtime checked. Each entry has
`runtime`, `directory`, `installed` (`null` when unreadable), `minimum`, `ok`,
`reason` and a human `message`. Any failing entry gives exit 1 and error kind
`requirements`.

```json
{
  "schema_version": 1,
  "command": "check",
  "ok": true,
  "data": {
    "minimum": "1.21.0",
    "results": [
      {
        "runtime": "claude",
        "directory": "/home/user/.claude/gsd-core",
        "installed": "1.21.0",
        "minimum": "1.21.0",
        "ok": true,
        "reason": "ok",
        "message": "meets the project minimum"
      },
      {
        "runtime": "codex",
        "directory": "/home/user/.codex/gsd-core",
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

Failing example (`claude` installed below the minimum):

```json
{
  "schema_version": 1,
  "command": "check",
  "ok": false,
  "data": {
    "minimum": "1.21.0",
    "results": [
      {
        "runtime": "claude",
        "directory": "/home/user/.claude/gsd-core",
        "installed": "1.20.0",
        "minimum": "1.21.0",
        "ok": false,
        "reason": "below_minimum",
        "message": "below the project minimum"
      }
    ]
  },
  "error": {
    "kind": "requirements",
    "message": "GSD requirements not met. Update or repair the reported installation, then rerun gsd-cli check."
  }
}
```

`reason` values:

| `reason` | Meaning |
|---|---|
| `ok` | The installation meets the project minimum. |
| `below_minimum` | The installed version is older than `gsd.min_version`. |
| `unverifiable` | `VERSION` is unreadable or malformed, or the bundle is incomplete. |

## policy

```sh
gsd-cli policy [--json]
```

Reads and validates `gsd-cli.config.json`. Without `--json` it prints one line
naming the validated file. Payload: `project`, `path`, `policy` (the complete
project policy) and `differs_from_shipped`, the dotted paths where the project
policy differs from the shipped starter policy. It shows local customizations
and reveals when the starter has moved on, for example a raised
`gsd.min_version`. An invalid policy gives `ok: false`, `data: null` and error
kind `policy`.

The `policy` object below is trimmed to a few keys.

```json
{
  "schema_version": 1,
  "command": "policy",
  "ok": true,
  "data": {
    "project": "/home/user/project",
    "path": "/home/user/project/gsd-cli.config.json",
    "policy": {
      "schema_version": 1,
      "gsd": {
        "min_version": "1.21.0"
      },
      "runtimes": {
        "claude": {
          "medium": {
            "session_model": "claude-opus-5-5",
            "agent_model": "opus",
            "session_effort": "medium"
          }
        }
      }
    },
    "differs_from_shipped": []
  },
  "error": null
}
```

## preview (`WORKFLOW RUNTIME --config --json`)

```sh
gsd-cli plan claude medium --config --json
```

`--json` on a workflow requires `--config`; otherwise it is a usage error and
nothing launches. It is exclusive with `--details`, because JSON is always
complete: it carries everything `--details` prints.

Payload fields:

- `project`, `workflow`, `runtime`, `level`, `complete`.
- `session`: requested `model`, `effort`, `permissions` (`bypass` or `normal`,
  after `--secure` is applied), `argv` and `forwarded` arguments.
- `reviewers`: the selected reviewer group, each `{name, cli, model, effort}`.
- `installation`: the selected GSD installation, shaped like a `check` entry.
- `agents`: every registered or configured agent. `in_workflow` marks those the
  compact text report would show; `phase` is `"unknown"` without catalog
  metadata. `expected` holds the configured `model` and `effort` with their
  sources. `resolved` is the installed GSD resolver's row, passed through
  unchanged (or `null`); it can gain keys with new GSD releases. `check` is
  `ok`, `mismatch` or `unknown`. `findings` are coded comparison results.
- `gsd_context`: the loader's config source, active workstream and the paths
  where GSD's loaded config differs from the launcher's; `null` when inspection
  did not get that far.
- `pending_capture`, `diagnostics` and `config` (the prospective effective
  configuration).

An incomplete inspection gives exit 1, `ok: false`, the full `data` and error
kind `incomplete`. In the example, `agents` and `config` are trimmed to one agent
and one key, and `reviewers` to one reviewer.

```json
{
  "schema_version": 1,
  "command": "preview",
  "ok": true,
  "data": {
    "project": "/home/user/project",
    "workflow": "plan",
    "runtime": "claude",
    "level": "medium",
    "complete": true,
    "session": {
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
    },
    "reviewers": [
      {
        "name": "astra-review",
        "cli": "codex",
        "model": "gpt-6-astra",
        "effort": "high"
      }
    ],
    "installation": {
      "runtime": "claude",
      "directory": "/home/user/.claude/gsd-core",
      "installed": "1.21.0",
      "minimum": "1.21.0",
      "ok": true,
      "reason": "ok",
      "message": "meets the project minimum"
    },
    "agents": [
      {
        "agent": "gsd-planner",
        "phase": "planning",
        "in_workflow": true,
        "expected": {
          "model": "opus",
          "effort": "high",
          "model_source": "models.planning=sonnet",
          "effort_source": "effort.agent_overrides.gsd-planner"
        },
        "resolved": {
          "model": "fixture-model",
          "profile": "balanced",
          "effort": "high",
          "effort_effective": "high",
          "effort_effective_source": "resolved",
          "effort_propagation": "spawn",
          "effort_param": "reasoning_effort",
          "effort_rendered": "high",
          "effort_clamped": false,
          "fast_mode": false,
          "fast_mode_supported": false,
          "effort_requested": "high",
          "effort_clamp_reason": null,
          "host": "claude",
          "effort_surface": "spawn",
          "effort_argv": [],
          "effort_argv_string": "",
          "effort_argv_value": "high"
        },
        "check": "mismatch",
        "findings": [
          {
            "code": "model_mismatch",
            "severity": "mismatch",
            "message": "model expected opus, resolved fixture-model"
          },
          {
            "code": "installed_effort_unknown",
            "severity": "unknown",
            "message": "installed Claude effort unknown; resolver supplied no file evidence"
          }
        ]
      }
    ],
    "gsd_context": {
      "source": "root",
      "workstream": "",
      "loader_differences": [
        "runtime"
      ]
    },
    "pending_capture": [],
    "diagnostics": [],
    "config": {
      "workflow": {
        "compact_content": true
      }
    }
  },
  "error": null
}
```

### Finding codes

| Code | Severity | Raised when |
|---|---|---|
| `model_mismatch` | `mismatch` | The resolved model differs from the configured one. |
| `effort_mismatch` | `mismatch` | The resolved effort differs from the configured one. |
| `effort_clamped` | `mismatch` | The runtime clamped the requested effort. |
| `installed_effort_mismatch` | `mismatch` | Effort drift: Claude's installed agent frontmatter effort differs from the configured effort. |
| `model_unknown` | `unknown` | The model expectation or the resolution is missing. |
| `effort_unknown` | `unknown` | The effort expectation or the resolution is missing. |
| `forwarded_may_override` | `unknown` | Forwarded child arguments may override inherited session effort. |
| `installed_effort_unknown` | `unknown` | The resolver supplied no installed-file evidence for Claude effort. |
| `inherit_depends_on_forwarded` | `unknown` | A requested inherited effort depends on forwarded session options. |
| `propagation_unknown` | `unknown` | Codex effort propagation is unsupported or unknown. |
| `unregistered_agent` | `unknown` | The agent is not in the installed GSD catalog. |
| `alias_equivalent` | `note` | A Claude model alias was confirmed equivalent by the installed catalog. |
| `inherits_session_effort` | `note` | The installed agent inherits the session effort. |

An agent's `check` is `mismatch` when any finding is a mismatch, otherwise
`unknown` when any is unknown, otherwise `ok`. Findings are ordered mismatches,
unknowns, notes.

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

```json
{
  "schema_version": 1,
  "command": "sessions",
  "ok": true,
  "data": {
    "project": "/home/user/project",
    "resolver_available": true,
    "sessions": [
      {
        "runtime": "claude",
        "run_id": "s1",
        "kind": "session",
        "cwd": "/home/user/project",
        "start": "2026-10-01T09:00:00Z",
        "end": "2026-10-01T09:02:00Z",
        "model": "claude-opus-5-5",
        "effort": "medium",
        "effort_varied": false,
        "advisor": null,
        "agent_type": null,
        "requested_model": null,
        "requested_effort": null,
        "resumed": false,
        "cleared": false,
        "marks": [],
        "mismatch": false,
        "launch": null,
        "children": [
          {
            "runtime": "claude",
            "run_id": "a1",
            "kind": "agent",
            "cwd": "/home/user/project",
            "start": "2026-10-01T09:01:30Z",
            "end": "2026-10-01T09:01:40Z",
            "model": "claude-sonnet-5-5",
            "effort": "high",
            "effort_varied": false,
            "advisor": null,
            "agent_type": "gsd-executor",
            "requested_model": "sonnet",
            "requested_effort": null,
            "resumed": false,
            "cleared": false,
            "marks": [],
            "mismatch": false,
            "launch": null,
            "children": []
          }
        ]
      }
    ],
    "older": []
  },
  "error": null
}
```

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
checks cross-references such as reviewer groups and workflow names.

## Guarantees

- **Read-only.** JSON mode never writes: no working config, baseline, journal,
  lock or launch-log change, and no recovery or capture.
- **Exit codes** equal the text-mode exit codes of the same invocation, and `ok`
  is `true` exactly when the exit code is 0. The one exception is a value the
  output schema cannot represent, which text mode can still display: JSON mode
  then exits 1 with error kind `config` instead of printing a traceback.
- **Only stdout.** JSON mode writes nothing to stderr beyond what a child
  process cannot be prevented from emitting.
- **Compatibility.** Within `schema_version` 1, fields may be added; consumers
  must ignore fields they do not know. Removing or retyping a field, or
  changing its meaning, bumps `schema_version`. The published schemas set
  `additionalProperties: false`, so a consumer that validates output should
  fetch them from the installed tool (`gsd-cli schema NAME`) rather than cache
  old copies, which would reject newly added fields.
