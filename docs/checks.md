# Check commands

Run checks from the intended project directory. Help also works outside a project.

## A practical check sequence

```sh
gsd-cli --help
gsd-cli check codex
gsd-cli status
gsd-cli plan codex high --config
gsd-cli plan codex high --config --details
gsd-cli sessions codex
gsd-cli policy
```

| Command | What it tells you | Behavior |
|---|---|---|
| `check [claude\|codex]` | Installed GSD version, required minimum and selected bundle | Read-only; omitting runtime checks both; any failure exits nonzero |
| `status` | Saved working state, including pending recovery | Read-only; does not calculate a future launch |
| `WORKFLOW RUNTIME [LEVEL] --config` | Proposed workflow settings versus installed resolution | Temporary snapshot; no AI launch or project writes |
| `--config --details` | Full resolver evidence, reviewer configuration and effective JSON | Requires `--config` |
| `sessions [claude\|codex]` | Session, agent and reviewer information recovered from logs | Read-only; historical evidence may be incomplete |
| `sessions codex --pick` | Interactive session selection | Read-only |
| `sessions codex --pick 1` | Select a numbered session | Read-only |
| `policy` | Validates `gsd-cli.config.json` and prints one line naming it | Read-only; `policy --json` adds the full policy and its differences from the shipped starter |
| `check --json` | The `check` results as JSON, with a machine-readable `reason` per entry | Read-only; same exit code as text mode |
| `WORKFLOW RUNTIME [LEVEL] --config --json` | The complete preview, including per-agent findings with codes | Requires `--config`; exclusive with `--details`; read-only |
| `sessions [claude\|codex] --json` | Sessions, agents and reviewers as JSON | Read-only; add `--pick [N]` for older sessions |

These inspection commands do not capture edits or recover interrupted writes.

`sessions` compares each run with what the installed GSD would resolve through the
same non-mutating resolver bridge as `--config`. It no longer runs `gsd-tools.cjs`,
so it cannot build or repair an installation, and it honours project-local and
overridden installations. Without Node or a usable `bin/lib/commands.cjs`, the
comparison is skipped and runs are listed without marks.

Every JSON form prints one document and never writes. Fields, error kinds and
finding codes are described in [machine-readable output](json-output.md).

## Read a configuration preview

- **✓ / OK:** applicable configured expectations match available evidence.
- **✗ / NOT OK:** a known difference exists; inspect `--details` for both values.
- **? / UNKNOWN:** evidence or an explicit expectation is missing.

Session and external reviewer rows are configuration-only and carry UNKNOWN.
Resolver output is not proof of actual AI execution. Use session logs to inspect
what ran, where the logs provide that information.

A completed preview exits **0**, even when it finds mismatches or legitimate
unknowns. An unavailable resolver, timeout or malformed response produces an
incomplete preview and exits **1**. Conflicts, pending recovery and held locks
can also prevent a reliable preview.

## Check installed routing directly

After the intended configuration has been materialized by a launch, query it
without calling an AI model. These paths assume the default global installations;
use the selected local or override installation path when applicable.

```sh
GSD_RUNTIME=claude node ~/.claude/gsd-core/bin/gsd-tools.cjs query resolve-model gsd-plan-checker
GSD_RUNTIME=codex node ~/.codex/gsd-core/bin/gsd-tools.cjs query resolve-model gsd-codebase-mapper
```

Claude agent frontmatter can determine effort independently of project config.
Preview synchronization before deciding whether to change installed definitions:

```sh
GSD_RUNTIME=claude node ~/.claude/gsd-core/bin/gsd-tools.cjs effort sync --dry-run
```

## If a check fails

| Finding | Next step |
|---|---|
| Missing or old selected GSD bundle | Inspect the path printed by `check`; repair or upgrade that installation |
| Missing `gsd.min_version` | Deliberately add the minimum your project requires to its policy |
| Known model or effort mismatch | Inspect detailed evidence and agent frontmatter; update the owning source |
| Pending recovery | Preserve files and journal; follow the recovery reference before a mutating retry |
| Incomplete preview | Check Node and installed resolver compatibility; read diagnostics |

`--secure` does not bypass version checks. The launcher does not fall back from
a broken selected local or override installation to another bundle.
