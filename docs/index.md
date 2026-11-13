# The problem: configuration drifts between AI sessions

A GSD workflow involves more than choosing a chat model. The session, its agents
and external reviewers can each use different models and reasoning efforts.
Switching between Claude Code and Codex adds another set of runtime conventions.

Without a project-owned policy, the next launch can inherit settings from the
previous task: an execution model used for planning, reviewers left over from a
different runtime, or expensive reasoning applied to routine extraction work.
The configuration you intended may also differ from what the installed GSD
resolver or Claude agent frontmatter actually selects.

## Where manual configuration becomes difficult

| Problem | Consequence |
|---|---|
| Models, agent effort and reviewer effort are edited separately | A session looks correct while its agents use different settings |
| Planning and execution share a working config | Temporary choices become the next workflow's defaults |
| Working configuration is tracked in Git | Machine-local settings and generated values create noisy changes |
| Each machine has its own GSD installation | The same policy can resolve differently or use an unsupported bundle |
| Reviewer selection is implicit | A workflow can reuse a previous reviewer roster |
| Concurrent sessions share a project directory | One session can change configuration used by another |

## What a reliable workflow needs

Keep the intended policy in version control, select the workflow and runtime
explicitly, check the installed resolver before spending model time, and retain
persistent GSD edits without mixing them with generated launch settings.

[See how gsd-cli addresses this](solution.md), then follow the
[configuration guide](configuration.md). Already initialized? Start with the
[check commands](checks.md).
