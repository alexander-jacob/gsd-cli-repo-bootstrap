"""Fixture writers for fake runtime logs used by the sessions tests."""

import json
import re
from datetime import timedelta
from pathlib import Path


def stamp(moment) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _assistant(cwd, session_id, moment, model, effort, advisor, entrypoint, tool_uses=()):
    content = [
        {"type": "tool_use", "id": tool_id, "name": "Agent", "input": tool_input}
        for tool_id, tool_input in tool_uses
    ] or [{"type": "text", "text": "ok"}]
    record = {
        "type": "assistant", "timestamp": stamp(moment), "cwd": str(cwd),
        "sessionId": session_id, "entrypoint": entrypoint,
        "message": {"model": model, "role": "assistant", "content": content},
        "effort": effort,
    }
    if advisor:
        record["advisorModel"] = advisor
    return record


def claude_session(home, cwd, session_id, start, model, effort, *, agents=(),
                   entrypoint="cli", prompt="hi", turns=2, advisor=None, start_hook=None):
    """Write a Claude session log plus subagent logs; each agent is a dict with
    id, type, requested, model, effort and parent (None or another agent id).
    start_hook ("startup", "clear", ...) writes a leading SessionStart hook
    attachment as Claude Code does for interactive sessions."""
    folder = Path(home) / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    folder.mkdir(parents=True, exist_ok=True)
    efforts = [effort] * turns if isinstance(effort, str) or effort is None else list(effort)
    spawns: dict = {}
    for agent in agents:
        spawns.setdefault(agent["parent"], []).append(agent)

    def tool_uses(owner):
        return [
            (f"toolu_{a['id']}", {"subagent_type": a["type"], "model": a["requested"],
                                  **({"effort": a["requested_effort"]} if a.get("requested_effort") else {})})
            for a in spawns.get(owner, [])
        ]

    def write(path, records):
        path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

    records = []
    if start_hook:
        records += [
            {"type": "mode", "mode": "normal", "sessionId": session_id},
            {"parentUuid": None, "isSidechain": False, "type": "attachment",
             "timestamp": stamp(start), "cwd": str(cwd), "sessionId": session_id,
             "entrypoint": entrypoint, "attachment": {
                 "type": "hook_success", "hookName": f"SessionStart:{start_hook}",
                 "toolUseID": "hook-1", "hookEvent": "SessionStart", "content": ""}},
        ]
    records.append({"type": "user", "timestamp": stamp(start), "cwd": str(cwd),
                    "sessionId": session_id, "entrypoint": entrypoint,
                    "message": {"role": "user", "content": prompt}})
    for index, turn_effort in enumerate(efforts):
        moment = start + timedelta(minutes=index + 1)
        records.append(_assistant(cwd, session_id, moment, model, turn_effort, advisor,
                                  entrypoint, tool_uses(None) if index == 0 else ()))
    write(folder / f"{session_id}.jsonl", records)

    sub = folder / session_id / "subagents"
    for number, agent in enumerate(agents, 1):
        sub.mkdir(parents=True, exist_ok=True)
        moment = start + timedelta(minutes=number, seconds=30)
        write(sub / f"agent-{agent['id']}.jsonl", [
            _assistant(cwd, session_id, moment, agent["model"], agent["effort"], None,
                       entrypoint, tool_uses(agent["id"])),
            _assistant(cwd, session_id, moment + timedelta(seconds=10), agent["model"],
                       agent["effort"], None, entrypoint),
        ])
        (sub / f"agent-{agent['id']}.meta.json").write_text(json.dumps({
            "agentType": agent["type"], "model": agent["requested"],
            "toolUseId": agent.get("tool_use_id", f"toolu_{agent['id']}"), "spawnDepth": 1 if agent["parent"] is None else 2,
        }), encoding="utf-8")
    return folder / f"{session_id}.jsonl"


def codex_session(home, cwd, thread_id, start, model, effort, *, parent=None, role=None,
                  source="cli", spawns=(), created=None):
    """Write a Codex rollout log. A child passes parent (its parent thread id) and
    role; each spawn is a dict with call_id, thread_id, agent_type, model, effort.
    created is the session_meta payload time when the session was opened before
    its first prompt (Codex writes the rollout only at that prompt)."""
    folder = Path(home) / ".codex" / "sessions" / start.strftime("%Y/%m/%d")
    folder.mkdir(parents=True, exist_ok=True)
    if parent:
        source = {"subagent": {"thread_spawn": {
            "parent_thread_id": parent, "depth": 1, "agent_path": f"/root/{role}",
            "agent_nickname": "Nick", "agent_role": role}}}
    meta = {"id": thread_id, "cwd": str(cwd), "timestamp": stamp(created or start), "source": source}
    records = [{"timestamp": stamp(start), "type": "session_meta", "payload": meta}]
    for index in range(2):
        records.append({"timestamp": stamp(start + timedelta(minutes=index + 1)),
                        "type": "turn_context",
                        "payload": {"model": model, "effort": effort, "cwd": str(cwd)}})
    moment = start + timedelta(minutes=1, seconds=30)
    for spawn in spawns:
        arguments = {"agent_type": spawn["agent_type"], "model": spawn["model"],
                     "reasoning_effort": spawn["effort"]}
        records.append({"timestamp": stamp(moment), "type": "response_item", "payload": {
            "type": "function_call", "name": "spawn_agent",
            "arguments": json.dumps(arguments), "call_id": spawn["call_id"]}})
        records.append({"timestamp": stamp(moment), "type": "event_msg", "payload": {
            "type": "item_completed", "thread_id": thread_id, "item": {
                "type": "SubAgentActivity",
                "model": spawn.get("activity_model", spawn["model"]),
                "reasoning_effort": spawn.get("activity_effort", spawn["effort"]), "id": spawn["call_id"],
                "kind": "started", "agent_thread_id": spawn["thread_id"],
                "agent_path": f"/root/{spawn['agent_type']}"}}})
    path = folder / f"rollout-{start.strftime('%Y-%m-%dT%H-%M-%S')}-{thread_id}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def launch_record(state_home, project, runtime, profile, time, session_model, session_effort,
                  forwarded=(), config=None):
    """Append one launch record shaped like record_launch's to the launch log."""
    log = Path(state_home) / "gsd-cli" / "launches.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ"), "project": str(project),
        "runtime": runtime, "profile": profile, "session_model": session_model,
        "session_effort": session_effort, "forwarded_args": list(forwarded),
        "config": config if config is not None else {}, "gsd_defaults": None,
    }
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return record


RESOLVER_STUB = """#!/usr/bin/env python3
import json, os, sys
table = json.loads({table!r})
runtime, agent = os.environ.get("GSD_RUNTIME"), sys.argv[-1]
try:
    overrides = json.load(open(".planning/config.json")).get("model_overrides") or {{}}
except (OSError, ValueError):
    overrides = {{}}
entry = table.get(runtime + ":" + agent)
if agent in overrides:
    entry = {{"model": overrides[agent], "effort": (entry or {{}}).get("effort")}}
print(json.dumps(entry or {{"unknown_agent": True}}))
"""


def install_resolver(home, bin_dir, table):
    """Fake the GSD resolver: an empty gsd-tools.cjs plus a node stub answering
    resolve-model from the snapshot's model_overrides, else table["runtime:agent"]."""
    tools = Path(home) / ".claude" / "gsd-core" / "bin" / "gsd-tools.cjs"
    tools.parent.mkdir(parents=True, exist_ok=True)
    tools.write_text("", encoding="utf-8")
    node = Path(bin_dir) / "node"
    node.write_text(RESOLVER_STUB.format(table=json.dumps(table)), encoding="utf-8")
    node.chmod(0o755)
