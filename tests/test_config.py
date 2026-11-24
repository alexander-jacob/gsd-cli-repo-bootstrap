"""Synchronization and migration exercise real temporary files and Git indexes."""
import copy
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from gsd_cli import config
from gsd_cli.policy import PolicyError, load_default
from resolver_fixtures import AGENT_PHASES


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


class DiscoverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_bare_planning_found_only_when_allowed(self):
        (self.root / '.planning/codebase').mkdir(parents=True)
        with self.assertRaisesRegex(config.ConfigError, 'expected .planning/config.json'):
            config.discover(self.root)
        self.assertEqual(config.discover(self.root, allow_bare=True), self.root.resolve())

    def test_bare_planning_found_from_subdirectory(self):
        (self.root / '.planning').mkdir()
        (self.root / 'src/pkg').mkdir(parents=True)
        self.assertEqual(config.discover(self.root / 'src/pkg', allow_bare=True), self.root.resolve())

    def test_nearest_bare_planning_wins_over_configured_parent(self):
        (self.root / '.planning').mkdir()
        (self.root / '.planning/config.json').write_text('{}\n')
        (self.root / 'child/.planning').mkdir(parents=True)
        self.assertEqual(config.discover(self.root / 'child', allow_bare=True), (self.root / 'child').resolve())

    def test_bare_planning_above_git_root_is_ignored(self):
        (self.root / '.planning').mkdir()
        repo = self.root / 'repo'
        (repo / 'src').mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        with self.assertRaisesRegex(config.ConfigError, 'gsd-map-codebase or gsd-new-project'):
            config.discover(repo / 'src', allow_bare=True)

    def test_bare_planning_in_home_is_ignored(self):
        (self.root / '.planning').mkdir()
        (self.root / 'app').mkdir()
        with mock.patch.dict('os.environ', {'HOME': str(self.root)}), \
                self.assertRaisesRegex(config.ConfigError, 'gsd-map-codebase or gsd-new-project'):
            config.discover(self.root / 'app', allow_bare=True)

    def test_planning_file_is_not_a_project(self):
        (self.root / '.planning').write_text('')
        with self.assertRaisesRegex(config.ConfigError, 'gsd-map-codebase or gsd-new-project'):
            config.discover(self.root, allow_bare=True)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = mock.patch.dict('os.environ', {
            'HOME': str(self.root), 'CODEX_HOME': str(self.root / '.codex'),
            'CLAUDE_CONFIG_DIR': str(self.root / '.claude'),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.catalog = {'agents': {name: {'phaseType': phase} for name, phase in AGENT_PHASES.items()}}
        installed = tempfile.TemporaryDirectory()
        self.addCleanup(installed.cleanup)
        self.installations = {r: Path(installed.name) / r / 'gsd-core' for r in ('claude', 'codex')}
        for installation in self.installations.values():
            (installation / 'bin/shared').mkdir(parents=True)
            self.put(installation / 'bin/shared/model-catalog.json', self.catalog)
        self.sources = self.installations['claude'].parent / 'agents'
        self.sources.mkdir()
        for name in (*self.catalog['agents'], 'gsd-only-claude'):
            (self.sources / (name + '.md')).write_bytes(
                f'---\r\nname: {name}\r\n---\r\n'.encode() + b'binary body \xff\r\n')
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

    def sync(self, runtime='codex', blueprint='medium', catalog=None):
        self.put(self.policy_file, self.policy)
        installation = self.installations[runtime]
        self.put(installation / 'bin/shared/model-catalog.json', catalog or self.catalog)
        return config.synchronize(self.root, self.policy, runtime, blueprint, installation)

    def preview(self, runtime='codex', blueprint='medium'):
        self.assertTrue(hasattr(config, 'preview'), 'read-only preview is not implemented')
        installation = self.installations[runtime]
        self.put(installation / 'bin/shared/model-catalog.json', self.catalog)
        return config.preview(self.root, self.policy, runtime, blueprint, installation)

    def file_snapshot(self):
        return {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_preview_matches_sync_and_captures_without_writes(self):
        self.init()
        self.sync()
        w = self.get(self.working)
        w['from_gsd'] = 2
        self.put(self.working, w)
        d = self.get(self.default)
        d['from_git'] = True
        self.put(self.default, d)
        before = self.file_snapshot()
        preview = self.preview()
        self.assertEqual(self.file_snapshot(), before)
        self.assertIn('from_gsd', preview[1])
        self.assertEqual(preview, self.sync())

    def test_preview_fresh_checkout_without_creating_lock_or_working(self):
        self.init()
        for name in (config.WORKING, config.STATE, config.LOCK):
            (self.root / name).unlink(missing_ok=True)
        before = self.file_snapshot()
        preview = self.preview()
        self.assertEqual(self.file_snapshot(), before)
        self.assertEqual(preview, self.sync())

    def test_preview_refuses_journal_and_held_lock_without_writes(self):
        self.init()
        journal = self.root / config.JOURNAL
        journal.write_text('{}')
        before = self.file_snapshot()
        with self.assertRaisesRegex(config.ConfigError, 'recovery'):
            self.preview()
        self.assertEqual(self.file_snapshot(), before)
        journal.unlink()
        with (self.root / config.LOCK).open('r') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(config.ConfigError, 'process'):
                self.preview()
        self.preview()  # An idle lock file is harmless.

    def test_preview_rejects_conflict_and_changed_policy(self):
        self.init()
        p = copy.deepcopy(self.policy)
        p['gsd']['min_version'] = '2.0.0'
        self.put(self.policy_file, p)
        with self.assertRaisesRegex(config.ConfigError, 'changed'):
            self.preview()
        self.put(self.policy_file, self.policy)
        self.sync()
        w, d = self.get(self.working), self.get(self.default)
        w['custom'], d['custom'] = 'local', 'remote'
        self.put(self.working, w)
        self.put(self.default, d)
        before = self.file_snapshot()
        with self.assertRaisesRegex(config.ConfigError, 'conflict'):
            self.preview()
        self.assertEqual(self.file_snapshot(), before)

    def test_preview_detects_inputs_changed_during_preparation(self):
        self.init()
        original = config.load_state
        def changing(root):
            state = original(root)
            self.put(self.default, {'changed': True})
            return state
        with mock.patch.object(config, 'load_state', side_effect=changing):
            with self.assertRaisesRegex(config.ConfigError, 'changed'):
                self.preview()

    def test_init_preserves_working_and_repeated_policy(self):
        before = self.working.read_bytes()
        self.init()
        self.assertEqual(self.working.read_bytes(), before)
        self.assertNotIn('_auto_chain_active', self.get(self.default)['workflow'])
        self.policy['runtimes']['codex']['blueprints']['medium']['session']['model'] = 'project-model'
        self.put(self.policy_file, self.policy)
        config.initialize(self.root)
        self.assertEqual(self.get(self.policy_file), self.policy)

    def test_switches_keep_default_stable_and_capture_changes(self):
        self.init()
        self.sync()
        before = self.default.read_bytes()
        self.sync('claude', 'high')
        self.assertEqual(self.default.read_bytes(), before)
        working = self.get(self.working)
        working['custom']['keep'] = False
        self.put(self.working, working)
        data, paths, _, _ = self.sync()
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
        data, _, _, _ = self.sync()
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
        section = self.policy['runtimes']['codex']
        del section['blueprints']['medium']['agents']['gsd-doc-classifier']
        self.catalog['agents']['gsd-doc-classifier']['phaseType'] = 'unknown'
        del section['review']['reviewer_instances']['deepseek-review']
        section['review']['default_reviewers'] = []
        data, _, _, _ = self.sync()
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
        d['model_overrides'] = {'gsd-executor': 'opus'}
        self.put(self.default, d)
        with self.assertRaisesRegex(config.ConfigError, 'model_overrides.gsd-executor'):
            self.sync()

    def test_boolean_default_edit_survives_complete_sync(self):
        self.put(self.working, {'number': 1})
        self.init()
        self.sync()
        d = self.get(self.default)
        d['number'] = True
        self.put(self.default, d)
        data, _, _, _ = self.sync()
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

    def interrupt_agent_removal(self):
        self.init()
        self.sync('claude')
        self.retired = '.claude/agents/gsd-doc-classifier.md'
        self.remaining = '.claude/agents/gsd-executor.md'
        section = self.policy['runtimes']['claude']['blueprints']['high']
        section['agents'].pop('gsd-doc-classifier', None)
        self.catalog['agents']['gsd-doc-classifier']['phaseType'] = 'unknown'
        original = config.atomic_write
        applied = []
        def interrupt(path, content):
            if path != self.root / config.JOURNAL:
                if applied:
                    raise OSError('interrupt after first target')
                applied.append(path)
            return original(path, content)
        with mock.patch.object(config, 'atomic_write', side_effect=interrupt), self.assertRaises(OSError):
            self.sync('claude', 'high')
        self.assertEqual(len(applied), 1)

    def test_recover_partial_agent_removal(self):
        self.interrupt_agent_removal()
        config.recover(self.root)
        self.assertFalse((self.root / self.retired).exists())
        after = (self.root / self.remaining).read_bytes()
        self.assertIn(b'body \xff\r\n', after)
        expected = self.get(self.working)['model_overrides']['gsd-executor']
        self.assertIn(f'model: {expected}\r\n'.encode(), after)
        owned = self.get(self.state)['claude_agents']
        self.assertNotIn(self.retired, owned)
        self.assertEqual(owned[self.remaining], hashlib.sha256(after).hexdigest())
        self.assertFalse((self.root / config.JOURNAL).exists())

    def test_external_edit_blocks_recovery_before_any_operation(self):
        self.interrupt_agent_removal()
        (self.root / self.retired).write_bytes(b'my edited prompt')
        before = self.file_snapshot()
        with self.assertRaisesRegex(config.ConfigError, 'edited externally'):
            config.recover(self.root)
        self.assertEqual(before, self.file_snapshot())

    def test_claude_preview_double_preparation_and_codex_preservation(self):
        self.git('init', '-q')
        self.init()
        original = (self.root / '.gitignore').read_bytes() + b'# comment \xff\r\n'
        (self.root / '.gitignore').write_bytes(original)
        before = self.file_snapshot()
        proposed = self.preview('claude')
        self.assertEqual(before, self.file_snapshot())
        self.assertFalse((self.root / '.claude').exists())
        self.assertEqual(proposed, self.sync('claude'))
        generated = self.root / '.claude/agents/gsd-executor.md'
        self.assertEqual(proposed[3]['gsd-executor']['action'], 'create')
        ignore = self.root / '.gitignore'
        self.assertTrue(ignore.read_bytes().startswith(original))
        self.assertEqual(self.git('check-ignore', str(generated)).strip(), str(generated))
        custom = self.root / '.claude/agents/custom.md'
        custom.write_bytes(b'custom prompt')
        self.assertIn('custom.md', self.git('ls-files', '--others', '--exclude-standard'))
        ignore.write_bytes(b'# my prefix\r\n' + ignore.read_bytes() + b'# my suffix\xff')
        inspected = self.preview('claude')
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (ignore, generated, self.state)}
        self.assertEqual(inspected[3]['gsd-executor']['action'], 'unchanged')
        self.assertEqual(inspected, self.sync('claude'))
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})
        owned = self.get(self.state)['claude_agents']
        generated.write_bytes(b'edited, preserve across a Codex launch')
        self.assertEqual(self.sync('codex')[3], {})
        self.assertEqual(generated.read_bytes(), b'edited, preserve across a Codex launch')
        self.assertEqual(self.get(self.state)['claude_agents'], owned)
        self.assertEqual(before[ignore], (ignore.read_bytes(), ignore.stat().st_mtime_ns))

    def test_ignore_rules_from_fresh_checkout_do_not_grant_ownership(self):
        self.git('init', '-q')
        self.init()
        self.sync('claude')
        self.git('add', '.gitignore', config.DEFAULT, config.POLICY)
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'fixture')
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory)
            self.git('clone', '-q', str(self.root), str(clone))
            self.assertFalse((clone / config.STATE).exists())
            self.assertFalse((clone / '.claude').exists())
            args = (clone, self.policy, 'claude', 'medium', self.installations['claude'])
            plan = config.preview(*args)[3]
            self.assertEqual(plan['gsd-executor']['action'], 'create')
            destination = clone / plan['gsd-executor']['destination']
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b'hand-written file')
            with self.assertRaisesRegex(config.ConfigError, 'Unowned'):
                config.synchronize(*args)
            self.assertEqual(destination.read_bytes(), b'hand-written file')
            destination.unlink()
            config.synchronize(*args)
            self.assertIn(destination.relative_to(clone).as_posix(), config.load_state(clone)['claude_agents'])

    def test_edits_inside_ignore_block_conflict(self):
        self.init()
        self.sync('claude')
        ignore = self.root / '.gitignore'
        ignore.write_bytes(ignore.read_bytes().replace(b'/.claude/agents/gsd-executor.md\n', b''))
        before = self.file_snapshot()
        with self.assertRaisesRegex(config.ConfigError, 'Edited.*.gitignore'):
            self.preview('claude')
        self.assertEqual(self.file_snapshot(), before)

    def test_nested_ignore_conflict_blocks_creation_and_subsequent_refresh(self):
        self.git('init', '-q')
        self.init()
        directory = self.root / '.claude/agents'
        directory.mkdir(parents=True)
        nested = directory / '.gitignore'
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    nested.unlink()
                    self.sync('claude')
                nested.write_text('!gsd-executor.md\n')
                before = self.file_snapshot()
                with self.assertRaisesRegex(config.ConfigError, 'expose.*gsd-executor.md'):
                    self.preview('claude')
                self.assertEqual(self.file_snapshot(), before)

    def test_preparation_rejects_concurrent_agent_and_catalog_changes(self):
        self.init()
        self.sync('claude')
        directory = self.root / '.claude/agents'
        catalog = self.installations['claude'] / 'bin/shared/model-catalog.json'
        for target in (self.sources / 'gsd-executor.md', directory / 'gsd-executor.md',
                       directory / 'duplicate.md', directory / '.gitignore', catalog):
            for write in (False, True):
                with self.subTest(target=target, write=write):
                    original = target.read_bytes() if target.exists() else None
                    def changing(*args):
                        plan = original_plan(*args)
                        target.write_bytes((original or b'') + b'\n')
                        return plan
                    original_plan = config.plan_agents
                    fn = config.synchronize if write else config.preview
                    try:
                        with mock.patch.object(config, 'plan_agents', side_effect=changing), \
                                self.assertRaisesRegex(config.ConfigError, 'changed during preparation'):
                            fn(self.root, self.policy, 'claude', 'high', self.installations['claude'])
                        self.assertFalse((self.root / config.JOURNAL).exists())
                    finally:
                        if original is None:
                            target.unlink()
                        else:
                            target.write_bytes(original)

    def test_codex_recovers_pending_claude_transaction_and_preview_leaves_it_pending(self):
        self.interrupt_agent_removal()
        before = self.file_snapshot()
        with self.assertRaisesRegex(config.ConfigError, 'Pending configuration recovery'):
            self.preview('codex')
        self.assertEqual(self.file_snapshot(), before)
        self.sync('codex')
        self.assertFalse((self.root / config.JOURNAL).exists())
        self.assertFalse((self.root / self.retired).exists())
        self.assertNotIn(self.retired, self.get(self.state)['claude_agents'])
        self.assertEqual(self.get(self.state)['claude_agents'][self.remaining],
                         hashlib.sha256((self.root / self.remaining).read_bytes()).hexdigest())

    def test_invalid_journal_paths_and_unowned_deletions_block_before_replay(self):
        self.interrupt_agent_removal()
        path = self.root / config.JOURNAL
        original = self.get(path)
        for name in ('.claude/agents/../config.md', '.claude/agents/user.md', config.POLICY,
                     '.claude/agents/gsd-never-owned.md'):
            with self.subTest(name=name):
                journal = copy.deepcopy(original)
                journal['files'][name] = journal['files'].pop(self.retired)
                self.put(path, journal)
                before = self.file_snapshot()
                with self.assertRaisesRegex(config.ConfigError, 'recovery|ownership'):
                    config.recover(self.root)
                self.assertEqual(self.file_snapshot(), before)

    def test_recovery_revalidates_git_index_ignore_rules_and_project_identities(self):
        self.git('init', '-q')
        self.interrupt_agent_removal()
        nested = self.root / '.claude/agents/.gitignore'
        collision = nested.parent / 'duplicate.md'
        for issue in ('index', 'ignore', 'identity'):
            with self.subTest(issue=issue):
                if issue == 'index':
                    self.git('add', '-f', self.retired)
                elif issue == 'ignore':
                    nested.write_text('!gsd-executor.md\n')
                else:
                    collision.write_text('---\nname: gsd-executor\n---\nnew agent')
                before = self.file_snapshot()
                with self.assertRaisesRegex(config.ConfigError, 'Git-tracked|expose|Duplicate'):
                    config.recover(self.root)
                self.assertEqual(self.file_snapshot(), before)
                if issue == 'index':
                    self.git('rm', '--cached', self.retired)
                else:
                    (nested if issue == 'ignore' else collision).unlink()
        config.recover(self.root)

    def test_git_directory_exclusion_can_disable_nested_exception(self):
        self.git('init', '-q')
        (self.root / '.git/info/exclude').write_text('/.claude/\n')
        self.init()
        agents = self.root / '.claude/agents'
        agents.mkdir(parents=True)
        (agents / '.gitignore').write_text('!gsd-executor.md\n')
        self.sync('claude')
        generated = '.claude/agents/gsd-executor.md'
        self.assertEqual(self.git('check-ignore', generated).strip(), generated)

    def test_catalog_errors_are_distinct_from_collisions(self):
        self.init()
        catalog = self.installations['claude'] / 'bin/shared/model-catalog.json'
        catalog.unlink()
        with self.assertRaisesRegex(config.CatalogError, 'model-catalog.json'):
            config.preview(self.root, self.policy, 'claude', 'medium', self.installations['claude'])
        self.put(catalog, self.catalog)
        path = self.root / '.claude/agents/gsd-executor.md'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'handwritten')
        with self.assertRaisesRegex(config.ConfigError, 'Unowned') as raised:
            self.preview('claude')
        self.assertNotIsInstance(raised.exception, config.CatalogError)

    def test_v1_replay_preserves_text_preconditions_and_index_migration(self):
        self.git('init', '-q')
        self.git('add', config.WORKING)
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'fixture')
        self.default.write_bytes(b'{}\r\n')
        journal = self.root / config.JOURNAL
        self.put(journal, {'version': 1, 'untrack': True, 'files': {
            config.DEFAULT: {'before': '{}\n', 'after': '{"new": true}\n'}}})
        config.recover(self.root)
        self.assertEqual(self.get(self.default), {'new': True})
        self.assertFalse(journal.exists())
        self.assertTrue(self.working.exists())
        self.assertEqual(self.git('ls-files', config.WORKING), '')

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
                self.sync('codex', 'high')
        self.assertTrue((self.root / '.planning/.gsd-cli-journal.json').exists())
        self.sync('codex', 'high')
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
            self.sync('codex', 'high')
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

    def test_starter_and_existing_unmanaged_reviewers(self):
        w = self.get(self.working)
        w['model_policy'] = {'runtime_tiers': {'codex': {'sonnet': {'model': 'custom-sol'}}}}
        w['review'] = {'reviewer_instances': {'mine': {'cli': 'codex', 'model': 'custom-review'}}}
        self.put(self.working, w)
        self.init()
        self.assertEqual(self.policy, load_default())
        self.assertEqual(self.policy['schema_version'], 2)
        self.assertEqual(self.get(self.default)['review'], w['review'])
        data, _, _, _ = self.sync()
        self.assertNotIn('model_policy', data)
        self.assertEqual(data['review']['reviewer_instances']['mine'], w['review']['reviewer_instances']['mine'])

    def test_manual_policy_conversion_uses_existing_version_one_metadata(self):
        self.init()
        self.put(self.policy_file, {'schema_version': 1})
        before = self.file_snapshot()
        with self.assertRaisesRegex(PolicyError, 'manually convert'):
            config.initialize(self.root)
        self.assertEqual(self.file_snapshot(), before)
        state = self.get(self.state)
        state['managed'] = [['models', 'execution'], ['model_overrides', 'gsd-retired']]
        self.put(self.state, state)
        working = self.get(self.working)
        working['models'] = {'execution': 'old', 'custom': 'keep'}
        working['model_overrides'] = {'gsd-retired': 'old'}
        self.put(self.working, working)
        self.put(self.policy_file, self.policy)
        self.init()
        data, _, _, _ = self.sync()
        self.assertEqual(data['models'], {'custom': 'keep'})
        self.assertNotIn('gsd-retired', data['model_overrides'])

    def test_switching_catalogs_retires_only_known_seed_values(self):
        original = {'model_overrides': {'gsd-only-codex': 'one', 'gsd-only-claude': 'two', 'gsd-custom': 'keep'}}
        self.put(self.working, original)
        self.init()
        self.assertEqual(self.get(self.default)['model_overrides'], original['model_overrides'])
        codex, claude = copy.deepcopy(self.catalog), copy.deepcopy(self.catalog)
        codex['agents']['gsd-only-codex'] = {'phaseType': 'planning'}
        claude['agents']['gsd-only-claude'] = {'phaseType': 'research'}
        _, captured, _, _ = self.sync('codex', catalog=codex)
        self.assertEqual(captured, [])
        data, captured, _, _ = self.sync('claude', catalog=claude)
        self.assertEqual(captured, [])
        self.assertNotIn('gsd-only-codex', data['model_overrides'])
        self.assertEqual(self.get(self.default)['model_overrides'], {'gsd-custom': 'keep'})
        self.assertEqual(data['model_overrides']['gsd-custom'], 'keep')

    def test_available_catalog_classifies_covered_roles_at_init(self):
        catalog = self.root / '.codex/gsd-core/bin/shared/model-catalog.json'
        catalog.parent.mkdir(parents=True)
        self.put(catalog, {'agents': {'gsd-found': {'phaseType': 'verification'},
                                      'gsd-unknown': {'phaseType': 'other'}}})
        self.put(self.working, {'model_overrides': {'gsd-found': 'old', 'gsd-unknown': 'keep'}})
        self.init()
        self.assertEqual(self.get(self.default)['model_overrides'], {'gsd-unknown': 'keep'})

    def test_fifo_catalog_is_optional_for_init_and_rejected_for_preparation(self):
        catalog = self.root / '.codex/gsd-core/bin/shared/model-catalog.json'
        catalog.parent.mkdir(parents=True)
        os.mkfifo(catalog)
        script = """
import sys
from pathlib import Path
from gsd_cli import config
from gsd_cli.resolver import load_catalog
root = Path(sys.argv[1])
config.initialize(root)
try:
    load_catalog(root / '.codex/gsd-core')
except config.ConfigError as exc:
    print(exc)
"""
        result = subprocess.run([sys.executable, '-c', script, str(self.root)],
                                capture_output=True, text=True, timeout=3, check=True)
        self.assertTrue(self.policy_file.exists())
        self.assertIn(str(catalog), result.stdout)
        self.assertIn('regular file', result.stdout)

    def test_provisional_entry_conflicts_on_edit_or_missing_metadata(self):
        self.put(self.working, {'model_overrides': {'gsd-addition': 'seed'}})
        self.init()
        self.catalog['agents']['gsd-addition'] = {'phaseType': 'planning'}
        for edited in (self.default, self.working):
            with self.subTest(edited=edited):
                original = edited.read_bytes()
                data = self.get(edited)
                data['model_overrides']['gsd-addition'] = 'edited'
                self.put(edited, data)
                with self.assertRaisesRegex(config.ConfigError, 'model_overrides.gsd-addition'):
                    self.preview()
                edited.write_bytes(original)
        self.working.unlink()
        state = self.state.read_bytes()
        self.state.unlink()
        with self.assertRaisesRegex(config.ConfigError, 'model_overrides.gsd-addition'):
            self.preview()
        self.state.write_bytes(state)
        defaults = self.get(self.default)
        del defaults['model_overrides']['gsd-addition']
        self.put(self.default, defaults)
        self.sync()
        self.assertNotIn('provisional', self.get(self.state))

    def test_nested_ignore_exception_allows_init(self):
        self.git('init', '-q')
        (self.root / '.planning/.gitignore').write_text('*\n!config.default.json\n')
        self.init()
        self.assertEqual(subprocess.run(['git', 'check-ignore', '-q', '--no-index', '.planning/config.default.json'], cwd=self.root).returncode, 1)

    def test_ignore_exception_is_appended_after_overriding_rule(self):
        self.git('init', '-q')
        (self.root / '.gitignore').write_text('!/.planning/config.default.json\n/.planning/*\n')
        self.init()
        self.assertEqual(subprocess.run(['git', 'check-ignore', '-q', '--no-index', '.planning/config.default.json'], cwd=self.root).returncode, 1)
        before = (self.root / '.gitignore').read_bytes()
        config.initialize(self.root)
        self.assertEqual((self.root / '.gitignore').read_bytes(), before)

    def test_ignored_policy_exception_is_appended_after_overriding_rule(self):
        self.git('init', '-q')
        (self.root / '.gitignore').write_text('!/gsd-cli.config.json\n*.json\n')
        self.init()
        self.assertEqual(subprocess.run(['git', 'check-ignore', '-q', '--no-index', 'gsd-cli.config.json'], cwd=self.root).returncode, 1)

    def test_subproject_nested_ignore_conflict_before_writes(self):
        self.git('init', '-q')
        subproject = self.root / 'app'
        (subproject / '.planning').mkdir(parents=True)
        self.put(subproject / '.planning/config.json', {})
        (subproject / '.planning/.gitignore').write_text('*\n')
        with self.assertRaisesRegex(config.ConfigError, 'Nested'):
            config.initialize(subproject)
        self.assertFalse((subproject / 'gsd-cli.config.json').exists())
        self.assertFalse((subproject / '.gitignore').exists())
        self.assertFalse((subproject / '.planning/config.default.json').exists())

    def test_ignored_project_ancestor_refuses_init_before_writes(self):
        self.git('init', '-q')
        (self.root / '.gitignore').write_text('/app/\n')
        subproject = self.root / 'app' / 'nested'
        (subproject / '.planning').mkdir(parents=True)
        self.put(subproject / '.planning/config.json', {})
        with self.assertRaisesRegex(config.ConfigError, 'ancestor'):
            config.initialize(subproject)
        self.assertFalse((subproject / 'gsd-cli.config.json').exists())
        self.assertFalse((subproject / '.gitignore').exists())
        self.assertFalse((subproject / '.planning/config.default.json').exists())

    def test_hidden_nested_ignore_is_checked_after_planned_reopen(self):
        self.git('init', '-q')
        (self.root / '.gitignore').write_text('.planning/\n')
        (self.root / '.planning/.gitignore').write_text('*\n')
        with self.assertRaisesRegex(config.ConfigError, 'Nested'):
            self.init()
        self.assertFalse(self.policy_file.exists())
        self.assertFalse(self.default.exists())

    def test_nested_rule_cannot_expose_private_sync_files(self):
        self.git('init', '-q')
        (self.root / '.planning/.gitignore').write_text('!.gsd-cli-sync.json\n')
        with self.assertRaisesRegex(config.ConfigError, 'Nested'):
            self.init()
        self.assertFalse(self.policy_file.exists())

    def test_generated_ignore_rules_are_trackable_under_wildcard(self):
        self.git('init', '-q')
        (self.root / '.gitignore').write_text('*\n')
        self.init()
        self.assertEqual(subprocess.run(['git', 'check-ignore', '-q', '--no-index', '.gitignore'], cwd=self.root).returncode, 1)


class ReadJsonTests(unittest.TestCase):
    def test_non_finite_constants_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            for constant in ('NaN', 'Infinity', '-Infinity'):
                with self.subTest(constant):
                    path.write_text('{"a": {"b": %s}}' % constant)
                    with self.assertRaisesRegex(config.ConfigError, f'{constant} is not valid JSON'):
                        config.read_json(path)
            path.write_text('{"a": 1.5e308, "b": -0.0}')
            self.assertEqual(config.read_json(path), {'a': 1.5e308, 'b': -0.0})
