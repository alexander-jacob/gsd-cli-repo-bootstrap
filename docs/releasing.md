# Releasing

gsd-cli and its Claude Code / Codex skill are released in two separate repositories, each on its own version
line:

| What | Repository | Version lives in | Tag |
|---|---|---|---|
| gsd-cli | this repository | `pyproject.toml` → `version` | `vX.Y.Z` |
| gsd-cli skill (plugin) | [`jacob-consulting/skills`](https://github.com/jacob-consulting/skills) | `plugins/gsd-cli/.claude-plugin/plugin.json` | `gsd-cli--vX.Y.Z` |
| Skills marketplace | `jacob-consulting/skills` | `.claude-plugin/marketplace.json` → `metadata.version` | `marketplace--vX.Y.Z` |

The skill depends on a minimum gsd-cli release and checks it with `gsd-cli --version`. When a gsd-cli release
changes something the skill relies on, release gsd-cli first, then raise the skill's requirement.

## Develop on a branch

1. Branch from `main` for one change: a feature, a fix or a documentation update.
2. Commit with an imperative subject and a body stating the behaviour before and after and why
   (see `AGENTS.md`). Record user-visible changes under `## Unreleased` in `CHANGELOG.md` as you go.
3. Run the suite with `python -m pytest -n auto tests` (with the `test` extra installed) and, after
   documentation changes, `mkdocs build --strict`.
4. Squash-merge into `main` with one commit whose message summarises the branch, then delete the branch.
   Documentation-only changes stop here; they need no release.

## Release gsd-cli

Choose the version by [Semantic Versioning](https://semver.org/spec/v2.0.0.html): a patch release for fixes,
a minor release for new features or new reserved names, a major release for incompatible changes.

1. **Bump.** In one commit titled `Release version X.Y.Z`:
    - set `version` in `pyproject.toml`;
    - in `CHANGELOG.md`, add a `Released` row to the tracking table, update the "current package version"
      sentence, and move the `## Unreleased` entries under `## [X.Y.Z](…/releases/tag/vX.Y.Z) — YYYY-MM-DD`,
      keeping an empty `## Unreleased` heading.
2. **Verify.** Run the suite on Python 3.10 and 3.11.
3. **Build.** Delete `dist/` and any leftover `gsd_workflow_cli.egg-info`, then run `uv build` (or
   `python -m build`). Install the wheel into a fresh virtual environment outside the checkout and smoke-test
   it: `gsd-cli --version` prints the new version, and the changed behaviour works.
4. **Tag and push.** `git tag -a vX.Y.Z -m "Release X.Y.Z"`, then `git push origin main vX.Y.Z`.
5. **Publish.** Create the GitHub release from the tag with the wheel and sdist attached and the changelog
   section as notes:

    ```sh
    gh release create vX.Y.Z dist/gsd_workflow_cli-X.Y.Z-py3-none-any.whl dist/gsd_workflow_cli-X.Y.Z.tar.gz \
      --title vX.Y.Z --notes-file <the X.Y.Z changelog section>
    ```

6. **Install locally.** Upgrade your own installation from the released wheel:
   `pipx install --force dist/gsd_workflow_cli-X.Y.Z-py3-none-any.whl`, or
   `uv tool install --force dist/gsd_workflow_cli-X.Y.Z-py3-none-any.whl`. Check `gsd-cli --version`.

## Release the skill

Do this when the skill must require the new gsd-cli release, or when the skill itself changed. The skills
repository's `RELEASING.md` describes its release script in detail.

1. **Update the skill** on a branch in `jacob-consulting/skills`:
    - raise the required version in `plugins/gsd-cli/skills/gsd-cli/SKILL.md` (the `gsd-cli --version` probe),
      `plugins/gsd-cli/README.md` (the requirement and why) and the version rows of
      `plugins/gsd-cli/skills/gsd-cli/references/troubleshooting.md`;
    - document new behaviour the skill should rely on, such as new error messages, in the references;
    - add an entry under `## [Unreleased]` in `plugins/gsd-cli/CHANGELOG.md`;
    - run `python3 scripts/validate.py`.
2. **Squash-merge** into `main` (subject `gsd-cli: …`) and delete the branch.
3. **Release the plugin.** `scripts/release.sh gsd-cli X.Y.Z --dry-run`, check the diff, then run it without
   `--dry-run`. Raising the required gsd-cli version drops support for older gsd-cli releases, so it is a minor
   bump of the plugin.
4. **Release the marketplace** so it ships the new plugin version: add an entry under `## [Unreleased]` in the
   skills repository's root `CHANGELOG.md` (for example "The `gsd-cli` plugin is now at X.Y.Z, which requires
   gsd-cli A.B.C or later"), commit it, then `scripts/release.sh marketplace X.Y.Z --dry-run` and the real run.
5. **Push** `main` and both tags: `git push origin main --follow-tags`. The release script never pushes, and
   plugin releases have no GitHub release page; the changelog links point at the tags.
6. **Update the installed plugin:**
    - Claude Code: `claude plugin marketplace update jacob-consulting`, then
      `claude plugin update gsd-cli@jacob-consulting`, and restart sessions;
    - Codex: `codex plugin marketplace upgrade jacob-consulting`, then
      `codex plugin add gsd-cli@jacob-consulting`; new sessions use it.

    Confirm that the cached `SKILL.md` in each tool names the new required gsd-cli version.
