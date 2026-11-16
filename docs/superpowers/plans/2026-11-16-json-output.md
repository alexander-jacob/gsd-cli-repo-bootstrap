# Machine-Readable Output (Wave 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every read-only gsd-cli command a stable JSON form with generated schemas, add the read-only `policy` and `schema` commands, and make `sessions` stop executing the installed `gsd-tools.cjs`.

**Architecture:** Pydantic v2 models in `gsd_cli/models.py` define the envelope and every payload; commands build a model and print it, and `gsd-cli schema NAME` prints the same model's generated schema. `main()` detects `--json` before Click parses, so every failure in JSON mode becomes an envelope with the text-mode exit code. Domain modules gain small builder functions that return models; Click stays at the boundary.

**Tech Stack:** Python 3.10+, Click 8, Pydantic v2 (new), standard library, `unittest`, Node only for resolver-bridge tests.

**Spec:** `docs/superpowers/specs/2026-11-16-json-output-and-skill-design.md` — read it first. It holds the payload examples, error kinds and finding codes this plan refers to. Wave 2 (the skill) has its own plan in the `skills` repository and depends only on this contract.

## Before you start

- Work on a new branch from `main` (for example `json-output`), not on the branch that is checked out.
- Create a virtual environment and run `python -m pip install -e .`. The system Python may carry Pydantic 1.x, which will not work.
- Read `AGENTS.md`. Its invariants bind every task.
- Full suite: `python -m unittest discover -s tests -v`. Run it at the end of every task; it must stay green.
- Tests follow `tests/test_gsd_cli.py`: subclass `GsdCliTestCase`, use `self.run_launcher(...)`, temporary projects, `install_gsd` from `tests/test_versions.py`, and `install_resolver` from `tests/resolver_fixtures.py` for bridge tests (decorated `@unittest.skipUnless(shutil.which('node'), ...)`).
- Commits: imperative subject, body stating behaviour before and after and why, one behaviour change per commit, no attribution lines.

## Global Constraints

- `pydantic>=2,<3` is the only new dependency. Pydantic is used only in `gsd_cli/models.py`, `gsd_cli/policy_model.py`, the builder functions that return those models, and the CLI boundary. `policy.validate`, config synchronization and version checks keep their standard-library code.
- Text output, exit codes and the plain `status` output of every existing invocation are unchanged.
- JSON mode prints exactly one JSON object plus a newline on stdout, no ANSI, serialized with `ensure_ascii=True` and two-space indentation.
- `ok` is `true` exactly when the exit code is 0; the exit code equals the text-mode exit code of the same invocation.
- JSON mode never writes: no working config, baseline, journal, lock or launch-log change.
- `schema_version` is `1`. Models forbid unknown fields except `agents[].resolved`, `config` and `policy`.
- Session JSON never includes a launch record's `config`, `policy` or `gsd_defaults`.
- `--json` counts only before the first `--`. `--help` behaves as today.

## Review Focus

- `gsd-cli --json status` (flag before the command): a usage envelope with exit 2, never a traceback. Test in Task 1.
- `status --json` run outside any GSD project: an envelope with `error.kind` `config` and exit 1. Test in Task 1.
- A model name containing an escape character or non-ASCII text in policy: stays inside a JSON string as `\u…`, stdout has no raw escape byte. Test in Task 4.
- A resolver row with keys this tool has never seen, or `null` in its nullable fields: `preview --json` still succeeds and validates. Test in Task 4.
- Old launch records (no `workflow`/`level`, `forwarded_args` not a list) and no Node on PATH: `sessions --json` succeeds, `launch` fields are `null`/empty, `resolver_available` is `false`. Test in Task 6.

## File map

| File | Responsibility |
|---|---|
| `gsd_cli/models.py` (new) | Envelope, error, all payload models, `SCHEMAS` registry, `dump` |
| `gsd_cli/policy_model.py` (new) | `PolicyFile` model, schema generation only |
| `gsd_cli/cli.py` | `--json` detection, error envelopes, new commands, `--json` options |
| `gsd_cli/policy.py` | `RESERVED` names |
| `gsd_cli/versions.py` | `CheckResult.reason` |
| `gsd_cli/preview.py` | structured findings, `report` builder |
| `gsd_cli/resolver.py` | `run_bridge` shared by preview and sessions |
| `gsd_cli/sessions.py` | bridge-based `Resolver`, `SessionsError`, `report` builder |
| `tests/test_json_output.py` (new) | JSON-mode tests for status, check, policy, schema, errors |
| `tests/test_policy_model.py` (new) | `policy-file` model parity tests |
| `tests/test_preview.py`, `tests/test_sessions.py`, `tests/session_fixtures.py` | extended |

---

### Task 1: Pydantic envelope and JSON-mode error handling

**Files:**
- Modify: `pyproject.toml` (dependency), `gsd_cli/cli.py`, `gsd_cli/policy.py`
- Create: `gsd_cli/models.py`, `tests/test_json_output.py`

**Interfaces — produces:**

```python
# gsd_cli/policy.py
RESERVED = ('init', 'status', 'sessions', 'check', 'policy', 'schema', 'help', 'claude', 'codex')

# gsd_cli/models.py
SCHEMA_VERSION = 1
ErrorKind = Literal['usage', 'config', 'policy', 'version', 'os', 'requirements', 'incomplete']
class Model(BaseModel): model_config = ConfigDict(extra='forbid')
class ErrorInfo(Model): kind: ErrorKind; message: str
class Envelope(Model, Generic[DataT]):
    schema_version: Literal[1] = 1
    command: str | None            # narrowed to a Literal in each subclass
    ok: bool
    data: DataT | None = None
    error: ErrorInfo | None = None
class ErrorEnvelope(Envelope[None]): command: None = None     # schema name 'error'
SCHEMAS: dict[str, type[BaseModel]]     # filled by later tasks; 'error' -> ErrorEnvelope now
JSON_COMMANDS = ('status', 'check', 'policy', 'sessions', 'preview')
def dump(model: BaseModel) -> str        # json.dumps(model.model_dump(mode='json'), indent=2, ensure_ascii=True, allow_nan=False) + '\n'
def failure(command: str | None, kind: str, message: str) -> BaseModel
    # envelope of the right class for `command`, ok False, data None

# gsd_cli/cli.py
def emit(envelope: BaseModel) -> NoReturn   # prints dump(envelope); raises SystemExit(0 if envelope.ok else 1)
def json_command(args: list[str]) -> str | None
    # first argument if in JSON_COMMANDS; None if absent, an option, or another RESERVED name; else 'preview'
```

Until later tasks register their envelope classes, `failure` for a not-yet-modelled command may use a plain `Envelope[None]` with that command string; each later task replaces it with the registered class.

- [ ] **Step 1: Add the dependency.** `dependencies = ["click>=8.1,<9", "pydantic>=2,<3"]` in `pyproject.toml`; reinstall with `python -m pip install -e .`.

- [ ] **Step 2: Write failing tests** in `tests/test_json_output.py` (class `JsonErrorTests(GsdCliTestCase)`, with a helper `envelope(result)` that asserts `result.stderr == ''`, parses `result.stdout` as one JSON object and returns it):

```python
def test_unknown_option_before_command_is_usage_envelope(self):
    result = self.run_launcher('--json', 'status')
    self.assertEqual(result.returncode, 2)
    body = self.envelope(result)
    self.assertEqual((body['ok'], body['command'], body['data'], body['error']['kind']),
                     (False, None, None, 'usage'))

def test_init_has_no_json_form(self):
    result = self.run_launcher('init', '--json')
    self.assertEqual(result.returncode, 2)
    self.assertEqual(self.envelope(result)['command'], None)
    self.assertFalse((self.project / 'gsd-cli.config.json').exists())

def test_outside_project_is_config_error(self):
    result = self.run_launcher('status', '--json', cwd=self.root)   # no .planning above
    self.assertEqual(result.returncode, 1)
    body = self.envelope(result)
    self.assertEqual((body['command'], body['error']['kind']), ('status', 'config'))

def test_json_after_separator_is_a_child_argument(self):
    result = self.run_launcher('status', '--', '--json')
    self.assertEqual(result.returncode, 2)
    self.assertIn('forwarding after --', result.stderr)     # text error, not an envelope

def test_help_wins_over_json(self):
    result = self.run_launcher('--help', '--json')
    self.assertEqual(result.returncode, 0)
    self.assertIn('Usage:', result.stdout)

def test_policy_and_schema_are_reserved_workflow_names(self):
    for name in ('policy', 'schema'):
        ...  # init, add workflows[name] copied from workflows['plan'], run `plan claude --config`
        # expect exit 1 and 'reserved or invalid workflow name' in stderr
```

`test_outside_project_is_config_error` will only pass once Task 2 adds `--json` to `status`; mark it `@unittest.expectedFailure` now and remove the marker in Task 2.

- [ ] **Step 3: Run** `python -m unittest tests.test_json_output -v` — expect failures.

- [ ] **Step 4: Implement.**
  - `policy.RESERVED`; `policy.validate` and the forwarding check in `cli.main` both use it (the forwarding check currently lists `init, status, sessions, check, help`; it must reject every `RESERVED` name except the two runtimes).
  - `gsd_cli/models.py` as above.
  - `cli.main`: compute `json_mode = '--json' in args` after splitting at `--`; pass it in `obj`; in each `except` branch, when `json_mode`, call `emit`'s underlying print with `failure(json_command(args), kind, message)` and exit with the same code as text mode. Mapping: `click.UsageError` → `usage` (exit 2); other `click.ClickException` → `config`; `config.ConfigError` → `config`; `PolicyError` → `policy`; `VersionError` → `version`; `OSError` → `os`. Messages are the same strings text mode prints, without the `Error: ` prefix.
  - Let `SystemExit` raised by `emit` pass through untouched.

- [ ] **Step 5: Run** the new tests and the full suite — all pass (one expected failure).

- [ ] **Step 6: Commit** — `Add JSON error envelopes and reserve policy and schema names`.

---

### Task 2: `status --json`, `check --json` and the `policy` command

**Files:**
- Modify: `gsd_cli/models.py`, `gsd_cli/versions.py`, `gsd_cli/cli.py`
- Test: `tests/test_json_output.py`, `tests/test_versions.py`

**Interfaces — produces:**

```python
# gsd_cli/versions.py — CheckResult gains a trailing field
reason: str        # 'ok' | 'below_minimum' | 'unverifiable'

# gsd_cli/models.py
class StatusData(Model): project: str; source: str; pending_recovery: bool; config: dict[str, Any]
class CheckEntry(Model):
    runtime: Literal['claude', 'codex']; directory: str; installed: str | None
    minimum: str; ok: bool; reason: Literal['ok', 'below_minimum', 'unverifiable']; message: str
class CheckData(Model): minimum: str; results: list[CheckEntry]
class PolicyData(Model): project: str; path: str; policy: dict[str, Any]; differs_from_shipped: list[str]
class StatusEnvelope(Envelope[StatusData]): command: Literal['status'] = 'status'
class CheckEnvelope(Envelope[CheckData]):   command: Literal['check'] = 'check'
class PolicyEnvelope(Envelope[PolicyData]): command: Literal['policy'] = 'policy'
# registered in SCHEMAS under 'status', 'check', 'policy'
```

`CheckEntry` is reused by Task 4 for `installation`.

- [ ] **Step 1: Write failing tests** (class `JsonReadTests(GsdCliTestCase)`). Each parses stdout with the model, strictly: `StatusEnvelope.model_validate_json(result.stdout, strict=True)`.

```python
def test_status_json_wraps_plain_status(self):
    self.run_launcher('init')
    plain = json.loads(self.run_launcher('status').stdout)
    env = StatusEnvelope.model_validate_json(self.run_launcher('status', '--json').stdout, strict=True)
    self.assertTrue(env.ok)
    self.assertEqual(env.data.model_dump(exclude={'project'}), plain)
    self.assertEqual(env.data.project, str(self.project.resolve()))

def test_check_json_reports_each_runtime_and_fails_with_data(self):
    # install_gsd current for claude, '1.0.0' for codex
    result = self.run_launcher('check', '--json')
    self.assertEqual(result.returncode, 1)
    env = CheckEnvelope.model_validate_json(result.stdout, strict=True)
    self.assertEqual([(r.runtime, r.ok, r.reason) for r in env.data.results],
                     [('claude', True, 'ok'), ('codex', False, 'below_minimum')])
    self.assertEqual(env.error.kind, 'requirements')

def test_check_json_unverifiable_install(self):       # no install at all -> reason 'unverifiable'
def test_check_json_single_runtime(self):             # `check claude --json` -> one result, exit 0
def test_policy_text_and_json(self):
    # text: stdout == f'Policy valid: {project}/gsd-cli.config.json\n', exit 0
    # json: env.data.policy == file contents; env.data.differs_from_shipped == []
def test_policy_reports_local_differences(self):
    # set agent_levels['gsd-planner'] = 'low' -> differs_from_shipped == ['agent_levels.gsd-planner']
def test_invalid_policy_is_policy_error(self):
    # set phase_defaults.planning = 'huge' -> exit 1, data None, kind 'policy',
    # message startswith 'phase_defaults.planning'
def test_missing_policy_is_config_error(self):        # no init -> kind 'config', message mentions gsd-cli init
def test_json_reads_write_nothing(self):
    # after init and one launch, snapshot bytes+mtime of every file under project and state dir;
    # also create .planning/.gsd-cli-journal.json; run status/check/policy with --json; snapshot unchanged
```

In `tests/test_versions.py` add assertions for `reason` on the three existing outcomes.

- [ ] **Step 2: Run** — expect failures.

- [ ] **Step 3: Implement.**
  - `CheckResult.reason`, set at the three return sites in `check_installation`. `format_result` is unchanged.
  - `status_command` and `check_command` take `--json` (`is_flag`). JSON branches build the envelope and call `emit`. A failed check: `ok=False`, full `data`, `error=ErrorInfo(kind='requirements', message=<the existing ClickException message>)`.
  - New `@cli.command('policy')` with `--json`: `root = config.discover()`, `policy = project_policy(root)`, `differs = config.changed_paths(load_default(), policy)`. Text: `Policy valid: <root>/gsd-cli.config.json`. Help text: `Validate project policy and show it.`
  - Replace Task 1's generic fallback in `failure` for these three commands; remove the `expectedFailure` marker.

- [ ] **Step 4: Run** new tests and the full suite — all pass.

- [ ] **Step 5: Commit** — `Add JSON output for status and check and a policy command`.

---

### Task 3: `policy-file` model and the `schema` command

**Files:**
- Create: `gsd_cli/policy_model.py`, `tests/test_policy_model.py`
- Modify: `gsd_cli/models.py` (registry), `gsd_cli/cli.py`
- Test: `tests/test_json_output.py`

**Interfaces — produces:**

```python
# gsd_cli/policy_model.py
class PolicyFile(BaseModel)     # extra='forbid'; mirrors the structural rules of policy.validate
# registered in models.SCHEMAS under 'policy-file'
```

`PolicyFile` builds its enums from `policy.LEVELS`, `policy.EFFORTS`, `policy.PHASES`, `policy.RUNTIMES` (for example `Literal[policy.LEVELS]`), uses the agent-name pattern `gsd-[a-z0-9-]+` and the workflow-name pattern `[a-z][a-z0-9-]*` for dictionary keys, and encodes the per-runtime differences `policy.validate` enforces (Claude `agent_model` is one of `fable, opus, sonnet, haiku`; Claude session and reviewer efforts are `LEVELS`, Codex and opencode are `EFFORTS`). `gsd_defaults` is a free-form object. Its docstring, which becomes the schema `description`, states that the launcher validates with `policy.validate` and that cross-references are not expressed.

- [ ] **Step 1: Write failing tests.**

```python
# tests/test_policy_model.py
def test_starter_and_example_validate(self):
    for data in (load_default(), json.loads(Path('examples/gsd-config-example.json').read_text())):
        PolicyFile.model_validate(data)

def test_structural_rejections_match_policy_validate(self):
    mutations = [   # (dotted path, bad value)
        ('schema_version', 2), ('phase_defaults.planning', 'huge'),
        ('runtimes.claude.high.agent_model', 'claude-opus-5-5'),
        ('runtimes.claude.high.session_effort', 'xhigh'),
        ('agent_levels.planner', 'high'), ('agent_efforts.gsd-planner', 'max'),
        ('reviewers.fable-review.cli', 'gemini'), ('reviewer_efforts.claude', 'xhigh'),
        ('workflows.plan.permissions.claude', 'yolo'), ('workflows.plan.parallel_reviews', 'yes'),
        ('extra_key', 1),
    ]
    for path, value in mutations:
        with self.subTest(path):
            data = mutated(load_default(), path, value)
            with self.assertRaises(PolicyError): validate(data)
            with self.assertRaises(ValidationError): PolicyFile.model_validate(data)

def test_missing_required_key_rejected(self):      # delete 'gsd' -> both reject
def test_codex_accepts_xhigh(self):                # runtimes.codex.high.session_effort='xhigh' -> both accept

# tests/test_json_output.py, class SchemaCommandTests
def test_lists_names_outside_a_project(self):
    result = self.run_launcher('schema', cwd=self.root)
    self.assertEqual(result.stdout.split(),
                     ['check', 'error', 'policy', 'policy-file', 'preview', 'sessions', 'status'])
def test_prints_generated_schema(self):
    for name, model in models.SCHEMAS.items():
        self.assertEqual(json.loads(self.run_launcher('schema', name).stdout), model.model_json_schema())
def test_unknown_name_is_usage_error(self):        # exit 2, 'policy-file' appears in the message
```

`test_lists_names…` and `test_prints_generated_schema` cover `preview` and `sessions` only after Tasks 4 and 6 register them; until then assert against `sorted(models.SCHEMAS)`.

- [ ] **Step 2: Run** — expect failures.

- [ ] **Step 3: Implement** `PolicyFile`, register it, and add `@cli.command('schema')` with an optional `NAME` argument. It must not call `config.discover()`. No argument: sorted names, one per line. With a name: `json.dumps(model.model_json_schema(), indent=2, ensure_ascii=True)` plus a newline. Unknown name: `click.UsageError` listing the names. Help: `Print the JSON Schema of a machine-readable output.`

- [ ] **Step 4: Run** new tests and the full suite — all pass.

- [ ] **Step 5: Commit** — `Add generated JSON schemas and a schema command`.

---

### Task 4: structured findings and `--config --json`

**Files:**
- Modify: `gsd_cli/preview.py`, `gsd_cli/models.py`, `gsd_cli/cli.py`
- Test: `tests/test_preview.py`

**Interfaces — produces:**

```python
# gsd_cli/preview.py
class Finding(NamedTuple): code: str; severity: str; message: str
def findings(model, effort, result, runtime, session_effort, forwarded, aliases) -> list[Finding]
def compare(...) -> tuple[str, list[str]]     # unchanged signature and results, now derived from findings()
def report(root, workflow, runtime, level, policy, resolved, data, captured, argv,
           forwarded, inspection) -> models.PreviewData

# gsd_cli/models.py
FindingCode = Literal['model_mismatch', 'effort_mismatch', 'effort_clamped', 'installed_effort_mismatch',
                      'model_unknown', 'effort_unknown', 'forwarded_may_override', 'installed_effort_unknown',
                      'inherit_depends_on_forwarded', 'propagation_unknown', 'unregistered_agent',
                      'alias_equivalent', 'inherits_session_effort']
class FindingModel(Model): code: FindingCode; severity: Literal['mismatch', 'unknown', 'note']; message: str
class ResolvedRow(BaseModel):       # extra='allow'; typed: the keys resolver.validate_result requires
class Expected(Model): model: str | None; effort: str | None; model_source: str; effort_source: str
class AgentRow(Model):
    agent: str; phase: str; in_workflow: bool; expected: Expected; resolved: ResolvedRow | None
    check: Literal['ok', 'mismatch', 'unknown']; findings: list[FindingModel]
class SessionRequest(Model): model: str; effort: str; permissions: Literal['bypass', 'normal']; argv: list[str]; forwarded: list[str]
class ReviewerRow(Model): name: str; cli: str | None; model: str | None; effort: str | None
class GsdContext(Model): source: str | None; workstream: str; loader_differences: list[str]
class PreviewData(Model):
    project: str; workflow: str; runtime: Literal['claude', 'codex']; level: Literal['low', 'medium', 'high']
    complete: bool; session: SessionRequest; reviewers: list[ReviewerRow]; installation: CheckEntry
    agents: list[AgentRow]; gsd_context: GsdContext | None
    pending_capture: list[str]; diagnostics: list[str]; config: dict[str, Any]
class PreviewEnvelope(Envelope[PreviewData]): command: Literal['preview'] = 'preview'
```

Finding codes map one-to-one onto the branches of today's `compare`, in this order of appearance in the function:

| Branch (today's note text) | code | severity |
|---|---|---|
| model expectation or resolution unknown | `model_unknown` | unknown |
| model alias equivalence confirmed… | `alias_equivalent` | note |
| model expected X, resolved Y | `model_mismatch` | mismatch |
| effort expectation or resolution unknown | `effort_unknown` | unknown |
| effort expected X, resolved Y | `effort_mismatch` | mismatch |
| effort clamped to… | `effort_clamped` | mismatch |
| installed effort inherits the session | `inherits_session_effort` | note |
| forwarded options may override inherited session effort | `forwarded_may_override` | unknown |
| installed Claude effort unknown… | `installed_effort_unknown` | unknown |
| requested inherited effort depends on forwarded… | `inherit_depends_on_forwarded` | unknown |
| installed effort expected X, found Y | `installed_effort_mismatch` | mismatch |
| runtime effort propagation unsupported or unknown | `propagation_unknown` | unknown |
| agent is not registered… | `unregistered_agent` | unknown |

`report` details: `agents` is the same name set and ordering as `render` (sorted by phase, then name); `in_workflow` is the `render_compact` phase filter; `phase` falls back to `'unknown'`; `session.permissions` is `'bypass'` when any `argv` item starts with `--dangerously-`; `reviewers` are built as `render` builds its reviewer rows; `gsd_context` is `None` when `inspection['context']` is empty, otherwise source, `inspection.get('workstream', '')` and `config.changed_paths(data, context['config'])`; `findings` are ordered mismatches, unknowns, notes.

- [ ] **Step 1: Write failing tests** in `tests/test_preview.py`.

```python
# unit, next to the existing compare tests
def test_findings_codes_cover_each_branch(self):     # one case per table row -> expected code and severity
def test_compare_is_unchanged(self):                  # for those same cases compare() returns the
                                                      # status and message list it returned before this task
# integration (Node-gated class), run via the launcher
def test_config_json_reports_session_agents_and_reviewers(self):
    result = self.run_launcher('plan', 'claude', 'high', '--config', '--json')
    env = PreviewEnvelope.model_validate_json(result.stdout, strict=True)
    self.assertTrue(env.ok and env.data.complete)
    self.assertEqual((env.data.workflow, env.data.runtime, env.data.level), ('plan', 'claude', 'high'))
    self.assertEqual(env.data.session.model, policy['runtimes']['claude']['high']['session_model'])
    self.assertEqual(env.data.session.permissions, 'normal')      # Claude planning never bypasses
    planner = next(a for a in env.data.agents if a.agent == 'gsd-planner')
    self.assertTrue(planner.in_workflow)
    self.assertEqual(planner.expected.effort_source, 'effort.agent_overrides.gsd-planner')
    self.assertEqual({a.agent for a in env.data.agents if not a.in_workflow}, {'gsd-executor'})
    self.assertEqual(env.data.config, <effective JSON printed by --config --details>)

def test_secure_changes_requested_permissions(self):  # exec codex --config --json -> 'bypass'; with --secure -> 'normal'
def test_installed_effort_drift_has_a_code(self):     # fixture row with effort_effective_source 'frontmatter'
                                                      # and a different effort -> 'installed_effort_mismatch', check 'mismatch'
def test_incomplete_inspection_fails_with_data(self): # fail_agent fixture -> exit 1, ok False,
                                                      # error.kind 'incomplete', data.complete False, diagnostics non-empty
def test_unknown_resolver_keys_pass_through(self):    # fixture adds 'future_key': 1 -> present in resolved, validates
def test_hostile_values_stay_inside_json_strings(self):
    # session_model 'evil\x1b[31m-é' in policy -> b'\x1b' not in stdout bytes; '\\u001b' and '\\u00e9' in stdout;
    # parsed session.model equals the original string
def test_json_requires_config_and_never_launches(self):
    # `plan claude --json` -> exit 2, usage envelope command 'preview', GSD_TEST_LOG not written
def test_json_and_details_are_exclusive(self):        # exit 2, usage envelope
def test_config_json_writes_nothing(self):            # same snapshot technique as Task 2
```

- [ ] **Step 2: Run** — expect failures.

- [ ] **Step 3: Implement** `Finding`, `findings`, the `compare` wrapper (status `NOT OK` if any mismatch, else `UNKNOWN` if any unknown, else `OK`; messages in mismatch, unknown, note order), the models, `report`, and the `--json` option on `workflow_command`. Order of checks in `launch`: `--details` without `--config`, `--json` without `--config`, `--json` with `--details`. Incomplete: `emit` an envelope with `ok=False`, the data, and `ErrorInfo(kind='incomplete', message='Configuration preview is incomplete; see diagnostics.')`. Register `'preview'`.

- [ ] **Step 4: Run** `tests.test_preview` and the full suite — all pass, including every pre-existing preview test untouched.

- [ ] **Step 5: Commit** — `Add JSON output for configuration previews with coded findings`.

---

### Task 5: `sessions` resolves through the non-mutating bridge

Its own behaviour change: text-mode `sessions` stops executing `gsd-tools.cjs` and starts honouring the selected installation.

**Files:**
- Modify: `gsd_cli/resolver.py`, `gsd_cli/sessions.py`, `tests/session_fixtures.py`
- Test: `tests/test_sessions.py`, `tests/test_resolver.py`

**Interfaces — produces:**

```python
# gsd_cli/resolver.py — extracted from inspect(), which now calls it
def run_bridge(installation: Path, runtime: str, snapshots: dict[str, dict],
               agents: list[str], env: dict) -> tuple[dict, list[str]]
    # writes snapshots into a temporary project, runs data/preview-resolver.cjs with node,
    # returns (payload with 'context' and 'rows', stderr lines);
    # raises config.ConfigError on a nonzero exit, oversize or malformed output,
    # subprocess.TimeoutExpired on timeout, OSError when node cannot be run

# gsd_cli/sessions.py
class Resolver:
    def __init__(self, root: Path) -> None
    available: bool
    def expected(self, launch: dict, agent_type: str) -> dict | None     # unchanged contract
```

`Resolver` rules:
- Installation: `versions.installation_dir(root, launch['runtime'], os.environ, Path.home())`. No minimum-version check.
- `available` becomes `False` when Node is missing, when `<installation>/bin/lib/commands.cjs` is not a file, or when `run_bridge` raises. A launch without a dict `config` returns `None` without changing `available`.
- One bridge call per `(launch time, runtime, agent_type)`, cached, with `snapshots={'.planning/config.json': launch['config']}`, `agents=[agent_type]`, `env=resolver.query_environment(root, runtime)`.
- The agent's row must pass `resolver.validate_result`; a missing or invalid row, or one with `unknown_agent` true, returns `None`.
- `sessions_command` constructs `Resolver(root)` and drops its own `gsd-tools.cjs` existence check; the "note: GSD resolver not available; profile comparison skipped" line stays.

- [ ] **Step 1: Rework the fixture and write failing tests.** `session_fixtures.install_resolver(home, bin_dir, table)` keeps its signature but now fakes the bridge protocol: the stub `node` reads the request JSON from stdin (`installation`, `runtime`, `agents`), reads `.planning/config.json` from its working directory, and prints `{"context": {"config": {...}, "source": "root"}, "rows": [{"agent": ..., "result": {...}}]}` with complete rows (every key `resolver.validate_result` requires), answering from the snapshot's `model_overrides`, else `table["runtime:agent"]`, else a row with `"unknown_agent": true`. It also creates `<home>/.<runtime>/gsd-core/bin/lib/commands.cjs` for both runtimes and a `bin/gsd-tools.cjs` whose execution would be detectable (the stub appends its argv to a log file).

```python
def test_sessions_never_executes_gsd_tools(self):
    # run `sessions` with agents present; the node stub's argv log shows only `-e <script>` calls,
    # none naming gsd-tools.cjs
def test_resolver_uses_project_local_installation(self):
    # project/.claude/gsd-core has the resolver modules, home has none -> resolver.available is True
def test_resolver_uses_runtime_installation_for_codex(self):
    # codex launch: request JSON 'installation' ends with '.codex/gsd-core'
def test_resolver_unavailable_without_modules(self):   # no bin/lib/commands.cjs -> available False, note printed
def test_bridge_failure_marks_unavailable(self):       # node stub exits 1 -> available False, no traceback

# tests/test_resolver.py
def test_run_bridge_returns_rows_for_requested_agents(self):   # real Node double from resolver_fixtures
```

Every existing test in `tests/test_sessions.py` that uses `install_resolver` keeps its assertions; only construction (`Resolver(root)`) changes.

- [ ] **Step 2: Run** `python -m unittest tests.test_sessions tests.test_resolver -v` — expect failures.

- [ ] **Step 3: Implement** `run_bridge` (move the scratch-directory, environment and subprocess code out of `inspect` without changing `inspect`'s results) and the new `Resolver`.

- [ ] **Step 4: Run** the full suite — all pass; `tests/test_preview.py` and `tests/test_resolver.py` pass unmodified apart from the added test.

- [ ] **Step 5: Commit** — `Resolve session expectations without executing gsd-tools`. The body states that `sessions` previously ran the installed `gsd-tools.cjs` from `~/.claude/gsd-core`, whose bootstrap can modify the installation, and now uses the preview bridge against the selected installation.

---

### Task 6: `sessions --json`

**Files:**
- Modify: `gsd_cli/sessions.py`, `gsd_cli/models.py`, `gsd_cli/cli.py`
- Test: `tests/test_sessions.py`

**Interfaces — produces:**

```python
# gsd_cli/sessions.py
class SessionsError(ValueError)        # str(exc) is the exact text sys.exit() printed before
def parse_args(args: list[str]) -> tuple[list[str], bool, str | None, bool]   # runtimes, picking, pick, as_json
def report(root: Path, runtimes: list[str], picking: bool, pick: str | None) -> models.SessionsData

# gsd_cli/models.py
class LaunchSummary(Model):
    time: str | None; profile: str | None; workflow: str | None; level: str | None
    session_model: str | None; session_effort: str | None; forwarded_args: list[str]
class RunModel(Model):
    runtime: Literal['claude', 'codex']; run_id: str; kind: Literal['session', 'agent', 'reviewer']; cwd: str
    start: str; end: str                       # UTC, 'YYYY-MM-DDTHH:MM:SSZ'
    model: str | None; effort: str | None; effort_varied: bool; advisor: str | None; agent_type: str | None
    requested_model: str | None; requested_effort: str | None; resumed: bool; cleared: bool
    marks: list[str]; mismatch: bool; launch: LaunchSummary | None; children: list['RunModel']
class SessionsData(Model): project: str; resolver_available: bool; sessions: list[RunModel]; older: list[RunModel]
class SessionsEnvelope(Envelope[SessionsData]): command: Literal['sessions'] = 'sessions'
```

Rules:
- `sessions_command` raises `SessionsError` where it called `sys.exit(...)`. `cli.main` catches it: text mode prints `str(exc)` to stderr unprefixed and exits 1 (identical to today); JSON mode emits `kind='usage'` with exit 1.
- `--json` is accepted anywhere among the `sessions` arguments; repeating it is harmless, as with a Click flag.
- Default: `sessions` = newest three, children loaded and checked. `--pick N`: that one older session. `--pick` without a number: `sessions=[]`, `older` = older top-level runs with `children=[]`, `marks=[]`, `mismatch=False`, in listing order (index 0 is pick 1); stdin is never read.
- `mismatch` is true when any mark starts with `!`. `LaunchSummary.forwarded_args` comes from `launch_args()`; other fields are the record's value when it is a string, else `None`.
- `resolver_available` is the `Resolver`'s `available` after checking (false when Node is missing).
- No sessions: success with empty lists.

- [ ] **Step 1: Write failing tests.**

```python
def test_json_recent_sessions_with_children_and_launch(self):
    # one claude session with a gsd-executor agent and a matching launch record
    env = SessionsEnvelope.model_validate_json(run('sessions', '--json').stdout, strict=True)
    s = env.data.sessions[0]
    self.assertEqual((s.kind, s.runtime, s.launch.profile), ('session', 'claude', 'exec/medium'))
    self.assertEqual(s.children[0].agent_type, 'gsd-executor')
    self.assertRegex(s.start, r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
    self.assertEqual(env.data.older, [])

def test_json_marks_mismatch(self):             # session ran another model than the launch requested
                                                # -> marks == ['! profile expects <model>'], mismatch True
def test_json_never_exports_embedded_configs(self):
    # launch record config contains the marker string 'SECRET-MARKER' -> not in stdout
def test_json_pick_lists_older_without_prompting(self):
    # five sessions; `sessions --pick --json` with stdin=subprocess.DEVNULL -> sessions == [],
    # len(older) == 2, older[0].children == []
def test_json_pick_number_selects_listing_entry(self):   # --pick 2 --json -> run_id == older[1].run_id
def test_json_pick_out_of_range_is_usage_error(self):    # exit 1, kind 'usage', message 'Error: no session 9'
def test_json_bad_argument_is_usage_error(self):         # `sessions bogus --json` -> exit 1, kind 'usage'
def test_json_no_sessions_is_success(self):              # ok True, both lists empty
def test_json_old_launch_record_and_no_node(self):
    # record without workflow/level and with forwarded_args 'oops'; PATH without node
    # -> ok True, launch.workflow is None, launch.forwarded_args == [], resolver_available False
def test_json_filters_by_runtime(self):                  # `sessions codex --json` -> only codex runs
def test_text_errors_unchanged(self):                    # usage and 'no session' text, stderr, exit 1 as before
def test_json_sessions_writes_nothing(self):
```

- [ ] **Step 2: Run** — expect failures.

- [ ] **Step 3: Implement** `SessionsError`, `parse_args`, `report` (reusing `link`, `load_claude_agents`, `check`), the models and registration, and the JSON branch. The text path keeps printing exactly what it prints today.

- [ ] **Step 4: Run** the full suite — all pass. The `schema` listing test from Task 3 now expects all seven names.

- [ ] **Step 5: Commit** — `Add JSON output for sessions`.

---

### Task 7: Documentation, project rules and changelog

**Files:**
- Create: `docs/json-output.md`
- Modify: `mkdocs.yml`, `README.md`, `docs/LAUNCHER.md`, `docs/checks.md`, `docs/solution.md`, `AGENTS.md`, `CHANGELOG.md`, `taskfile.yaml` (the `install` description mentions Click alone)

- [ ] **Step 1: Write `docs/json-output.md`** ("Machine-readable output", added to the MkDocs `nav` after "Check commands"): the envelope and its fields; one section per command with a real example captured from the tool; error kinds; check `reason` values; the finding-code table with severities and a sentence that `installed_effort_mismatch` is effort drift; the `schema` command and names; how to map `policy-file` in an editor (save `gsd-cli schema policy-file` to a file and map it to `gsd-cli.config.json` in the editor's JSON Schema settings; the policy file itself must not contain `$schema`); the read-only guarantee; the compatibility rule (fields may be added within `schema_version` 1).

- [ ] **Step 2: Update the rest.**
  - `AGENTS.md`: command list gains `policy`, `schema` and the `--json` forms; the dependency sentence becomes "Avoid dependencies beyond Click, Pydantic and the standard library. Pydantic defines machine-readable output and its schemas only."; the module list gains `models.py` and `policy_model.py`; the `sessions.py` line notes it resolves through the preview bridge.
  - `README.md`, `docs/LAUNCHER.md`, `docs/solution.md`: mention Pydantic wherever Click is named as the installed dependency; add the new commands and flags to the command references.
  - `docs/checks.md`: `check --json`, `policy`, `--config --json`, `sessions --json`, and that `sessions` no longer runs `gsd-tools.cjs`.
  - `CHANGELOG.md`, under Unreleased: **Added** (JSON output, `policy`, `schema`, coded findings); **Changed** (`sessions` resolves through the non-mutating bridge and honours project-local and overridden installations; new runtime dependency `pydantic>=2,<3`); a clearly marked breaking note that `policy` and `schema` are now reserved workflow names.

- [ ] **Step 3: Verify.**

Run: `uv run --isolated --no-project --with-requirements docs/requirements.txt mkdocs build --strict` — builds without warnings.
Run: `python -m unittest discover -s tests -v` — all pass.
Run: `python -m gsd_cli --help` — lists `policy` and `schema`.

- [ ] **Step 4: Commit** — `Document machine-readable output and the Pydantic dependency`.

---

## Done when

- The full suite passes on Python 3.10 and 3.11 with Pydantic 2 installed.
- In a real GSD project, `gsd-cli status --json`, `check --json`, `policy --json`, `plan claude --config --json` and `sessions --json` each print one JSON document that validates against `gsd-cli schema <name>`.
- No release is cut and nothing is pushed; versioning (expected 2.1.0) is the maintainer's step.
