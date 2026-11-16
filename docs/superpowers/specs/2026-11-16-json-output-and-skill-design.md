# Machine-readable output and the gsd-cli skill

Date: 2026-11-16. Status: approved.

## Intent

Let an AI session inspect, explain and adjust a project's gsd-cli setup in conversation. Today the read-only commands print prose meant for a terminal, so anything that wants to reason about them has to parse text that was never a contract. This work gives those commands a stable JSON form with published schemas, then builds a Claude Code skill on top of it.

The JSON output is the durable part. It also serves CI, status lines and hooks. The skill is a thin layer that knows which command answers which question and how to edit policy safely.

The work ships in two waves, in two repositories:

- **Wave 1** — this repository (`gsd-cli-repo-bootstrap`): JSON output, two new read-only commands, schemas, docs.
- **Wave 2** — the `jacob-consulting` marketplace at `/home/alex/projects/alex/skills`: a new `gsd-cli` plugin holding one skill.

Wave 2 depends only on the wave 1 contract described here.

## Goals

- Every read-only command can emit one JSON document on stdout with a fixed envelope.
- A JSON Schema is published for each output and for `gsd-cli.config.json`, retrievable from the installed tool.
- Failures in JSON mode are also JSON, with unchanged exit codes.
- A skill can: show and explain settings, run checks and triage failures, explain why an agent resolves to a model and effort, surface effort drift, answer questions about recent sessions, and make guided policy edits.

## Non-goals

- No CLI command that writes policy. The skill edits `gsd-cli.config.json` as a file and the CLI validates it (see Approaches).
- No JSON for `init` or for real workflow launches.
- No change to existing text output, exit codes or the plain `status` output.
- No collection of every policy validation error; validation still stops at the first one.
- No `$schema` key inside `gsd-cli.config.json`. Policy validation rejects unknown top-level keys and that stays. Editors map the schema through their own settings.
- No Codex packaging of the skill. The marketplace is a Claude Code marketplace.

## Anti-goals

- The skill launching a workflow. Starting a runtime from inside a runtime is the launcher's job.
- The skill running anything that modifies global agent files, including GSD's effort sync. It reports drift and names the command; the user runs it.
- JSON mode writing any file, capturing config, recovering a journal or appending to the launch log.
- Schemas embedded in the skill. They would go stale and cost context on every load.
- A dependency beyond Click, Pydantic and the standard library. Pydantic is the one addition this work makes (see Constraints).

## Constraints

- Python 3.10+, Click at the CLI boundary only. The functions that build JSON payloads live in domain modules and are usable without a Click context.
- **Pydantic defines the output.** Every JSON document is built as a Pydantic v2 model and serialized from it, and every published schema is generated from the same model. This adds `pydantic>=2,<3` as a runtime dependency, which changes the project rule in `AGENTS.md` ("Avoid dependencies beyond Click and the standard library"); that line is updated to name Pydantic as the second allowed dependency. Pydantic stays confined to the output models and the `schema` command: policy validation, config synchronization, version checks and session reading keep their current standard-library code.
- Untrusted values (model names, paths, argv) are emitted as JSON strings with `ensure_ascii=True`; no ANSI color in JSON mode, ever.
- The launch log embeds whole configs and is mode 0600. Session JSON must not re-export embedded `config`, `policy` or `gsd_defaults` from launch records.
- Repository invariants in `AGENTS.md` continue to hold, in particular: `status` and `sessions` strictly read-only, no bypass of `gsd.min_version`, no fallback to bundled policy.

## Approaches

How guided policy edits get written decided the size of wave 1.

1. **Skill edits the file, CLI validates — selected.** The policy file is tracked, hand-editable and re-validated on every launch, and nothing else writes it concurrently. A file edit handles nested paths, lists and deletions for free. Wave 1 stays strictly read-only, so every new command is safe to run without confirmation. Weakness: the file can be invalid between an edit and its fix; the skill validates after every edit and offers to revert.
2. **CLI write commands (`policy set <path> <value>`) — not selected.** Usable without the skill and atomic, but a large mutation surface (paths, lists, deletions, coercion) with matching tests, protecting a file that has no concurrent writer. Can be added later on top of the same validation.
3. **Diagnostics only — not selected.** Smallest, but leaves the most common follow-up ("so change it") to the user.

## Wave 1: the JSON contract

### Envelope

Every JSON-mode invocation prints exactly one JSON object and a trailing newline to stdout:

```json
{
  "schema_version": 1,
  "command": "check",
  "ok": false,
  "data": { },
  "error": { "kind": "requirements", "message": "GSD requirements not met. ..." }
}
```

- `schema_version` — integer, `1`. Bumped only for incompatible changes; adding fields is compatible.
- `command` — one of `status`, `check`, `policy`, `sessions`, `preview`, or `null` when the invocation maps to none of them (`init --json`, `schema X --json`, `--json` with no command; these are usage errors). `--help` keeps its normal behaviour and prints help text with exit 0, with or without `--json`.
- `ok` — `true` exactly when the exit code is 0. The exit code is always the one the same invocation produces in text mode.
- `data` — the command payload, or `null` when the command could not produce one.
- `error` — `null` on success, otherwise `{kind, message}`. `data` and `error` can both be present: a failed check still reports its results.

Error kinds: `usage`, `config`, `policy`, `version`, `os`, `requirements` (a check failed), `incomplete` (preview resolver evidence incomplete). Click usage errors exit 2. Everything else exits 1, including the `sessions` argument errors (bad arguments, "no session N"), which exit 1 today and are reported as `usage`. `sessions` currently calls `sys.exit` from its domain function; it has to raise instead so the JSON path can report these, with text-mode output and exit codes unchanged.

JSON mode is on when `--json` appears among the arguments before the first `--`. `main()` decides this before Click parses, so usage errors and exceptions raised before a command body runs are also reported as envelopes. For an error envelope, `command` is the first argument when it is one of the five JSON commands, `null` when it is another built-in (`init`, `schema`, `help`) or absent, and `preview` otherwise. In JSON mode nothing is written to stderr except what a child process (the resolver bridge) cannot be prevented from emitting; resolver stderr is already captured into diagnostics.

### Commands

| Invocation | `command` | Payload |
|---|---|---|
| `gsd-cli status --json` | `status` | `{project, source, pending_recovery, config}` |
| `gsd-cli check [claude\|codex] --json` | `check` | `{minimum, results: [{runtime, directory, installed, minimum, ok, reason, message}]}` |
| `gsd-cli policy [--json]` (new) | `policy` | `{project, path, policy, differs_from_shipped}` |
| `gsd-cli WORKFLOW RUNTIME [LEVEL] [--secure] --config --json` | `preview` | see below |
| `gsd-cli sessions [claude\|codex] [--pick [N]] --json` | `sessions` | see below |
| `gsd-cli schema [NAME]` (new) | — | a raw JSON Schema, not enveloped |

**`check`** results carry a machine-readable `reason` next to the human `message`: `ok`, `below_minimum`, or `unverifiable` (VERSION unreadable or malformed, or the bundle incomplete). `message` wording is not part of the contract.

**`policy`** reads and validates `gsd-cli.config.json`. `differs_from_shipped` is the list of dotted paths where the project policy differs from the shipped starter policy (`config.changed_paths(shipped, project)`); it lets a reader see local customizations and notice when the starter has moved on, for example a raised `gsd.min_version`. Without `--json` it prints one line naming the validated file, or the usual error. An invalid policy gives `ok: false`, `data: null`, `error.kind: "policy"` and the existing validation message, which starts with the offending path.

**`schema`** works outside a project. With no argument it prints the available names, one per line. With a name it prints that schema. Names: `status`, `check`, `policy`, `preview`, `sessions`, `error` for the envelope whose `command` is `null`, and `policy-file` for `gsd-cli.config.json` itself. An unknown name is a usage error.

**`preview`** payload:

```json
{
  "project": "/abs/path",
  "workflow": "plan", "runtime": "claude", "level": "medium",
  "complete": true,
  "session": { "model": "claude-opus-5-5", "effort": "medium",
               "permissions": "normal", "argv": ["claude", "--model", "..."], "forwarded": [] },
  "reviewers": [ { "name": "astra-review", "cli": "codex", "model": "gpt-6-astra", "effort": "high" } ],
  "installation": { "runtime": "claude", "directory": "...", "installed": "1.21.0",
                    "minimum": "1.21.0", "ok": true, "message": "meets the project minimum" },
  "agents": [ {
      "agent": "gsd-planner", "phase": "planning", "in_workflow": true,
      "expected": { "model": "opus", "effort": "high",
                    "model_source": "models.planning=opus",
                    "effort_source": "effort.agent_overrides.gsd-planner" },
      "resolved": { "model": "opus", "effort": "high", "effort_effective": "high",
                    "effort_effective_source": "frontmatter", "effort_rendered": "high",
                    "effort_clamped": false, "...": "rest of the resolver row" },
      "check": "ok",
      "findings": []
  } ],
  "gsd_context": { "source": "...", "workstream": "", "loader_differences": [] },
  "pending_capture": [],
  "diagnostics": [],
  "config": { }
}
```

- `session.permissions` is what the launch would request after `--secure` is applied: `bypass` or `normal`.
- The example is illustrative for `resolved` and exhaustive for everything else.
- `agents` lists every registered or configured agent, the same set as today's `--details` report. `in_workflow` marks those the compact report would show. `phase` is `"unknown"` without catalog metadata.
- `resolved` is the installed GSD resolver's row passed through unchanged, or `null` when it returned none. The row comes from third-party GSD and can grow, so its schema requires the keys `resolver.validate_result` already checks and allows additional ones.
- `check` is `ok`, `mismatch` or `unknown`, mapped from `preview.compare`'s `OK` / `NOT OK` / `UNKNOWN`. The comparison logic is reused, never reimplemented.
- `findings` replaces prose notes with `{code, severity, message}` items so a consumer never parses wording. `severity` is `mismatch`, `unknown` or `note`. Codes, one per branch of `preview.compare`:
  - mismatch: `model_mismatch`, `effort_mismatch`, `effort_clamped`, `installed_effort_mismatch`
  - unknown: `model_unknown`, `effort_unknown`, `forwarded_may_override`, `installed_effort_unknown`, `inherit_depends_on_forwarded`, `propagation_unknown`, `unregistered_agent`
  - note: `alias_equivalent`, `inherits_session_effort`

  `compare` therefore has to return structured findings; the text renderers keep printing the same messages. **Effort drift** is exactly a finding with code `installed_effort_mismatch`.
- `gsd_context` carries what `--details` prints about the GSD loader: its config source, the active workstream, and the paths where GSD's loaded config differs from the launcher's. It is `null` when inspection did not get that far.
- `config` is the launcher's effective configuration, as printed by `--details`. With these fields the JSON carries everything `--details` shows.
- An incomplete inspection gives exit 1, `ok: false`, the full `data`, and `error.kind: "incomplete"`.
- `--json` requires `--config` (usage error otherwise, and nothing is launched). `--json` with `--details` is a usage error: JSON is always complete.

**`sessions`** payload:

```json
{
  "project": "/abs/path",
  "resolver_available": true,
  "sessions": [ {
      "runtime": "claude", "run_id": "...", "kind": "session", "cwd": "...",
      "start": "2026-11-16T07:58:00Z", "end": "2026-11-16T08:40:00Z",
      "model": "claude-opus-5-5", "effort": "medium", "effort_varied": false,
      "advisor": null, "agent_type": null,
      "requested_model": null, "requested_effort": null,
      "resumed": false, "cleared": false,
      "marks": ["! profile expects claude-fable-5-2"], "mismatch": true,
      "launch": { "time": "...", "profile": "exec/medium", "workflow": "exec", "level": "medium",
                  "session_model": "...", "session_effort": "...", "forwarded_args": [] },
      "children": [ ]
  } ],
  "older": [ ]
}
```

- Default: `sessions` holds the newest three, fully loaded with children and checked, as the text command does. `older` is empty.
- `--pick N --json`: `sessions` holds that one older session.
- `--pick --json` without a number: `sessions` is empty and `older` lists the older top-level sessions without children, in the same order and numbering the text listing uses (index 0 is pick 1). It never prompts.
- `marks` are the existing human-readable marks. `mismatch` is true when any mark starts with `!`. `kind` is `session`, `agent` or `reviewer`; children nest recursively.
- `launch` is a summary and omits the embedded `config`, `policy` and `gsd_defaults`. It is `null` when no launch record matched.
- No sessions found is success with empty lists.

### A non-mutating resolver for `sessions`

`sessions` compares what each agent ran with what installed GSD would have resolved for it. Today it gets that by running the installed `gsd-tools.cjs query resolve-model`, always from `~/.claude/gsd-core`. `gsd_cli/resolver.py` avoids that tool on purpose, because its bootstrap can build or repair the installed library even for a query. A skill that runs `sessions --json` unprompted must not be able to change the global install, so this work removes the exception:

- `sessions` resolves expectations through the same bridge the preview uses (`gsd_cli/data/preview-resolver.cjs`), which loads GSD's resolver modules directly and never runs `gsd-tools.cjs`.
- It uses the installation selected for the launch's runtime by the existing rules (`versions.installation_dir`: environment override, then project-local, then home), not a hard-coded Claude path.
- It does not enforce `gsd.min_version`: reading history must work with an old install. When Node or the installation's resolver modules are missing, the comparison is skipped and reported as unavailable, as today.
- This changes text-mode `sessions` too and lands as its own commit, before the JSON work for `sessions`.

### Reserved names

`policy` and `schema` become built-in command names. Policy validation adds them to the reserved workflow names, and `main()` adds them to the commands that reject forwarding after `--`. The reserved list is defined once and used by both. A project that already has a workflow named `policy` or `schema` will fail validation with the existing "reserved or invalid workflow name" message; this goes in the changelog as a breaking note.

### Schemas

- **One source of truth.** A module of Pydantic v2 models (for example `gsd_cli/models.py`) defines the envelope and each payload. Commands construct the model and print `model_dump_json`; `gsd-cli schema NAME` prints `model_json_schema()` for the matching model. Output and schema cannot drift, because both come from the same class. No schema files are written by hand or shipped as package data.
- Each output schema describes the whole envelope for that command, including the error shape. The envelope is a generic model parameterized by the payload, so `command` is a fixed literal per schema.
- Pydantic generates JSON Schema draft 2020-12 with `$defs` and local `$ref`, which covers the recursively nested session `children`.
- Models forbid unknown fields (`extra='forbid'`), so a payload cannot gain an undocumented key. The exceptions are the pass-through parts that this tool does not own: the resolver row in `agents[].resolved` (required keys typed, extras allowed) and the free-form `config` and `policy` objects.
- Enumerated values (`command`, error `kind`, check `reason`, agent `check`, finding `code` and `severity`, run `kind`) are `Literal` types, so they appear as enums in the schema.
- `policy-file` is a Pydantic model of `gsd-cli.config.json` used only to generate its schema: required keys, enums for levels, efforts, phases, permissions and adapters, the `gsd-…` agent-name pattern, the workflow-name pattern. It does not replace `policy.validate`, which stays the only validator the launcher uses and the only place cross-references are checked (a group naming a declared reviewer, a workflow naming a declared group, non-overlapping tasks). The schema's description says so. Its enums are built from the constants in `gsd_cli/policy.py`, not retyped.

### Documentation

A new user-guide page on machine-readable output (added to the MkDocs nav) covering the envelope, each payload, error kinds, the `schema` command and how to map `policy-file` in an editor. Updates to `README.md`, `docs/LAUNCHER.md`, `docs/checks.md`, the command list and the dependency rule in `AGENTS.md`, CLI help, and an Unreleased changelog entry that also names the new Pydantic dependency. `pyproject.toml` gains `pydantic>=2,<3`; install instructions that mention Click alone are updated.

### Testing

Offline `unittest`, in the style of the existing suite (subprocess runs of the launcher in temporary projects with fabricated installs and logs):

- Every JSON command's real output, captured from a subprocess run, parses back into its model with `model_validate_json` in strict mode, for success and for each reachable error kind.
- `gsd-cli schema NAME` prints valid JSON equal to the model's `model_json_schema()` for every name.
- The shipped starter policy and `examples/gsd-config-example.json` validate against the `policy-file` model, and policies that `policy.validate` rejects for structural reasons are rejected by the model too. The model's enums equal the constants in `gsd_cli/policy.py`.
- Exit codes and text output of existing invocations are unchanged.
- JSON mode is read-only: no working config, baseline, journal, lock or launch-log change, including with a pending journal.
- stdout is exactly one JSON document; no ANSI; hostile model names and paths stay inside JSON strings.
- `--json` after `--` is a child argument and does not switch modes. `--json` without `--config` on a workflow never launches.
- Session JSON omits embedded configs; `--pick --json` never reads stdin.
- `policy` and `schema` are rejected as workflow names; `schema` works outside a project.
- `sessions` never executes the installed `gsd-tools.cjs`, in text or JSON mode, and resolves against a project-local or overridden installation when one is selected.

## Wave 2: the skill

### Packaging

A third plugin in the marketplace, following its existing conventions (`README.md`, `RELEASING.md`, `scripts/validate.py`):

```
plugins/gsd-cli/
  .claude-plugin/plugin.json        # name gsd-cli, version 0.1.0
  CHANGELOG.md                      # [0.1.0] section, hand-built first release
  README.md
  PRIVACY.md
  skills/gsd-cli/
    SKILL.md
    references/
      commands.md                   # which command answers what; envelope; error kinds
      policy-editing.md             # policy structure, invariants, edit recipes
      troubleshooting.md            # failure → cause → fix
```

Plus the marketplace entry, the plugin table in the root `README.md`, and an Unreleased entry in the root `CHANGELOG.md`. Tagging, the marketplace version bump and pushing follow `RELEASING.md` and are the maintainer's steps.

`PRIVACY.md` differs from the other plugins in one fact: the skill instructs Claude to run the locally installed `gsd-cli`. The plugin itself still ships no code, hooks or network calls.

### Behaviour

`SKILL.md` stays short: when to use it, the rules, a table from question to command, and pointers to the references. The description triggers on gsd-cli, `gsd-cli.config.json`, workflow presets, model/effort routing for GSD agents, reviewer groups, GSD version checks and "which model did my session use".

Rules the skill states:

1. **Probe first.** Run `gsd-cli schema`. If it fails, the installed gsd-cli predates JSON output: say so and stop, rather than parsing text.
2. **Read through JSON.** Use `--json` for every read; fetch a schema with `gsd-cli schema NAME` only when a field's meaning is unclear.
3. **Never launch.** Do not run `gsd-cli WORKFLOW RUNTIME` without `--config`.
4. **Never touch global agents.** Report effort drift (an agent with an `installed_effort_mismatch` finding) and name GSD's effort sync as the fix for the user to run.
5. **Edits are confirmed and validated.** For a policy change: show the intended change, edit `gsd-cli.config.json`, run `gsd-cli policy --json`. On failure show the error and offer to revert the edit. On success show the diff and run the relevant `--config --json` preview to confirm the effect. Never commit.
6. **`init` only on request.** It writes files; run it only when the user asks or after they confirm.

Question-to-command map:

| The user wants | Command |
|---|---|
| Current settings, pending recovery | `status --json` |
| Policy, local customizations, drift from the starter | `policy --json` |
| Is my GSD install good enough | `check --json` |
| What a preset would launch; why an agent gets a model or effort; effort drift | `WORKFLOW RUNTIME [LEVEL] --config --json` |
| What recent sessions actually ran, mismatches, which preset this session came from | `sessions --json` |

`policy-editing.md` carries the invariants an editor must respect, taken from `AGENTS.md` and `policy.validate`: Claude agent models are aliases while Codex agent models are full IDs; `agent_levels` are runtime-independent levels; every workflow names a reviewer group per runtime; workflow tasks and task levels do not overlap; permissions are explicit; Claude planning never gets a bypass. It includes recipes for the common edits: pin an agent's level, set an agent's effort, add a reviewer and put it in a group, add a custom workflow, raise `gsd.min_version`.

`troubleshooting.md` maps each error kind, check `reason` and finding code to a cause and a fix: below minimum, incomplete install, missing policy (run `init`), reserved workflow name, missing Node for the resolver, billing-guard environment variables, pending recovery.

### Testing

`python3 scripts/validate.py` passes. The marketplace has no evaluation harness and this work does not add one. Behaviour gets a one-off acceptance run by the implementer: a fresh agent with only the skill loaded, in a temporary GSD project, is given each prompt below and its transcript is checked against the rules. The outcome of each goes in the pull request description. The run needs Node and a real GSD install, and wave 1's gsd-cli installed from its branch (`python -m pip install -e`); it does not need wave 1 to be released.

Releasing is the maintainer's step in both repositories. Wave 1 is a feature release with one breaking note (the reserved names), expected as 2.1.0. The plugin's README names the first gsd-cli release that contains JSON output as its requirement, and the plugin is published after that release.

- "Which model will the planner use in `plan claude high`, and why?"
- "Is my GSD install OK?" with an install below the minimum.
- "Pin gsd-code-fixer to the low level" — confirms, edits, validates, shows the diff, does not commit.
- The same edit with a deliberately invalid value — reports the validation error and offers to revert.
- "Start an exec session for me" — declines and gives the command to run.
- "Fix the effort drift" — reports the drift and names the command without running it.
- A gsd-cli without `schema` on PATH — stops at the probe.
- "Why can't I see my policy?" in a project without `gsd-cli.config.json` — explains the missing policy and asks before running `init`.

## Left to the builder

- Module layout for payload builders and whether the text renderers are rebuilt on top of them (not required; text output must not change).
- The exact wording of help text, error messages and documentation.
- Field ordering in output and JSON indentation (two-space).
- How the models are organized and named, and how the generic envelope is expressed.
- Skill prose, and how the references are split beyond the three files named.
