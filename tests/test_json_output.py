"""JSON-mode envelope and error handling; no network or real model calls."""
import copy
import fcntl
import importlib.metadata
import json
import shutil
import unittest
from datetime import datetime, timezone
from unittest import mock

from jsonschema import Draft202012Validator, ValidationError

import test_gsd_cli as fixtures
from gsd_cli import cli, config, models, policy
from gsd_cli.models import CheckEnvelope, PolicyEnvelope, StatusEnvelope
from session_fixtures import claude_session
from test_versions import install_gsd


class JsonErrorTests(fixtures.GsdCliFixture):
    def envelope(self, result):
        self.assertEqual(result.stderr, '')
        self.assertTrue(result.stdout.endswith('\n'))
        body = json.loads(result.stdout)
        self.assertIsInstance(body, dict)
        self.assertEqual(body['schema_version'], 2)
        return body

    def test_unknown_option_before_command_is_usage_envelope(self):
        result = self.run_launcher('--json', 'status')
        self.assertEqual(result.returncode, 2)
        body = self.envelope(result)
        self.assertEqual((body['ok'], body['command'], body['data'], body['error']['kind']),
                         (False, None, None, 'usage'))

    def test_init_has_no_json_form(self):
        result = self.run_launcher('init', '--json')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.envelope(result)['command'], None)
        self.assertFalse((self.project / 'gsd-cli.config.json').exists())

    def test_outside_project_is_config_error(self):
        result = self.run_launcher('status', '--json', cwd=self.root)
        self.assertEqual(result.returncode, 1)
        body = self.envelope(result)
        self.assertEqual((body['command'], body['error']['kind']), ('status', 'config'))

    def test_json_after_separator_is_a_child_argument(self):
        result = self.run_launcher('status', '--', '--json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('forwarding after --', result.stderr)

    def test_help_wins_over_json(self):
        result = self.run_launcher('--help', '--json')
        self.assertEqual(result.returncode, 0)
        self.assertIn('Usage:', result.stdout)

    def test_version_prints_installed_version(self):
        expected = f"gsd-cli {importlib.metadata.version('gsd-workflow-cli')}\n"
        for args in (('--version',), ('-V',), ('--version', '--json'), ('--json', '--version')):
            with self.subTest(args):
                result = self.run_launcher(*args, cwd=self.root)  # outside any project
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ''))

    def test_version_after_a_command_keeps_json_mode(self):
        result = self.run_launcher('status', '--json', '--version', cwd=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.envelope(result)['error']['kind'], 'usage')

    def test_short_flag_clusters_win_over_json_like_click_accepts_them(self):
        version = f"gsd-cli {importlib.metadata.version('gsd-workflow-cli')}\n"
        for args in (('--json', '-hV'), ('-hV', '--json'), ('status', '--json', '-hh')):
            with self.subTest(args):
                result = self.run_launcher(*args, cwd=self.root)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertTrue(result.stdout.startswith('Usage:'), result.stdout)
        result = self.run_launcher('--json', '-Vh', cwd=self.root)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, version, ''))

    def test_short_flag_clusters_click_rejects_stay_usage_envelopes(self):
        for args in (('--json', '-hX'), ('status', '--json', '-hV')):
            with self.subTest(args):
                result = self.run_launcher(*args, cwd=self.root)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.envelope(result)['error']['kind'], 'usage')

    def test_package_version_without_metadata(self):
        with mock.patch('importlib.metadata.version', side_effect=importlib.metadata.PackageNotFoundError):
            self.assertEqual(cli.package_version(), 'unknown')

    def test_policy_and_schema_are_selectable_blueprint_names(self):
        self.initialize()
        path = self.project / 'gsd-cli.config.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        for name in ('policy', 'schema'):
            policy = copy.deepcopy(original)
            blueprints = policy['runtimes']['claude']['blueprints']
            blueprints[name] = copy.deepcopy(blueprints['medium'])
            path.write_text(json.dumps(policy), encoding='utf-8')
            result = self.run_launcher('claude', name)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_forwarding_after_policy_or_schema_is_rejected(self):
        for name in ('policy', 'schema'):
            result = self.run_launcher(name, '--', 'x')
            self.assertEqual(result.returncode, 2)
            self.assertIn('forwarding after --', result.stderr)

    def test_policy_error_is_policy_envelope(self):
        self.initialize()
        (self.project / 'gsd-cli.config.json').write_text('{}', encoding='utf-8')
        result = self.run_launcher('claude', 'medium', '--config', '--json')
        self.assertEqual(result.returncode, 1)
        body = self.envelope(result)
        self.assertEqual((body['ok'], body['command'], body['error']['kind']), (False, 'preview', 'policy'))


class JsonReadTests(fixtures.GsdCliFixture):
    def test_status_json_wraps_plain_status(self):
        self.initialize()
        plain = json.loads(self.run_launcher('status').stdout)
        result = self.run_launcher('status', '--json')
        env = StatusEnvelope.model_validate_json(result.stdout, strict=True)
        self.assertTrue(env.ok)
        self.assertEqual(env.data.model_dump(exclude={'project'}), plain)
        self.assertEqual(env.data.project, str(self.project.resolve()))

    def test_check_json_reports_each_runtime_and_fails_with_data(self):
        self.initialize()
        install_gsd(self.home / '.codex', '1.0.0')
        result = self.run_launcher('check', '--json')
        self.assertEqual(result.returncode, 1)
        env = CheckEnvelope.model_validate_json(result.stdout, strict=True)
        self.assertEqual([(r.runtime, r.ok, r.reason) for r in env.data.results],
                         [('claude', True, 'ok'), ('codex', False, 'below_minimum')])
        self.assertEqual(env.error.kind, 'requirements')

    def test_check_json_unverifiable_install(self):
        self.initialize()
        shutil.rmtree(self.home / '.codex')
        result = self.run_launcher('check', '--json')
        self.assertEqual(result.returncode, 1)
        env = CheckEnvelope.model_validate_json(result.stdout, strict=True)
        codex = env.data.results[1]
        self.assertEqual((codex.ok, codex.reason, codex.installed), (False, 'unverifiable', None))

    def test_check_json_single_runtime(self):
        self.initialize()
        result = self.run_launcher('check', 'claude', '--json')
        self.assertEqual(result.returncode, 0)
        env = CheckEnvelope.model_validate_json(result.stdout, strict=True)
        self.assertEqual([r.runtime for r in env.data.results], ['claude'])
        self.assertTrue(env.ok)
        self.assertIsNone(env.error)

    def test_policy_text_and_json(self):
        self.initialize()
        text = self.run_launcher('policy')
        self.assertEqual(text.returncode, 0)
        self.assertEqual(text.stdout, f'Policy valid: {self.project}/gsd-cli.config.json\n')
        env = PolicyEnvelope.model_validate_json(self.run_launcher('policy', '--json').stdout, strict=True)
        self.assertEqual(env.data.policy, self.policy())
        self.assertEqual(env.data.differs_from_shipped, [])

    def test_policy_reports_local_differences(self):
        self.initialize()
        policy = self.policy()
        policy['runtimes']['claude']['blueprints']['high']['agents']['gsd-planner']['effort'] = 'low'
        self.put_policy(policy)
        env = PolicyEnvelope.model_validate_json(self.run_launcher('policy', '--json').stdout, strict=True)
        self.assertEqual(env.data.differs_from_shipped, ['runtimes.claude.blueprints.high.agents.gsd-planner.effort'])

    def test_invalid_policy_is_policy_error(self):
        self.initialize()
        policy = self.policy()
        policy['runtimes']['codex']['blueprints']['low']['phases']['planning']['effort'] = 'huge'
        self.put_policy(policy)
        result = self.run_launcher('policy', '--json')
        self.assertEqual(result.returncode, 1)
        body = json.loads(result.stdout)
        self.assertEqual((body['ok'], body['command'], body['data'], body['error']['kind']),
                         (False, 'policy', None, 'policy'))
        self.assertTrue(body['error']['message'].startswith('runtimes.codex.blueprints.low.phases.planning.effort'))

    def test_missing_policy_is_config_error(self):
        result = self.run_launcher('policy', '--json')
        self.assertEqual(result.returncode, 1)
        body = json.loads(result.stdout)
        self.assertEqual(body['error']['kind'], 'config')
        self.assertIn('gsd-cli init', body['error']['message'])

    def snapshot_tree(self):
        return {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.root.rglob('*') if path.is_file()}

    def test_read_commands_leave_held_lock_and_pending_journal_untouched(self):
        self.initialize()
        self.assertEqual(self.run_launcher('claude', 'medium').returncode, 0)
        journal = self.project / config.JOURNAL
        lock = self.project / config.LOCK
        with lock.open('r') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = self.snapshot_tree()
            self.assert_preview_config_error('Another gsd-cli process')
            self.assertEqual(self.snapshot_tree(), before)

        journal.write_text('pending recovery', encoding='utf-8')
        before = self.snapshot_tree()
        self.assert_preview_config_error('Pending configuration recovery')
        for args in (('status',), ('check',), ('policy',), ('sessions',)):
            with self.subTest(args=args):
                plain = self.run_launcher(*args)
                structured = self.run_launcher(*args, '--json')
                self.assertEqual((plain.returncode, structured.returncode), (0, 0))
                body = json.loads(structured.stdout)
                self.assertTrue(body['ok'])
                if args == ('status',):
                    self.assertTrue(json.loads(plain.stdout)['pending_recovery'])
                    self.assertTrue(body['data']['pending_recovery'])
        self.assertEqual(self.snapshot_tree(), before)

    def assert_preview_config_error(self, message):
        args = ('codex', 'medium', '--config')
        text = self.run_launcher(*args)
        structured = self.run_launcher(*args, '--json')
        self.assertEqual((text.returncode, structured.returncode), (1, 1))
        self.assertIn(message, text.stderr)
        body = json.loads(structured.stdout)
        self.assertIsNone(body['data'])
        self.assertEqual(body['error']['kind'], 'config')
        self.assertIn(message, body['error']['message'])


class ModelTests(unittest.TestCase):
    def test_json_command_detection(self):
        from gsd_cli.cli import json_command
        self.assertEqual(json_command(['status', '--json']), 'status')
        self.assertIsNone(json_command([]))
        self.assertIsNone(json_command(['--json']))
        self.assertIsNone(json_command(['init']))
        self.assertIsNone(json_command(['plan', 'claude']))
        self.assertEqual(json_command(['claude', 'medium']), 'preview')

    def test_failure_uses_each_command_envelope(self):
        from gsd_cli.models import ErrorEnvelope, failure
        self.assertIsInstance(failure(None, 'usage', 'x'), ErrorEnvelope)
        for command in models.JSON_COMMANDS:
            with self.subTest(command):
                envelope = failure(command, 'config', 'x')
                self.assertIs(type(envelope), models.SCHEMAS[command])
                self.assertEqual((envelope.command, envelope.ok, envelope.data), (command, False, None))

    def test_dump_format(self):
        from gsd_cli.models import dump, failure
        text = dump(failure(None, 'usage', 'café'))
        self.assertTrue(text.endswith('\n'))
        self.assertIn('\\u00e9', text)
        self.assertIn('\n  "ok": false', text)
        with self.assertRaises(Exception):
            from gsd_cli.models import ErrorInfo
            ErrorInfo(kind='bogus', message='x')


class SchemaCommandTests(fixtures.GsdCliFixture):
    def test_lists_names_outside_a_project(self):
        result = self.run_launcher('schema', cwd=self.root)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.split(), sorted(models.SCHEMAS))
        self.assertEqual(result.stdout.split(),
                         ['check', 'error', 'policy', 'policy-file', 'preview', 'sessions', 'status'])

    def test_prints_generated_schema(self):
        for name, model in models.SCHEMAS.items():
            with self.subTest(name):
                result = self.run_launcher('schema', name, cwd=self.root)
                self.assertEqual(result.returncode, 0)
                self.assertTrue(result.stdout.endswith('\n'))
                self.assertEqual(json.loads(result.stdout), model.model_json_schema())

    def test_cli_documents_validate_against_published_schemas(self):
        names = ('check', 'error', 'policy', 'policy-file', 'preview', 'sessions', 'status')
        validators = {}
        for name in names:
            with self.subTest(schema=name):
                result = self.run_launcher('schema', name, cwd=self.root)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                schema = json.loads(result.stdout)
                Draft202012Validator.check_schema(schema)
                validators[name] = Draft202012Validator(schema)

        example = fixtures.LAUNCHER.parent / 'examples' / 'gsd-config-example.json'
        for data in (policy.load_default(), json.loads(example.read_text(encoding='utf-8'))):
            policy.validate(data)
            self.assertEqual(data['schema_version'], 2)
            validators['policy-file'].validate(data)

        def validate_envelope(name, args, exit_code=0, error_kind=None, cwd=None):
            plain = self.run_launcher(*args, cwd=cwd)
            result = self.run_launcher(*args, '--json', cwd=cwd)
            self.assertEqual((plain.returncode, result.returncode), (exit_code, exit_code))
            self.assertEqual(result.stderr, '')
            data = json.loads(result.stdout)
            validators[name].validate(data)
            self.assertEqual(data['schema_version'], 2)
            self.assertEqual(data['command'], None if name == 'error' else name)
            self.assertIs(data['ok'], exit_code == 0)
            if error_kind is None:
                self.assertIsNone(data['error'])
                self.assertIsInstance(data['data'], dict)
            else:
                self.assertEqual(data['error']['kind'], error_kind)
            return data

        self.initialize()
        claude_session(
            self.home, self.project, 'fixture-session', datetime(2026, 10, 1, tzinfo=timezone.utc),
            'claude-sonnet-5-5', 'medium',
            agents=[{'id': 'executor', 'type': 'gsd-executor', 'requested': 'sonnet',
                     'model': 'claude-sonnet-5-5', 'effort': 'medium', 'parent': None}],
        )
        preview_args = ('codex', 'medium', '--config')
        for name, args in (
            ('check', ('check',)),
            ('policy', ('policy',)),
            ('sessions', ('sessions', 'claude')),
            ('status', ('status',)),
        ):
            with self.subTest(schema=name, ok=True):
                envelope = validate_envelope(name, args)
                if name == 'policy':
                    validators['policy-file'].validate(envelope['data']['policy'])
                if name == 'sessions':
                    child, = envelope['data']['sessions'][0]['children']
                    self.assertEqual(child['agent_type'], 'gsd-executor')
        if shutil.which('node', path=self.env['PATH']):
            with self.subTest(schema='preview', ok=True):
                preview = validate_envelope('preview', preview_args)
                self.assertTrue(preview['data']['complete'])

        bundle = self.home / '.codex' / 'gsd-core'
        version = bundle / 'VERSION'
        installed = version.read_bytes()
        version.write_text('1.0.0\n', encoding='utf-8')
        check = validate_envelope('check', ('check',), 1, 'requirements')
        self.assertEqual([(r['runtime'], r['reason']) for r in check['data']['results']],
                         [('claude', 'ok'), ('codex', 'below_minimum')])
        with self.assertRaises(ValidationError):
            validators['check'].validate({**check, 'schema_version': 1})
        version.write_bytes(installed)
        (bundle / 'bin/shared/model-catalog.json').unlink()
        preview = validate_envelope('preview', preview_args, 1, 'incomplete')
        self.assertFalse(preview['data']['complete'])
        self.assertTrue(preview['data']['diagnostics'])

        for name, args, code, kind, cwd in (
            ('error', ('--unknown',), 2, 'usage', self.root),
            ('check', ('check',), 1, 'config', self.root),
            ('policy', ('policy',), 1, 'config', self.root),
            ('sessions', ('sessions', 'invalid'), 1, 'usage', self.project),
            ('status', ('status',), 1, 'config', self.root),
        ):
            with self.subTest(schema=name, ok=False):
                envelope = validate_envelope(name, args, code, kind, cwd)
                self.assertIsNone(envelope['data'])

    def test_unknown_name_is_usage_error(self):
        result = self.run_launcher('schema', 'nope', cwd=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn('policy-file', result.stderr)


if __name__ == '__main__':
    unittest.main()
