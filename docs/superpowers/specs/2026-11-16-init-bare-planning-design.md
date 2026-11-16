# Init on a bare `.planning/` directory

## Intent

`gsd-map-codebase` creates only `.planning/codebase/`. `gsd-cli init` then fails with
"No GSD project found" because `config.discover()` recognises a project only by
`.planning/config.json`, `.planning/config.default.json` or `gsd-cli.config.json`.
`initialize()` already supports a missing working config (treated as `{}`), so the
blocker is discovery alone. Goal: `init` works right after a mapping-only GSD start.

## Goals / non-goals

- Goal: `gsd-cli init` succeeds in (or below) a project whose `.planning/` has no config file.
- Non-goal: `init` creating `.planning/` itself; GSD owns that directory.
- Anti-goal: loosening discovery for `status`, `sessions`, `check` or launches. They read a
  real config file and would only fail later with a worse error.

## Approaches

- **Init-only discovery that also accepts a `.planning/` directory (picked).** Smallest
  change, matches what `initialize()` already supports.
- Loosen `discover()` for every command: rejected (anti-goal above).
- Init only in the current directory, no upward walk: rejected; inconsistent with the
  other commands and breaks running init from a subdirectory.

## Design

- Add an opt-in to discovery (e.g. `discover(start, allow_bare=True)` or a dedicated
  `discover_for_init`) that walks up from the start directory and returns the nearest
  ancestor with any existing marker file or a `.planning/` directory. The nearest match wins.
- `init_command` uses it; all other commands keep strict discovery.
- When nothing is found, init's error tells the user to start GSD first (for example
  `gsd-map-codebase` or `gsd-new-project`).
- Tests: a temporary project containing only `.planning/codebase/` initializes, including
  from a subdirectory; the seeded policy, `config.default.json` and `.gitignore` are written;
  strict discovery for other commands is unchanged; the no-`.planning` error message.
- Docs: mention that init works after `gsd-map-codebase` alone; CHANGELOG `Unreleased` entry.

## Left to the builder

The exact function signature and how the error wording reads.
Release (patch) and the follow-up skill release happen only when the maintainer asks.
