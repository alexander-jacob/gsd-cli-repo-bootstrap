# Installation, migration and first use

This walkthrough replaces the legacy single-file launcher and initializes the
packaged launcher in an existing GSD project. Run the steps one at a time.
You need Python 3.10+, Linux/macOS, and an existing `.planning/config.json`.
The launcher does not create GSD requirements or a roadmap.

## 1. Install the packaged launcher

If `pipx list` already shows `gsd-workflow-cli` and `gsd-cli --help` lists
`check`, installation is complete: continue with step 2.

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
ls .planning/config.json
git diff --cached -- .planning/config.json
```

If the working config has staged changes, commit or unstage those deliberately
before migration. If `.planning/config.json` is absent and this project has
never been initialized with GSD, initialize GSD first.

```sh
gsd-cli init
```

Initialization preserves the existing working config byte-for-byte and creates
the tracked policy/default files. It also adds ignore rules and, when necessary,
removes the working config from the Git index while leaving it on disk.

| File | Purpose | Git |
|---|---|---|
| `gsd-cli.config.json` | Models, efforts, workflows, reviewers, minimum GSD version | Track |
| `.planning/config.default.json` | Persistent GSD settings outside launcher ownership | Track |
| `.planning/config.json` | Effective configuration used by GSD | Ignore |
| `.planning/.gsd-cli-sync.json` | Local capture baseline and ownership metadata | Ignore |

The launcher generates the effective policy in the working config on the next
successful workflow launch. `init` itself does not launch an AI CLI.

If a project policy already exists from before version checking was added,
add the following field to that complete JSON object, choosing the floor your
project requires, then retry. Do not replace the rest of the policy:

```json
"gsd": {
  "min_version": "1.20.1"
}
```

A fresh checkout of an already migrated project can contain just the tracked
policy and default. In that case, proceed to step 4; a successful workflow launch
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

## 4. Check and, if necessary, update GSD

```sh
gsd-cli check
```

The default minimum is `1.20.1`, an editable project requirement. The check
reports each runtime's installed version, required minimum and selected path.
An older, missing or invalid selected installation blocks that runtime's launch
before capture or other configuration writes.

For example, the installations inspected during development produced:

```text
PASS claude: GSD 1.20.1
FAIL codex: GSD 1.18.0
```

To update the Codex installation, open Codex directly from the project:

```sh
codex
```

Inside Codex, enter the skill invocation below; this is not a shell command:

```text
$gsd-update
```

Follow the update workflow and verify that it targets the installation reported
by `gsd-cli check`. Exit Codex, then rerun:

```sh
gsd-cli check codex
```

For Claude, use its GSD update command in a directly opened Claude session,
then run `gsd-cli check claude`. Only the runtime you launch must pass; an old
Codex installation does not prevent a passing Claude installation from opening.

`check` is offline and read-only. It does not update GSD or require either AI
CLI executable. Explicit `CLAUDE_CONFIG_DIR`/`CODEX_HOME` overrides take precedence
over project-local and global bundles; repair the reported installation rather
than assuming the global copy is selected.

## 5. Open your first workflow session

Preview the settings before opening the session:

```sh
gsd-cli plan claude --config
# Or: gsd-cli plan codex --config
```

This prints the prospective config and GSD's agent model/effort results, then
exits without starting a session or modifying project files. Node is required.
Scan the `Check` column: `OK` matches the available evidence, `NOT OK` identifies
a difference, and `UNKNOWN` means there is not enough evidence to compare.
Claude's installed effort can differ from policy; the report shows both values.
An `INCOMPLETE` report exits 1 and explains what could not be resolved. Review
the full behavior in [Configuration preview](docs/LAUNCHER.md#configuration-preview).

For planning with Claude:

```sh
gsd-cli plan claude
```

Or, once Codex's GSD version passes:

```sh
gsd-cli plan codex --secure
```

Both default to medium. The launcher configures and opens the runtime; it does
not invoke a GSD skill. Inside the session, run your usual GSD command for the
project's next action or phase.

Other examples:

```sh
gsd-cli plan claude high
gsd-cli exec codex medium --secure
gsd-cli exec claude low --secure
```

`--secure` retains normal runtime permission settings. Without it, the shipped
Codex planning and both execution presets bypass approval prompts; Claude
planning retains normal permissions. `--secure` does not bypass version checks.

Child CLI arguments go after `--`. Codex `-C`/`--cd` directory switches are
rejected: run the launcher from the destination project so configuration and
version checks refer to the same project.

## 6. Check configuration changes and Claude agent effort

After leaving a session:

```sh
gsd-cli status
git diff -- .planning/config.default.json
```

Persistent edits GSD makes to the working config are captured into the tracked
default on the **next successful workflow launch**. `status`, `check` and
`sessions` are read-only and do not trigger capture. Switching runtime or model
level alone should leave the tracked default unchanged.

Edit `gsd-cli.config.json` to change launcher-owned models, efforts and reviewers.
Edit the tracked default for other persistent GSD settings. Conflicting changes
to working/default values stop a launch and name the paths to reconcile.

For Claude, project agent-effort settings also depend on installed agent
frontmatter. After the first launch has materialized the policy, exit and preview
synchronization from the project. These commands assume the standard global
Claude installation. For a custom installation, use its tool path and pass its
configuration directory with `--config-dir`:

```sh
GSD_RUNTIME=claude node ~/.claude/gsd-core/bin/gsd-tools.cjs effort sync --dry-run
```

If the preview is appropriate, apply it:

```sh
GSD_RUNTIME=claude node ~/.claude/gsd-core/bin/gsd-tools.cjs effort sync --apply
```

This updates shared installed agent files and can affect other projects. The
launcher never performs it automatically. Until synchronization is appropriate
for that installation, project effort settings alone do not establish the
effort Claude subagents actually use.

See the [launcher guide](docs/LAUNCHER.md) for the full policy schema, custom
workflows, billing guards and interrupted-write recovery.
