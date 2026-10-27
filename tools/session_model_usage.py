#!/usr/bin/env python3
"""Which model did which GSD agent run on, and how many tokens did it spend?

Offline analysis of local CLI transcripts. Standard library only. Nothing is
sent anywhere; the script only reads log files under the home directory.

Commands:
  session_model_usage.py claude [--since DATE] [--projects DIR] [--all]
      One block per Claude Code session that spawned GSD agents: cwd, session
      model, orchestrator token usage, every Agent spawn as agent@model with
      the subagent's own token usage, orchestrator file edits, and prompts that
      mention gsd commands or --fix.
  session_model_usage.py timeline SESSION_JSONL
      Ordered events of one Claude Code session: user prompts, spawns (with the
      head of the prompt), orchestrator edits, git commits, assistant text that
      mentions review/fix/gap.
  session_model_usage.py codex [--since DATE] [--sessions DIR]
      One line per Codex rollout: cwd, agent role (orchestrator or subagent),
      model, total token usage, and every spawn_agent call as agent_type@model.
  session_model_usage.py resolve [--runtime claude|codex] [AGENT ...]
      Run the real GSD resolver (gsd-tools query resolve-model) for the given
      agents from the current directory, which must be inside a GSD project.

Token usage is deduplicated per message id (Claude Code writes one line per
content block, all carrying the same usage). Output tokens are the best cost
proxy; cache reads are listed because they dominate volume.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HOME = Path.home()
CLAUDE_PROJECTS = HOME / ".claude" / "projects"
CODEX_SESSIONS = HOME / ".codex" / "sessions"
GSD_TOOLS = HOME / ".claude" / "gsd-core" / "bin" / "gsd-tools.cjs"
DEFAULT_AGENTS = [
    "gsd-executor", "gsd-code-reviewer", "gsd-code-fixer", "gsd-verifier",
    "gsd-ui-auditor", "gsd-security-auditor", "gsd-nyquist-auditor",
    "gsd-debugger", "gsd-planner", "gsd-phase-researcher",
]
PROMPT_PATTERN = re.compile(r"gsd-[a-z-]+|--fix|--all|--auto", re.IGNORECASE)
TEXT_PATTERN = re.compile(r"REVIEW|fix|gap|BLOCKER|WARNING", re.IGNORECASE)


# ---------------------------------------------------------------- helpers

def iter_json_lines(path: Path):
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


class Usage:
    __slots__ = ("turns", "inp", "out", "cache_read", "cache_write", "_seen")

    def __init__(self) -> None:
        self.turns = 0
        self.inp = self.out = self.cache_read = self.cache_write = 0
        self._seen: set[str] = set()

    def add(self, message: dict) -> None:
        usage = message.get("usage") or {}
        if not usage:
            return
        key = message.get("id") or ""
        if key and key in self._seen:
            return
        if key:
            self._seen.add(key)
        self.turns += 1
        self.inp += usage.get("input_tokens", 0) or 0
        self.out += usage.get("output_tokens", 0) or 0
        self.cache_read += usage.get("cache_read_input_tokens", 0) or 0
        self.cache_write += usage.get("cache_creation_input_tokens", 0) or 0

    def merge(self, other: "Usage") -> None:
        self.turns += other.turns
        self.inp += other.inp
        self.out += other.out
        self.cache_read += other.cache_read
        self.cache_write += other.cache_write

    def __str__(self) -> str:
        return (f"turns={self.turns} out={self.out:,} in={self.inp:,} "
                f"cache_read={self.cache_read:,} cache_write={self.cache_write:,}")


def tool_uses(message: dict):
    content = message.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            yield block.get("name") or "", block.get("input") or {}


def text_blocks(message: dict):
    content = message.get("content")
    if isinstance(content, str):
        yield content
        return
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                yield block.get("text") or ""


def since_ok(timestamp: str | None, since: str | None) -> bool:
    return not since or not timestamp or timestamp[:10] >= since


def squash(text: str, limit: int) -> str:
    return re.sub(r"\s+", " ", text)[:limit]


# ---------------------------------------------------------------- claude

def scan_claude_session(path: Path) -> dict:
    info = {
        "path": path, "cwd": None, "start": None, "models": defaultdict(int),
        "orchestrator": Usage(), "spawns": defaultdict(int), "edits": 0,
        "prompts": [],
    }
    for record in iter_json_lines(path):
        if info["start"] is None and record.get("timestamp"):
            info["start"] = record["timestamp"]
        if record.get("cwd"):
            info["cwd"] = record["cwd"]
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        if record.get("type") == "assistant":
            model = message.get("model")
            if model:
                info["models"][model] += 1
            info["orchestrator"].add(message)
            for name, inputs in tool_uses(message):
                if name in ("Agent", "Task"):
                    key = f"{inputs.get('subagent_type') or '?'}@{inputs.get('model') or '(inherit)'}"
                    info["spawns"][key] += 1
                elif name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                    info["edits"] += 1
        elif record.get("type") == "user":
            content = message.get("content")
            if isinstance(content, str) and "task-notification" not in content:
                hits = sorted(set(m.lower() for m in PROMPT_PATTERN.findall(content)))
                if hits:
                    info["prompts"].append(" ".join(hits))
    return info


def subagent_usage(session_path: Path) -> dict[str, tuple[int, Usage]]:
    """agent@model -> (runs, usage) from <session>/subagents/*.jsonl."""
    result: dict[str, tuple[int, Usage]] = {}
    folder = session_path.with_suffix("") / "subagents"
    if not folder.is_dir():
        return result
    for transcript in sorted(folder.glob("*.jsonl")):
        meta_path = transcript.with_suffix(".meta.json")
        agent_type, model = "?", "(inherit)"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            agent_type = meta.get("agentType") or agent_type
            model = meta.get("model") or model
        except (OSError, json.JSONDecodeError):
            pass
        usage = Usage()
        for record in iter_json_lines(transcript):
            if record.get("type") == "assistant" and isinstance(record.get("message"), dict):
                usage.add(record["message"])
        runs, total = result.get(f"{agent_type}@{model}", (0, Usage()))
        total.merge(usage)
        result[f"{agent_type}@{model}"] = (runs + 1, total)
    return result


def cmd_claude(args: argparse.Namespace) -> None:
    root = Path(args.projects)
    if not root.is_dir():
        sys.exit(f"No Claude Code project logs under {root}")
    sessions = sorted(root.glob("*/*.jsonl"))
    shown = 0
    for path in sessions:
        info = scan_claude_session(path)
        if not since_ok(info["start"], args.since):
            continue
        gsd_spawns = {k: v for k, v in info["spawns"].items() if k.startswith("gsd-")}
        if not args.all and not gsd_spawns:
            continue
        shown += 1
        print(f"\n### {path.stem[:8]}  {info['start']}  cwd={info['cwd']}")
        print(f"  session models: {dict(info['models'])}")
        print(f"  orchestrator:   {info['orchestrator']}   edits by orchestrator: {info['edits']}")
        per_agent = subagent_usage(path)
        for key, count in sorted(info["spawns"].items()):
            runs, usage = per_agent.get(key, (0, None))
            detail = f"  {usage}" if usage else "  (no subagent transcript found)"
            print(f"  spawn {key:<34} x{count}{detail}")
        for key in sorted(set(per_agent) - set(info["spawns"])):
            runs, usage = per_agent[key]
            print(f"  spawn {key:<34} x{runs}  {usage}   (transcript only)")
        if info["prompts"]:
            print(f"  prompts mentioning: {'; '.join(info['prompts'][:6])}")
    print(f"\n{shown} session(s) shown of {len(sessions)} under {root}")


def cmd_timeline(args: argparse.Namespace) -> None:
    path = Path(args.session)
    for record in iter_json_lines(path):
        stamp = (record.get("timestamp") or "")[11:19]
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        if record.get("type") == "assistant":
            for name, inputs in tool_uses(message):
                if name in ("Agent", "Task"):
                    head = squash(str(inputs.get("prompt") or ""), 110)
                    print(f"{stamp} SPAWN  {inputs.get('subagent_type')} @ {inputs.get('model') or '(inherit)'} :: {head}")
                elif name in ("Edit", "Write", "MultiEdit"):
                    print(f"{stamp} EDIT   {inputs.get('file_path')}")
                elif name == "Bash" and "git commit" in str(inputs.get("command") or ""):
                    subject = re.search(r"-m ['\"]([^'\"\n]{0,80})", inputs.get("command") or "")
                    print(f"{stamp} COMMIT {subject.group(1) if subject else ''}")
            for text in text_blocks(message):
                if TEXT_PATTERN.search(text):
                    print(f"{stamp} TEXT   {squash(text, 140)}")
        elif record.get("type") == "user":
            content = message.get("content")
            if isinstance(content, str) and "task-notification" not in content:
                print(f"{stamp} USER   {squash(content, 140)}")


# ---------------------------------------------------------------- codex

def cmd_codex(args: argparse.Namespace) -> None:
    root = Path(args.sessions)
    if not root.is_dir():
        sys.exit(f"No Codex session logs under {root}")
    rows = []
    for path in sorted(root.rglob("rollout-*.jsonl")):
        cwd = role = None
        models: dict[str, int] = defaultdict(int)
        spawns: dict[str, int] = defaultdict(int)
        totals = None
        start = None
        for record in iter_json_lines(path):
            payload = record.get("payload") or {}
            if start is None:
                start = record.get("timestamp")
            if not isinstance(payload, dict):
                continue
            if record.get("type") == "session_meta":
                cwd = payload.get("cwd")
                source = payload.get("source")
                spawn = {}
                if isinstance(source, dict):
                    subagent = source.get("subagent")
                    if isinstance(subagent, dict):
                        spawn = subagent.get("thread_spawn") or {}
                role = spawn.get("agent_role") or "orchestrator"
            if payload.get("model"):
                models[payload["model"]] += 1
            if payload.get("type") == "token_count":
                totals = (payload.get("info") or {}).get("total_token_usage") or totals
            if payload.get("type") == "function_call" and payload.get("name") == "spawn_agent":
                try:
                    call = json.loads(payload.get("arguments") or "{}")
                except json.JSONDecodeError:
                    call = {}
                spawns[f"{call.get('agent_type') or '?'}@{call.get('model') or '(inherit)'}"] += 1
        if not since_ok(start, args.since):
            continue
        rows.append((start, cwd, role, dict(models), totals, dict(spawns), path))
    for start, cwd, role, models, totals, spawns, path in rows:
        out = f"out={totals.get('output_tokens', 0):,} in={totals.get('input_tokens', 0):,} cached={totals.get('cached_input_tokens', 0):,}" if totals else "no token_count"
        print(f"{start}  {role or '?':<24} models={models}  {out}  cwd={cwd}")
        for key, count in sorted(spawns.items()):
            print(f"    spawn_agent {key} x{count}")
    print(f"\n{len(rows)} rollout(s) under {root}")


# ---------------------------------------------------------------- resolve

def cmd_resolve(args: argparse.Namespace) -> None:
    if not GSD_TOOLS.is_file():
        sys.exit(f"gsd-tools not found at {GSD_TOOLS}")
    if not any((d / ".planning" / "config.json").is_file() for d in (Path.cwd(), *Path.cwd().parents)):
        sys.exit("No .planning/config.json above the current directory; the resolver would "
                 "report GSD's built-in defaults, not a project's routing. Run inside a GSD project.")
    env = os.environ.copy()
    env["GSD_RUNTIME"] = args.runtime
    print(f"GSD_RUNTIME={args.runtime}  cwd={Path.cwd()}")
    for agent in args.agents or DEFAULT_AGENTS:
        result = subprocess.run(
            ["node", str(GSD_TOOLS), "query", "resolve-model", agent, "--raw"],
            capture_output=True, text=True, env=env, check=False,
        )
        print(f"  {agent:<26} -> {result.stdout.strip() or '(empty)'}")
        if result.returncode != 0:
            print(f"    stderr: {result.stderr.strip()[:200]}")


# ---------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    claude = sub.add_parser("claude")
    claude.add_argument("--since", help="only sessions starting on/after YYYY-MM-DD")
    claude.add_argument("--projects", default=str(CLAUDE_PROJECTS))
    claude.add_argument("--all", action="store_true", help="include sessions without GSD spawns")
    claude.set_defaults(func=cmd_claude)

    timeline = sub.add_parser("timeline")
    timeline.add_argument("session", help="path to a Claude Code session .jsonl")
    timeline.set_defaults(func=cmd_timeline)

    codex = sub.add_parser("codex")
    codex.add_argument("--since", help="only rollouts starting on/after YYYY-MM-DD")
    codex.add_argument("--sessions", default=str(CODEX_SESSIONS))
    codex.set_defaults(func=cmd_codex)

    resolve = sub.add_parser("resolve")
    resolve.add_argument("--runtime", default="claude", choices=("claude", "codex"))
    resolve.add_argument("agents", nargs="*")
    resolve.set_defaults(func=cmd_resolve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # let `| head` end the output quietly
    main()
