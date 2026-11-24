import importlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from resolver_fixtures import install_resolver


@unittest.skipUnless(shutil.which('node'), 'Node is needed for resolver bridge integration tests')
class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        (self.project / '.planning').mkdir(parents=True)
        self.core = install_resolver(self.project / '.codex', 'codex-model')
        install_resolver(self.project / '.claude', 'claude-model')
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GSD_') and k not in ('CLAUDE_CONFIG_DIR', 'CODEX_HOME')}
        self.env['HOME'] = str(self.root / 'home')
        self.data = {'model_overrides': {'custom-agent': 'custom-model'}}

    def inspect(self, runtime='codex', data=None):
        self.assertIsNotNone(importlib.util.find_spec('gsd_cli.resolver'), 'resolver adapter is not implemented')
        from gsd_cli.resolver import inspect
        with mock.patch.dict(os.environ, self.env, clear=True):
            return inspect(self.project, self.data if data is None else data, runtime, '1.20.1')

    def snapshot(self):
        return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}

    def test_selected_runtime_and_snapshot_without_writes_or_bootstrap(self):
        before = self.snapshot()
        result = self.inspect()
        self.assertTrue(result['complete'], result['diagnostics'])
        self.assertEqual(result['context']['config']['runtime'], 'codex')
        self.assertEqual(result['agents']['gsd-planner']['model'], 'codex-model')
        self.assertEqual(result['agents']['custom-agent']['model'], 'custom-model')
        self.assertEqual(self.inspect('claude')['agents']['gsd-planner']['model'], 'claude-model')
        self.assertEqual(self.snapshot(), before)

    def test_relative_env_install_selection_and_workstream_overlay(self):
        install_resolver(self.project / 'other', 'explicit-model')
        self.env['CODEX_HOME'] = 'other'
        self.env['GSD_WORKSTREAM'] = 'feature'
        path = self.project / '.planning/workstreams/feature/config.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'model_overrides': {'gsd-planner': 'overlay-model'}}))
        before = self.snapshot()
        result = self.inspect()
        self.assertTrue(result['complete'], result['diagnostics'])
        self.assertEqual(result['agents']['gsd-verifier']['model'], 'explicit-model')
        self.assertEqual(result['agents']['gsd-planner']['model'], 'overlay-model')
        self.assertEqual(result['context']['source'], 'workstream')
        self.assertEqual(self.snapshot(), before)

    def test_run_bridge_returns_rows_for_requested_agents(self):
        self.assertIsNotNone(importlib.util.find_spec('gsd_cli.resolver'), 'resolver adapter is not implemented')
        from gsd_cli.resolver import query_environment, run_bridge
        before = self.snapshot()
        with mock.patch.dict(os.environ, self.env, clear=True):
            payload, stderr = run_bridge(self.core, 'codex', {'.planning/config.json': self.data},
                                         ['gsd-planner'], query_environment(self.project, 'codex'))
        rows = {row['agent']: row['result'] for row in payload['rows']}
        self.assertEqual(set(rows), {'gsd-planner', 'custom-agent'})
        self.assertEqual(rows['gsd-planner']['model'], 'codex-model')
        self.assertEqual(rows['custom-agent']['model'], 'custom-model')
        self.assertEqual(payload['context']['config']['runtime'], 'codex')
        self.assertEqual(stderr, [])
        self.assertEqual(self.snapshot(), before)

    def test_missing_node_old_install_and_malformed_catalog_are_incomplete(self):
        self.assertIsNotNone(importlib.util.find_spec('gsd_cli.resolver'), 'resolver adapter is not implemented')
        with mock.patch('gsd_cli.resolver.shutil.which', return_value=None):
            self.assertIn('Node', ' '.join(self.inspect()['diagnostics']))
        (self.core / 'VERSION').write_text('1.0.0')
        self.assertFalse(self.inspect()['complete'])
        (self.core / 'VERSION').write_text('1.20.1')
        (self.core / 'bin/shared/model-catalog.json').write_text('{"agents": []}')
        self.assertFalse(self.inspect()['complete'])

    def test_partial_failure_and_malformed_output_are_explicit(self):
        result = self.inspect(data={'fail_agent': 'gsd-planner'})
        self.assertFalse(result['complete'])
        self.assertIn('gsd-verifier', result['agents'])
        self.assertIn('gsd-planner', ' '.join(result['diagnostics']))
        self.assertFalse(self.inspect(data={'malformed_result': True})['complete'])

    def test_malformed_catalog_nested_metadata_is_incomplete(self):
        path = self.core / 'bin/shared/model-catalog.json'
        catalog = json.loads(path.read_text())
        catalog['runtimeTierDefaults'] = []
        path.write_text(json.dumps(catalog))
        result = self.inspect()
        self.assertFalse(result['complete'])
        self.assertIn('catalog', ' '.join(result['diagnostics']))

    def test_catalog_rejects_invalid_phase_metadata(self):
        from gsd_cli.config import ConfigError
        from gsd_cli.resolver import load_catalog
        path = self.core / 'bin/shared/model-catalog.json'
        path.write_text(json.dumps({'agents': {'gsd-executor': {'phaseType': []}}}))
        with self.assertRaisesRegex(ConfigError, r'gsd-executor\.phaseType'):
            load_catalog(self.core)

    def test_installed_catalog_rejects_invalid_role_names(self):
        from gsd_cli.config import ConfigError
        from gsd_cli.resolver import load_catalog
        path = self.core / 'bin/shared/model-catalog.json'
        for role in ('executor', 'gsd-../../executor'):
            with self.subTest(role=role):
                path.write_text(json.dumps({'agents': {role: {'phaseType': 'execution'}}}))
                with self.assertRaisesRegex(ConfigError, re.escape(role)):
                    load_catalog(self.core)

    def test_blueprint_values_match_installed_resolver(self):
        from gsd_cli.config import put_path
        from gsd_cli.policy import load_default, resolve
        from gsd_cli.resolver import load_catalog
        policy = load_default()
        high = policy['runtimes']['codex']['blueprints']['high']
        high['agents']['gsd-executor'] = {'effort': 'xhigh'}
        high['phases']['verification'].update(model='gpt-6.1-sol', effort='medium')
        resolved = resolve(policy, 'codex', 'high', load_catalog(self.core))
        data = {}
        for path, value in resolved['values'].items():
            put_path(data, path, value)
        result = self.inspect(data=data)
        self.assertTrue(result['complete'], result['diagnostics'])
        for agent, expected in {
            'gsd-executor': ('gpt-6-astra', 'xhigh'),
            'gsd-verifier': ('gpt-6.1-sol', 'medium'),
            'gsd-codebase-mapper': ('gpt-6.1-sol', 'medium'),
        }.items():
            with self.subTest(agent=agent):
                row = result['agents'][agent]
                self.assertEqual((row['model'], row['effort']), expected)

    def test_timeout_is_incomplete(self):
        self.assertIsNotNone(importlib.util.find_spec('gsd_cli.resolver'), 'resolver adapter is not implemented')
        with mock.patch('gsd_cli.resolver.subprocess.run', side_effect=subprocess.TimeoutExpired('node', 20)):
            result = self.inspect()
        self.assertFalse(result['complete'])
        self.assertIn('timed out', ' '.join(result['diagnostics']))

    def test_inherited_effort_with_null_propagation_is_a_complete_query(self):
        result = self.inspect(data={'effort': {'agent_overrides': {'gsd-planner': 'inherit'}}})
        self.assertTrue(result['complete'], result['diagnostics'])
        self.assertEqual(result['agents']['gsd-planner']['effort'], 'inherit')
        self.assertIsNone(result['agents']['gsd-planner']['effort_propagation'])

    def test_unsupported_context_and_filesystem_migration_are_explicit(self):
        self.env['GSD_PROJECT'] = 'other-project'
        self.assertFalse(self.inspect()['complete'])
        self.env.pop('GSD_PROJECT')
        self.assertFalse(self.inspect(data={'multiRepo': True})['complete'])
        self.env['GSD_WORKSTREAM'] = '../elsewhere'
        self.assertFalse(self.inspect()['complete'])
