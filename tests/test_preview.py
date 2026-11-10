import copy
import importlib
import json
import shutil
import unittest
from pathlib import Path
from resolver_fixtures import install_resolver
import test_gsd_cli as fixtures


def resolution(**changes):
    return dict(model='chosen-model', effort='high', effort_rendered='high',
                effort_param='model_reasoning_effort', effort_propagation='api',
                effort_effective='high', effort_effective_source='resolved',
                effort_clamped=False, effort_clamp_reason=None,
                fast_mode=False, fast_mode_supported=False, **changes)


class ComparisonTests(unittest.TestCase):
    def check(self, model='chosen-model', effort='high', result=None, runtime='codex', forwarded=False, aliases=None):
        self.assertIsNotNone(importlib.util.find_spec('gsd_cli.preview'), 'preview report is not implemented')
        from gsd_cli.preview import compare
        return compare(model, effort, resolution() if result is None else result,
                       runtime, 'high', forwarded, aliases or {})

    def test_match_and_effort_or_model_mismatch(self):
        self.assertEqual(self.check()[0], 'OK')
        for key, value in [('model', 'other-model'), ('effort', 'low')]:
            r = resolution()
            r[key] = value
            status, notes = self.check(result=r)
            self.assertEqual(status, 'NOT OK')
            self.assertIn(key, ' '.join(notes).lower())

    def test_claude_installed_evidence_and_mismatch_precedence(self):
        r = resolution()
        self.assertEqual(self.check(result=r, runtime='claude')[0], 'UNKNOWN')
        r['model'] = 'wrong-model'
        self.assertEqual(self.check(result=r, runtime='claude')[0], 'NOT OK')
        r.update(model='chosen-model', effort_effective_source='frontmatter', effort_effective='low')
        self.assertEqual(self.check(result=r, runtime='claude')[0], 'NOT OK')

    def test_inheritance_and_forwarding_uncertainty(self):
        r = resolution()
        r.update(effort_effective_source='frontmatter-absent', effort_effective='inherit')
        self.assertEqual(self.check(result=r, runtime='claude')[0], 'OK')
        self.assertEqual(self.check(result=r, runtime='claude', forwarded=True)[0], 'UNKNOWN')
        self.assertEqual(self.check(effort='low', result=r, runtime='claude')[0], 'NOT OK')

    def test_clamp_unknown_expectation_and_alias_evidence(self):
        r = resolution()
        r.update(effort_clamped=True, effort_rendered='medium', effort_clamp_reason='host ceiling')
        self.assertEqual(self.check(result=r)[0], 'NOT OK')
        self.assertEqual(self.check(effort=None)[0], 'UNKNOWN')
        r.update(model='opus', effort_rendered='high', effort_clamped=False,
                 effort_effective_source='frontmatter', effort_effective='high')
        self.assertEqual(self.check(model='full-opus-id', result=r, runtime='claude',
                                    aliases={'opus': 'full-opus-id'})[0], 'OK')

    def test_explicit_installed_inherit_uses_session_effort(self):
        r = resolution()
        r.update(effort_effective_source='frontmatter', effort_effective='inherit')
        self.assertEqual(self.check(result=r, runtime='claude')[0], 'OK')
        r['effort'] = 'inherit'
        self.assertEqual(self.check(effort='inherit', result=r, runtime='claude')[0], 'OK')


@unittest.skipUnless(shutil.which('node'), 'Node is needed for resolver bridge integration tests')
class PreviewCliTests(unittest.TestCase):
    setUp = fixtures.GsdCliTestCase.setUp
    run_launcher = fixtures.GsdCliTestCase.run_launcher
    initialize = fixtures.GsdCliTestCase.initialize
    policy = fixtures.GsdCliTestCase.policy
    put_policy = fixtures.GsdCliTestCase.put_policy

    def install(self):
        self.initialize()
        for runtime in ('claude', 'codex'):
            install_resolver(self.home / f'.{runtime}')
        for key in ('GSD_WORKSTREAM', 'GSD_PROJECT', 'GSD_HOME', 'GSD_AGENTS_DIR'):
            self.env.pop(key, None)

    def snapshot(self):
        return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}

    def test_print_exit_no_writes_sessions_or_billing_requirements(self):
        self.install()
        self.env['OPENAI_API_KEY'] = 'do-not-use'
        self.env['ANTHROPIC_API_KEY'] = 'do-not-use'
        for runtime in ('codex', 'claude'):
            (self.bin / runtime).unlink()
        before = self.snapshot()
        result = self.run_launcher('plan', 'codex', '--config')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('plan/codex/medium', result.stdout)
        self.assertIn('Check', result.stdout)
        self.assertIn('gsd-planner', result.stdout)
        self.assertIn('fable-review', result.stdout)
        self.assertIn('UNKNOWN', result.stdout)
        data = json.loads(result.stdout.split('Launcher effective configuration:\n', 1)[1])
        self.assertEqual(data['models']['planning'], 'sonnet')
        self.assertEqual(data['custom'], {'keep': True})
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.log.exists())

    def test_custom_workflow_secure_and_forwarded_options(self):
        self.install()
        p = self.policy()
        p['workflows']['ship'] = copy.deepcopy(p['workflows']['exec'])
        self.put_policy(p)
        result = self.run_launcher('ship', 'claude', 'high', '--secure', '--config', '--', '--model', 'override')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ship/claude/high', result.stdout)
        self.assertIn('may override', result.stdout)
        self.assertIn('override', result.stdout)
        self.assertNotIn('--dangerously-skip-permissions', result.stdout)
        self.assertFalse(self.log.exists())

    def test_after_boundary_config_is_forwarded_to_real_launch(self):
        self.install()
        result = self.run_launcher('exec', 'codex', '--', '--config')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.log.read_text())['args'][-1], '--config')

    def test_incomplete_resolver_still_prints_configuration(self):
        self.install()
        (self.home / '.codex/gsd-core/bin/lib/commands.cjs').unlink()
        before = self.snapshot()
        result = self.run_launcher('exec', 'codex', '--config')
        self.assertEqual(result.returncode, 1)
        self.assertIn('INCOMPLETE', result.stdout)
        self.assertIn('Launcher effective configuration:', result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_inherited_effort_keeps_complete_cli_report(self):
        self.install()
        path = self.project / '.planning/config.default.json'
        data = json.loads(path.read_text())
        data['effort'] = {'agent_overrides': {'gsd-executor': 'inherit'}}
        path.write_text(json.dumps(data))
        before = self.snapshot()
        result = self.run_launcher('exec', 'codex', '--config')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('[COMPLETE]', result.stdout)
        self.assertNotIn('malformed resolver result', result.stdout)
        row = next(line for line in result.stdout.splitlines() if line.startswith('gsd-executor |'))
        self.assertIn('| inherit | inherit |', row)
        self.assertEqual(self.snapshot(), before)

    def test_pending_capture_and_config_equal_normal_launch(self):
        self.install()
        self.assertEqual(self.run_launcher('exec', 'claude').returncode, 0)
        self.log.unlink()
        data = json.loads(self.config_path.read_text())
        data['custom']['keep'] = False
        self.config_path.write_text(json.dumps(data))
        before = self.snapshot()
        result = self.run_launcher('plan', 'codex', '--config')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('custom.keep', result.stdout)
        self.assertEqual(self.snapshot(), before)
        expected = json.loads(result.stdout.split('Launcher effective configuration:\n', 1)[1])
        self.assertEqual(self.run_launcher('plan', 'codex').returncode, 0)
        self.assertEqual(json.loads(self.config_path.read_text()), expected)

    def test_terminal_controls_are_escaped(self):
        self.install()
        result = self.run_launcher('exec', 'codex', '--config', '--', 'hello\x1b[31m\nworld')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('\x1b', result.stdout)
        self.assertIn('hello\\u001b[31m\\nworld', result.stdout)

    def test_preview_help_works_without_project(self):
        result = self.run_launcher('ship', '--help', cwd=self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--config', result.stdout)
