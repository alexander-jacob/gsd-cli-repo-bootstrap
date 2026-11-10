import importlib
import json
import os
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

    def test_timeout_is_incomplete(self):
        self.assertIsNotNone(importlib.util.find_spec('gsd_cli.resolver'), 'resolver adapter is not implemented')
        with mock.patch('gsd_cli.resolver.subprocess.run', side_effect=subprocess.TimeoutExpired('node', 20)):
            result = self.inspect()
        self.assertFalse(result['complete'])
        self.assertIn('timed out', ' '.join(result['diagnostics']))

    def test_unsupported_context_and_filesystem_migration_are_explicit(self):
        self.env['GSD_PROJECT'] = 'other-project'
        self.assertFalse(self.inspect()['complete'])
        self.env.pop('GSD_PROJECT')
        self.assertFalse(self.inspect(data={'multiRepo': True})['complete'])
        self.env['GSD_WORKSTREAM'] = '../elsewhere'
        self.assertFalse(self.inspect()['complete'])
