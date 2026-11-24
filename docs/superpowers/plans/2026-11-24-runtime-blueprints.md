# Runtime Blueprints Implementation Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task by task. Mark completed steps with the checkboxes.

**Goal** — Launch one explicitly named blueprint for Claude or Codex, with predictable model and effort settings and safe project-local Claude agent updates.

**Architecture** — Validate the complete project policy offline. Expand the chosen blueprint against the selected installation's role catalog. Feed one preparation calculation into the read-only preview and the journaled writer. Save enough evidence at launch to explain the session after the project policy changes.

**Tech stack** — POSIX, Python 3.10/3.11, Click, Pydantic, package resources, Git, the installed Node resolver, unittest-style tests under pytest-xdist, and MkDocs.

**Spec** — [Runtime blueprint design](../specs/2026-11-24-runtime-blueprints-design.md). Tasks are ordered for one feature branch; the public CLI switches over once the underlying pieces are ready.

## Global constraints

- The public syntax is `gsd-cli RUNTIME BLUEPRINT`. Each runtime defines its own names. Every launch requires a name. Full permissions are the default, with `--secure` available. The first literal `--` still separates child arguments.
- Only the explicitly selected GSD installation supplies launch data. Enforce `gsd.min_version` before capture, recovery or project writes. Keep `init`, `policy`, `schema`, `status` and installation diagnostics usable under their existing offline contracts.
- Keep Click at the boundary, Pydantic for machine-readable models and schemas, and runtime dependencies limited to Click, Pydantic and the standard library. Use `python -m pytest -n auto` even for one test. Use temporary projects, real Git indexes and fake CLI binaries for automated tests.
- Manual conversion of old policy is the maintainer's choice. Preserve working config during init, unmanaged GSD settings, historic launch logs, project-owned agents, and upstream agent files. Keep preview free of project, Git-index and launch-log writes.
- One active session per worktree. Keep the existing short preparation lock. This plan ends at local verification; releases, installs into the user's runtime, tags and pushes are separate operations.

## Review focus

1. An override removed from one blueprint can still be supplied by its phase. Distinguish regeneration from deletion (tasks 2, 4, 5).
2. Ownership is runtime-specific and can expand after a catalog update. A fresh checkout may have shared defaults but no baseline, and init can run without either installation (task 3).
3. Same-name author files, tracked-but-locally-missing files, nested agent identities and coincident install/project paths must survive reconciliation (tasks 4, 5).
4. A crash between unlinking an obsolete file and replacing metadata must be replayable. An external edit while recovery is pending must survive (task 5).
5. Projected Claude frontmatter, installed resolver evidence and actual historical child events may disagree. Preserve all three sources and identify missing evidence (tasks 7, 8).

## Files and boundaries

| Area | Files | Responsibility |
|---|---|---|
| Policy | `gsd_cli/policy.py`, `gsd_cli/policy_model.py`, `gsd_cli/data/default-config.json`, `examples/gsd-config-example.json` | Runtime-local names, structural schema, domain validation and shared starter |
| Catalog and routing | `gsd_cli/resolver.py`, `gsd_cli/policy.py` | Installed catalog, phase lookup, explicit GSD overrides |
| Project state | `gsd_cli/config.py`, new `gsd_cli/claude_agents.py` | Three-way capture, agent definitions, ownership, ignore rules, locking and recovery |
| Public surfaces | `gsd_cli/cli.py`, `gsd_cli/preview.py`, `gsd_cli/models.py`, `gsd_cli/sessions.py` | Dispatch, read-only checks, JSON contracts and history |
| Verification and guides | Existing `tests/` fixtures and suites, new `tests/test_claude_agents.py`, `pyproject.toml`, README, migration guide, published docs, `AGENTS.md` | Offline regression tests, schema validation, operator and contributor guidance |

## Task 1 — Define and validate the version-two policy

**Files** — Policy files above, `tests/test_policy.py`, `tests/test_policy_model.py`. **Interface** — Keep `load_default() -> dict` and `validate(p: dict) -> None`. `PolicyFile` describes the input file independently of the output envelope.

- [x] Add failing policy and schema tests. In `test_runtime_local_names`, copy only Codex's high blueprint to `xhigh`; assert `validate(p) is None` and `"xhigh" not in p["runtimes"]["claude"]["blueprints"]`. Reject an empty blueprint map, missing verification phase, empty agent override, invalid Claude agent alias, unknown reviewer reference and a version-one file. Assert the domain error identifies the offending path. Test an inactive blueprint as well as the selected one.
- [x] Run `python -m pytest -n auto tests/test_policy.py tests/test_policy_model.py`. Confirm failures exercise the fixed tier/workflow schema. Replace old workflow-specific policy assertions with their blueprint equivalents in tasks 1 and 2; keep independent validation regressions.
- [x] Define policy version 2 with `runtimes.<rt>.blueprints.<name>.{session,phases,agents?}` per the spec. Use `runtimes.<rt>.review.{reviewer_instances,default_reviewers,effort,parallel_lanes}` so review settings map directly to GSD. Keep reviewer adapter IDs and validation rules. Require both runtime sections; validate nonempty, CLI-selectable blueprint names without enumerating them. An override must contain at least one of model and effort. For the first implementation, accept explicit low/medium/high/xhigh for Codex sessions and agents. Use the documented Claude CLI effort vocabulary supported by the selected release for Claude sessions and agents; check the installed host’s advertised effort and report any model-specific clamping or unavailable evidence in preview. Keep the reviewer adapter effort rules independent. A JSON blueprint key such as `careful` or `xhigh` is valid without joining the effort vocabulary.
- [x] Seed both runtimes with current low/medium/high session models and efforts, apply each tier's agent model and effort to each phase, and translate current named model/effort pins into direct overrides. Preserve reviewer selections and compact-content seed. Check byte-equivalent example and seed, schema acceptance, and explicit `codex.high.session.effort == "high"`. Rerun the two suites, then commit `Define runtime-local blueprint policy`.

## Task 2 — Expand phases and individual overrides through the installed catalog

**Files** — `gsd_cli/policy.py`, `gsd_cli/resolver.py`, `tests/test_policy.py`, `tests/test_resolver.py`, `tests/resolver_fixtures.py`. **Interfaces** — `load_catalog(installation: Path) -> dict` returns the validated installed manifest. `resolve(p: dict, runtime: str, blueprint: str, catalog: dict) -> dict` returns session `model`, `effort`, selected `reviewers`, GSD tuple-path `values` and `agents` keyed by role with model, effort, phase and the policy path supplying each field.

- [x] Add `test_executor_inherits_only_missing_fields`. With the spec example assert `r["agents"]["gsd-executor"]["model"] == "gpt-6-astra"`, its effort is `xhigh`, and removing the named entry gives `high`. Test a model-only override, verifier called during execution, explicit unknown role, uncovered catalog role and both-field override for an unclassified role.
- [x] Run `python -m pytest -n auto tests/test_policy.py tests/test_resolver.py`; confirm failure on the new selection interface.
- [x] Extract the catalog reader already inside `inspect`. Use each role's registered `phaseType`. Emit `model_overrides.<role>` and `effort.agent_overrides.<role>` plus the selected review settings. Keep the runtime selection in the child environment and resolve reviewer adapter billing from the v2 policy. Retire any old generated provider, tier-map or phase keys using the previous ownership metadata when switching from legacy state. Carry uncovered roles into reporting without claiming ownership. A partial override without a phase to supply the missing field gets a path-specific error. Preserve selected-install failure behavior. Extend fixtures to supply every role explicitly named by the policy under test, with separate tests for missing roles.
- [x] Rerun both suites; verify effective values match the fixture's installed query output. Commit `Resolve blueprint phase settings into GSD agent overrides`.

## Task 3 — Initialize and capture settings without a fixed ownership set

**Files** — `gsd_cli/config.py`, `tests/test_config.py`, `tests/test_gsd_cli.py`. **Interfaces** — Preserve `initialize(root: Path) -> None`. Update `prepare(default, working, state, resolved)` and `load_state` to read existing state and compute the active policy's owned paths. Keep the existing per-key three-way merge.

- [x] Extend `test_init_preserves_working_and_repeated_policy`: assert byte-identical working config, installation-independent init, starter v2, custom unmanaged siblings retained and no automatic conversion of a v1 policy. Test switching between two runtime catalogs and a fresh checkout containing only policy and defaults. The previous launch's generated keys must disappear without entering the tracked defaults.
- [x] Run `python -m pytest -n auto tests/test_config.py`; confirm init currently assumes one workflow represents all ownership.
- [x] Replace init's call to resolve an arbitrary workflow. At init, separate known legacy generated paths, explicit blueprint pins and reviewer paths from unmanaged settings. Use available catalog metadata only when present; retain unclassified pre-existing agent entries provisionally. Record which entries were seeded from the old working config. At first catalog-backed preparation, retire exactly the newly managed entries still matching that seed; conflicting subsequent edits receive path-specific diagnostics. Once the baseline is established, keep the existing prohibition on managed entries in hand-authored shared defaults. If a fresh checkout lacks provisional metadata, report an overlapping shared default for manual reconciliation. Keep the version-one *sync metadata and journal* readers even though v1 *policies* require manual conversion.
- [x] Test staged Git changes, nested ignore rules, missing baseline, removed pins, custom siblings and manual policy conversion with existing metadata. Run `python -m pytest -n auto tests/test_config.py` and commit `Preserve persistent settings across blueprint initialization and switches`.

## Task 4 — Calculate project-local Claude agent changes without writing

**Files** — New `gsd_cli/claude_agents.py`, new `tests/test_claude_agents.py`. **Interfaces** — `render_definition(source: bytes, name: str, model: str, effort: str) -> bytes`; `plan_agents(root: Path, installation: Path, agents: dict, owned: dict[str, str]) -> AgentPlan`. The returned plan contains original/desired bytes per changed path, the new SHA-256 ownership map, and per-role source/destination evidence.

- [x] Add `test_patch_preserves_full_definition`: compare the complete output with fixture bytes where only two top-level header lines differ. Include CRLF, nested hook keys, a quoted description, tool restrictions and a body containing a second `---`. Test absent model, missing effort, duplicate identity, duplicate relevant header keys, supported aliases, and missing or ambiguous source.
- [x] Run `python -m pytest -n auto tests/test_claude_agents.py`; confirm the missing renderer.
- [x] Resolve pristine sources relative to the selected bundle's runtime directory. Walk agent definitions for duplicate declared identities, including nested project files. Use line-preserving edits in the first Markdown frontmatter block and report ambiguous target syntax before writing. Reject source/destination aliasing, symlink ancestors or targets and tracked conflicting destinations (including an absent working file still in the index). Preserve byte content outside the two fields.
- [x] For every desired path: unowned existing destination is a collision; absent destination is a create; an owned destination matching its digest is eligible for refresh. Use binary reads and preserve encoding/newlines through journal replay as well as rendering. Retire an obsolete path only when its stored digest matches existing bytes. Missing obsolete files need only an ownership update. An edited owned file is a conflict. Test an upstream prompt update, named override removal falling back to phase effort, deleted upstream role, unrelated hand-written agent and zero changes on a second identical calculation. Rerun the agent suite and commit `Calculate owned Claude agent updates from installed definitions`.

## Task 5 — Journal config, ownership, ignore rules and agent deletions together

**Files** — `gsd_cli/config.py`, `gsd_cli/claude_agents.py`, `tests/test_config.py`, `tests/test_claude_agents.py`. **Interfaces** — Extend `transaction(root, contents, untrack=False)` and `recover(root)` to represent absent postimages. Extend `preview` and `synchronize` with the selected runtime and installation; both return the same prepared effective config, captured paths and agent change summary.

- [x] In `test_recover_partial_agent_removal`, interrupt after the first target operation, reopen and recover; assert both desired config and agent contents, final ownership, obsolete file absence and journal removal. Repeat with an external edit before recovery; assert the edited file survives and recovery fails before applying other targets. Run `python -m pytest -n auto tests/test_config.py tests/test_claude_agents.py` to see deletion/recovery fail.
- [x] Store `claude_agents` digests in private sync state. An older state without this field owns zero files. Codex preparations preserve that map. Run reconciliation inside the existing preparation lock after ordinary recovery. Extend the journal with before/after states for exact safe project-agent paths, retaining v1 replay and index migration. Validate all paths, ownership records and expected contents before replay, allow a validated delete or atomic replacement, fsync affected directories, and remove the journal last. Handle an absent destination directory on first launch without creating it in preview.
- [x] Ignore individual generated paths using a delimited block of exact root-relative paths in the existing project `.gitignore`. Recalculate that block within the transaction, preserve other bytes and validate effective Git rules against nested files. An ignore rule is never proof of ownership. Preserve any author changes outside the block and report conflicting edits inside it. Check a fresh checkout with committed ignore entries and no local ownership state.
- [x] Extend read-only input checks to cover catalog/source files, project agent identities, destination bytes, ignore rules and metadata. Exercise held-lock and pending-journal cases, double preparation, a concurrent source edit, invalid journal paths and a Codex launch with pending Claude recovery. Check `git check-ignore` for generated files and that an unrelated agent remains trackable. Rerun both suites and commit `Recover blueprint configuration and owned agent files together`.

## Task 6 — Switch Click dispatch, permission and billing preflight, and logging

**Files** — `gsd_cli/cli.py`, `gsd_cli/sessions.py`, `tests/test_gsd_cli.py`, `tests/test_versions.py`, `tests/resolver_fixtures.py`. **Interface** — Static runtime commands consume the explicit blueprint string and call tasks 2–5. Extend `record_launch(..., blueprint: str, ...)` to snapshot the review block, policy and effective config; retain the existing private log path and warning behavior.

- [x] Add `test_runtime_requires_its_own_blueprint` and replace fixed-tier dispatch assertions. Verify missing level lists valid names without writes, Codex-only `xhigh` succeeds for Codex and fails for Claude, and old workflow-first syntax points to the new form. Verify `--help` outside a project. Run `python -m pytest -n auto tests/test_gsd_cli.py tests/test_versions.py` and observe the old dispatch contract.
- [x] Replace dynamic workflow discovery with static Claude and Codex commands. Resolve the blueprint name from project policy after parsing help. Update `main`, `json_command`, forward-only handling and option exclusivity. Keep executable, billing, directory-switch and minimum-version guards before synchronization. Check billing through the selected review block's active adapter names. Apply automatic bypass for both runtimes, suppress with `--secure`. Keep the argument boundary, session model/effort flags, project cwd and `GSD_RUNTIME`.
- [x] Upgrade `GsdCliFixture.initialize` to install catalogs and pristine agent fixtures for launch tests, leaving no-install tests explicit. Test exact child argv, an old unrelated runtime, selected broken local install, missing binary, subscription guard, failed logging, old policy, and v2 launch snapshots through the subprocess wrapper. Retain independent `check`, `policy`, `schema`, `sessions` and `status` commands. Rerun suites and commit `Launch the explicit runtime blueprint`.

## Task 7 — Show blueprint evidence and preserve session history

**Files** — `gsd_cli/{cli,models,preview,resolver,sessions}.py`, `tests/{test_preview,test_sessions,test_json_output}.py`, `tests/session_fixtures.py`. **Interfaces** — Preview payload identifies `runtime` and `blueprint: str`, includes per-role source/evidence and prospective owned file actions. `LaunchSummary` exposes optional `blueprint` alongside historical workflow/profile fields.

- [x] Add `test_preview_distinguishes_installed_from_project_effort`: installed executor says high, prospective project executor says low, CLI JSON names both sources and the planned update. No project bytes, lock, index or launch log change. In historical fixtures assert a v2 launch uses its own captured reviewer definitions even after switching blueprints; include v1 and pre-workflow records and overlapping adapter names. Run `python -m pytest -n auto tests/test_preview.py tests/test_sessions.py tests/test_json_output.py` and observe the old payload.
- [x] Replace workflow-phase filtering with covered/uncovered catalog roles and identify whether phase or agent supplied each value. Carry the agent plan into text, details and JSON. Expose creates, updates, removals and path-specific conflicts (diagnostic on failed preparation). Keep installed resolver evidence separate from prospective project evidence, session args and observed logs. Use the disposable resolver bridge, preserve workstream overlay and incomplete-result semantics. If catalog inspection fails, report known session/reviewer details and the failure, without fabricating agent settings. Keep known mismatches, clamping and unknown findings distinguishable.
- [x] Update session reading/rendering to recognize new records by blueprint and old records by their existing shape. Use captured review and effective config for expectations, retain model/effort evidence from the logs, and preserve the oldest historical mapping only for records lacking snapshots. Make output JSON contract version 2 for the incompatible payload changes; keep the input policy version separately defined. Rerun the three suites and commit `Report blueprint evidence in previews and session history`.

## Task 8 — Verify all check functions, schemas and the installed-runtime boundary

**Files** — `tests/{test_json_output,test_policy_model,test_preview,test_resolver,test_gsd_cli}.py`, `pyproject.toml` (test extra). **Interface** — Exercise the seven existing schema names and actual emitted envelopes via the CLI rather than a hand-built model instance.

- [x] Declare `jsonschema` in the test extra and install that extra in the test venv. Add `test_cli_documents_validate_against_published_schemas`. Load each `schema NAME` from outside a project. Use `jsonschema.Draft202012Validator.check_schema(schema)` and `validator.validate(payload)` on real CLI success and failure fixtures, including a mixed-result installation check, a usage error, and a preview with incomplete evidence. Validate the starter and example with both the domain validator and `policy-file`. Run `python -m pytest -n auto tests/test_json_output.py tests/test_policy_model.py` and confirm the new assertions exercise the emitted version and shape.
- [x] Cover all seven names, parity of text and JSON exit codes, legacy version diagnostics, template-only fields, invalid partial overrides, held lock and no journal replay. Test `check` without Node or AI executables. Use both CLI and direct-domain fixtures for read-only snapshot equality.
- [x] Run the installed compatibility smoke in a disposable project using real selected bundles when available. Run installed `query resolve-model gsd-executor` and `query resolve-execution gsd-executor --host RUNTIME` with the prepared config. Verify each against configured model/effort and its source. For Claude also inspect the CLI's project agent discovery in that worktree with a pristine user definition and a distinct project model/effort. Use a supported local inspection surface (for example the agent library in versions providing it); record CLI version, chosen definition and evidence available. If the CLI cannot expose a field without a model call, report it unverified. Never substitute GSD's global-frontmatter result as proof of Claude's project selection.
- [x] Run `python -m pytest -n auto tests` on 3.10 and 3.11; expect the whole suite green. Commit `Verify blueprint diagnostics and published schemas`.

## Task 9 — Update user guides and exercise the quick start

**Files** — `README.md`, `MIGRATION.md`, `docs/{index,solution,configuration,LAUNCHER,checks,json-output,best-practices}.md`, `AGENTS.md`; use existing CI in `.github/workflows/{tests,docs}.yml`. **Interface** — Examples must execute against the shipped policy and the same schemas checked in task 8.

- [x] Inventory old examples with `rg -n 'gsd-cli (plan|exec)|WORKFLOW RUNTIME|default.*medium' README.md MIGRATION.md AGENTS.md docs/*.md`. Label intended historical examples in the migration guide. Rewrite the quick start to initialize, discover names by issuing a runtime without a blueprint, preview, and launch; include forwarding, permissions, ownership, cleanup, conflict resolution and manual v1 conversion. Update the project instructions that still describe retired commands and permission exceptions.
- [x] Refresh the check sequence and JSON samples from fixture-backed commands. In a temporary project run the README's init, policy, check, blueprint preview, and both runtime launches with the existing fake child executables. Assert the recorded model and effort for the sample executor/verifier and verify generated files with `git check-ignore`. Confirm historical logs still render. Smoke-test the installed package outside the checkout using the procedure in the existing test workflow.
- [x] Run `mkdocs build --strict` and rerun the old-example search. Expect a clean build and only deliberately historical matches. Run `python -m pytest -n auto tests` and `git diff --check`. Commit `Document runtime blueprints and manual policy conversion`.

## Completion evidence

Record the Python versions and full suite results, schema validation results, MkDocs build result, scratch-project launch/cleanup observations, and separate installed Claude/Codex resolver and discovery evidence. Identify any unverified runtime behavior explicitly before treating the implementation as complete.
