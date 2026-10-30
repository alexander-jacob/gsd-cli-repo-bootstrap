# `gsd-cli sessions` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only `gsd-cli sessions` command that shows, for the current project's three most recent Claude/Codex sessions (picker for older), the model and effort the session and each subagent actually ran with, flagging requested-vs-actual and profile-vs-actual mismatches.

**Architecture:** Everything stays in the single `gsd-cli` file. Each launch appends a record to a launch log. Two log readers (Claude, Codex) turn runtime logs into a common `Run` tree. A linker nests reviewer runs and matches launches. A checker computes expected values with the real GSD resolver against the launch's config snapshot. A renderer prints text.

**Tech Stack:** Python 3.10+ standard library only (`json`, `dataclasses`, `datetime`, `collections.Counter`, `subprocess`, `tempfile`); `unittest` subprocess tests.

**Spec:** `docs/superpowers/specs/2026-10-30-session-models-design.md`

## Global Constraints

- Standard library only; `gsd-cli` stays one executable file with its entry point.
- `sessions` never writes anything: no session logs, no project config, no launch log.
- A launch-log write failure prints a warning on stderr and the launch continues; launch `argv` is unchanged.
- Launch log: `$XDG_STATE_HOME/gsd-cli/launches.jsonl`, default `~/.local/state/gsd-cli/launches.jsonl`, one JSON object per line.
- Claude logs: `~/.claude/projects/*/<id>.jsonl` and `<id>/subagents/agent-<id>.{jsonl,meta.json}`. Codex logs: `~/.codex/sessions/**/rollout-*.jsonl`. Projects are matched on the `cwd` inside the records, never on folder names alone.
- Resolver: `GSD_RUNTIME=<runtime> node ~/.claude/gsd-core/bin/gsd-tools.cjs query resolve-model <agent>`, run with cwd set to a temp dir holding the launch snapshot as `.planning/config.json`. Its JSON output has `model`, `effort` and, for agents GSD does not route, `unknown_agent: true`.
- Tests are offline: fake `HOME`, fake `XDG_STATE_HOME`, `TZ=UTC`, stub `node`; no real credentials.
- Keep README, `docs/LAUNCHER.md`, AGENTS.md and the module docstring aligned.

## Review Focus

1. **Corrupt or truncated log lines** (a session still being written, a crashed run). Expected: skip the bad line, keep the session. Test: `test_sessions_skips_malformed_log_lines` (Task 2).
2. **A project with no sessions at all, or no launch log yet.** Expected: one friendly line, exit 0. Test: `test_sessions_with_no_logs_prints_message` (Task 5).
3. **Two projects whose paths map to the same Claude folder name** (`a.b` and `a-b`). Expected: only sessions whose `cwd` is this project. Test: `test_sessions_filters_claude_by_cwd_not_folder` (Task 2).
4. **A launch whose config snapshot later changed** (another profile launched since). Expected: comparison uses the snapshot, not the current config. Test: `test_profile_comparison_uses_launch_snapshot` (Task 4).
5. **Running inside a subdirectory of the project.** Expected: same sessions as from the root. Test: `test_sessions_from_nested_directory` (Task 5).

---

### Task 1: Launch log

**Files:**
- Modify: `gsd-cli` (new helpers after `session_effort_args`; call in `main` after `save(path, data)`)
- Test: `tests/test_gsd_cli.py`

**Interfaces:**
- Produces:
  - `session_effort(runtime: str, profile: str, session_model: str) -> str | None`: the effort `session_effort_args` already computes. `session_effort_args` now wraps it.
  - `launch_log_path() -> Path`
  - `record_launch(root: Path, runtime: str, profile: str, session_model: str, forwarded: list[str], data: dict) -> None`. It appends `{"time": "<UTC ISO, Z suffix>", "project": str(root), "runtime", "profile", "session_model", "session_effort", "forwarded_args", "config": data, "gsd_defaults": <~/.gsd/defaults.json parsed or null>}`. On `OSError` it prints `GSD: warning: could not write launch log: <exc>` to stderr. `forwarded` is the args after `--` only.

- [ ] **Step 1: Write the failing tests.** In `setUp`, set `self.home = self.root / "home"`, then `env["HOME"]`, `env["XDG_STATE_HOME"] = str(self.root / "state")` and `env["TZ"] = "UTC"`. Add a helper `launches()` that reads `state/gsd-cli/launches.jsonl` lines.
  - `test_launch_appends_one_record`: `init`, then `codex exec-high -- --foo`. Assert one record: `runtime == "codex"`, `profile == "exec-high"`, `session_model == "gpt-6-astra"`, `session_effort == "medium"`, `forwarded_args == ["--foo"]`, `project == str(self.project)`, `config == self.config()`. The `invocation()["args"]` assertion stays exactly as in the existing exec-high test. A second launch makes two records.
  - `test_claude_launch_records_no_session_effort`: `claude exec-opus` gives `session_effort is None`.
  - `test_launch_log_failure_warns_and_launches`: make `state` a regular file so the directory can't be created. The launch exits 0, the stub is invoked, and stderr contains `could not write launch log`.
- [ ] **Step 2: Run** `python3 -m unittest discover -s tests -v`. Expected: the three new tests FAIL; the existing ones PASS.
- [ ] **Step 3: Implement** the helpers and the call in `main`. `record_launch` runs before `os.chdir`/`execvpe`. Use `root = path.parent.parent`.
- [ ] **Step 4: Run the suite.** Expected: all PASS.
- [ ] **Step 5: Commit** `Record each profile launch in a launch log`.

### Task 2: Claude log reader and the `Run` model

**Files:**
- Modify: `gsd-cli`
- Create: `tests/session_fixtures.py` (fixture writers shared by Tasks 2–5)
- Create: `tests/test_sessions.py` (subclasses `GsdCliTestCase` from `test_gsd_cli`)

**Interfaces:**
- Produces:
```python
@dataclass
class Run:
    runtime: str                    # "claude" | "codex"
    run_id: str
    kind: str                       # "session" | "agent" | "reviewer"
    cwd: str
    start: datetime                 # tz-aware UTC
    end: datetime
    model: str | None               # most common actual model
    effort: str | None              # most common actual effort
    effort_varied: bool = False
    advisor: str | None = None
    agent_type: str | None = None
    requested_model: str | None = None
    requested_effort: str | None = None
    children: list["Run"] = field(default_factory=list)
    launch: dict | None = None
    resumed: bool = False
    marks: list[str] = field(default_factory=list)
```
  - `most_common(values: list[str | None]) -> tuple[str | None, bool]`: the most frequent non-None value and whether more than one distinct value occurred.
  - `read_claude_runs(root: Path) -> list[Run]`: top-level `session` and `reviewer` runs for `cwd == str(root)`, with agents nested under the file that contains the `tool_use` whose id equals the meta `toolUseId`. If no parent is found, the agent goes under the session.
- Fixture writers in `tests/session_fixtures.py`:
  - `claude_session(home, cwd, session_id, start, model, effort, *, agents=(), entrypoint="cli", prompt="hi", turns=2, advisor=None)`. Each agent is `{"id", "type", "requested", "model", "effort", "parent": None | agent id}`. The writer emits matching `tool_use` ids in the parent file.
  - The Claude folder name is `re.sub(r"[^A-Za-z0-9]", "-", str(cwd))`.

- [ ] **Step 1: Write failing tests** that call the reader through the module, loaded with `importlib.machinery.SourceFileLoader("gsd_cli", str(LAUNCHER))`.
  - `test_claude_reader_session_and_agents`: the session runs `claude-opus-5-5`/`medium`, advisor `claude-opus-5-5`, with one agent `gsd-executor` (requested `sonnet`, ran `claude-sonnet-5-5`/`high`). Assert one session with `model == "claude-opus-5-5"`, `effort == "medium"`, `advisor` set, and one child with `agent_type == "gsd-executor"`, `requested_model == "sonnet"`, `model == "claude-sonnet-5-5"`, `effort == "high"`.
  - `test_claude_reader_nests_sub_subagents`: an agent whose parent is another agent appears in that agent's `children`.
  - `test_claude_reader_marks_reviewer_runs`: `entrypoint="sdk-cli"`, prompt starting with `# Cross-AI Plan Review Request`, model `claude-fable-5-1` gives `kind == "reviewer"`.
  - `test_claude_reader_effort_varied`: turns with `high`, `high`, `low` give `effort == "high"` and `effort_varied`.
  - `test_sessions_filters_claude_by_cwd_not_folder`: projects `/x/a.b` and `/x/a-b` share a folder; only the one matching `root` is returned.
  - `test_sessions_skips_malformed_log_lines`: a truncated last line still yields the session.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_sessions -v`. Expected: FAIL (`read_claude_runs` missing).
- [ ] **Step 3: Implement** `Run`, `most_common` and `read_claude_runs`. Actual model is `message.model` and effort is the top-level `effort` on `type == "assistant"` records. Requested model is `meta.model`; `requested_effort` comes from the parent's `tool_use.input.effort` if present. Ignore `<synthetic>` models. Folder candidates use the `re.sub` rule; filter on the first record's `cwd`.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `Read Claude session logs into a run tree`.

### Task 3: Codex log reader

**Files:**
- Modify: `gsd-cli`
- Modify: `tests/session_fixtures.py`, `tests/test_sessions.py`

**Interfaces:**
- Consumes: `Run` and `most_common` (Task 2).
- Produces: `read_codex_runs(root: Path) -> list[Run]`. It returns top-level runs only; children are nested via `source.subagent.thread_spawn.parent_thread_id`. A top-level run is `kind="reviewer"` when `session_meta.payload.source == "exec"` and `"session"` otherwise.
- Fixture writer: `codex_session(home, cwd, thread_id, start, model, effort, *, parent=None, role=None, source="cli", spawns=())`. Each spawn is `{"call_id", "thread_id", "agent_type", "model", "effort"}`. The writer emits a `spawn_agent` `function_call` and a `SubAgentActivity` item (`id` = call id, `agent_thread_id`, `model`, `reasoning_effort`) in the parent.

- [ ] **Step 1: Write failing tests.**
  - `test_codex_reader_links_spawn_to_child`: the parent runs `gpt-6-astra`/`medium` and spawns `gsd-executor` requested `gpt-6.1-sol`/`high`. The child's turns run `gpt-6.1-sol`/`high`. Assert the child is nested with `requested_model == "gpt-6.1-sol"`, `requested_effort == "high"`, and actual values from `turn_context`.
  - `test_codex_reader_falls_back_to_parent_thread_id`: with no `SubAgentActivity`, the child is still nested via `parent_thread_id`, with `agent_type` from `agent_role` and requested values `None`.
  - `test_codex_reader_filters_other_projects`: a session with another `cwd` is excluded.
  - `test_codex_reader_marks_exec_as_reviewer`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Read only the first line of each rollout to filter on `cwd`. Actual values come from `turn_context.payload.model`/`effort`. Requested values come from the `SubAgentActivity` whose `agent_thread_id` is the child's id, falling back to `spawn_agent` args matched by call id.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `Read Codex session logs into a run tree`.

### Task 4: Linking and checks

**Files:**
- Modify: `gsd-cli`
- Modify: `tests/session_fixtures.py`, `tests/test_sessions.py`

**Interfaces:**
- Consumes: `Run`, `read_claude_runs`, `read_codex_runs`, `launch_log_path`.
- Produces:
  - `MATCH_WINDOW = timedelta(seconds=60)`
  - `load_launches(root: Path) -> list[dict]`: records for this project, skipping malformed lines.
  - `link(runs: list[Run], launches: list[dict]) -> list[Run]`: nests each reviewer under the session of the same project whose `[start, end]` contains the reviewer's start. If none does, the reviewer stays top-level with mark `reviewer, unattached`. It sets `session.launch` to the latest same-runtime launch with `time <= start` and `start - time <= MATCH_WINDOW`. It sets `resumed` when a later same-runtime launch falls inside the session span and its forwarded args start with `resume` (Codex) or contain `--resume`, `-r` or `--continue` (Claude). Returns top-level runs, newest first.
  - `model_matches(runtime: str, expected: str, actual: str | None) -> bool`: true when the values are equal, or, for Claude, when `actual` starts with `f"claude-{expected}-"`.
  - `class Resolver` with `expected(self, launch: dict, agent_type: str) -> dict | None`. Results are cached per `(launch["time"], runtime, agent_type)`. It returns `None` for `unknown_agent`. It sets `self.available = False` when `node` or the tools file is missing or the call fails.
  - `check(run: Run, resolver: Resolver, runtime: str, launch: dict | None) -> None`: appends these marks, with exact text:
    - requested vs actual: `! asked {requested}, ran {actual}`
    - profile vs actual, agent: `! profile expects {model}` and `! profile expects effort {effort}`
    - session model: `! profile expects {session_model}`. Codex session effort: `! profile expects effort {session_effort}`. Claude session effort is never compared.
    - when forwarded args contain `--model`, `-m` or an arg containing `model_reasoning_effort=`: one mark `overridden at launch` replaces the session-level profile marks.
    - `resumed, profile may differ` when `run.resumed`.
    - reviewer: `! {name} expects {model}`, with `name` from `REVIEWERS` by `cli` (`claude` for Claude runs, `codex` for Codex runs). Fable/Astra are the only matching entries.
  - Skip comparison steps when the expected value is missing; never mark when `actual` is `None`.
- Fixture: `launch_record(state_home, project, runtime, profile, time, session_model, session_effort, forwarded=(), config=None)`. Also `install_resolver(home, bin_dir, table)`, which creates `home/.claude/gsd-core/bin/gsd-tools.cjs` (an empty file) and a `node` stub in `bin_dir`. The stub reads `GSD_RUNTIME` and the agent from argv. It prints `{"model", "effort"}` from `./.planning/config.json` `model_overrides[agent]` when present, otherwise `table[f"{runtime}:{agent}"]`, otherwise `{"unknown_agent": true}`.

- [ ] **Step 1: Write failing tests.**
  - `test_link_nests_reviewer_under_overlapping_session` and `test_link_keeps_unattached_reviewer`.
  - `test_link_matches_launch_within_window`: a launch 5 s before the session matches; one 5 min before gives `launch is None`.
  - `test_link_marks_resumed`.
  - `test_check_flags_requested_vs_actual`: requested `sonnet`, ran `claude-opus-5-5` gives the mark `! asked sonnet, ran claude-opus-5-5`. Requested `sonnet` with actual `claude-sonnet-5-5` gives no mark.
  - `test_check_flags_profile_mismatch`: the resolver expects `gsd-executor` → `opus`/`high`, but the run used `claude-sonnet-5-5`/`high`. This gives `! profile expects opus`.
  - `test_profile_comparison_uses_launch_snapshot`: the snapshot has `model_overrides["gsd-executor"] = "opus"`, the current project config says `sonnet`, and the run used `claude-opus-5-5`. This gives no profile mark.
  - `test_check_skips_unknown_agents`, `test_check_overridden_at_launch`, `test_check_reviewer_model` (`fable-review` ran `claude-opus-5-5` gives `! fable-review expects claude-fable-5-1`).
  - `test_check_without_resolver_sets_unavailable`: no stub installed gives `resolver.available is False` and no profile marks.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** The resolver writes `launch["config"]` to a `tempfile.TemporaryDirectory()` as `.planning/config.json` and runs with `cwd` set there, `env GSD_RUNTIME=runtime`, `timeout=10`. Global defaults are not fed: GSD ignores them when a project config exists, and the launch record keeps them only for reference.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `Link sessions to launches and flag model mismatches`.

### Task 5: `sessions` command, output, picker, docs

**Files:**
- Modify: `gsd-cli` (`main` dispatch next to `status`, module docstring)
- Modify: `README.md`, `docs/LAUNCHER.md`, `AGENTS.md`
- Modify: `tests/test_sessions.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `render(run: Run, depth: int = 0) -> list[str]`. The session line holds runtime, start (local time, `%Y-%m-%d %H:%M`), `profile: <name|unknown>`, model, effort (`<effort> (varied)` when varied), and `advisor <model>` when set. The agent line holds `agent_type`, `asked <model>/<effort>` and `ran <model>/<effort>`. The reviewer line is `reviewer <name or model>  ran <model>`. Marks go at the end of the line, separated by two spaces. Children are indented two spaces per depth. Column widths are left to the builder.
  - CLI: `gsd-cli sessions [claude|codex] [--pick [N]]`.
    - Default: the three newest top-level runs.
    - `--pick` with a TTY stdin lists the older runs as `N) <session line>` and prompts `Session number: `. With a non-TTY stdin it prints the list and exits 0.
    - `--pick N` shows the Nth older run (1 = the fourth newest) directly.
    - A bad number exits with `Error: no session N`.
    - No runs at all prints `No Claude or Codex sessions found for <root>.` and exits 0.
    - When the resolver is unavailable, the last line is `note: GSD resolver not available; profile comparison skipped`.

- [ ] **Step 1: Write failing tests** (end-to-end via `run_launcher`).
  - `test_sessions_shows_three_newest`: four Claude sessions and one Codex session over five days. Only the three newest start times appear; the oldest doesn't.
  - `test_sessions_runtime_filter`: `sessions codex` shows only Codex.
  - `test_sessions_pick_number_shows_older`: `sessions --pick 2` shows the fifth-newest session.
  - `test_sessions_pick_without_tty_lists`: the output contains `1) ` and `2) ` and no `Session number:`.
  - `test_sessions_reports_marks_and_note`: a mismatch fixture with no resolver gives output containing `! asked sonnet, ran claude-opus-5-5`, `profile: unknown` and the note line.
  - `test_sessions_with_no_logs_prints_message`, `test_sessions_from_nested_directory`.
  - `test_sessions_writes_nothing`: the config, the launch log and the log files' mtimes and bytes are unchanged after the run.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `render` and the dispatch. Update the docstring command list. Add a "Checking what a session actually ran" section to README and `docs/LAUNCHER.md` showing sample output, the launch-log path and the two mismatch kinds. In AGENTS.md, add the launch-log write to the launch description, list `sessions` under commands, and add "Cover … launch-log records and `sessions` mismatch flags" to the testing guidelines.
- [ ] **Step 4: Run** `python3 -m unittest discover -s tests -v`. Expected: all PASS. Then from a real GSD project run `python3 <repo>/gsd-cli sessions` and check that the output is sane against the logs inspected during design.
- [ ] **Step 5: Commit** `Add gsd-cli sessions command`.
