"""JSON-mode envelope and error handling; no network or real model calls."""
import copy
import importlib.metadata
import json
import shutil
import unittest
from unittest import mock

import test_gsd_cli as fixtures
from gsd_cli import cli, models
from gsd_cli.models import CheckEnvelope, PolicyEnvelope, StatusEnvelope
from test_versions import install_gsd


class JsonErrorTests(fixtures.GsdCliFixture):
    def envelope(self, result):
        self.assertEqual(result.stderr, '')
        self.assertTrue(result.stdout.endswith('\n'))
        body = json.loads(result.stdout)
        self.assertIsInstance(body, dict)
        self.assertEqual(body['schema_version'], 1)
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

    def test_policy_and_schema_are_reserved_workflow_names(self):
        self.initialize()
        path = self.project / 'gsd-cli.config.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        for name in ('policy', 'schema'):
            policy = copy.deepcopy(original)
            policy['workflows'][name] = copy.deepcopy(policy['workflows']['plan'])
            path.write_text(json.dumps(policy), encoding='utf-8')
            result = self.run_launcher('plan', 'claude', '--config')
            self.assertEqual(result.returncode, 1, name)
            self.assertIn('reserved or invalid workflow name', result.stderr)

    def test_forwarding_after_policy_or_schema_is_rejected(self):
        for name in ('policy', 'schema'):
            result = self.run_launcher(name, '--', 'x')
            self.assertEqual(result.returncode, 2)
            self.assertIn('forwarding after --', result.stderr)

    def test_policy_error_is_policy_envelope(self):
        self.initialize()
        (self.project / 'gsd-cli.config.json').write_text('{}', encoding='utf-8')
        result = self.run_launcher('plan', 'claude', '--config', '--json')
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
        policy['agent_levels']['gsd-planner'] = 'low'
        self.put_policy(policy)
        env = PolicyEnvelope.model_validate_json(self.run_launcher('policy', '--json').stdout, strict=True)
        self.assertEqual(env.data.differs_from_shipped, ['agent_levels.gsd-planner'])

    def test_invalid_policy_is_policy_error(self):
        self.initialize()
        policy = self.policy()
        policy['phase_defaults']['planning'] = 'huge'
        self.put_policy(policy)
        result = self.run_launcher('policy', '--json')
        self.assertEqual(result.returncode, 1)
        body = json.loads(result.stdout)
        self.assertEqual((body['ok'], body['command'], body['data'], body['error']['kind']),
                         (False, 'policy', None, 'policy'))
        self.assertTrue(body['error']['message'].startswith('phase_defaults.planning'))

    def test_missing_policy_is_config_error(self):
        result = self.run_launcher('policy', '--json')
        self.assertEqual(result.returncode, 1)
        body = json.loads(result.stdout)
        self.assertEqual(body['error']['kind'], 'config')
        self.assertIn('gsd-cli init', body['error']['message'])

    def snapshot_tree(self):
        found = {}
        for base in (self.project, self.root / 'state'):
            for path in base.rglob('*'):
                if path.is_file():
                    found[str(path)] = (path.read_bytes(), path.stat().st_mtime_ns)
        return found

    def test_json_reads_write_nothing(self):
        self.initialize()
        self.assertEqual(self.run_launcher('plan', 'claude').returncode, 0)
        (self.project / '.planning/.gsd-cli-journal.json').write_text('{}', encoding='utf-8')
        before = self.snapshot_tree()
        for args in (('status',), ('check',), ('policy',)):
            result = self.run_launcher(*args, '--json')
            self.assertEqual(result.returncode, 0, (args, result.stdout))
            self.assertTrue(json.loads(result.stdout)['ok'], args)
        self.assertEqual(self.snapshot_tree(), before)


class ModelTests(unittest.TestCase):
    def test_json_command_detection(self):
        from gsd_cli.cli import json_command
        self.assertEqual(json_command(['status', '--json']), 'status')
        self.assertIsNone(json_command([]))
        self.assertIsNone(json_command(['--json']))
        self.assertIsNone(json_command(['init']))
        self.assertIsNone(json_command(['claude']))
        self.assertEqual(json_command(['plan', 'claude']), 'preview')

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

    def test_unknown_name_is_usage_error(self):
        result = self.run_launcher('schema', 'nope', cwd=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn('policy-file', result.stderr)


if __name__ == '__main__':
    unittest.main()
