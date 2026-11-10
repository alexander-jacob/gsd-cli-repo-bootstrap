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
        self.home = self.root / "home"
        self.home.mkdir()
        self.env["HOME"] = str(self.home)
        self.env["XDG_STATE_HOME"] = str(self.root / "state")
        self.env["TZ"] = "UTC"

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

    def launches(self):
        path = self.root / "state" / "gsd-cli" / "launches.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def initialize(self):
        result = self.run_launcher("init")
        self.assertEqual(result.returncode, 0, result.stderr)

    def policy(self):
        return json.loads((self.project / 'gsd-cli.config.json').read_text())

    def put_policy(self, policy):
        (self.project / 'gsd-cli.config.json').write_text(json.dumps(policy))

    def snapshot(self):
        return {str(p.relative_to(self.project)): p.read_bytes() for p in self.project.rglob('*') if p.is_file() and p.name != '.gsd-cli.lock'}

    def test_init_seeds_complete_policy_without_changing_working(self):
        before = self.config_path.read_bytes()
        self.initialize()
        self.assertEqual(self.config_path.read_bytes(), before)
        self.assertEqual(self.policy()['schema_version'], 1)
        self.assertEqual(json.loads((self.project / '.planning/config.default.json').read_text())['custom'], {'keep': True})

    def test_all_levels_exact_arguments_and_routing(self):
        self.initialize()
        for workflow in ('plan', 'exec'):
            for runtime in ('claude', 'codex'):
                for level in ('low', 'medium', 'high'):
                    with self.subTest(workflow=workflow, runtime=runtime, level=level):
                        result = self.run_launcher(workflow, runtime, level)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        model = {'claude': {'low': 'claude-sonnet-5-5', 'medium': 'claude-opus-5-5', 'high': 'claude-fable-5-1'},
                                 'codex': {'low': 'gpt-6-luna', 'medium': 'gpt-6.1-sol', 'high': 'gpt-6-astra'}}[runtime][level]
                        expected = {'model': model, 'effort': 'medium' if (workflow, runtime, level) == ('exec', 'codex', 'high') else level,
                                    'permissions': 'normal' if (workflow, runtime) == ('plan', 'claude') else 'bypass',
                                    'reviewers': ['astra-review' if runtime == 'claude' else 'fable-review', 'grok-review', 'gemini-review']}
                        argv = ['--model', expected['model']]
                        argv += ['--effort', expected['effort']] if runtime == 'claude' else ['-c', 'model_reasoning_effort=' + expected['effort']]
                        if expected['permissions'] == 'bypass':
                            argv += ['--dangerously-skip-permissions' if runtime == 'claude' else '--dangerously-bypass-approvals-and-sandbox']
                        self.assertEqual(self.invocation()['args'], argv)
                        self.assertEqual(self.invocation()['runtime'], runtime)
                        self.assertEqual(self.config()['review']['default_reviewers'], expected['reviewers'])
                        self.assertEqual(self.launches()[-1]['session_effort'], expected['effort'])
                        self.assertEqual(self.launches()[-1]['level'], level)
                        tier = {'low': 'haiku', 'medium': 'sonnet', 'high': 'opus'}[level]
                        self.assertEqual(self.config()['models']['planning' if workflow == 'plan' else 'execution'], tier)
                        self.assertEqual(self.config()['models']['verification'], 'opus')
                        self.assertEqual(self.config()['model_overrides']['gsd-integration-checker'], 'opus' if runtime == 'claude' else 'gpt-6.1-sol')

    def test_default_medium_and_custom_workflow_policy_authority(self):
        self.initialize()
        p = self.policy()
        p['workflows']['ship'] = p['workflows']['exec']
        p['runtimes']['codex']['medium']['session_model'] = 'my-model'
        self.put_policy(p)
        nested = self.project / 'src'
        nested.mkdir()
        result = self.run_launcher('ship', 'codex', cwd=nested)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.invocation()['args'][:2], ['--model', 'my-model'])
        self.assertEqual(self.invocation()['cwd'], str(self.project))
        self.assertEqual(self.launches()[-1]['workflow'], 'ship')
        self.assertEqual(self.launches()[-1]['level'], 'medium')

    def test_exact_forwarding_boundary_and_secure(self):
        self.initialize()
        forwarded = ['--help', '--secure', '--model', 'override', '--', '~high', 'with spaces']
        result = self.run_launcher('exec', 'claude', '--secure', '--', *forwarded)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.invocation()['args'], ['--model', 'claude-opus-5-5', '--effort', 'medium', *forwarded])
        self.assertEqual(self.launches()[-1]['forwarded_args'], forwarded)
        self.assertNotIn('--dangerously-skip-permissions', self.invocation()['args'])

    def test_help_and_errors_never_write(self):
        self.initialize()
        before = self.snapshot()
        for args in [('--help',), ('init', '--help'), ('exec', '--help'), ('exec', 'codex', '--help')]:
            result = self.run_launcher(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.snapshot(), before)
        for args in [('exec', 'codex', '--unknown'), ('exec', 'codex', 'huge'), ('codex', 'plan')]:
            result = self.run_launcher(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.snapshot(), before)
        self.assertIn('plan codex', self.run_launcher('codex', 'plan').stderr)
        self.put_policy({'broken': True})
        self.assertEqual(self.run_launcher('--help').returncode, 0)
        self.assertEqual(self.run_launcher('init', '--help').returncode, 0)
        self.assertEqual(self.run_launcher('--help', cwd=self.root).returncode, 0)

    def test_incomplete_policy_does_not_fall_back_or_write(self):
        self.initialize()
        p = self.policy()
        del p['runtimes']['codex']['low']
        self.put_policy(p)
        before = self.snapshot()
        result = self.run_launcher('exec', 'codex')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('runtimes.codex', result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.log.exists())

    def test_capture_default_stability_and_read_only_status(self):
        self.initialize()
        self.assertEqual(self.run_launcher('plan', 'codex').returncode, 0)
        default = self.project / '.planning/config.default.json'
        before = default.read_bytes()
        self.assertEqual(self.run_launcher('exec', 'claude').returncode, 0)
        self.assertEqual(default.read_bytes(), before)
        w = self.config()
        w['workflow']['research'] = False
        self.config_path.write_text(json.dumps(w))
        before = self.snapshot()
        self.assertEqual(self.run_launcher('status').returncode, 0)
        self.assertEqual(self.snapshot(), before)
        result = self.run_launcher('exec', 'codex')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('workflow.research', result.stderr)
        self.assertFalse(json.loads(default.read_text())['workflow']['research'])

    def test_fresh_checkout_works_without_working_or_baseline(self):
        self.initialize()
        self.config_path.unlink()
        (self.project / '.planning/.gsd-cli-sync.json').unlink()
        self.assertEqual(self.run_launcher('status').returncode, 0)
        result = self.run_launcher('plan', 'codex')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.config_path.exists())

    def test_missing_executable_no_changes_or_launch_log(self):
        self.initialize()
        (self.bin / 'codex').unlink()
        env = {**self.env, 'PATH': str(self.bin)}
        before = self.snapshot()
        result = self.run_launcher('exec', 'codex', env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Cannot find CLI', result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / 'state/gsd-cli/launches.jsonl').exists())

    def test_billing_guards_follow_custom_reviewer_adapters(self):
        self.initialize()
        p = self.policy()
        p['reviewers']['custom'] = {'cli': 'claude', 'model': 'custom'}
        p['reviewer_groups']['custom'] = ['custom']
        p['workflows']['exec']['reviewer_groups']['codex'] = 'custom'
        self.put_policy(p)
        before = self.snapshot()
        for key in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'CODEX_API_KEY'):
            result = self.run_launcher('exec', 'codex', env={**self.env, key: 'test-only'})
            self.assertNotEqual(result.returncode, 0, key)
            self.assertIn('Refusing', result.stderr)
            self.assertEqual(self.snapshot(), before)

    def test_unselected_adapter_does_not_trigger_billing_guard(self):
        self.initialize()
        p = self.policy()
        p['reviewer_groups']['none'] = []
        p['workflows']['exec']['reviewer_groups']['claude'] = 'none'
        self.put_policy(p)
        result = self.run_launcher('exec', 'claude', env={**self.env, 'OPENAI_API_KEY': 'test-only'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config()['review']['default_reviewers'], [])

    def test_launch_log_failure_warns_and_launches(self):
        self.initialize()
        state = self.root / 'state'
        state.write_text('blocked')
        result = self.run_launcher('exec', 'codex')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('could not write launch log', result.stderr)
        self.assertTrue(self.log.exists())

    def test_legacy_project_requires_explicit_init(self):
        before = self.snapshot()
        result = self.run_launcher('plan', 'codex')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('gsd-cli init', result.stderr)
        self.assertEqual(self.snapshot(), before)
