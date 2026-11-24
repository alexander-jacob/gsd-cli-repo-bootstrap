import copy
import importlib
import json
import os
import pty
import shutil
import subprocess
import sys
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
    def test_json_color_and_terminal_detection(self):
        from gsd_cli.preview import colorize_json, use_color
        raw = '{"key":"safe\\u001b[31m", "count":12, "enabled":true, "empty":null}'
        self.assertEqual(colorize_json(raw, False), raw)
        styled = colorize_json(raw, True)
        self.assertIn('\x1b[', styled)
        self.assertEqual(__import__('re').sub(r'\x1b\[[0-9;]*m', '', styled), raw)
        self.assertEqual(styled.count('\x1b['), 16)
        class Stream:
            def isatty(self):
                return True
        self.assertTrue(use_color(Stream(), {}))
        self.assertFalse(use_color(Stream(), {'NO_COLOR': ''}))

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

    def branch_cases(self):
        """One case per compare branch: (code, severity, kwargs, status, messages) as compare returned before."""
        def r(**changes):
            row = resolution()
            row.update(changes)
            return row
        inherit = dict(effort_effective_source='frontmatter-absent', effort_effective='inherit')
        claude_ok = dict(effort_effective_source='frontmatter', effort_effective='high')
        return [
            ('model_unknown', 'unknown', dict(model=None), 'UNKNOWN',
             ['model expectation or resolution unknown']),
            ('alias_equivalent', 'note', dict(model='full-opus-id', result=r(model='opus', **claude_ok),
                                              runtime='claude', aliases={'opus': 'full-opus-id'}), 'OK',
             ['model alias equivalence confirmed by installed GSD catalog']),
            ('model_mismatch', 'mismatch', dict(result=r(model='other\x1b')), 'NOT OK',
             ['model expected chosen-model, resolved other\\u001b']),
            ('effort_unknown', 'unknown', dict(effort=None), 'UNKNOWN',
             ['effort expectation or resolution unknown']),
            ('effort_mismatch', 'mismatch', dict(result=r(effort='low')), 'NOT OK',
             ['effort expected high, resolved low']),
            ('effort_clamped', 'mismatch', dict(result=r(effort_clamped=True, effort_rendered='medium',
                                                         effort_clamp_reason='host ceiling')), 'NOT OK',
             ['effort clamped to medium: host ceiling']),
            ('inherits_session_effort', 'note', dict(result=r(**inherit), runtime='claude'), 'OK',
             ['installed effort inherits the session']),
            ('forwarded_may_override', 'unknown', dict(result=r(**inherit), runtime='claude', forwarded=True),
             'UNKNOWN', ['forwarded options may override inherited session effort',
                         'installed effort inherits the session']),
            ('installed_effort_unknown', 'unknown', dict(runtime='claude'), 'UNKNOWN',
             ['installed Claude effort unknown; resolver supplied no file evidence']),
            ('inherit_depends_on_forwarded', 'unknown',
             dict(effort='inherit', result=r(effort='inherit', **claude_ok), runtime='claude', forwarded=True),
             'UNKNOWN', ['requested inherited effort depends on forwarded session options']),
            ('installed_effort_mismatch', 'mismatch',
             dict(result=r(effort_effective_source='frontmatter', effort_effective='low'), runtime='claude'),
             'NOT OK', ['installed effort expected high, found low']),
            ('propagation_unknown', 'unknown', dict(result=r(effort_propagation=None)), 'UNKNOWN',
             ['runtime effort propagation unsupported or unknown']),
            ('unregistered_agent', 'unknown', dict(result=r(unknown_agent=True)), 'UNKNOWN',
             ['agent is not registered in the installed GSD catalog']),
        ]

    def test_findings_codes_cover_each_branch(self):
        from gsd_cli.preview import findings
        cases = self.branch_cases()
        self.assertEqual(len({case[0] for case in cases}), 13)
        for code, severity, kwargs, _, _ in cases:
            with self.subTest(code):
                options = dict(model='chosen-model', effort='high', result=resolution(), runtime='codex',
                               forwarded=False, aliases={})
                options.update(kwargs)
                found = findings(options['model'], options['effort'], options['result'], options['runtime'],
                                 'high', options['forwarded'], options['aliases'])
                self.assertIn((code, severity), [(f.code, f.severity) for f in found])

    def test_compare_is_unchanged(self):
        for code, _, kwargs, status, messages in self.branch_cases():
            with self.subTest(code):
                self.assertEqual(self.check(**kwargs), (status, messages))
        r = resolution()
        r.update(model='bad', effort_propagation=None, effort_effective_source='frontmatter-absent', effort_effective='inherit')
        self.assertEqual(self.check(effort=None, result=r, runtime='claude', forwarded=True),
                         ('NOT OK', ['model expected chosen-model, resolved bad',
                                     'effort expectation or resolution unknown',
                                     'forwarded options may override inherited session effort',
                                     'installed effort inherits the session']))

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
        result = self.run_launcher('codex', 'medium', '--config')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('codex/medium', result.stdout)
        self.assertIn('Check', result.stdout)
        self.assertIn('gsd-planner', result.stdout)
        self.assertIn('fable-review', result.stdout)
        self.assertIn('?', result.stdout)
        self.assertNotIn('Launcher effective configuration:', result.stdout)
        self.assertIn('Coverage', result.stdout)
        self.assertIn('gsd-executor', result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.log.exists())

    def test_custom_blueprint_secure_and_forwarded_options(self):
        self.install()
        p = self.policy()
        p['runtimes']['claude']['blueprints']['ship'] = copy.deepcopy(p['runtimes']['claude']['blueprints']['high'])
        self.put_policy(p)
        result = self.run_launcher('claude', 'ship', '--secure', '--config', '--', '--model', 'override')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('claude/ship', result.stdout)
        self.assertIn('forwarded options', result.stdout.lower())
        self.assertNotIn('--dangerously-skip-permissions', result.stdout)
        self.assertFalse(self.log.exists())

    def test_after_boundary_config_is_forwarded_to_real_launch(self):
        self.install()
        result = self.run_launcher('codex', 'medium', '--', '--config')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.log.read_text())['args'][-1], '--config')

    def test_incomplete_resolver_still_prints_configuration(self):
        self.install()
        (self.home / '.codex/gsd-core/bin/lib/commands.cjs').unlink()
        before = self.snapshot()
        result = self.run_launcher('codex', 'medium', '--config')
        self.assertEqual(result.returncode, 1)
        self.assertIn('INCOMPLETE', result.stdout)
        self.assertIn('Diagnostic:', result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_inherited_effort_keeps_complete_cli_report(self):
        self.install()
        path = self.project / '.planning/config.default.json'
        data = json.loads(path.read_text())
        data['effort'] = {'agent_overrides': {'gsd-unmanaged': 'inherit'}}
        path.write_text(json.dumps(data))
        before = self.snapshot()
        result = self.run_launcher('codex', 'medium', '--config')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('[COMPLETE]', result.stdout)
        self.assertNotIn('malformed resolver result', result.stdout)
        self.assertIn('gsd-executor', result.stdout)
        self.assertIn('inherit', result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_pending_capture_and_config_equal_normal_launch(self):
        self.install()
        self.assertEqual(self.run_launcher('claude', 'medium').returncode, 0)
        self.log.unlink()
        data = json.loads(self.config_path.read_text())
        data['custom']['keep'] = False
        self.config_path.write_text(json.dumps(data))
        before = self.snapshot()
        result = self.run_launcher('codex', 'medium', '--config')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('custom.keep', result.stdout)
        self.assertEqual(self.snapshot(), before)
        details = self.run_launcher('codex', 'medium', '--config', '--details')
        self.assertEqual(details.returncode, 0, details.stderr)
        expected = json.loads(details.stdout.split('Launcher effective configuration:\n', 1)[1])
        self.assertEqual(self.run_launcher('codex', 'medium').returncode, 0)
        self.assertEqual(json.loads(self.config_path.read_text()), expected)

    def test_terminal_controls_are_escaped(self):
        self.install()
        result = self.run_launcher('codex', 'medium', '--config', '--', 'hello\x1b[31m\nworld')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('\x1b', result.stdout)
        self.assertIn('hello\\u001b[31m\\nworld', result.stdout)

    def test_preview_help_works_without_project(self):
        result = self.run_launcher('claude', '--help', cwd=self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--config', result.stdout)
        self.assertIn('--details', result.stdout)

    def test_details_requires_config_and_forwarded_details_is_child_option(self):
        self.install()
        self.assertNotEqual(self.run_launcher('codex', 'medium', '--details').returncode, 0)
        result = self.run_launcher('codex', 'medium', '--config', '--details')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Launcher effective configuration:', result.stdout)
        self.assertIn('Host effort argv:', result.stdout)
        self.assertEqual(self.run_launcher('codex', 'medium', '--', '--details').returncode, 0)
        self.assertEqual(json.loads(self.log.read_text())['args'][-1], '--details')

    def test_compact_includes_uncovered_and_explicitly_covered_roles(self):
        self.install()
        catalog = self.home / '.codex/gsd-core/bin/shared/model-catalog.json'
        data = json.loads(catalog.read_text())
        data['agents']['gsd-uncovered'] = {'phaseType': 'future'}
        data['agents']['gsd-special'] = {'phaseType': 'future'}
        catalog.write_text(json.dumps(data))
        policy = self.policy()
        policy['runtimes']['codex']['blueprints']['medium']['agents']['gsd-special'] = {
            'model': 'custom-model', 'effort': 'high'}
        self.put_policy(policy)
        result = self.run_launcher('codex', 'medium', '--config')
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, covered in [('gsd-special', True), ('gsd-uncovered', False)]:
            line = next(line for line in result.stdout.splitlines() if name in line)
            self.assertIn('covered' if covered else 'uncovered', line)
        rows = {row.agent: row for row in self.preview_json('codex', 'medium').data.agents}
        self.assertIn('agent/agent', next(line for line in result.stdout.splitlines() if 'gsd-special' in line))
        self.assertIn('phase/agent', next(line for line in result.stdout.splitlines() if 'gsd-planner' in line))
        self.assertTrue(rows['gsd-special'].covered)
        self.assertFalse(rows['gsd-uncovered'].covered)
        self.assertTrue(rows['gsd-special'].expected.model_source.endswith('agents.gsd-special.model'))

    def test_tty_colors_checks_and_no_color_disables_them(self):
        self.install()
        def tty_output(env):
            master, slave = pty.openpty()
            try:
                result = subprocess.run([sys.executable, str(fixtures.LAUNCHER), 'codex', 'medium', '--config'],
                                        cwd=self.project, env=env, stdout=slave, stderr=subprocess.PIPE, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                os.close(slave)
                slave = -1
                chunks = []
                while True:
                    try:
                        chunks.append(os.read(master, 65536))
                    except OSError:
                        break
                return b''.join(chunks).decode()
            finally:
                os.close(master)
                if slave != -1:
                    os.close(slave)
        color_env = self.env.copy()
        color_env.pop('NO_COLOR', None)
        colored = tty_output(color_env)
        self.assertIn('\x1b[', colored)
        self.assertIn('✓', colored)
        plain = tty_output({**self.env, 'NO_COLOR': ''})
        self.assertNotIn('\x1b[', plain)

    def preview_json(self, *args, code=0):
        from gsd_cli.models import PreviewEnvelope
        result = self.run_launcher(*args, '--config', '--json')
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')
        return PreviewEnvelope.model_validate_json(result.stdout, strict=True)

    def patch_fixture(self, runtime, old, new):
        path = self.home / f'.{runtime}/gsd-core/bin/lib/commands.cjs'
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new))

    def test_config_json_reports_session_agents_and_reviewers(self):
        self.install()
        policy = self.policy()
        env = self.preview_json('claude', 'high')
        self.assertTrue(env.ok and env.data.complete)
        self.assertIsNone(env.error)
        self.assertEqual((env.data.runtime, env.data.blueprint), ('claude', 'high'))
        self.assertEqual(env.data.project, str(self.project.resolve()))
        self.assertEqual(env.data.session.model, policy['runtimes']['claude']['blueprints']['high']['session']['model'])
        self.assertEqual(env.data.session.permissions, 'bypass')
        self.assertEqual(env.data.session.argv[0], 'claude')
        self.assertEqual(env.data.session.forwarded, [])
        planner = next(a for a in env.data.agents if a.agent == 'gsd-planner')
        self.assertTrue(planner.covered)
        self.assertEqual(planner.phase, 'planning')
        self.assertTrue(planner.expected.effort_source.endswith('agents.gsd-planner.effort'))
        self.assertTrue(planner.expected.model_source.endswith('phases.planning.model'))
        self.assertEqual(planner.resolved.model, 'fable')
        self.assertEqual([a.agent for a in env.data.agents],
                         [a.agent for a in sorted(env.data.agents, key=lambda a: (a.phase, a.agent))])
        self.assertEqual([r.name for r in env.data.reviewers],
                         policy['runtimes']['claude']['review']['default_reviewers'])
        self.assertTrue(all(r.cli for r in env.data.reviewers))
        self.assertTrue(env.data.installation.ok)
        self.assertEqual(env.data.installation.runtime, 'claude')
        self.assertIsNotNone(env.data.gsd_context)
        self.assertEqual(env.data.gsd_context.source, 'root')
        details = self.run_launcher('claude', 'high', '--config', '--details')
        self.assertEqual(details.returncode, 0, details.stderr)
        effective = json.loads(details.stdout.split('Launcher effective configuration:\n', 1)[1])
        self.assertEqual(env.data.config, effective)
        self.assertFalse(self.log.exists())

    def test_secure_changes_requested_permissions(self):
        self.install()
        self.assertEqual(self.preview_json('codex', 'medium').data.session.permissions, 'bypass')
        secure = self.preview_json('codex', 'medium', '--secure').data.session
        self.assertEqual(secure.permissions, 'normal')
        self.assertFalse(any(a.startswith('--dangerously-') for a in secure.argv))

    def test_policy_defaults_seed_only_the_initial_tracked_defaults(self):
        from gsd_cli.policy import load_default

        policy = load_default()
        policy['gsd_defaults']['template_field'] = 'initial'
        self.put_policy(policy)
        self.install()
        self.assertNotIn('template_field', json.loads(self.config_path.read_text(encoding='utf-8')))
        self.assertEqual(self.preview_json('codex', 'medium').data.config['template_field'], 'initial')

        policy['gsd_defaults']['template_field'] = 'changed'
        policy['gsd_defaults']['new_template_field'] = True
        self.put_policy(policy)
        self.initialize()
        before = self.snapshot()
        preview = self.preview_json('codex', 'medium')
        self.assertEqual(preview.data.config['template_field'], 'initial')
        self.assertNotIn('new_template_field', preview.data.config)
        self.assertEqual(self.snapshot(), before)

    def test_partial_override_for_uncovered_role_requires_both_fields(self):
        self.install()
        catalog = self.home / '.codex/gsd-core/bin/shared/model-catalog.json'
        manifest = json.loads(catalog.read_text(encoding='utf-8'))
        manifest['agents']['gsd-uncovered'] = {}
        catalog.write_text(json.dumps(manifest), encoding='utf-8')
        policy = self.policy()
        agents = policy['runtimes']['codex']['blueprints']['medium'].setdefault('agents', {})
        agents['gsd-uncovered'] = {'effort': 'high'}
        self.put_policy(policy)
        before = self.snapshot()
        text = self.run_launcher('codex', 'medium', '--config')
        self.assertEqual(text.returncode, 1)
        error = self.preview_json('codex', 'medium', code=1)
        self.assertIsNone(error.data)
        self.assertEqual(error.error.kind, 'policy')
        message = 'runtimes.codex.blueprints.medium.agents.gsd-uncovered.model'
        self.assertIn(message, text.stderr)
        self.assertIn(message, error.error.message)
        self.assertEqual(self.snapshot(), before)

    def test_preview_distinguishes_installed_from_project_effort(self):
        self.install()
        subprocess.run(['git', 'init', '-q'], cwd=self.project, check=True)
        subprocess.run(['git', 'add', 'gsd-cli.config.json'], cwd=self.project, check=True)
        self.assertEqual(self.run_launcher('claude', 'high').returncode, 0)
        self.patch_fixture('claude', "effort_effective: effort, effort_effective_source: 'resolved'",
                           "effort_effective: 'high', effort_effective_source: 'frontmatter'")
        before = self.snapshot()
        env = self.preview_json('claude', 'low')
        executor = next(a for a in env.data.agents if a.agent == 'gsd-executor')
        self.assertEqual(executor.resolved.effort_effective, 'high')
        self.assertEqual(executor.resolved.effort_effective_source, 'frontmatter')
        definition = executor.project_definition
        self.assertEqual(definition.source, str(self.home / '.claude/agents/gsd-executor.md'))
        self.assertEqual(definition.destination, '.claude/agents/gsd-executor.md')
        self.assertEqual((definition.effort, definition.action), ('low', 'update'))
        self.assertEqual(executor.check, 'unknown')
        self.assertIn(('project_effort_unverified', 'unknown'), [(f.code, f.severity) for f in executor.findings])
        self.assertFalse(any(f.severity == 'mismatch' for f in executor.findings))
        for options in ([], ['--details']):
            output = self.run_launcher('claude', 'low', '--config', *options)
            self.assertEqual(output.returncode, 0, output.stderr)
            self.assertIn(definition.destination, output.stdout)
            self.assertIn('update', output.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_preview_reports_orphan_removal_and_path_specific_conflict(self):
        self.install()
        catalog = self.home / '.claude/gsd-core/bin/shared/model-catalog.json'
        manifest = json.loads(catalog.read_text())
        manifest['agents']['gsd-retired'] = {'phaseType': 'execution'}
        catalog.write_text(json.dumps(manifest))
        source = self.home / '.claude/agents/gsd-retired.md'
        source.write_text('---\nname: gsd-retired\n---\nPrompt')
        created = self.preview_json('claude', 'medium')
        row = next(row for row in created.data.agents if row.agent == 'gsd-retired')
        self.assertEqual(row.project_definition.action, 'create')
        self.assertIn('installed_effort_unknown', {finding.code for finding in row.findings})
        self.assertEqual(self.run_launcher('claude', 'medium').returncode, 0)
        del manifest['agents']['gsd-retired']
        catalog.write_text(json.dumps(manifest))
        before = self.snapshot()
        row = next(row for row in self.preview_json('claude', 'medium').data.agents if row.agent == 'gsd-retired')
        self.assertFalse(row.covered)
        self.assertEqual(row.project_definition.action, 'remove')
        self.assertIsNone(row.project_definition.source)
        self.assertEqual(self.snapshot(), before)
        target = self.project / row.project_definition.destination
        target.write_text(target.read_text() + 'hand edit')
        before = self.snapshot()
        failure = self.preview_json('claude', 'medium', code=1)
        self.assertIsNone(failure.data)
        self.assertEqual(failure.error.kind, 'config')
        self.assertIn(str(target), failure.error.message)
        self.assertEqual(self.snapshot(), before)

    def test_catalog_failure_preserves_session_and_reviewers(self):
        self.install()
        catalog = self.home / '.claude/gsd-core/bin/shared/model-catalog.json'
        catalog.unlink()
        before = self.snapshot()
        env = self.preview_json('claude', 'high', code=1)
        self.assertEqual(env.error.kind, 'incomplete')
        self.assertEqual(env.data.agents, [])
        self.assertIsNone(env.data.config)
        self.assertEqual(env.data.session.effort, 'high')
        self.assertTrue(env.data.reviewers)
        self.assertIn(str(catalog), ' '.join(env.data.diagnostics))
        for options in ([], ['--details']):
            output = self.run_launcher('claude', 'high', '--config', *options)
            self.assertEqual(output.returncode, 1)
            self.assertIn('INCOMPLETE', output.stdout)
            self.assertIn(str(catalog), output.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_incomplete_inspection_fails_with_data(self):
        self.install()
        path = self.project / '.planning/config.default.json'
        data = json.loads(path.read_text())
        data['fail_agent'] = 'gsd-planner'
        path.write_text(json.dumps(data))
        env = self.preview_json('codex', 'medium', code=1)
        self.assertFalse(env.ok)
        self.assertEqual(env.error.kind, 'incomplete')
        self.assertFalse(env.data.complete)
        self.assertTrue(env.data.diagnostics)
        planner = next(a for a in env.data.agents if a.agent == 'gsd-planner')
        self.assertIsNone(planner.resolved)
        self.assertEqual(planner.check, 'unknown')

    def test_unknown_resolver_keys_pass_through(self):
        self.install()
        self.patch_fixture('codex', "fast_mode: false,", "future_key: 1, fast_mode: false,")
        result = self.run_launcher('codex', 'medium', '--config', '--json')
        self.assertEqual(result.returncode, 0, result.stdout)
        body = json.loads(result.stdout)
        self.assertEqual(body['data']['agents'][0]['resolved']['future_key'], 1)
        from gsd_cli.models import PreviewEnvelope
        PreviewEnvelope.model_validate_json(result.stdout, strict=True)

    def put_working(self, change):
        path = self.project / '.planning/config.default.json'
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))

    def test_non_string_configured_values_are_reported_as_configured(self):
        self.install()
        def change(data):
            data.setdefault('model_overrides', {})['gsd-unmanaged'] = 5
            data.setdefault('effort', {}).setdefault('agent_overrides', {})['gsd-unmanaged'] = ['high']
        self.put_working(change)
        text = self.run_launcher('claude', 'medium', '--config')
        result = self.run_launcher('claude', 'medium', '--config', '--json')
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.returncode, text.returncode, text.stderr)
        from gsd_cli.models import PreviewEnvelope
        env = PreviewEnvelope.model_validate_json(result.stdout, strict=True)
        agent = next(a for a in env.data.agents if a.agent == 'gsd-unmanaged')
        self.assertEqual((agent.expected.model, agent.expected.effort), (5, ['high']))

    def test_non_finite_config_values_are_a_config_error(self):
        self.install()
        effective = self.project / '.planning/config.json'
        effective.write_text(json.dumps({**json.loads(effective.read_text()), 'gsd_cli_probe': float('nan')}))
        for args in (('status', '--json'), ('claude', 'medium', '--config', '--json')):
            with self.subTest(args):
                result = self.run_launcher(*args)
                self.assertEqual((result.returncode, result.stderr), (1, ''))
                body = json.loads(result.stdout)
                self.assertEqual((body['ok'], body['data'], body['error']['kind']), (False, None, 'config'))
                self.assertIn('NaN is not valid JSON', body['error']['message'])
        for args in (('status',), ('claude', 'medium', '--config')):
            with self.subTest(args):
                result = self.run_launcher(*args)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn('Traceback', result.stderr)
                self.assertIn('NaN is not valid JSON', result.stderr)

    def test_hostile_values_stay_inside_json_strings(self):
        self.install()
        hostile = 'evil\x1b[31m-é'
        p = self.policy()
        p['runtimes']['claude']['blueprints']['high']['session']['model'] = hostile
        self.put_policy(p)
        result = subprocess.run([sys.executable, str(fixtures.LAUNCHER), 'claude', 'high', '--config', '--json'],
                                cwd=self.project, env=self.env, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn(b'\x1b', result.stdout)
        self.assertIn(b'\\u001b', result.stdout)
        self.assertIn(b'\\u00e9', result.stdout)
        self.assertEqual(json.loads(result.stdout)['data']['session']['model'], hostile)

    def test_json_requires_config_and_never_launches(self):
        self.install()
        result = self.run_launcher('claude', 'medium', '--json')
        self.assertEqual(result.returncode, 2)
        body = json.loads(result.stdout)
        self.assertEqual((body['ok'], body['command'], body['error']['kind']), (False, 'preview', 'usage'))
        self.assertIn('--json requires --config', body['error']['message'])
        self.assertFalse(self.log.exists())

    def test_json_and_details_are_exclusive(self):
        self.install()
        result = self.run_launcher('claude', 'medium', '--config', '--details', '--json')
        self.assertEqual(result.returncode, 2)
        body = json.loads(result.stdout)
        self.assertEqual((body['ok'], body['command'], body['error']['kind']), (False, 'preview', 'usage'))
        self.assertIn('--details', body['error']['message'])
        self.assertFalse(self.log.exists())

    def test_config_json_writes_nothing(self):
        self.install()
        self.assertEqual(self.run_launcher('claude', 'medium').returncode, 0)
        self.log.unlink()
        data = json.loads(self.config_path.read_text())
        data['custom']['keep'] = False
        self.config_path.write_text(json.dumps(data))
        def tree():
            return {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
                    for base in (self.project, self.root / 'state') for p in base.rglob('*') if p.is_file()}
        before = tree()
        env = self.preview_json('codex', 'medium')
        self.assertIn('custom.keep', env.data.pending_capture)
        self.assertEqual(tree(), before)
        self.assertFalse(self.log.exists())
