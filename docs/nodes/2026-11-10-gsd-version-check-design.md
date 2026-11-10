# GSD minimum-version checks

The owner chose **block** after the proposal to combine launch checks with a standalone diagnostic command. This extends the approved project-owned launcher policy; implementation continues with the previously requested defaults and inline execution.

## Intent and approaches

Claude's installed GSD is 1.20.1; Codex's is 1.18.0. Both have update-check hooks, while Claude additionally displays update information in its statusline. The absence of a Codex toolbar does not prove why the installations diverged. A launcher check makes project requirements independent of notification visibility.

Manual-only checking can be forgotten; launch-only checking lacks a convenient diagnostic command. Use both, sharing the same offline checker. No update installation, network lookup, latest-version claim, bypass option, or paid call is added.

## Contract

- Complete project policy gains required `gsd: {"min_version": "1.20.1"}`. The starter uses 1.20.1 as an editable policy floor, not a proven technical compatibility minimum. Existing project policy must explicitly add the field; never silently replace it or impose a hidden fallback.
- Before each workflow launch, check the selected runtime after policy/executable/billing validation and before any capture, journal recovery, lock creation or launch record. Old, missing, unreadable, malformed or incomplete GSD blocks with exit 1 and a diagnostic containing runtime, installation path and minimum.
- `gsd-cli check` checks both Claude and Codex and reports every result; `gsd-cli check claude|codex` checks one. Exit 0 only when every requested installation satisfies the project floor. The command is read-only, including when recovery is pending, and does not require either AI CLI executable or Node.
- Help, status, sessions and init remain usable without a supported GSD installation. `check` becomes a reserved workflow name.
- Compare strict [SemVer 2.0.0](https://semver.org/spec/v2.0.0.html) versions numerically. Accept prereleases and build metadata; ignore build metadata for precedence. A prerelease does not satisfy its corresponding stable release. Reject malformed/partial versions, leading zero numeric components and invalid numeric prerelease identifiers. Trim whitespace from installed VERSION files.

## Installation discovery and evidence

Check only the requested runtime. Never let a Claude installation satisfy a Codex requirement. Resolve relative paths against the discovered project root, matching the launcher's eventual child working directory.

1. An explicit `CLAUDE_CONFIG_DIR` or `CODEX_HOME` selects that runtime's config directory. Expand a leading `~`; an invalid/missing explicit location blocks rather than falling back.
2. Otherwise select the project's `.claude/gsd-core` or `.codex/gsd-core` when present, including incomplete installations.
3. Otherwise use `~/.claude/gsd-core` or `~/.codex/gsd-core`.

Inspect `VERSION`, `workflows/update.md`, and `bin/gsd-tools.cjs` in that directory. VERSION must be a readable regular UTF-8 file with bounded size; marker/tool files must be regular files. Do not execute installation code. A broken selected local installation blocks rather than borrowing a global version.

The installed `bin/lib/update-context.cjs` uses VERSION plus the update workflow marker to establish an installation and recognizes runtime environment overrides and local/global installs. It can fall through to other runtimes, so this launch gate deliberately uses runtime-specific discovery. The extra tool-file check rejects an unusable partial bundle. This checks the selected bundle, not every hook/agent file or the absolute paths embedded in every installed skill. Explicit runtime configuration directories take precedence; users with custom skill paths must keep them aligned.

## Review refinement: child directory changes

The independent review reproduced a supported Codex `-C`/`--cd` option moving the child to a different project's older bundle after the original project passed its check. Reject these options, including attached values, before any project writes. The caller should run gsd-cli from the destination project instead. Tokens after the child's own `--` remain literal positional arguments. Other forwarded tokens remain unchanged. This deliberately limits directory forwarding to keep the configured project and checked bundle aligned; it does not claim to prevent arbitrary runtime reconfiguration after startup.

## Scope and verification

Use stdlib Python plus existing Click; Python 3.10+, POSIX. Keep installation checks separate from policy validation and Click. No changes to historical session routing or prior deferred findings.

Regression tests cover version precedence, malformed/unreadable files and nonregular files, strict runtime discovery, env/local/global precedence, incomplete installations, both check commands, per-runtime launch blocking, no writes on failure, pending journal preservation, `--secure` not bypassing the gate, read-only commands, explicit project floors and existing policy migration errors. Inspect actual installed bundles without changing them: Claude should pass 1.20.1, Codex should fail 1.18.0 against that floor.
