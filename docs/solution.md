# Why use runtime blueprints?

A project can use the same GSD workflow with different budgets or switch runtimes while retaining its persistent settings. A blueprint gives that choice a name. For example, `gsd-cli codex medium --config` previews a Codex session with the project's medium settings. The project's Claude blueprint of the same name can select different models.

## One launch, separate settings

The launcher reads the selected runtime's installed GSD catalog to identify the phase for each role. Session settings control the main CLI, phase settings cover catalog roles, and an explicit role setting takes precedence for that field. The runtime's reviewer roster and adapter efforts apply across its blueprints. [Configuration details](configuration.md)

## Preserve project settings

Each launch merges persistent edits from the working config into the tracked default. Changes to distinct keys merge automatically. If two edits disagree on the same key, the launcher identifies the conflict so the project owner can reconcile it. A journal records interrupted writes. [Recovery reference](LAUNCHER.md#automatic-capture-and-recovery)

## Inspect before and after launch

```sh
gsd-cli init
gsd-cli check
gsd-cli codex medium --config --secure
gsd-cli codex medium --secure
gsd-cli sessions codex
```

Preview queries the selected resolver in a temporary project snapshot. Session history shows runtime evidence when the CLI logs provide it. For automated checks, the inspection commands also emit versioned JSON. [Check commands](checks.md) · [Machine-readable output](json-output.md)
