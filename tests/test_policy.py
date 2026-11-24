"""Project policy contracts checked without invoking a runtime."""
import copy
import re
import unittest

from gsd_cli.policy import PolicyError, load_default, validate


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_default()

    def test_runtime_local_names(self):
        runtimes = self.policy['runtimes']
        self.assertIn('blueprints', runtimes['codex'])
        codex = runtimes['codex']['blueprints']
        codex['xhigh'] = copy.deepcopy(codex['high'])
        self.assertIsNone(validate(self.policy))
        self.assertNotIn('xhigh', runtimes['claude']['blueprints'])
        self.assertEqual(codex['xhigh']['session']['effort'], 'high')

    def test_starter_preserves_named_pins_and_runtime_reviewers(self):
        validate(self.policy)
        runtimes = self.policy['runtimes']
        self.assertIn('blueprints', runtimes['codex'])
        for runtime, expected in (
            ('claude', ('claude-fable-5-2', 'fable', 'opus', 'astra-review')),
            ('codex', ('gpt-6-astra', 'gpt-6-astra', 'gpt-6.1-sol', 'fable-review')),
        ):
            with self.subTest(runtime=runtime):
                session, agent, pin, reviewer = expected
                policy = runtimes[runtime]
                blueprint = policy['blueprints']['high']
                self.assertEqual(blueprint['session'], {'model': session, 'effort': 'high'})
                self.assertEqual(blueprint['phases']['verification'], {'model': agent, 'effort': 'high'})
                self.assertEqual(blueprint['agents']['gsd-codebase-mapper'], {'model': pin, 'effort': 'medium'})
                self.assertEqual(blueprint['agents']['gsd-plan-checker'], {'effort': 'high'})
                self.assertEqual(policy['review']['default_reviewers'], [reviewer, 'grok-review', 'gemini-review'])
                self.assertEqual(policy['review']['effort']['claude'], 'high')
        self.assertTrue(self.policy['gsd_defaults']['workflow']['compact_content'])

    def test_validation_identifies_invalid_policy_paths(self):
        self.assertIn('blueprints', self.policy['runtimes']['codex'])
        replacements = [
            ('runtimes.codex.blueprints', {}),
            ('runtimes.codex.blueprints.bad name', self.policy['runtimes']['codex']['blueprints']['high']),
            ('runtimes.claude.blueprints.low.phases.execution.model', 'claude-sonnet-5-5'),
            ('runtimes.claude.blueprints.low.agents.gsd-planner', {}),
            ('runtimes.claude.blueprints.high.agents.gsd-planner.model', 'claude-fable-5-2'),
            ('runtimes.codex.blueprints.high.agents.gsd-executor', {'effort': 'max'}),
            ('runtimes.codex.blueprints.high.agents.executor', {'effort': 'high'}),
            ('runtimes.codex.review.default_reviewers', ['missing']),
            ('runtimes.codex.review.default_reviewers', ['fable-review', 'fable-review']),
            ('runtimes.codex.review.reviewer_instances.fable-review.cli', 'gemini'),
            ('runtimes.codex.review.parallel_lanes', 'yes'),
            ('runtimes.claude.review.effort.claude', 'xhigh'),
            ('schema_version', True),
            ('typo', 'unknown'),
        ]
        for path, value in replacements:
            with self.subTest(path=path, value=value):
                data = copy.deepcopy(self.policy)
                *parents, key = path.split('.')
                target = data
                for parent in parents:
                    target = target[parent]
                target[key] = value
                expected = f'{path}.effort' if key == 'gsd-executor' else path
                with self.assertRaisesRegex(PolicyError, re.escape(expected)):
                    validate(data)

    def test_codex_requires_full_agent_model_ids(self):
        for alias in ('opus', 'fable', 'sonnet', 'haiku'):
            for section, key in (('phases', 'execution'), ('agents', 'gsd-codebase-mapper')):
                with self.subTest(alias=alias, section=section):
                    data = copy.deepcopy(self.policy)
                    settings = data['runtimes']['codex']['blueprints']['high'][section][key]
                    settings['model'] = alias
                    path = f'runtimes.codex.blueprints.high.{section}.{key}.model'
                    with self.assertRaisesRegex(PolicyError, re.escape(path)):
                        validate(data)
                    settings['model'] = 'custom-provider/opus-compatible-v2'
                    self.assertIsNone(validate(data))

    def test_missing_phase_in_inactive_blueprint_is_rejected(self):
        self.assertIn('blueprints', self.policy['runtimes']['codex'])
        del self.policy['runtimes']['codex']['blueprints']['low']['phases']['verification']
        with self.assertRaisesRegex(PolicyError, r'runtimes\.codex\.blueprints\.low\.phases\.verification'):
            validate(self.policy)

    def test_both_runtime_sections_are_required(self):
        del self.policy['runtimes']['claude']
        with self.assertRaisesRegex(PolicyError, r'runtimes\.claude'):
            validate(self.policy)

    def test_version_one_requires_manual_conversion(self):
        with self.assertRaisesRegex(PolicyError, 'schema_version:.*manually'):
            validate({'schema_version': 1, 'gsd': {'min_version': '1.21.0'}, 'workflows': {}})

    def test_required_gsd_minimum(self):
        self.assertEqual(self.policy['gsd']['min_version'], '1.21.0')
        for value in (None, {}, {'min_version': '1.2'}, {'min_version': True}, {'min_version': '1.20.1', 'on_failure': 'warn'}):
            p = copy.deepcopy(self.policy)
            p['gsd'] = value
            with self.subTest(value=value), self.assertRaisesRegex(PolicyError, 'gsd'):
                validate(p)
