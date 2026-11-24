import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from gsd_cli.claude_agents import AgentError, plan_agents, render_definition


ROLE = 'gsd-executor'
DEST = f'.claude/agents/{ROLE}.md'
SOURCE = (b'---\r\nname: "gsd-executor"\r\ndescription: "With: a colon"\r\n'
          b'tools: Read, Edit\r\nhooks:\r\n  model: untouched\r\n'
          b"model: 'sonnet'  # alias\r\neffort: medium\r\n---\r\nPrompt\xff\r\n---\r\n")


class RendererTests(unittest.TestCase):
    def test_patch_preserves_full_definition(self):
        self.assertEqual(render_definition(SOURCE, ROLE, 'opus', 'high'),
                         SOURCE.replace(b"'sonnet'", b"'opus'").replace(b': medium', b': high'))

    def test_absent_settings_and_supported_aliases(self):
        source = b'---\nname: gsd-executor\n---\nbody'
        for model in ('fable', 'opus', 'sonnet', 'haiku'):
            self.assertEqual(render_definition(source, ROLE, model, 'low'),
                             source.replace(b'\n---\n', f'\nmodel: {model}\neffort: low\n---\n'.encode()))

    def test_missing_effort(self):
        source = b'---\nname: gsd-executor\nmodel: opus\n---\n'
        self.assertEqual(render_definition(source, ROLE, 'haiku', 'high'),
                         b'---\nname: gsd-executor\nmodel: haiku\neffort: high\n---\n')

    def test_ambiguous_headers(self):
        for line in (b'name: other', b'model: opus', b'effort: high', b'<<: *settings'):
            with self.subTest(line=line), self.assertRaises(AgentError):
                render_definition(SOURCE.replace(b'---\r\nPrompt', line + b'\r\n---\r\nPrompt'),
                                  ROLE, 'opus', 'high')


class AgentPlanTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'project'
        self.root.mkdir()
        self.install = Path(tmp.name) / 'runtime/get-shit-done'
        self.install.mkdir(parents=True)
        self.source = self.install.parent / 'agents' / 'upstream.md'
        self.source.parent.mkdir()
        self.source.write_bytes(SOURCE)
        self.agents = {ROLE: {'model': 'opus', 'effort': 'high'}}
        self.dest = self.root / DEST

    def plan(self, agents=None, owned=None):
        return plan_agents(self.root, self.install, self.agents if agents is None else agents,
                           owned or {})

    def apply_initial(self):
        plan = self.plan()
        before, after = plan.changes[DEST]
        self.assertIsNone(before)
        self.assertFalse(self.dest.parent.exists())
        self.dest.parent.mkdir(parents=True)
        self.dest.write_bytes(after)
        self.assertEqual(plan.owned[DEST], hashlib.sha256(after).hexdigest())
        return plan.owned

    def test_refresh_fallback_and_retirement(self):
        owned = self.apply_initial()
        hand = self.dest.parent / 'other.md'
        hand.write_bytes(b'---\nname: mine\n---\nHello')
        self.assertEqual(self.plan(owned=owned).changes, {})
        self.source.write_bytes(SOURCE + b'New upstream prompt')
        self.agents[ROLE]['effort'] = 'low'
        plan = self.plan(owned=owned)
        self.assertIn(b'effort: low', plan.changes[DEST][1])
        self.assertTrue(plan.changes[DEST][1].endswith(b'New upstream prompt'))
        self.source.unlink()
        plan = self.plan({}, owned)
        self.assertEqual(plan.changes, {DEST: (self.dest.read_bytes(), None)})
        self.assertEqual(plan.owned, {})
        self.dest.unlink()
        self.assertEqual(self.plan({}, owned).changes, {})
        self.assertTrue(hand.exists())

    def test_missing_ambiguous_and_nested_identity(self):
        copy = self.source.with_name('other.md')
        copy.write_bytes(SOURCE)
        with self.assertRaisesRegex(AgentError, ROLE):
            self.plan()
        copy.unlink()
        nested = self.dest.parent / 'nested/other.md'
        nested.parent.mkdir(parents=True)
        nested.write_bytes(SOURCE)
        with self.assertRaisesRegex(AgentError, 'other.md'):
            self.plan()
        nested.unlink()
        self.source.unlink()
        with self.assertRaisesRegex(AgentError, ROLE):
            self.plan()

    def test_user_conflict_edit_and_tracked_missing(self):
        owned = self.apply_initial()
        with self.assertRaisesRegex(AgentError, DEST):
            self.plan()
        self.dest.write_bytes(b'my edits')
        for roles in (self.agents, {}):
            with self.assertRaisesRegex(AgentError, DEST):
                self.plan(roles, owned)
        subprocess.run(['git', 'init', '-q'], cwd=self.root, check=True)
        subprocess.run(['git', 'add', DEST], cwd=self.root, check=True)
        self.dest.unlink()
        with self.assertRaisesRegex(AgentError, DEST):
            self.plan()

    def test_symlink_and_source_overlap(self):
        (self.root / '.claude').symlink_to(self.install.parent, target_is_directory=True)
        with self.assertRaisesRegex(AgentError, 'symlink'):
            self.plan()
        (self.root / '.claude').unlink()
        (self.root / '.claude').mkdir()
        with self.assertRaisesRegex(AgentError, 'coincide'):
            plan_agents(self.root, self.root / '.claude/get-shit-done', self.agents, {})

    def test_hardlinked_source_and_recreation(self):
        owned = self.apply_initial()
        self.dest.unlink()
        self.assertEqual(self.plan(owned=owned).evidence[ROLE]['action'], 'create')
        os.link(self.source, self.dest)
        digest = hashlib.sha256(SOURCE).hexdigest()
        with self.assertRaisesRegex(AgentError, 'aliases'):
            self.plan(owned={DEST: digest})

    def test_rejects_unsafe_ownership(self):
        for path in ('.claude/agents/../oops.md', '.claude/agents/gsd-a/b.md',
                     '.claude/agents/custom.md'):
            with self.subTest(path=path), self.assertRaisesRegex(AgentError, 'ownership'):
                self.plan({}, {path: 'a' * 64})

    def test_unrelated_author_and_indented_duplicate(self):
        hand = self.dest.parent / 'nested/custom.md'
        hand.parent.mkdir(parents=True)
        hand.write_bytes(b'---\nname: "My Agent"\ndescription: >-\n  agent description\n---\n')
        self.assertEqual(self.plan().evidence[ROLE]['action'], 'create')
        hand.write_bytes(b'---\n  name: gsd-executor\n  tools: Read\n---\n')
        with self.assertRaisesRegex(AgentError, 'custom.md'):
            self.plan()

    def test_uncovered_agent(self):
        self.source.unlink()
        self.assertEqual(self.plan({ROLE: {'model': None, 'effort': None}}).changes, {})
