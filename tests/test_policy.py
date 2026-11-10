"""Project policy contracts; no runtime/model calls."""
import copy
import unittest

from gsd_cli.policy import PolicyError, load_default, resolve, validate


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_default()

    def test_complete_resource_and_runtime_levels(self):
        validate(self.policy)
        for runtime in ('claude', 'codex'):
            for level, tier in [('low', 'haiku'), ('medium', 'sonnet'), ('high', 'opus')]:
                with self.subTest(runtime=runtime, level=level):
                    result = resolve(self.policy, 'plan', runtime, level)
                    self.assertEqual(result['values'][('models', 'planning')], tier)
                    self.assertEqual(result['model'], self.policy['runtimes'][runtime][level]['session_model'])
                    self.assertEqual(result['values'][('effort', 'agent_overrides', 'gsd-plan-checker')], 'high')
                    self.assertEqual(result['values'][('review', 'effort', 'claude')], 'high')
                    self.assertEqual(result['reviewers'][0], 'astra-review' if runtime == 'claude' else 'fable-review')

    def test_custom_workflow_and_independent_efforts(self):
        self.policy['workflows']['ship'] = copy.deepcopy(self.policy['workflows']['exec'])
        result = resolve(self.policy, 'ship', 'codex', 'high')
        self.assertEqual(result['effort'], 'medium')
        self.assertEqual(result['values'][('models', 'execution')], 'opus')
        self.assertEqual(result['values'][('models', 'verification')], 'opus')
        self.assertEqual(result['values'][('model_overrides', 'gsd-codebase-mapper')], 'gpt-6.1-sol')
        self.assertEqual(result['values'][('review', 'reviewer_instances', 'fable-review')]['model'], 'claude-fable-5-1')

    def test_no_hidden_fallback(self):
        edits = [
            lambda p: p['runtimes']['claude'].pop('low'),
            lambda p: p['workflows']['exec'].pop('reviewer_groups'),
            lambda p: p['workflows']['exec']['tasks'].append('verification'),
            lambda p: p['reviewer_groups']['review-codex-plan'].append('missing'),
            lambda p: p['runtimes']['claude']['low'].update(agent_model='claude-sonnet-5-5'),
            lambda p: p['workflows'].update(status=p['workflows']['plan']),
            lambda p: p['workflows']['plan']['permissions'].update(codex='yes'),
            lambda p: p.update(schema_version=True),
            lambda p: p.update(typo='unknown'),
            lambda p: p['agent_efforts'].update({'gsd-planner': 'huge'}),
            lambda p: p['phase_defaults'].update(execution='opus'),
        ]
        for edit in edits:
            policy = copy.deepcopy(self.policy)
            edit(policy)
            with self.subTest(edit=edit), self.assertRaises(PolicyError):
                validate(policy)

    def test_required_gsd_minimum_and_reserved_check_workflow(self):
        self.assertEqual(self.policy['gsd']['min_version'], '1.20.1')
        for value in (None, {}, {'min_version': '1.2'}, {'min_version': True}, {'min_version': '1.20.1', 'on_failure': 'warn'}):
            p = copy.deepcopy(self.policy)
            p['gsd'] = value
            with self.subTest(value=value), self.assertRaises(PolicyError):
                validate(p)
        self.policy['workflows']['check'] = copy.deepcopy(self.policy['workflows']['plan'])
        with self.assertRaises(PolicyError):
            validate(self.policy)
