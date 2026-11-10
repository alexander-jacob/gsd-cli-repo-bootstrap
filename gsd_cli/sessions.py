"""Read-only session reports, including historical launcher records."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Historical compatibility only; never used to resolve a new launch.
REVIEWERS = {
    "fable-review": {"cli": "claude", "model": "claude-fable-5-1"},
    "astra-review": {"cli": "codex", "model": "gpt-6-astra"},
    "grok-review": {"cli": "opencode", "model": "openrouter/x-ai/grok-4.7"},
    "gemini-review": {"cli": "opencode", "model": "openrouter/google/gemini-4-argon"},
    "deepseek-review": {"cli": "opencode", "model": "openrouter/deepseek/deepseek-v3.2"},
}

@dataclass
class Run:
    """One session, subagent or reviewer run recovered from a runtime's logs."""
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
    cleared: bool = False           # Claude session started by /clear in a running CLI
    agents_from: Path | None = None # Claude log whose subagents are not loaded yet
    tool_inputs: dict = field(default_factory=dict)


REVIEW_PROMPT_PREFIX = "# Cross-AI Plan Review Request"


def most_common(values: list[str | None]) -> tuple[str | None, bool]:
    """Most frequent non-None value, and whether more than one distinct value occurred."""
    counts = Counter(value for value in values if value is not None)
    if not counts:
        return None, False
    return counts.most_common(1)[0][0], len(counts) > 1


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def read_jsonl(path: Path) -> list[dict]:
    """Parse a JSON-lines log, skipping blank, truncated or unreadable lines."""
    records = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return records
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def prompt_text(record: dict) -> str:
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def claude_run(records: list[dict], kind: str, run_id: str) -> Run | None:
    """Summarise one Claude log file; None when it holds no timestamped records."""
    times = [t for t in (parse_timestamp(r.get("timestamp")) for r in records) if t]
    if not times:
        return None
    assistants = [
        r for r in records
        if r.get("type") == "assistant" and isinstance(r.get("message"), dict)
    ]
    models = [
        a["message"].get("model") for a in assistants
        if a["message"].get("model") != "<synthetic>"
    ]
    model, _ = most_common(models)
    effort, varied = most_common([a.get("effort") for a in assistants])
    advisor, _ = most_common([a.get("advisorModel") for a in assistants])
    cwd = next((r["cwd"] for r in records if isinstance(r.get("cwd"), str)), "")
    return Run("claude", run_id, kind, cwd, min(times), max(times), model, effort,
               effort_varied=varied, advisor=advisor)


def claude_tool_uses(records: list[dict]) -> dict[str, dict]:
    """Agent/Task tool_use inputs in a log, keyed by tool_use id."""
    found = {}
    for record in records:
        if record.get("type") != "assistant":
            continue
        content = (record.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if (isinstance(block, dict) and block.get("type") == "tool_use"
                    and block.get("name") in ("Agent", "Task")):
                found[block.get("id")] = block.get("input") or {}
    return found


def is_review_prompt(prompt: str) -> bool:
    """Whether a headless prompt is a cross-AI review request; `claude -p -`
    records the prompt read from stdin behind a leading "-" line."""
    return prompt.lstrip().removeprefix("-").lstrip().startswith(REVIEW_PROMPT_PREFIX)


def started_by_clear(records: list[dict]) -> bool:
    """Whether the log's first SessionStart hook fired for /clear."""
    for record in records:
        attachment = record.get("attachment")
        if isinstance(attachment, dict) and attachment.get("hookEvent") == "SessionStart":
            return str(attachment.get("hookName", "")).endswith(":clear")
    return False


def read_claude_runs(root: Path) -> list[Run]:
    """Top-level Claude sessions and reviewers for root; their subagents are
    loaded later, for the runs actually shown, by load_claude_agents."""
    folder = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(root))
    runs = []
    for log in sorted(folder.glob("*.jsonl")):
        records = read_jsonl(log)
        first_cwd = next((r["cwd"] for r in records if isinstance(r.get("cwd"), str)), None)
        if first_cwd != str(root):
            continue
        first_prompt = next((prompt_text(r) for r in records if r.get("type") == "user"), "")
        headless = any(r.get("entrypoint") == "sdk-cli" for r in records)
        kind = "reviewer" if headless and is_review_prompt(first_prompt) else "session"
        session = claude_run(records, kind, log.stem)
        if session is None:
            continue
        session.cleared = started_by_clear(records)
        session.agents_from = log
        session.tool_inputs = claude_tool_uses(records)
        runs.append(session)
    return runs


def load_claude_agents(run: Run) -> None:
    """Nest the subagents of run and of every Claude run below it (reviewers),
    reading each log's subagent folder at most once."""
    for child in list(run.children):
        load_claude_agents(child)
    log, run.agents_from = run.agents_from, None
    if log is None:
        return
    tool_inputs = dict(run.tool_inputs)
    owners = {tool_id: run for tool_id in tool_inputs}
    agents = []
    for agent_log in sorted((log.parent / log.stem / "subagents").glob("agent-*.jsonl")):
        agent_records = read_jsonl(agent_log)
        agent = claude_run(agent_records, "agent", agent_log.stem.removeprefix("agent-"))
        if agent is None:
            continue
        try:
            meta = json.loads(agent_log.with_suffix(".meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        agent.agent_type = meta.get("agentType")
        agent.requested_model = meta.get("model")
        agent.cwd = agent.cwd or run.cwd
        agents.append((agent, meta.get("toolUseId")))
        for tool_id, tool_input in claude_tool_uses(agent_records).items():
            owners[tool_id] = agent
            tool_inputs[tool_id] = tool_input
    for agent, tool_id in agents:
        agent.requested_effort = (tool_inputs.get(tool_id) or {}).get("effort")
        parent = owners.get(tool_id, run)
        (run if parent is agent else parent).children.append(agent)
    if run.kind == "session":
        run.children.sort(key=lambda child: child.start)


def codex_first_record(path: Path) -> dict:
    """The session_meta payload on a rollout's first line; {} when unreadable."""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            record = json.loads(handle.readline())
    except (OSError, ValueError):
        return {}
    if not isinstance(record, dict) or record.get("type") != "session_meta":
        return {}
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else {}


def read_codex_runs(root: Path) -> list[Run]:
    """Top-level Codex sessions and reviewers for root, with subagent threads nested."""
    logs = Path.home() / ".codex" / "sessions"
    threads: dict[str, tuple[Run, str | None]] = {}
    started: dict[str, dict] = {}
    spawn_args: dict[str, dict] = {}
    for log in sorted(logs.glob("**/rollout-*.jsonl")):
        meta = codex_first_record(log)
        if meta.get("cwd") != str(root) or not isinstance(meta.get("id"), str):
            continue
        records = read_jsonl(log)
        times = [t for t in (parse_timestamp(r.get("timestamp")) for r in records) if t]
        if not times:
            continue
        # Codex writes the rollout only at the first prompt; the session_meta
        # payload keeps the real creation time.
        created = parse_timestamp(meta.get("timestamp"))
        start = min(times + [created] if created else times)
        contexts = [r["payload"] for r in records
                    if r.get("type") == "turn_context" and isinstance(r.get("payload"), dict)]
        model, _ = most_common([c.get("model") for c in contexts])
        effort, varied = most_common([c.get("effort") for c in contexts])
        source = meta.get("source")
        spawn = {}
        if isinstance(source, dict):
            spawn = ((source.get("subagent") or {}).get("thread_spawn") or {})
        parent_id = spawn.get("parent_thread_id") if spawn else None
        if parent_id:
            kind = "agent"
        else:
            kind = "reviewer" if source == "exec" else "session"
        run = Run("codex", meta["id"], kind, meta["cwd"], start, max(times), model, effort,
                  effort_varied=varied, agent_type=spawn.get("agent_role") if spawn else None)
        threads[run.run_id] = (run, parent_id)
        for record in records:
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            item = payload.get("item")
            if isinstance(item, dict) and item.get("type") == "SubAgentActivity" \
                    and item.get("kind") == "started" and item.get("agent_thread_id"):
                started[item["agent_thread_id"]] = item
            elif payload.get("type") == "function_call" and payload.get("name") == "spawn_agent":
                try:
                    arguments = json.loads(payload.get("arguments") or "")
                except ValueError:
                    continue
                if isinstance(arguments, dict):
                    spawn_args[payload.get("call_id")] = arguments
    runs = []
    for run, parent_id in threads.values():
        if parent_id in threads:
            threads[parent_id][0].children.append(run)
        if parent_id:
            activity = started.get(run.run_id) or {}
            arguments = spawn_args.get(activity.get("id")) or {}
            run.requested_model = activity.get("model") or arguments.get("model")
            run.requested_effort = activity.get("reasoning_effort") or arguments.get("reasoning_effort")
            run.agent_type = run.agent_type or arguments.get("agent_type")
        if parent_id not in threads:
            runs.append(run)
    return runs


# A launch record matches a session that starts at most this long after it.
MATCH_WINDOW = timedelta(seconds=60)


def load_launches(root: Path) -> list[dict]:
    """Launch records for root, skipping malformed lines."""
    return [
        record for record in read_jsonl(launch_log_path())
        if record.get("project") == str(root) and isinstance(record.get("runtime"), str)
        and parse_timestamp(record.get("time")) is not None
    ]


def launch_args(launch: dict) -> list[str]:
    args = launch.get("forwarded_args")
    return [arg for arg in args if isinstance(arg, str)] if isinstance(args, list) else []


def resumes(launch: dict) -> bool:
    """Whether a launch resumed an earlier session rather than starting one."""
    args = launch_args(launch)
    if launch.get("runtime") == "codex":
        return args[:1] == ["resume"]
    return any(arg in ("--resume", "-r", "--continue", "-c") for arg in args)


def link(runs: list[Run], launches: list[dict]) -> list[Run]:
    """Nest reviewers under their triggering session and attach launch records;
    returns the top-level runs, newest first."""
    timed = sorted(((parse_timestamp(launch.get("time")), launch) for launch in launches),
                   key=lambda pair: pair[0])
    sessions = [run for run in runs if run.kind == "session"]
    top = [run for run in runs if run.kind != "reviewer"]
    for reviewer in (run for run in runs if run.kind == "reviewer"):
        hosts = [s for s in sessions if s.cwd == reviewer.cwd and s.start <= reviewer.start <= s.end]
        if hosts:
            max(hosts, key=lambda s: s.start).children.append(reviewer)
        else:
            reviewer.marks.append("reviewer, unattached")
            top.append(reviewer)
    for run in sessions:
        run.children.sort(key=lambda child: child.start)
    for session in sorted(sessions, key=lambda run: run.start):
        same = [(time, launch) for time, launch in timed if launch.get("runtime") == session.runtime]
        if session.cleared:
            # /clear starts a new log inside the launched process: continue the
            # previous session's launch unless a newer launch came in between.
            earlier = [s for s in sessions if s.runtime == session.runtime
                       and s.cwd == session.cwd and s.start < session.start]
            previous = max(earlier, key=lambda s: s.start) if earlier else None
            relaunched = previous is None or any(
                previous.start < time <= session.start for time, _ in same)
            session.launch = None if relaunched else previous.launch
        else:
            matches = [launch for time, launch in same
                       if time <= session.start and session.start - time <= MATCH_WINDOW]
            session.launch = matches[-1] if matches else None
        session.resumed = any(session.start < time <= session.end and resumes(launch)
                              for time, launch in same)
    return sorted(top, key=lambda run: run.start, reverse=True)


def model_matches(runtime: str, expected: str, actual: str | None) -> bool:
    """Equal IDs, or for Claude an alias matching the actual model's family."""
    if actual is None:
        return False
    return expected == actual or (runtime == "claude" and actual.startswith(f"claude-{expected}-"))


class Resolver:
    """Per-agent expected model and effort from the real GSD resolver, evaluated
    against a launch's config snapshot in a throwaway project directory."""

    def __init__(self) -> None:
        self.tools = Path.home() / ".claude" / "gsd-core" / "bin" / "gsd-tools.cjs"
        self.available = True
        self.cache: dict[tuple, dict | None] = {}

    def expected(self, launch: dict, agent_type: str) -> dict | None:
        """{"model", "effort", ...} for agent_type; None when unknown or unavailable."""
        key = (launch.get("time"), launch.get("runtime"), agent_type)
        if key not in self.cache:
            self.cache[key] = self.resolve(launch, agent_type) if self.available else None
        return self.cache[key]

    def resolve(self, launch: dict, agent_type: str) -> dict | None:
        node = shutil.which("node")
        config = launch.get("config")
        if node is None or not self.tools.is_file():
            self.available = False
            return None
        if not isinstance(config, dict) or not isinstance(launch.get("runtime"), str):
            return None
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / ".planning").mkdir()
            (Path(temp) / ".planning" / "config.json").write_text(json.dumps(config), encoding="utf-8")
            try:
                result = subprocess.run(
                    [node, str(self.tools), "query", "resolve-model", agent_type],
                    cwd=temp, env={**os.environ, "GSD_RUNTIME": launch["runtime"]},
                    capture_output=True, text=True, timeout=10, check=False,
                )
                answer = json.loads(result.stdout) if result.returncode == 0 else None
            except (OSError, subprocess.SubprocessError, ValueError):
                answer = None
        if not isinstance(answer, dict):
            self.available = False
            return None
        return None if answer.get("unknown_agent") else answer


def expected_value(entry: dict | None, key: str) -> str | None:
    # "inherit" means the session model, which the session line already checks.
    value = (entry or {}).get(key)
    return value if isinstance(value, str) and value and value != "inherit" else None


def overridden_at_launch(launch: dict) -> bool:
    return any(arg in ("--model", "-m") or arg.startswith("--model=")
               or "model_reasoning_effort=" in arg for arg in launch_args(launch))


def reviewer_name(runtime: str) -> str | None:
    """Name of the first REVIEWERS entry run through the given CLI."""
    return next((name for name, entry in REVIEWERS.items() if entry["cli"] == runtime), None)


def check(run: Run, resolver: Resolver, runtime: str, launch: dict | None) -> None:
    """Append mismatch marks to run and its descendants."""
    if run.kind == "reviewer":
        if launch and 'workflow' in launch:
            review = launch.get('config', {}).get('review', {})
            definitions = review.get('reviewer_instances', {})
            names = [name for name in review.get('default_reviewers', [])
                     if definitions.get(name, {}).get('cli') == runtime]
            # Logs do not identify an instance when several share an adapter.
            name = names[0] if len(names) == 1 else None
            expected = definitions[name].get('model') if name else None
            run.launch = launch
        else:
            name = reviewer_name(runtime)
            expected = REVIEWERS[name]["model"] if name else None
        if expected and run.model and not model_matches(runtime, expected, run.model):
            run.marks.append(f"! {name} expects {expected}")
        launch = None  # a reviewer's own subagents are not routed by the session's profile
    elif run.kind == "session":
        if launch and overridden_at_launch(launch):
            run.marks.append("overridden at launch")
        elif launch:
            model = expected_value(launch, "session_model")
            if model and run.model and not model_matches(runtime, model, run.model):
                run.marks.append(f"! profile expects {model}")
            effort = expected_value(launch, "session_effort")
            if runtime == "codex" and effort and run.effort and effort != run.effort:
                run.marks.append(f"! profile expects effort {effort}")
        if run.resumed:
            run.marks.append("resumed, profile may differ")
    else:
        if run.requested_model and run.model and not model_matches(runtime, run.requested_model, run.model):
            run.marks.append(f"! asked {run.requested_model}, ran {run.model}")
        if launch and run.agent_type and launch.get("runtime") == runtime:
            entry = resolver.expected(launch, run.agent_type)
            model, effort = expected_value(entry, "model"), expected_value(entry, "effort")
            if model and run.model and not model_matches(runtime, model, run.model):
                run.marks.append(f"! profile expects {model}")
            if effort and run.effort and effort != run.effort:
                run.marks.append(f"! profile expects effort {effort}")
    for child in run.children:
        check(child, resolver, child.runtime, launch)


def with_effort(model: str | None, effort: str | None) -> str:
    return f"{model or '?'}/{effort}" if effort else model or "?"


def render(run: Run, depth: int = 0) -> list[str]:
    """Output lines for a run and, indented two spaces per level, its children."""
    if run.kind == "session":
        effort = f"{run.effort} (varied)" if run.effort_varied else run.effort
        profile = run.launch.get("profile") if run.launch else None
        parts = [f"{run.runtime:<6}", run.start.astimezone().strftime("%Y-%m-%d %H:%M"),
                 f"profile: {profile or 'unknown'}", f"{run.model or '?'}", f"{effort or '?'}"]
        if run.advisor:
            parts.append(f"advisor {run.advisor}")
    elif run.kind == "reviewer":
        parts = [f"reviewer {(run.model if run.launch and 'workflow' in run.launch else reviewer_name(run.runtime)) or run.model or '?'}",
                 f"ran {run.model or '?'}"]
    else:
        parts = [f"{run.agent_type or 'agent'}",
                 f"asked {with_effort(run.requested_model, run.requested_effort)}",
                 f"ran {with_effort(run.model, run.effort)}"]
    line = "  ".join(parts + run.marks)
    return ["  " * depth + line] + [row for child in run.children for row in render(child, depth + 1)]


SESSIONS_USAGE = "Usage: gsd-cli sessions [claude|codex] [--pick [N]]"
RECENT_SESSIONS = 3


def sessions_command(root: Path, args: list[str]) -> None:
    """Show the newest sessions of a project; --pick browses older ones."""
    runtimes: list[str] = []
    pick: str | None = None
    picking = False
    items = iter(args)
    for arg in items:
        if arg in ("claude", "codex") and arg not in runtimes:
            runtimes.append(arg)
        elif arg == "--pick" and not picking:
            picking = True
        elif picking and pick is None and arg.isdigit():
            pick = arg
        else:
            sys.exit(SESSIONS_USAGE)
    if len(runtimes) > 1:
        sys.exit(SESSIONS_USAGE)
    readers = {"claude": read_claude_runs, "codex": read_codex_runs}
    runs = [run for name in (runtimes or list(readers)) for run in readers[name](root)]
    top = link(runs, [launch for launch in load_launches(root)
                      if not runtimes or launch["runtime"] in runtimes])
    if not top:
        print(f"No Claude or Codex sessions found for {root}.")
        return
    recent, older = top[:RECENT_SESSIONS], top[RECENT_SESSIONS:]
    if picking:
        if pick is None:
            for number, run in enumerate(older, 1):
                print(f"{number}) {render(run)[0]}")
            if not older:
                print("No older sessions.")
                return
            if not sys.stdin.isatty():
                return
            try:
                pick = input("Session number: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
        if not pick.isdigit() or not 1 <= int(pick) <= len(older):
            sys.exit(f"Error: no session {pick}")
        shown = [older[int(pick) - 1]]
    else:
        shown = recent
    resolver = Resolver()
    if shutil.which("node") is None or not resolver.tools.is_file():
        resolver.available = False
    for run in shown:
        load_claude_agents(run)
        check(run, resolver, run.runtime, run.launch)
        print("\n".join(render(run)))
    if not resolver.available:
        print("note: GSD resolver not available; profile comparison skipped")


def launch_log_path() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "gsd-cli" / "launches.jsonl"


def record_launch(root: Path, runtime: str, profile: str, session_model: str,
                  forwarded: list[str], data: dict, *, effort: str | None = None,
                  workflow: str | None = None, level: str | None = None, policy: dict | None = None) -> None:
    """Append one launch record (mode 0600: it embeds whole configs); a failure
    only warns."""
    try:
        defaults = json.loads((Path.home() / ".gsd" / "defaults.json").read_text(encoding="utf-8"))
    except (OSError, RuntimeError, ValueError):
        defaults = None
    record = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "project": str(root),
        "runtime": runtime,
        "profile": profile,
        "session_model": session_model,
        "session_effort": effort,
        "forwarded_args": forwarded,
        "config": data,
        "gsd_defaults": defaults,
    }
    if workflow is not None:
        record.update(workflow=workflow, level=level, policy=policy)
    try:
        log = launch_log_path()
        log.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            os.fchmod(fd, 0o600)
            handle.write(json.dumps(record) + "\n")
    except (OSError, RuntimeError) as exc:
        print(f"GSD: warning: could not write launch log: {exc}", file=sys.stderr)

