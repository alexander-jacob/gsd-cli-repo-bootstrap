# Runtime blueprints for gsd-cli

## Launch contract

Run `gsd-cli RUNTIME BLUEPRINT` to open Claude Code or Codex with an explicit bundle of session, phase and agent settings. A single session can move from planning into implementation. The operator invokes the GSD skills they need. Each worktree serves one active session.

Each runtime declares its own nonempty set of named blueprints. The keys themselves define the choices. A missing or unknown name lists the available names for that runtime and exits before writes. A name such as `xhigh` only selects a blueprint. Each reasoning effort is configured separately. Normal launches use the runtime's existing full-permission flag. Preserve `--secure`, arguments forwarded after the first `--`, and the existing executable, project location, billing and GSD version checks.

## Policy

Use a new project policy schema version. Keep the explicit GSD minimum and initialization-only persistent GSD defaults. Under `runtimes.<runtime>`, define a single external review configuration and a `blueprints` object. The review configuration supplies reviewer definitions, active reviewers, effort per CLI adapter and the parallel review setting for every blueprint of that runtime. Reviewer names resolve within that configuration.

Each blueprint declares a session model and effort, and direct model and effort values for planning, discussion (`discuss`), research, execution and verification. Its optional `agents` map overrides the model, effort or both by agent name. There is no inheritance between blueprints. Here is one complete illustrative blueprint value under `runtimes.codex.blueprints.high`.

```json
{
  "session": {"model": "gpt-6-astra", "effort": "high"},
  "phases": {
    "planning": {"model": "gpt-6-astra", "effort": "high"},
    "discuss": {"model": "gpt-6.1-sol", "effort": "medium"},
    "research": {"model": "gpt-6.1-sol", "effort": "high"},
    "execution": {"model": "gpt-6-astra", "effort": "high"},
    "verification": {"model": "gpt-6.1-sol", "effort": "high"}
  },
  "agents": {
    "gsd-executor": {"effort": "xhigh"},
    "gsd-codebase-mapper": {"model": "gpt-6-luna", "effort": "medium"}
  }
}
```

Validate the entire policy when loading it, including required phase keys, nonempty overrides, runtime-appropriate models and effort syntax, and reviewer references. Keep Claude agent models as supported Agent-tool aliases and Codex models as full IDs. Session model IDs can differ from agent models. A blueprint name has no bearing on valid effort values. Installed role membership and catalog-dependent checks use the selected runtime's installation during launch preparation and preview.

The maintainer will convert existing project policies manually. A version-one policy gets an actionable format error without rewriting it. New initialization seeds the new format, with explicit runtime-local blueprints. Retain existing working-config preservation and Git migration for GSD files. Convert the shipped seed, example, CLI help, documentation, schemas and reports together. Preserve historical session log readability. New launch records identify the runtime and blueprint and snapshot the review configuration and policy.

### Proposed starter for review

Ship `low`, `medium` and `high` for each runtime. Projects can add `codex.xhigh` without adding a Claude counterpart. For each starter blueprint, use the current packaged runtime tier's session model and session effort. Thus the new stock `codex.high` session uses Astra at high effort. Use that tier's agent model and effort for the five phases. Materialize the current packaged named agent model and effort pins as direct values in each blueprint and preserve the current packaged reviewer selections per runtime. These choices define fresh-project defaults. The sample above illustrates customization.

For projects with an existing GSD working config but no launcher policy, seed the same starter and capture persistent unmanaged GSD settings as today. Keep the existing working file byte-for-byte on init. Conversion of old routing choices into named blueprints is manual. Init should tell the operator to review the starter before the first launch.

## Resolve the blueprint

Use the selected installation's agent catalog to find each role's registered phase. Apply phase settings, then the named agent's individual fields. Emit the resulting per-agent GSD model and effort overrides. This lets an arbitrary number of named blueprints use GSD's existing resolver. Keep unrelated GSD settings and continue retiring previously owned generated settings through synchronization. A role outside the five configured phases can be managed by supplying both fields explicitly. Otherwise leave it to GSD and make its coverage visible in preview. Report an explicitly configured role missing from the selected installation before starting a session.

The session model and effort become child CLI arguments. Codex uses its existing model and effort dispatch mechanism. Actual effort propagation depends on the runtime and its spawn tool. External reviewer settings come from the selected runtime. Represent requested settings, resolver output and available evidence separately in the existing read-only preview.

## Read-only checks and JSON schemas

- `gsd-cli check [claude|codex] [--json]` validates the project policy and checks the selected GSD installation against `gsd.min_version`. A blueprint argument is unnecessary. Omitting the runtime checks both and reports all results, including a failure alongside a pass. Keep installation selection, failure reasons, and text/JSON exit codes consistent with the launch version gate.
- `gsd-cli policy [--json]` validates every runtime and blueprint, including phase completeness, agent override syntax and reviewer references. Report errors at the offending policy path. A valid policy can be inspected without installing the AI CLIs. The JSON result includes differences from the shipped starter.
- `gsd-cli RUNTIME BLUEPRINT --config` checks the selected blueprint against the installed resolver. Compare configured model and effort with available evidence for each role. For Claude, identify the installed source and the prospective project definition so readers can tell which effort each supplies. Retain coded findings for mismatches, clamped effort and missing evidence. Keep the existing exit semantics: a completed comparison can report mismatches and exit zero; an incomplete resolver check exits nonzero and retains available results. Preserve `--details` and `--json` as alternative output formats.
- `status` reports saved configuration and pending recovery. `sessions` uses recorded launch expectations and available runtime evidence, including legacy records. All inspection commands stay read-only with respect to project files, recovery, agent ownership and launch logs.
- `gsd-cli schema` lists all seven published names: `status`, `check`, `policy`, `preview`, `sessions`, `error`, and `policy-file`. `schema NAME` works outside a project. Generate `policy-file` from the updated policy model; it describes runtime-local blueprint names, required phases, direct models and efforts, partial agent overrides, and per-runtime reviewers. The domain validator enforces cross-references and other rules beyond the structural schema. `schema policy` describes the command's response envelope. Update the preview and session payload models to represent runtime-specific blueprint names and the documented evidence. Keep policy-file and output-envelope versioning independent and version incompatible output changes according to the published JSON contract.

## Approaches for Claude agent effort

1. **Project-local definitions (chosen).** Generate complete files under the project's `.claude/agents/` before a Claude launch. Claude Code gives a project definition precedence over a user definition of the same name. The operator can inspect the active files and accepts one session per worktree.
2. **Session-scoped definitions.** Claude's `--agents` can provide a complete definition for a single launch. This offers per-session isolation, but the installed interactive CLI requires inline JSON. The 36 installed agent prompts measured about 750 KB, above the measured 128 KiB single-argument limit on the development machine. Smaller sets may fit.

Project JSON alone did not set effective Claude effort in the installed resolver checks. A requested executor effort of `low` still reported `high` from its installed Markdown header. Codex resolved the executor's Astra model at `xhigh` and a verifier's Sol model at `medium` in disposable projects. These are configuration and resolver observations. Verification of a real project-local definition must use Claude's project-scope discovery as well as GSD's resolver, which may inspect a different agent directory.

## Generate, refresh and clean up

1. On a mutating Claude launch, read pristine agent files from the selected Claude GSD installation. The usual source is `~/.claude/agents/`. Respect explicit and project-local installation selection. If source and destination coincide, protect the originals and report the collision before writing. Preserve the entire installed definition, including prompt body, tools, hooks, comments, restrictions and other frontmatter. Change only the top-level `model` and `effort` fields. Verify the source identity and reject ambiguous definitions before writing.
2. Compute every desired destination and compare it with a private per-worktree ownership record. Record exact paths and a digest of the last generated contents. Preflight the complete set. A user-owned file, conflicting agent identity, edited generated file or unsafe filesystem path gets a path-specific diagnostic before replacements or deletions. Hand-written agents remain available and trackable in Git.
3. Create missing desired files and refresh changed files from current upstream sources. Removing a named effort override regenerates a phase-covered role with its phase effort. When a role leaves the desired set, delete its previously generated file only if ownership and contents still match. A missing, previously owned file can be recreated if desired or forgotten if obsolete. An explicit reference to an upstream role that disappeared blocks preparation until the policy is corrected. Never sweep the directory by filename pattern.
4. Include creation, replacement, removal, and ownership changes in the existing locked, recoverable launch transaction. Support absence as a before/after state and compare all preconditions before recovery. Perform writes only for changed content. Git exclusions must cover generated files without hiding user-authored agents. Regeneration follows GSD updates on the next launcher invocation; starting Claude directly uses the last prepared definitions.
5. Normal Codex preparation leaves Claude files alone. A pending interrupted Claude transaction must be handled consistently with existing journal rules. Preview shows prospective creates, updates, removals and conflicts using the same calculation. It leaves project files, ownership, index, and logs untouched.

## README and user documentation

Update the root `README.md` quick start to show initialization, preview and launch with an explicit runtime and blueprint. Show how to discover valid blueprint names and where to edit them. In `docs/index.md`, `docs/solution.md`, `docs/LAUNCHER.md` and `docs/configuration.md`, align the command reference and policy examples with the shipped starter. Explain session, phase and per-agent settings, per-runtime reviewers, permission defaults, and how Claude agent files are generated, refreshed, ignored and safely removed.

Update `docs/checks.md`, `docs/json-output.md` and `docs/best-practices.md` with current preview commands, output fields and advice for one active session per worktree. Update `MIGRATION.md` with an old-to-new command example and the manual policy conversion steps. Label historical syntax wherever it helps explain conversion.

## Acceptance

- A Codex-only `xhigh` blueprint is selectable. Missing names and incomplete policies fail before project writes. Each session gets the selected runtime's reviewer configuration.
- Two launches with different blueprints in one worktree produce the expected model and effort for an executor, a verifier and a named exception. The installed model resolver confirms routing. Preview identifies any mismatch or lack of runtime evidence.
- After an upstream prompt or tool change, a fresh Claude launch carries it into the project copy. After an override removal, the file reverts to its phase values. After role removal, only an unmodified stale owned file disappears. A manually edited copy or same-name user file survives with a diagnostic. An unrelated agent remains Git-trackable.
- Simulate interrupted update and deletion, retry after a conflict, repeated identical launches and read-only previews using temporary projects and Git indexes. Tests must use offline fixtures and stub runtimes. Check installed resolver and CLI discovery separately without paid model calls.
- Existing diagnostics, subscription checks, unmanaged config capture and generation of JSON schemas continue to work. Historical logs still display the workflow/profile recorded at the time.
- Exercise single- and dual-runtime installation checks, including mixed pass/fail output. Test valid and invalid blueprint policies, preview matches, mismatches, clamped effort, missing evidence and incomplete results. Verify that inspections leave project state and launch history untouched. Enumerate and generate all seven schemas outside a project. Check real CLI JSON responses against their corresponding schemas using offline fixtures, including success, failure-with-data and usage errors. Check the starter and complete example against both the policy-file schema and domain validator.
- Verify the README quick start and documented preview against a temporary initialized project with offline fixtures. Check the policy example against the shipped schema, compare JSON examples with the CLI output, and build the published guides with `mkdocs build --strict`.

The builder can choose the ownership metadata layout, frontmatter editing technique and journal encoding within those constraints. Project-local generation belongs in the launcher. Installation changes, automatic policy conversion, publishing and a session-lifetime lock are outside this design.
