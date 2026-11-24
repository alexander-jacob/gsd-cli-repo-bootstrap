# Installation, migration and first use

This walkthrough replaces the legacy single-file launcher and initializes the
packaged launcher in an existing GSD project. Run the steps one at a time.
You need Python 3.10+, Linux/macOS, and an existing `.planning/` directory.
The launcher does not create GSD requirements or a roadmap.

## 1. Install the packaged launcher

If `pipx list` already shows `gsd-workflow-cli` and `gsd-cli --help` lists
`claude` and `codex` launch commands, installation is complete: continue with step 2.

If pipx is missing and uv is installed:

```sh
uv tool install pipx
```

Otherwise follow the [pipx installation instructions](https://pipx.pypa.io/stable/installation/).

Inspect the existing command before replacing it:

```sh
command -v gsd-cli
ls -l "$HOME/.local/bin/gsd-cli"
head -6 "$HOME/.local/bin/gsd-cli"
```

The legacy copy is a regular Python script whose opening docstring says
`GSD Core CLI launcher: subscription-backed model and reviewer profiles.`
If this is the file you found, back it up:

```sh
mkdir -p "$HOME/.local/state/gsd-cli/backups"
mv "$HOME/.local/bin/gsd-cli" \
  "$HOME/.local/state/gsd-cli/backups/gsd-cli-$(date +%Y%m%d-%H%M%S)"
```

Skip the backup when no old launcher exists. If the command is a symlink or
another application, identify its owner before replacing it.

Install from the checkout containing the new `pyproject.toml` and `gsd_cli/`
package. If the changes are still on a feature branch, use that worktree rather
than an older main checkout. Replace the example path:

```sh
cd /path/to/gsd-cli-repo-bootstrap
pipx install .
hash -r

command -v gsd-cli
pipx list
gsd-cli --help
gsd-cli check --help
```

Help should list `init`, `status`, `sessions`, and `check`. Click is installed
inside the pipx environment; copying the source `gsd-cli` wrapper alone no
longer works.

For a later update, after confirming that pipx owns the command, run
`pipx install --force .` from the intended source checkout. This updates the
application without overwriting existing project policy.

## 2. Initialize your existing GSD project

Replace the project path, then inspect its current Git state:

```sh
cd /path/to/your/project
git status --short
ls -d .planning
git diff --cached -- .planning/config.json
```

If the working config has staged changes, commit or unstage those deliberately
before migration. A bare `.planning/` is sufficient. If your project already has a version-one policy, convert it before running init.

```sh
gsd-cli init
```

Initialization preserves the existing working config byte-for-byte and creates
the tracked policy/default files. It also adds ignore rules and, when necessary,
removes the working config from the Git index while leaving it on disk.

| File | Purpose | Git |
|---|---|---|
| `gsd-cli.config.json` | Runtime blueprints, efforts, reviewers, minimum GSD version | Track |
| `.planning/config.default.json` | Persistent GSD settings outside launcher ownership | Track |
| `.planning/config.json` | Effective configuration used by GSD | Ignore |
| `.planning/.gsd-cli-sync.json` | Local capture baseline and ownership metadata | Ignore |

The launcher generates the effective policy in the working config on the next
successful launch. `init` itself does not launch an AI CLI.

A fresh checkout of an already migrated project can contain just the tracked
policy and default. In that case, proceed to the check and preview commands; a successful launch
will recreate the local working config and baseline.

## 3. Review and commit the migration

```sh
git status --short
git diff -- .gitignore
cat gsd-cli.config.json
cat .planning/config.default.json

git add gsd-cli.config.json .planning/config.default.json .gitignore
git diff --cached
```

A staged deletion of `.planning/config.json` is expected if it was tracked:
it means Git will stop tracking it, not that the local file was deleted. Check
that the staged diff contains only what you intend to commit, including any
changes you had staged before migration.

```sh
git commit -m "Adopt project-owned GSD launcher configuration"
```

Initialization never commits automatically. If it reports an ignore-rule
conflict, reconcile the named rule and rerun init; avoid forcing ignored local
state into Git.

## Convert a version-one project policy

Historical version-one commands such as `gsd-cli plan codex high` and `gsd-cli exec claude low` combined a workflow, runtime and optional level. Version two requires a runtime and an explicit blueprint. Existing v1 policies are rejected with a conversion diagnostic. Renaming the version field alone leaves the previous policy shape invalid.

1. Save the v1 policy in Git or a backup. If the old launcher is still installed, capture its detailed preview for each combination you use before upgrading. For example, the historical command `gsd-cli plan claude high --config --details` shows the session request, per-agent resolver evidence and prospective config without launching a session. Use the [complete version-two example](examples/gsd-config-example.json) as a separate working copy. Preserve your project’s `gsd.min_version` and initialization-only `gsd_defaults`.
2. For each runtime, decide which former workflow/level combinations you actually use. Give each one a blueprint name under `runtimes.RUNTIME.blueprints`, for example `plan-high` or `exec-low`. Set its `session.model` from the previous runtime level and `session.effort` from the former effective session setting, including any workflow-specific adjustment.
3. For each of the five phases, first look for an explicit `workflows.<workflow>.task_levels.<phase>`. If absent and the phase appears in the workflow’s `tasks`, use the selected launch level. Otherwise use `phase_defaults.<phase>`. Look up `runtimes.<runtime>.<effective-level>.agent_model` and copy that value into the blueprint’s `phases.<phase>.model`. For each v1 `agent_levels` pin, look up the same runtime’s `agent_model` at the **pinned** level and place it in `agents.<role>.model`.

    Choose `phases.<phase>.effort` separately. The v1 Codex runtime tier map used each tier’s `session_effort` as its `reasoning_effort`. Workflow-specific session adjustments applied to the main CLI only. For Claude, v1 wrote no effort into the runtime tier map. Use the old detailed preview to inspect the resolver and installed agent frontmatter, then choose explicit v2 effort values for the phase and any roles that need exceptions. In either runtime, carry `agent_efforts.<role>` into `agents.<role>.effort`. Where requested and installed Claude effort differed, decide which value the generated project definition should request. Check each role against the selected catalog. An explicitly listed role without a recognized phase needs both model and effort.

4. Under each runtime's `review`, move the reviewer definitions into `reviewer_instances`, select the roster in `default_reviewers`, copy the per-adapter efforts into `effort`, and set `parallel_lanes`. Choose a single review configuration for all that runtime’s blueprints. Different old workflow rosters require an explicit project choice.
5. Remove retired workflow, tier, permission and reviewer-group fields. Set `schema_version` to `2` and save the complete file as `gsd-cli.config.json`. Update shell aliases and automation to pass the blueprint explicitly. Use `--secure` wherever you previously relied on normal permission prompts, including Claude planning.
6. Run `gsd-cli policy`, `gsd-cli check` and a preview for each blueprint you converted. Review model and effort provenance for representative agents before launching. Keep the local baseline and working config available so the launcher can retire paths it previously owned. Version-one launch logs remain readable through `gsd-cli sessions`.

For example, with the shipped v1 policy, the historical launch `gsd-cli plan claude high` used normal Claude permissions. If you named the converted blueprint `plan-high`, its equivalent launch is `gsd-cli claude plan-high --secure`. In the old high planning session, the execution phase still followed `phase_defaults.execution` (medium), so the converted Claude blueprint uses `opus` for that phase and `fable` for planning.

## Check, preview and launch

```sh
gsd-cli check
gsd-cli codex medium --secure --config
gsd-cli claude medium --secure --config
gsd-cli claude medium --secure
```

Use your converted names in place of `medium`. The starter requires GSD 1.21.0 or newer. Repair the exact installation named by a failed check, then rerun it. Explicit config-directory overrides take priority over project and global bundles. Only the selected runtime must pass to launch.

After a Claude launch, inspect the generated `.gitignore` changes and confirm an expected path, for example `git check-ignore .claude/agents/gsd-executor.md`. Commit shared ignore rules with the policy and default. The generated agent files are local. Preview the next launch before resolving an ownership or merge conflict. See [capture and recovery](docs/LAUNCHER.md#automatic-capture-and-recovery).
