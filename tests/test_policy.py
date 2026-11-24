"""Project policy contracts checked without invoking a runtime."""
import copy
import re
import unittest

from gsd_cli.policy import PolicyError, load_default, resolve, validate


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
        for alias in ('opus', 'fable', 'sonnet', 'haiku', 'inherit'):
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


class BlueprintRoutingTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_default()
        self.blueprint = self.policy['runtimes']['codex']['blueprints']['high']
        self.blueprint.update({
            'session': {'model': 'gpt-6-astra', 'effort': 'high'},
            'phases': {
                'planning': {'model': 'gpt-6-astra', 'effort': 'high'},
                'discuss': {'model': 'gpt-6.1-sol', 'effort': 'medium'},
                'research': {'model': 'gpt-6.1-sol', 'effort': 'high'},
                'execution': {'model': 'gpt-6-astra', 'effort': 'high'},
                'verification': {'model': 'gpt-6.1-sol', 'effort': 'high'},
            },
            'agents': {
                'gsd-executor': {'effort': 'xhigh'},
                'gsd-codebase-mapper': {'model': 'gpt-6-luna', 'effort': 'medium'},
            },
        })
        self.catalog = {'agents': {
            'gsd-executor': {'phaseType': 'execution'},
            'gsd-codebase-mapper': {'phaseType': 'research'},
            'gsd-verifier': {'phaseType': 'verification'},
            'gsd-future-agent': {'phaseType': 'future'},
        }}

    def resolve(self, runtime='codex', name='high'):
        return resolve(self.policy, runtime, name, self.catalog)

    def test_executor_inherits_only_missing_fields(self):
        resolved = self.resolve()
        self.assertEqual(resolved['agents']['gsd-executor'], {
            'model': 'gpt-6-astra', 'effort': 'xhigh', 'phase': 'execution',
            'model_source': 'runtimes.codex.blueprints.high.phases.execution.model',
            'effort_source': 'runtimes.codex.blueprints.high.agents.gsd-executor.effort',
        })
        self.assertEqual(resolved['values']['model_overrides', 'gsd-executor'], 'gpt-6-astra')
        self.assertEqual(resolved['values']['effort', 'agent_overrides', 'gsd-executor'], 'xhigh')
        del self.blueprint['agents']['gsd-executor']
        executor = self.resolve()['agents']['gsd-executor']
        self.assertEqual(executor['effort'], 'high')
        self.assertEqual(executor['effort_source'], 'runtimes.codex.blueprints.high.phases.execution.effort')

    def test_model_only_override_inherits_phase_effort(self):
        self.blueprint['agents']['gsd-executor'] = {'model': 'gpt-6-luna'}
        executor = self.resolve()['agents']['gsd-executor']
        self.assertEqual(executor['model'], 'gpt-6-luna')
        self.assertEqual(executor['model_source'], 'runtimes.codex.blueprints.high.agents.gsd-executor.model')
        self.assertEqual(executor['effort'], 'high')

    def test_verifier_uses_verification_settings_in_same_session_as_executor(self):
        resolved = self.resolve()
        self.assertEqual((resolved['model'], resolved['effort']), ('gpt-6-astra', 'high'))
        self.assertEqual(resolved['values']['model_overrides', 'gsd-verifier'], 'gpt-6.1-sol')
        self.assertEqual(resolved['values']['effort', 'agent_overrides', 'gsd-verifier'], 'high')

    def test_explicit_role_missing_from_catalog_is_an_error(self):
        del self.catalog['agents']['gsd-codebase-mapper']
        with self.assertRaisesRegex(PolicyError, r'runtimes\.codex\.blueprints\.high\.agents\.gsd-codebase-mapper'):
            self.resolve()

    def test_catalog_role_must_be_a_valid_gsd_agent_name(self):
        for role in ('executor', 'gsd-../../executor'):
            with self.subTest(role=role):
                catalog = {'agents': {**self.catalog['agents'], role: {'phaseType': 'execution'}}}
                with self.assertRaisesRegex(PolicyError, re.escape(role)):
                    resolve(self.policy, 'codex', 'high', catalog)

    def test_uncovered_role_is_visible_without_managed_values(self):
        resolved = self.resolve()
        self.assertEqual(resolved['agents']['gsd-future-agent'], {
            'phase': 'future', 'model': None, 'effort': None,
            'model_source': None, 'effort_source': None,
        })
        self.assertFalse(any(path[-1] == 'gsd-future-agent' for path in resolved['values']))

    def test_uncovered_role_can_supply_both_fields(self):
        self.catalog['agents']['gsd-future-agent'] = {}
        self.blueprint['agents']['gsd-future-agent'] = {'model': 'gpt-6-luna', 'effort': 'medium'}
        resolved = self.resolve()
        self.assertEqual(resolved['values']['model_overrides', 'gsd-future-agent'], 'gpt-6-luna')
        self.assertEqual(resolved['values']['effort', 'agent_overrides', 'gsd-future-agent'], 'medium')

    def test_uncovered_partial_override_reports_missing_field_path(self):
        self.blueprint['agents']['gsd-future-agent'] = {'model': 'gpt-6-luna'}
        with self.assertRaisesRegex(PolicyError, r'runtimes\.codex\.blueprints\.high\.agents\.gsd-future-agent\.effort'):
            self.resolve()

    def test_only_selected_runtime_review_settings_are_emitted(self):
        review = self.policy['runtimes']['codex']['review']
        review['reviewer_instances']['custom-review'] = {'cli': 'opencode', 'model': 'custom-model'}
        review['default_reviewers'] = ['custom-review']
        resolved = self.resolve()
        self.assertEqual(resolved['reviewers'], ['custom-review'])
        self.assertEqual(resolved['review']['reviewer_instances']['custom-review']['cli'], 'opencode')
        expected = {
            ('review', 'reviewer_instances', name): reviewer for name, reviewer in review['reviewer_instances'].items()
        }
        expected.update({('review', 'effort', cli): effort for cli, effort in review['effort'].items()})
        expected['review', 'default_reviewers'] = ['custom-review']
        expected['review', 'parallel_lanes'] = review['parallel_lanes']
        self.assertEqual({path: value for path, value in resolved['values'].items() if path[0] == 'review'}, expected)
        self.assertLessEqual({path[0] for path in resolved['values']}, {'review', 'model_overrides', 'effort'})

    def test_unknown_blueprint_lists_only_selected_runtime_choices(self):
        self.policy['runtimes']['codex']['blueprints']['xhigh'] = self.blueprint
        with self.assertRaisesRegex(PolicyError, r'runtimes\.claude\.blueprints.*high, low, medium') as error:
            self.resolve('claude', 'xhigh')
        self.assertNotIn('medium, xhigh', str(error.exception))
