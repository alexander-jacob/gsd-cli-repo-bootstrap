# Why gsd-cli is the solution

`gsd-cli` turns a project policy into a repeatable Claude Code or Codex launch.
GSD still runs the workflows. The launcher prepares configuration and opens your
chosen CLI; you invoke the desired GSD skill inside that session.

```sh
gsd-cli plan claude high
gsd-cli exec codex medium
gsd-cli plan codex --config
```

## One policy, explicit launches

A complete `gsd-cli.config.json` declares runtime levels, phase settings, agent
pins, independent effort settings and reviewer groups. Every workflow selects
its reviewers explicitly for each runtime. Package upgrades preserve that
project policy, so adopting new models is a deliberate project change.

## Preserve useful changes

The launcher separates tracked persistent defaults from the effective working
config. Before launch, it merges persistent GSD edits using the last successful
baseline, current working config and tracked default. Independent changes merge;
conflicting edits stop with the affected path. A recovery journal protects
interrupted writes.

## Inspect the installed behavior

`--config` previews the proposed settings and queries the selected installed GSD
resolver using a temporary snapshot. It compares configured models and efforts
with available resolver evidence. `sessions` helps inspect the resulting logs.
This makes configuration discrepancies visible before and after a launch.

## Check compatibility before changing configuration

Each workflow launch checks the selected GSD installation against the project's
minimum version before synchronization. A broken selected installation blocks
launch rather than borrowing another runtime's bundle.

## Get started

Use Python 3.10+ on Linux or macOS, pipx, Git, the desired AI CLI and a compatible
GSD installation. OpenCode is used by the shipped OpenRouter reviewers. Node is
required for resolver previews.

```sh
pipx install /path/to/gsd-cli-repo-bootstrap
cd /path/to/your/gsd-project
gsd-cli init
gsd-cli check
gsd-cli plan codex --config
```

Initialize an existing GSD project containing `.planning/config.json` or
`.planning/config.default.json`. Review and commit the generated policy, tracked
default and ignore rules. Then launch your chosen workflow:

```sh
gsd-cli plan codex high --secure
```

`--secure` uses the CLI's normal permission settings. See the
[configuration guide](configuration.md#permissions-and-billing) for preset defaults.
For existing installations, consult the
[migration walkthrough](https://github.com/alexander-jacob/gsd-cli-repo-bootstrap/blob/main/MIGRATION.md).
