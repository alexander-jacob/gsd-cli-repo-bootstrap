"""Tests for the gsd-cli sessions readers; logs are fabricated under a fake HOME."""

import importlib.machinery
import importlib.util
import os
import unittest
from datetime import datetime, timezone
from unittest import mock

from session_fixtures import claude_session
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


if __name__ == "__main__":
    unittest.main()
