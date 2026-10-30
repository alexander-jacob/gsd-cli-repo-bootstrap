"""Tests for the gsd-cli sessions readers; logs are fabricated under a fake HOME."""

import importlib.machinery
import importlib.util
import os
import unittest
from datetime import datetime, timezone
from unittest import mock

from session_fixtures import claude_session, codex_session
import test_gsd_cli
from test_gsd_cli import LAUNCHER


def load_launcher():
    loader = importlib.machinery.SourceFileLoader("gsd_cli", str(LAUNCHER))
    spec = importlib.util.spec_from_loader("gsd_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


START = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


class SessionsTestCase(unittest.TestCase):
    """Reuses the shared fixture setUp without inheriting the launcher tests."""

    def setUp(self):
        test_gsd_cli.GsdCliTestCase.setUp(self)
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.gsd = load_launcher()

    def agent(self, agent_id, **overrides):
        base = {"id": agent_id, "type": "gsd-executor", "requested": "sonnet",
                "model": "claude-sonnet-5-5", "effort": "high", "parent": None}
        return {**base, **overrides}


class ClaudeReaderTests(SessionsTestCase):
    def test_claude_reader_session_and_agents(self):
        claude_session(self.home, self.project, "s1", START, "claude-opus-5-5", "medium",
                       advisor="claude-opus-5-5", agents=[self.agent("a1")])
        runs = self.gsd.read_claude_runs(self.project)
        self.assertEqual(len(runs), 1)
        session = runs[0]
        self.assertEqual((session.kind, session.model, session.effort), ("session", "claude-opus-5-5", "medium"))
        self.assertEqual(session.advisor, "claude-opus-5-5")
        self.assertEqual(len(session.children), 1)
        child = session.children[0]
        self.assertEqual(child.agent_type, "gsd-executor")
        self.assertEqual(child.requested_model, "sonnet")
        self.assertEqual((child.model, child.effort), ("claude-sonnet-5-5", "high"))

    def test_claude_reader_nests_sub_subagents(self):
        claude_session(self.home, self.project, "s1", START, "claude-opus-5-5", "medium",
                       agents=[self.agent("a1"), self.agent("a2", parent="a1", type="gsd-verifier")])
        session = self.gsd.read_claude_runs(self.project)[0]
        self.assertEqual([c.run_id for c in session.children], ["a1"])
        self.assertEqual([c.run_id for c in session.children[0].children], ["a2"])

    def test_claude_reader_requested_effort_from_tool_use(self):
        claude_session(self.home, self.project, "s1", START, "claude-opus-5-5", "medium",
                       agents=[self.agent("a1", requested_effort="low")])
        child = self.gsd.read_claude_runs(self.project)[0].children[0]
        self.assertEqual(child.requested_effort, "low")

    def test_claude_reader_orphan_agent_goes_under_session(self):
        claude_session(self.home, self.project, "s1", START, "claude-opus-5-5", "medium",
                       agents=[self.agent("a1"), self.agent("a2", parent="a1", tool_use_id="toolu_missing")])
        session = self.gsd.read_claude_runs(self.project)[0]
        self.assertEqual(sorted(c.run_id for c in session.children), ["a1", "a2"])
        self.assertEqual(session.children[0].children, [])

    def test_claude_reader_agent_without_requested_model(self):
        claude_session(self.home, self.project, "s1", START, "claude-opus-5-5", "medium",
                       agents=[self.agent("a1", requested=None, model="claude-opus-5-5", effort="low")])
        child = self.gsd.read_claude_runs(self.project)[0].children[0]
        self.assertIsNone(child.requested_model)
        self.assertEqual((child.model, child.effort), ("claude-opus-5-5", "low"))

    def test_claude_reader_marks_reviewer_runs(self):
        claude_session(self.home, self.project, "r1", START, "claude-fable-5-1", "high",
                       entrypoint="sdk-cli", prompt="# Cross-AI Plan Review Request\nplan")
        self.assertEqual(self.gsd.read_claude_runs(self.project)[0].kind, "reviewer")

    def test_claude_reader_effort_varied(self):
        claude_session(self.home, self.project, "s1", START, "claude-opus-5-5",
                       ["high", "high", "low"], turns=3)
        session = self.gsd.read_claude_runs(self.project)[0]
        self.assertEqual(session.effort, "high")
        self.assertTrue(session.effort_varied)

    def test_sessions_filters_claude_by_cwd_not_folder(self):
        dotted, dashed = self.root / "x" / "a.b", self.root / "x" / "a-b"
        claude_session(self.home, dotted, "dot", START, "claude-opus-5-5", "high")
        claude_session(self.home, dashed, "dash", START, "claude-opus-5-5", "high")
        self.assertEqual([r.run_id for r in self.gsd.read_claude_runs(dashed)], ["dash"])

    def test_sessions_skips_malformed_log_lines(self):
        log = claude_session(self.home, self.project, "s1", START, "claude-opus-5-5", "high")
        with log.open("a", encoding="utf-8") as handle:
            handle.write('{"type": "assistant", "timest')
        runs = self.gsd.read_claude_runs(self.project)
        self.assertEqual([r.run_id for r in runs], ["s1"])

    def test_most_common(self):
        self.assertEqual(self.gsd.most_common([None, "a", "a", "b"]), ("a", True))
        self.assertEqual(self.gsd.most_common([None]), (None, False))


class CodexReaderTests(SessionsTestCase):
    def spawn(self, **overrides):
        base = {"call_id": "call_1", "thread_id": "child-1", "agent_type": "gsd-executor",
                "model": "gpt-6.1-sol", "effort": "high"}
        return {**base, **overrides}

    def test_codex_reader_links_spawn_to_child(self):
        codex_session(self.home, self.project, "parent-1", START, "gpt-6-astra", "medium",
                      spawns=[self.spawn()])
        codex_session(self.home, self.project, "child-1", START, "gpt-6.1-sol", "high",
                      parent="parent-1", role="gsd-executor")
        runs = self.gsd.read_codex_runs(self.project)
        self.assertEqual([r.run_id for r in runs], ["parent-1"])
        parent = runs[0]
        self.assertEqual((parent.kind, parent.model, parent.effort), ("session", "gpt-6-astra", "medium"))
        child = parent.children[0]
        self.assertEqual((child.kind, child.agent_type), ("agent", "gsd-executor"))
        self.assertEqual((child.requested_model, child.requested_effort), ("gpt-6.1-sol", "high"))
        self.assertEqual((child.model, child.effort), ("gpt-6.1-sol", "high"))

    def test_codex_reader_falls_back_to_parent_thread_id(self):
        codex_session(self.home, self.project, "parent-1", START, "gpt-6-astra", "medium")
        codex_session(self.home, self.project, "child-1", START, "gpt-6.1-sol", "high",
                      parent="parent-1", role="gsd-plan-checker")
        parent = self.gsd.read_codex_runs(self.project)[0]
        child = parent.children[0]
        self.assertEqual(child.agent_type, "gsd-plan-checker")
        self.assertEqual((child.requested_model, child.requested_effort), (None, None))

    def test_codex_reader_falls_back_to_spawn_arguments(self):
        codex_session(self.home, self.project, "parent-1", START, "gpt-6-astra", "medium",
                      spawns=[self.spawn(activity_model=None, activity_effort=None)])
        codex_session(self.home, self.project, "child-1", START, "gpt-6.1-sol", "high",
                      parent="parent-1", role="gsd-executor")
        child = self.gsd.read_codex_runs(self.project)[0].children[0]
        self.assertEqual((child.requested_model, child.requested_effort), ("gpt-6.1-sol", "high"))

    def test_codex_reader_nests_grandchildren(self):
        codex_session(self.home, self.project, "parent-1", START, "gpt-6-astra", "medium",
                      spawns=[self.spawn()])
        codex_session(self.home, self.project, "child-1", START, "gpt-6.1-sol", "high",
                      parent="parent-1", role="gsd-executor",
                      spawns=[self.spawn(call_id="call_2", thread_id="grand-1",
                                         agent_type="gsd-verifier", model="gpt-6-astra")])
        codex_session(self.home, self.project, "grand-1", START, "gpt-6-astra", "high",
                      parent="child-1", role="gsd-verifier")
        runs = self.gsd.read_codex_runs(self.project)
        self.assertEqual([r.run_id for r in runs], ["parent-1"])
        child = runs[0].children[0]
        self.assertEqual([c.run_id for c in child.children], ["grand-1"])
        self.assertEqual(child.children[0].requested_model, "gpt-6-astra")

    def test_codex_reader_keeps_orphans_as_top_level_agents(self):
        codex_session(self.home, self.project, "child-1", START, "gpt-6.1-sol", "high",
                      parent="missing", role="gsd-executor")
        codex_session(self.home, self.project, "grand-1", START, "gpt-6.1-sol", "high",
                      parent="child-1", role="gsd-verifier")
        runs = self.gsd.read_codex_runs(self.project)
        self.assertEqual([(r.run_id, r.kind) for r in runs], [("child-1", "agent")])
        self.assertEqual([c.run_id for c in runs[0].children], ["grand-1"])

    def test_codex_reader_ignores_non_object_first_line(self):
        for name, line in (("a", "[]"), ("b", "null")):
            path = codex_session(self.home, self.project, name, START, "m", "high")
            path.write_text(line + "\n", encoding="utf-8")
        codex_session(self.home, self.project, "ok", START, "gpt-6-astra", "high")
        self.assertEqual([r.run_id for r in self.gsd.read_codex_runs(self.project)], ["ok"])

    def test_codex_reader_filters_other_projects(self):
        codex_session(self.home, self.project, "mine", START, "gpt-6-astra", "medium")
        codex_session(self.home, self.root / "other", "theirs", START, "gpt-6-astra", "medium")
        self.assertEqual([r.run_id for r in self.gsd.read_codex_runs(self.project)], ["mine"])

    def test_codex_reader_marks_exec_as_reviewer(self):
        codex_session(self.home, self.project, "rev", START, "gpt-6-astra", "high", source="exec")
        codex_session(self.home, self.project, "tui", START, "gpt-6-astra", "high", source="vscode")
        kinds = {r.run_id: r.kind for r in self.gsd.read_codex_runs(self.project)}
        self.assertEqual(kinds, {"rev": "reviewer", "tui": "session"})


if __name__ == "__main__":
    unittest.main()
