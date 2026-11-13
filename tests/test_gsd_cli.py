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
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY", "GSD_RUNTIME", "CODEX_HOME", "CLAUDE_CONFIG_DIR"):
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
        # Only launcher tests need installed-GSD fixtures. Session reader tests
        # reuse setUp and intentionally test missing resolver installations.
        from test_versions import install_gsd
        for runtime in ('claude', 'codex'):
            install_gsd(self.home / f'.{runtime}')
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
                        model = {'claude': {'low': 'claude-sonnet-5-5', 'medium': 'claude-opus-5-5', 'high': 'claude-fable-5-2'},
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

    def test_check_reports_both_runtimes_read_only_and_fails_if_one_is_old(self):
        self.initialize()
        (self.home / '.codex/gsd-core/VERSION').write_text('1.18.0\n')
        before = self.snapshot()
        result = self.run_launcher('check')
        self.assertEqual(result.returncode, 1, result.stderr)
        for value in ('claude', 'codex', '1.20.1', '1.18.0', 'PASS', 'FAIL', str(self.home / '.codex/gsd-core')):
            self.assertIn(value, result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.root / 'state').exists())
        self.assertEqual(self.run_launcher('check', 'claude').returncode, 0)
        self.assertEqual(self.run_launcher('check', 'codex').returncode, 1)

    def test_unsupported_gsd_blocks_before_capture_recovery_logs_or_exec(self):
        self.initialize()
        (self.project / '.planning/.gsd-cli.lock').unlink()
        w = self.config()
        w['pending_capture'] = True
        self.config_path.write_text(json.dumps(w))
        # A pending journal must not be replayed or even parsed by this failure.
        (self.project / '.planning/.gsd-cli-journal.json').write_text('pending recovery')
        (self.home / '.codex/gsd-core/VERSION').write_text('1.18.0')
        before = self.snapshot()
        for extra in ((), ('--secure',)):
            result = self.run_launcher('exec', 'codex', *extra)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('1.18.0', result.stderr)
            self.assertIn('1.20.1', result.stderr)
            self.assertIn('gsd-cli check codex', result.stderr)
            self.assertEqual(self.snapshot(), before)
            self.assertFalse((self.project / '.planning/.gsd-cli.lock').exists())
            self.assertFalse(self.log.exists())
            self.assertFalse((self.root / 'state').exists())
        result = self.run_launcher('check')
        self.assertEqual(result.returncode, 1)
        self.assertIn('1.18.0', result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_check_does_not_require_cli_executables_or_node(self):
        self.initialize()
        env = {**self.env, 'PATH': ''}
        result = self.run_launcher('check', env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PASS', result.stdout)

    def test_missing_malformed_and_incomplete_gsd_block_launch(self):
        self.initialize()
        version = self.home / '.codex/gsd-core/VERSION'
        before = self.snapshot()
        for content in (None, 'invalid', '1.20.1-rc.1'):
            if content is None:
                version.unlink()
            else:
                version.write_text(content)
            result = self.run_launcher('exec', 'codex')
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(self.snapshot(), before)
            self.assertFalse(self.log.exists())
        version.write_text('1.20.1')
        (self.home / '.codex/gsd-core/bin/gsd-tools.cjs').unlink()
        self.assertEqual(self.run_launcher('exec', 'codex').returncode, 1)
        self.assertEqual(self.snapshot(), before)

    def test_project_floor_is_authoritative_and_old_other_runtime_does_not_block(self):
        self.initialize()
        p = self.policy()
        p['gsd'] = {'min_version': '1.18.0'}
        self.put_policy(p)
        (self.home / '.codex/gsd-core/VERSION').write_text('1.18.0')
        (self.home / '.claude/gsd-core/VERSION').write_text('1.0.0')
        result = self.run_launcher('exec', 'codex')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.policy()['gsd']['min_version'], '1.18.0')

    def test_check_from_descendant_honors_relative_override(self):
        self.initialize()
        from test_versions import install_gsd
        selected = install_gsd(self.project / 'config-root', '1.18.0')
        nested = self.project / 'src'
        nested.mkdir()
        env = {**self.env, 'CODEX_HOME': 'config-root'}
        result = self.run_launcher('check', 'codex', cwd=nested, env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn(str(selected), result.stdout)
        self.assertIn('1.18.0', result.stdout)

    def test_old_project_policy_requires_explicit_version_field(self):
        self.initialize()
        p = self.policy()
        p.pop('gsd', None)
        self.put_policy(p)
        before = self.snapshot()
        for args in [('exec', 'codex'), ('check',), ('init',)]:
            result = self.run_launcher(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('gsd.min_version', result.stderr)
            self.assertEqual(self.snapshot(), before)

    def test_maintenance_commands_remain_available_with_old_gsd(self):
        self.initialize()
        (self.home / '.codex/gsd-core/VERSION').write_text('1.0.0')
        (self.home / '.claude/gsd-core/VERSION').write_text('1.0.0')
        for args in [('init',), ('status',), ('sessions',), ('--help',), ('check', '--help')]:
            result = self.run_launcher(*args)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_forwarded_codex_directory_switches_block_before_writes(self):
        self.initialize()
        from test_versions import install_gsd
        destination = self.root / 'other-project'
        install_gsd(destination / '.codex', '1.18.0')
        before = self.snapshot()
        for forwarded in (['-C', str(destination)], ['--cd', str(destination)],
                          ['-C' + str(destination)], ['-C=' + str(destination)],
                          ['--cd=' + str(destination)]):
            with self.subTest(forwarded=forwarded):
                result = self.run_launcher('exec', 'codex', '--', *forwarded)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn('destination project', result.stderr)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.log.exists())
                self.assertFalse((self.root / 'state').exists())

    def test_literal_child_prompt_directory_flags_still_forward_unchanged(self):
        self.initialize()
        forwarded = ['--', '-C', 'literal prompt', '--cd=also-literal']
        result = self.run_launcher('exec', 'codex', '--', *forwarded)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.invocation()['args'][-len(forwarded):], forwarded)
