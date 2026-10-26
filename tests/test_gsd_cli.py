"""Smoke tests for gsd-cli; no network or real model calls are made."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


LAUNCHER = Path(__file__).resolve().parents[1] / "gsd-cli"


class GsdCliTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        (self.project / ".planning").mkdir(parents=True)
        self.config_path = self.project / ".planning" / "config.json"
        self.config_path.write_text(
            json.dumps({"runtime": "opencode", "custom": {"keep": True}}),
            encoding="utf-8",
        )
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "cli-invocation.json"
        stub = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
Path(os.environ['GSD_TEST_LOG']).write_text(json.dumps({
  'program': Path(sys.argv[0]).name,
  'args': sys.argv[1:],
  'runtime': os.environ.get('GSD_RUNTIME'),
  'cwd': os.getcwd()
}))
"""
        for name in ("codex", "claude"):
            cli = self.bin / name
            cli.write_text(stub, encoding="utf-8")
            cli.chmod(0o755)
        self.env = os.environ.copy()
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY", "GSD_RUNTIME"):
            self.env.pop(key, None)
        self.env["PATH"] = str(self.bin) + os.pathsep + self.env.get("PATH", "")
        self.env["GSD_TEST_LOG"] = str(self.log)

    def run_launcher(self, *args, cwd=None, env=None):
        return subprocess.run(
            [sys.executable, str(LAUNCHER), *args],
            cwd=cwd or self.project,
            env=env or self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def config(self):
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def invocation(self):
        return json.loads(self.log.read_text(encoding="utf-8"))

    def initialize(self):
        result = self.run_launcher("init")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_init_merges_without_erasing_existing_settings(self):
        self.initialize()
        config = self.config()
        self.assertEqual(config["custom"], {"keep": True})
        self.assertNotIn("runtime", config)
        # Claude tiers must be Agent-tool aliases, not full IDs (GSD cannot map
        # a full ID back to an alias and would spawn subagents with no model).
        claude_tiers = config["model_policy"]["runtime_tiers"]["claude"]
        self.assertEqual({tier: entry["model"] for tier, entry in claude_tiers.items()},
                         {"opus": "fable", "sonnet": "opus", "haiku": "sonnet"})
        self.assertEqual(config["model_policy"]["runtime_tiers"]["codex"]["opus"]["model"], "gpt-6-astra")
        self.assertEqual(len(config["review"]["reviewer_instances"]), 5)
        self.assertEqual(config["review"]["default_reviewers"][0], "fable-review")
        self.assertFalse(config["review"]["parallel_lanes"])
        # Running init again should not break or truncate JSON.
        self.initialize()
        self.assertEqual(self.config()["custom"], {"keep": True})

    def test_codex_plan_selects_fable_reviewer_and_runtime(self):
        self.initialize()
        result = self.run_launcher("codex", "plan", "--", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        invocation = self.invocation()
        self.assertEqual(invocation["program"], "codex")
        self.assertEqual(invocation["runtime"], "codex")
        self.assertEqual(invocation["args"], ["--model", "gpt-6-astra", "--help"])
        self.assertEqual(invocation["cwd"], str(self.project))
        self.assertEqual(
            self.config()["review"]["default_reviewers"],
            ["fable-review", "grok-review", "gemini-review", "deepseek-review"],
        )

    def test_claude_plan_chooses_astra_reviewer(self):
        self.initialize()
        result = self.run_launcher("claude", "plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.invocation()["args"][:2], ["--model", "claude-fable-5-1"])
        self.assertEqual(self.invocation()["runtime"], "claude")
        self.assertEqual(
            self.config()["review"]["default_reviewers"],
            ["astra-review", "grok-review", "gemini-review", "deepseek-review"],
        )

    def test_execution_preserves_reviewers_and_changes_execution_tier(self):
        self.initialize()
        self.assertEqual(self.run_launcher("claude", "plan").returncode, 0)
        result = self.run_launcher("claude", "exec-sonnet")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.invocation()["args"][:2], ["--model", "claude-sonnet-5-5"])
        config = self.config()
        self.assertEqual(config["models"]["execution"], "haiku")
        self.assertEqual(config["models"]["verification"], "opus")
        self.assertEqual(config["review"]["default_reviewers"][0], "astra-review")
        result = self.run_launcher("codex", "exec-high")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config()["models"]["execution"], "opus")
        self.assertEqual(self.config()["review"]["default_reviewers"][0], "astra-review")

    def test_explicit_reviewer_preset_uses_plan_author(self):
        self.initialize()
        self.assertEqual(self.run_launcher("claude", "plan").returncode, 0)
        self.assertEqual(self.run_launcher("codex", "review-codex-plan").returncode, 0)
        self.assertEqual(self.config()["review"]["default_reviewers"][0], "fable-review")
        self.assertEqual(self.run_launcher("claude", "review-claude-plan").returncode, 0)
        self.assertEqual(self.config()["review"]["default_reviewers"][0], "astra-review")

    def test_insecure_execution_translates_runtime_flags(self):
        self.initialize()
        for runtime, profiles, flag in (
            ("claude", ("exec-opus", "exec-sonnet"), "--dangerously-skip-permissions"),
            ("codex", ("exec-high", "exec-medium", "exec-low"),
             "--dangerously-bypass-approvals-and-sandbox"),
        ):
            for profile in profiles:
                with self.subTest(runtime=runtime, profile=profile):
                    result = self.run_launcher(runtime, profile, "--insecure", "--", "--help")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(self.invocation()["args"][2:], [flag, "--help"])

    def test_insecure_after_separator_is_forwarded_unchanged(self):
        self.initialize()
        result = self.run_launcher("codex", "exec-high", "--", "--insecure")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.invocation()["args"][2:], ["--insecure"])

    def test_insecure_rejected_outside_execution_without_config_changes(self):
        self.initialize()
        original = self.config_path.read_bytes()
        for profile in ("plan", "review-claude-plan"):
            result = self.run_launcher("codex", profile, "--insecure")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("only supported for execution", result.stderr)
            self.assertEqual(self.config_path.read_bytes(), original)
            self.assertFalse(self.log.exists())

    def test_insecure_preserves_billing_guard(self):
        self.initialize()
        env = self.env.copy()
        env["OPENAI_API_KEY"] = "fake-key"
        result = self.run_launcher("codex", "exec-high", "--insecure", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OPENAI_API_KEY", result.stderr)
        self.assertFalse(self.log.exists())

    def test_api_key_guard_blocks_subscription_mode(self):
        self.initialize()
        guarded_env = self.env.copy()
        guarded_env["ANTHROPIC_API_KEY"] = "fake-key"
        result = self.run_launcher("codex", "plan", env=guarded_env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ANTHROPIC_API_KEY", result.stderr)
        self.assertFalse(self.log.exists())

    def test_find_config_from_nested_directory(self):
        self.initialize()
        nested = self.project / "nested" / "subdir"
        nested.mkdir(parents=True)
        result = self.run_launcher("codex", "exec-medium", cwd=nested)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.invocation()["cwd"], str(self.project))

    def test_reports_missing_config(self):
        result = self.run_launcher("init", cwd=self.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".planning/config.json not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
