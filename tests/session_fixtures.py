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
                   entrypoint="cli", prompt="hi", turns=2, advisor=None):
    """Write a Claude session log plus subagent logs; each agent is a dict with
    id, type, requested, model, effort and parent (None or another agent id)."""
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

    records = [{"type": "user", "timestamp": stamp(start), "cwd": str(cwd),
                "sessionId": session_id, "entrypoint": entrypoint,
                "message": {"role": "user", "content": prompt}}]
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
