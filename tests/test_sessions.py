"""Tests for the gsd-cli sessions readers; logs are fabricated under a fake HOME."""

import importlib.machinery
import importlib.util
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from session_fixtures import claude_session, codex_session, install_resolver, launch_record
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
        patcher = mock.patch.dict(os.environ, {
            "HOME": str(self.home), "XDG_STATE_HOME": self.env["XDG_STATE_HOME"],
            "PATH": self.env["PATH"],
        })
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


class LinkTests(SessionsTestCase):
    def run_(self, run_id, kind="session", runtime="claude", start=START, minutes=30, cwd=None):
        return self.gsd.Run(runtime, run_id, kind, str(cwd or self.project), start,
                            start + timedelta(minutes=minutes), "m", "high")

    def launch(self, runtime, time, forwarded=(), project=None):
        return launch_record(self.env["XDG_STATE_HOME"], project or self.project, runtime,
                             "exec-opus", time, "claude-opus-5-5", None, forwarded)

    def test_link_nests_reviewer_under_overlapping_session(self):
        session = self.run_("s1", runtime="codex")
        reviewer = self.run_("r1", kind="reviewer", start=START + timedelta(minutes=10), minutes=2)
        top = self.gsd.link([reviewer, session], [])
        self.assertEqual([r.run_id for r in top], ["s1"])
        self.assertEqual([c.run_id for c in session.children], ["r1"])
        self.assertEqual(reviewer.marks, [])

    def test_link_keeps_unattached_reviewer(self):
        session = self.run_("s1")
        late = self.run_("r1", kind="reviewer", start=START + timedelta(hours=2))
        other = self.run_("r2", kind="reviewer", start=START + timedelta(minutes=5),
                          cwd=self.root / "other")
        top = self.gsd.link([session, late, other], [])
        self.assertEqual([r.run_id for r in top], ["r1", "r2", "s1"])
        self.assertEqual(late.marks, ["reviewer, unattached"])
        self.assertEqual(other.marks, ["reviewer, unattached"])
        self.assertEqual(session.children, [])

    def test_link_matches_launch_within_window(self):
        self.launch("claude", START - timedelta(seconds=5))
        self.launch("codex", START - timedelta(seconds=2))
        self.launch("claude", START - timedelta(minutes=10), project=self.root / "other")
        near = self.run_("near")
        far = self.run_("far", start=START + timedelta(hours=3))
        self.launch("claude", far.start - timedelta(minutes=5))
        orphan = self.run_("orphan", kind="agent", runtime="codex", start=START + timedelta(hours=1))
        launches = self.gsd.load_launches(self.project)
        self.assertEqual(len(launches), 3)
        top = self.gsd.link([near, far, orphan], launches)
        self.assertEqual([r.run_id for r in top], ["far", "orphan", "near"])
        self.assertEqual(near.launch["time"], "2026-10-01T08:59:55Z")
        self.assertEqual(near.launch["runtime"], "claude")
        self.assertIsNone(far.launch)
        self.assertIsNone(orphan.launch)

    def test_load_launches_skips_malformed_lines(self):
        self.launch("claude", START)
        log = self.gsd.launch_log_path()
        with log.open("a", encoding="utf-8") as handle:
            handle.write('{"time": "2026-\n[]\n')
        self.assertEqual(len(self.gsd.load_launches(self.project)), 1)

    def test_link_marks_resumed(self):
        self.launch("claude", START - timedelta(seconds=3))
        self.launch("claude", START + timedelta(minutes=10), forwarded=["--resume", "s1"])
        self.launch("codex", START + timedelta(minutes=10), forwarded=["resume", "t1"])
        self.launch("codex", START + timedelta(minutes=12), forwarded=["--search"])
        claude = self.run_("s1")
        codex = self.run_("t1", runtime="codex")
        plain = self.run_("s2", start=START + timedelta(hours=1))
        self.gsd.link([claude, codex, plain], self.gsd.load_launches(self.project))
        self.assertTrue(claude.resumed)
        self.assertTrue(codex.resumed)
        self.assertFalse(plain.resumed)
        self.assertEqual(claude.launch["forwarded_args"], [])

    def test_model_matches(self):
        self.assertTrue(self.gsd.model_matches("claude", "opus", "claude-opus-5-5"))
        self.assertTrue(self.gsd.model_matches("claude", "claude-opus-5-5", "claude-opus-5-5"))
        self.assertFalse(self.gsd.model_matches("claude", "opus", "claude-sonnet-5-5"))
        self.assertFalse(self.gsd.model_matches("codex", "gpt-6-astra", "gpt-6-astra-mini"))
        self.assertFalse(self.gsd.model_matches("claude", "opus", None))


class CheckTests(SessionsTestCase):
    TABLE = {
        "claude:gsd-executor": {"model": "opus", "effort": "high"},
        "codex:gsd-executor": {"model": "gpt-6.1-sol", "effort": "medium"},
    }

    def session(self, runtime="claude", model="claude-opus-5-5", effort="medium", children=()):
        run = self.gsd.Run(runtime, "s1", "session", str(self.project), START,
                           START + timedelta(minutes=30), model, effort)
        run.children.extend(children)
        return run

    def child(self, runtime="claude", agent_type="gsd-executor", requested="opus",
              model="claude-opus-5-5", effort="high", kind="agent"):
        return self.gsd.Run(runtime, "a1", kind, str(self.project), START, START, model, effort,
                            agent_type=agent_type, requested_model=requested)

    def launch(self, runtime="claude", session_model="claude-opus-5-5", session_effort=None,
               forwarded=(), config=None):
        return launch_record(self.env["XDG_STATE_HOME"], self.project, runtime, "exec-opus",
                             START - timedelta(seconds=5), session_model, session_effort,
                             forwarded, config)

    def checked(self, session, launch, runtime="claude"):
        resolver = self.gsd.Resolver()
        self.gsd.check(session, resolver, runtime, launch)
        return resolver

    def test_check_flags_requested_vs_actual(self):
        wrong = self.child(requested="sonnet", model="claude-opus-5-5")
        right = self.child(requested="sonnet", model="claude-sonnet-5-5")
        inherits = self.child(requested=None, model="claude-opus-5-5")
        nested = self.child(requested="haiku", model="claude-opus-5-5")
        right.children.append(nested)
        self.checked(self.session(children=[wrong, right, inherits]), None)
        self.assertEqual(wrong.marks, ["! asked sonnet, ran claude-opus-5-5"])
        self.assertEqual(right.marks, [])
        self.assertEqual(inherits.marks, [])
        self.assertEqual(nested.marks, ["! asked haiku, ran claude-opus-5-5"])

    def test_check_flags_profile_mismatch(self):
        install_resolver(self.home, self.bin, self.TABLE)
        agent = self.child(requested="sonnet", model="claude-sonnet-5-5", effort="high")
        session = self.session(children=[agent])
        resolver = self.checked(session, self.launch())
        self.assertTrue(resolver.available)
        self.assertEqual(agent.marks, ["! profile expects opus"])
        self.assertEqual(session.marks, [])

    def test_check_flags_profile_effort_and_codex_session(self):
        install_resolver(self.home, self.bin, self.TABLE)
        agent = self.child(runtime="codex", requested="gpt-6.1-sol", model="gpt-6.1-sol", effort="high")
        session = self.session(runtime="codex", model="gpt-6-luna", effort="low", children=[agent])
        self.checked(session, self.launch("codex", "gpt-6-astra", "medium"), "codex")
        self.assertEqual(agent.marks, ["! profile expects effort medium"])
        self.assertEqual(session.marks, ["! profile expects gpt-6-astra", "! profile expects effort medium"])

    def test_check_never_compares_claude_session_effort(self):
        session = self.session(model="claude-sonnet-5-5", effort="low")
        self.checked(session, self.launch(session_effort="high"))
        self.assertEqual(session.marks, ["! profile expects claude-opus-5-5"])

    def test_profile_comparison_uses_launch_snapshot(self):
        install_resolver(self.home, self.bin, {"claude:gsd-executor": {"model": "sonnet", "effort": "high"}})
        self.config_path.write_text(json.dumps({"model_overrides": {"gsd-executor": "sonnet"}}),
                                    encoding="utf-8")
        agent = self.child(requested="opus", model="claude-opus-5-5")
        launch = self.launch(config={"model_overrides": {"gsd-executor": "opus"}})
        self.checked(self.session(children=[agent]), launch)
        self.assertEqual(agent.marks, [])

    def test_resolver_caches_per_launch(self):
        install_resolver(self.home, self.bin, self.TABLE)
        resolver = self.gsd.Resolver()
        launch = self.launch()
        with mock.patch.object(self.gsd.subprocess, "run", wraps=self.gsd.subprocess.run) as run:
            first = resolver.expected(launch, "gsd-executor")
            second = resolver.expected(launch, "gsd-executor")
        self.assertEqual(first, {"model": "opus", "effort": "high"})
        self.assertEqual(second, first)
        self.assertEqual(run.call_count, 1)

    def test_check_skips_unknown_agents(self):
        install_resolver(self.home, self.bin, self.TABLE)
        agent = self.child(agent_type="general-purpose", requested=None, model="claude-haiku-5-5")
        resolver = self.checked(self.session(children=[agent]), self.launch())
        self.assertIsNone(resolver.expected(self.launch(), "general-purpose"))
        self.assertTrue(resolver.available)
        self.assertEqual(agent.marks, [])

    def test_check_overridden_at_launch(self):
        for forwarded in (["--model", "claude-sonnet-5-5"], ["-m", "x"],
                          ["-c", "model_reasoning_effort=low"]):
            session = self.session(runtime="codex", model="gpt-6-luna", effort="low")
            self.checked(session, self.launch("codex", "gpt-6-astra", "high", forwarded), "codex")
            self.assertEqual(session.marks, ["overridden at launch"], forwarded)

    def test_check_marks_resumed(self):
        session = self.session()
        session.resumed = True
        self.checked(session, self.launch())
        self.assertEqual(session.marks, ["resumed, profile may differ"])

    def test_check_reviewer_model(self):
        fable = self.child(kind="reviewer", agent_type=None, requested=None, model="claude-opus-5-5")
        fine = self.child(kind="reviewer", agent_type=None, requested=None, model="claude-fable-5-1")
        astra = self.child(runtime="codex", kind="reviewer", agent_type=None, requested=None,
                           model="gpt-6.1-sol")
        self.checked(self.session(runtime="codex", model="gpt-6-astra", children=[fable, fine, astra]),
                     None, "codex")
        self.assertEqual(fable.marks, ["! fable-review expects claude-fable-5-1"])
        self.assertEqual(fine.marks, [])
        self.assertEqual(astra.marks, ["! astra-review expects gpt-6-astra"])

    def test_check_without_resolver_sets_unavailable(self):
        agent = self.child(requested="opus", model="claude-sonnet-5-5")
        resolver = self.checked(self.session(children=[agent]), self.launch())
        self.assertFalse(resolver.available)
        self.assertEqual(agent.marks, ["! asked opus, ran claude-sonnet-5-5"])

    def test_check_never_marks_missing_actual(self):
        install_resolver(self.home, self.bin, self.TABLE)
        agent = self.child(requested="sonnet", model=None, effort=None)
        session = self.session(model=None, effort=None, children=[agent])
        self.checked(session, self.launch())
        self.assertEqual((session.marks, agent.marks), ([], []))


if __name__ == "__main__":
    unittest.main()
