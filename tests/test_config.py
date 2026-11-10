"""Synchronization and migration exercise real temporary files and Git indexes."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from gsd_cli import config
from gsd_cli.policy import load_default, resolve


class MergeTests(unittest.TestCase):
    def test_merge_preserves_independent_changes_and_deletions(self):
        self.assertEqual(config.merge({'a': 1, 'b': 2}, {'a': None, 'b': 2}, {'a': 1}), {'a': None})
        self.assertEqual(config.merge({}, {'x': {'a': 1}}, {'x': {'b': 2}}), {'x': {'a': 1, 'b': 2}})
        self.assertEqual(config.merge({'a': [1]}, {'a': [2]}, {'a': [2]}), {'a': [2]})

    def test_json_equality_distinguishes_booleans_and_numbers(self):
        for base, remote in [(1, True), (0, False), ({'x': 1}, {'x': True}), ([0], [False])]:
            with self.subTest(base=base):
                merged = config.merge({'v': base}, {'v': base}, {'v': remote})
                self.assertEqual(json.dumps(merged), json.dumps({'v': remote}))
                self.assertEqual(config.changed_paths({'v': base}, {'v': remote}), ['v.x'] if isinstance(base, dict) else ['v'])
        with self.assertRaises(config.ConfigError):
            config.merge(0, False, 2)
        with self.assertRaises(config.ConfigError):
            config.merge({'v': [0]}, {'v': [False]}, {'v': [2]})

    def test_conflicting_values_arrays_and_parent_deletion(self):
        for base, local, default in [({'a': 1}, {'a': 2}, {'a': 3}),
                                     ({'a': [1]}, {'a': [2]}, {'a': [3]}),
                                     ({'a': {'b': 1}}, {}, {'a': {'b': 2}}),
                                     ({'a': None}, {}, {'a': 3})]:
            with self.subTest(base=base), self.assertRaisesRegex(config.ConfigError, 'a'):
                config.merge(base, local, default)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.planning').mkdir()
        self.working = self.root / '.planning/config.json'
        self.default = self.root / '.planning/config.default.json'
        self.state = self.root / '.planning/.gsd-cli-sync.json'
        self.policy_file = self.root / 'gsd-cli.config.json'
        self.put(self.working, {'custom': {'keep': True}, 'workflow': {'_auto_chain_active': True}})

    def put(self, path, data):
        path.write_text(json.dumps(data) + '\n')

    def get(self, path):
        return json.loads(path.read_text())

    def init(self):
        config.initialize(self.root)
        self.policy = self.get(self.policy_file)

    def sync(self, workflow='plan', runtime='codex', level='medium'):
        self.put(self.policy_file, self.policy)
        return config.synchronize(self.root, self.policy, resolve(self.policy, workflow, runtime, level))

    def test_init_preserves_working_and_repeated_policy(self):
        before = self.working.read_bytes()
        self.init()
        self.assertEqual(self.working.read_bytes(), before)
        self.assertNotIn('_auto_chain_active', self.get(self.default)['workflow'])
        self.policy['runtimes']['codex']['medium']['session_model'] = 'project-model'
        self.put(self.policy_file, self.policy)
        config.initialize(self.root)
        self.assertEqual(self.get(self.policy_file), self.policy)

    def test_switches_keep_default_stable_and_capture_changes(self):
        self.init()
        self.sync()
        before = self.default.read_bytes()
        self.sync('exec', 'claude', 'high')
        self.assertEqual(self.default.read_bytes(), before)
        working = self.get(self.working)
        working['custom']['keep'] = False
        self.put(self.working, working)
        data, paths = self.sync()
        self.assertFalse(self.get(self.default)['custom']['keep'])
        self.assertIn('custom.keep', paths)
        self.assertTrue(data['workflow']['_auto_chain_active'])

    def test_default_edits_and_local_edits_merge(self):
        self.init()
        self.sync()
        default = self.get(self.default)
        default['from_git'] = 1
        self.put(self.default, default)
        working = self.get(self.working)
        working['from_gsd'] = 2
        self.put(self.working, working)
        data, _ = self.sync()
        self.assertEqual((data['from_git'], data['from_gsd']), (1, 2))

    def test_conflict_does_not_change_files(self):
        self.init()
        self.sync()
        d = self.get(self.default)
        d['custom'] = 'remote'
        self.put(self.default, d)
        w = self.get(self.working)
        w['custom'] = 'local'
        self.put(self.working, w)
        before = [p.read_bytes() for p in (self.default, self.working, self.state)]
        with self.assertRaisesRegex(config.ConfigError, 'custom'):
            self.sync()
        self.assertEqual(before, [p.read_bytes() for p in (self.default, self.working, self.state)])

    def test_removed_owned_entries_and_custom_siblings(self):
        self.init()
        self.sync()
        w = self.get(self.working)
        w['model_overrides']['custom-agent'] = 'custom-model'
        self.put(self.working, w)
        del self.policy['agent_levels']['gsd-doc-classifier']
        del self.policy['reviewers']['deepseek-review']
        data, _ = self.sync()
        self.assertNotIn('gsd-doc-classifier', data['model_overrides'])
        self.assertNotIn('deepseek-review', data['review']['reviewer_instances'])
        self.assertEqual(data['model_overrides']['custom-agent'], 'custom-model')
        self.assertEqual(self.get(self.default)['model_overrides'], {'custom-agent': 'custom-model'})

    def test_fresh_checkout_and_missing_baseline_conflict(self):
        self.init()
        self.sync()
        self.state.unlink()
        self.working.unlink()
        self.sync()
        self.assertTrue(self.working.exists())
        self.state.unlink()
        self.put(self.working, {'unknown': True})
        with self.assertRaisesRegex(config.ConfigError, 'baseline'):
            self.sync()

    def test_missing_default_and_managed_default_are_errors(self):
        self.init()
        self.sync()
        d = self.get(self.default)
        self.default.unlink()
        with self.assertRaisesRegex(config.ConfigError, 'config.default.json'):
            self.sync()
        d['models'] = {'execution': 'opus'}
        self.put(self.default, d)
        with self.assertRaisesRegex(config.ConfigError, 'models.execution'):
            self.sync()

    def test_boolean_default_edit_survives_complete_sync(self):
        self.put(self.working, {'number': 1})
        self.init()
        self.sync()
        d = self.get(self.default)
        d['number'] = True
        self.put(self.default, d)
        data, _ = self.sync()
        self.assertIs(data['number'], True)
        self.assertIs(self.get(self.default)['number'], True)

    def test_missing_baseline_detects_boolean_number_disagreement(self):
        self.put(self.working, {'number': 1})
        self.init()
        self.sync()
        self.state.unlink()
        d = self.get(self.default)
        d['number'] = True
        self.put(self.default, d)
        with self.assertRaisesRegex(config.ConfigError, 'baseline'):
            self.sync()

    def test_recovery_after_partial_write(self):
        self.init()
        self.sync()
        w = self.get(self.working)
        w['new'] = 42
        self.put(self.working, w)
        original = config.atomic_write
        def fail_working(path, content):
            if path == self.working:
                raise OSError('simulated interruption')
            return original(path, content)
        with mock.patch.object(config, 'atomic_write', side_effect=fail_working):
            with self.assertRaises(OSError):
                self.sync('exec')
        self.assertTrue((self.root / '.planning/.gsd-cli-journal.json').exists())
        self.sync('exec')
        self.assertEqual(self.get(self.default)['new'], 42)
        self.assertFalse((self.root / '.planning/.gsd-cli-journal.json').exists())
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)

    def test_recovery_refuses_external_edits(self):
        self.init()
        self.sync()
        original = config.atomic_write
        def fail_working(path, content):
            if path == self.working:
                raise OSError('interruption')
            return original(path, content)
        with mock.patch.object(config, 'atomic_write', side_effect=fail_working), self.assertRaises(OSError):
            self.sync('exec')
        self.put(self.working, {'external': True})
        with self.assertRaisesRegex(config.ConfigError, 'recovery'):
            self.sync()
        self.assertEqual(self.get(self.working), {'external': True})

    def test_symlink_and_invalid_metadata_are_rejected(self):
        self.init()
        self.sync()
        other = self.root / 'outside.json'
        other.write_text('{}')
        self.working.unlink()
        self.working.symlink_to(other)
        with self.assertRaisesRegex(config.ConfigError, 'symlink'):
            self.sync()
        self.working.unlink()
        self.put(self.state, {'version': 1, 'baseline': {}, 'managed': [['custom']]})
        with self.assertRaisesRegex(config.ConfigError, 'managed'):
            self.sync()

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], text=True, capture_output=True, check=True).stdout

    def test_git_migration_untracks_only_working_and_exposes_default(self):
        self.git('init', '-q')
        self.git('add', '.planning/config.json')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'fixture')
        (self.root / '.gitignore').write_text('.planning/\n')
        self.init()
        self.assertEqual(self.git('ls-files', '.planning/config.json'), '')
        self.assertTrue(self.working.exists())
        for name in ('gsd-cli.config.json', '.planning/config.default.json'):
            self.assertEqual(subprocess.run(['git','check-ignore',name],cwd=self.root,capture_output=True).returncode,1)
        self.assertEqual(self.git('check-ignore', '.planning/config.json').strip(), '.planning/config.json')
        self.assertEqual(self.git('check-ignore', '.planning/STATE.md').strip(), '.planning/STATE.md')

    def test_staged_config_refuses_migration_without_writes(self):
        self.git('init', '-q')
        self.git('add', '.planning/config.json')
        before = self.working.read_bytes()
        with self.assertRaisesRegex(config.ConfigError, 'staged'):
            self.init()
        self.assertFalse(self.default.exists())
        self.assertFalse(self.policy_file.exists())
        self.assertEqual(self.working.read_bytes(), before)

    def test_legacy_policy_migration_preserves_models_and_custom_reviewers(self):
        w = self.get(self.working)
        w['model_policy'] = {'runtime_tiers': {'codex': {'sonnet': {'model': 'custom-sol', 'reasoning_effort': 'high'}}}}
        w['review'] = {'reviewer_instances': {'mine': {'cli': 'codex', 'model': 'custom-review'}}, 'parallel_lanes': True}
        self.put(self.working, w)
        self.init()
        self.assertEqual(self.policy['runtimes']['codex']['medium']['agent_model'], 'custom-sol')
        self.assertEqual(self.policy['reviewers']['mine']['model'], 'custom-review')
        self.assertTrue(self.policy['workflows']['exec']['parallel_reviews'])
