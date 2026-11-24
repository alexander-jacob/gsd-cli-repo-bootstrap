"""PolicyFile mirrors the structural rules of policy.validate."""
import copy
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from gsd_cli.policy import PolicyError, load_default, validate
from gsd_cli.policy_model import PolicyFile

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / 'examples' / 'gsd-config-example.json'
SEED = ROOT / 'gsd_cli' / 'data' / 'default-config.json'


def mutated(data, path, value):
    data = copy.deepcopy(data)
    keys = path.split('.')
    target = data
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    return data


class PolicyFileTests(unittest.TestCase):
    def test_starter_and_example_validate(self):
        self.assertEqual(EXAMPLE.read_bytes(), SEED.read_bytes())
        for data in (load_default(), json.loads(EXAMPLE.read_text(encoding='utf-8'))):
            self.assertEqual(data['schema_version'], 2)
            validate(data)
            PolicyFile.model_validate(data)

    def test_structural_rejections_match_policy_validate(self):
        self.assertEqual(load_default()['schema_version'], 2)
        mutations = [
            ('schema_version', 1),
            ('runtimes.codex.blueprints', {}),
            ('runtimes.claude.blueprints.high.session.effort', 'auto'),
            ('runtimes.claude.blueprints.high.phases.verification.model', 'claude-opus-5-5'),
            ('runtimes.codex.blueprints.high.phases', {}),
            ('runtimes.codex.blueprints.high.agents', None),
            ('runtimes.codex.blueprints.high.agents.gsd-executor', {}),
            ('runtimes.codex.blueprints.high.agents.gsd-executor', {'model': None}),
            ('runtimes.codex.blueprints.high.agents.gsd-executor', {'effort': 'max'}),
            ('runtimes.codex.blueprints.high.agents.executor', {'effort': 'high'}),
            ('runtimes.claude.review.reviewer_instances.astra-review.cli', 'gemini'),
            ('runtimes.claude.review.effort.claude', 'xhigh'),
            ('runtimes.claude.review.parallel_lanes', 'yes'),
            ('runtimes.claude.review.default_reviewers', ['astra-review', 'astra-review']),
            ('extra_key', 1),
        ]
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                data = mutated(load_default(), path, value)
                with self.assertRaises(PolicyError):
                    validate(data)
                with self.assertRaises(ValidationError):
                    PolicyFile.model_validate(data)

    def test_codex_agent_models_exclude_claude_aliases(self):
        data = load_default()
        for path in (
            'runtimes.codex.blueprints.high.phases.execution.model',
            'runtimes.codex.blueprints.high.agents.gsd-codebase-mapper.model',
        ):
            with self.subTest(path=path):
                with self.assertRaises(ValidationError):
                    PolicyFile.model_validate(mutated(data, path, 'opus'))
                PolicyFile.model_validate(mutated(data, path, 'custom-provider/opus-compatible-v2'))

    def test_published_schema_disallows_claude_aliases_in_codex_agent_models(self):
        schema = PolicyFile.model_json_schema()

        def resolve(node):
            if '$ref' in node:
                return schema['$defs'][node['$ref'].rsplit('/', 1)[-1]]
            return node

        def property_schema(node, name):
            return resolve(node['properties'][name])

        runtimes = property_schema(schema, 'runtimes')
        blueprint_map = property_schema(property_schema(runtimes, 'codex'), 'blueprints')
        blueprint = resolve(next(iter(blueprint_map['patternProperties'].values())))
        phases = property_schema(blueprint, 'phases')
        phase_model = property_schema(property_schema(phases, 'execution'), 'model')
        agents = property_schema(blueprint, 'agents')
        agent_model = property_schema(resolve(next(iter(agents['patternProperties'].values()))), 'model')
        for model in (phase_model, agent_model):
            self.assertCountEqual(model['not']['enum'], ('opus', 'fable', 'sonnet', 'haiku'))

    def test_missing_required_key_rejected(self):
        data = load_default()
        del data['gsd']
        with self.assertRaises(PolicyError):
            validate(data)
        with self.assertRaises(ValidationError):
            PolicyFile.model_validate(data)

    def test_partial_agent_overrides_and_absent_agents(self):
        data = load_default()
        self.assertIn('blueprints', data['runtimes']['codex'])
        codex = data['runtimes']['codex']['blueprints']
        del codex['low']['agents']
        codex['high']['agents'] = {
            'gsd-codebase-mapper': {'model': 'gpt-6-luna'},
            'gsd-executor': {'effort': 'xhigh'},
        }
        validate(data)
        PolicyFile.model_validate(data)
        schema = json.dumps(PolicyFile.model_json_schema())
        self.assertNotIn('"null"', schema)
        self.assertNotIn('"default": null', schema)

    def test_runtime_efforts_and_blueprint_names_are_independent(self):
        data = load_default()
        self.assertIn('blueprints', data['runtimes']['codex'])
        codex = data['runtimes']['codex']['blueprints']
        codex['careful'] = copy.deepcopy(codex['high'])
        codex['careful']['session']['effort'] = 'xhigh'
        claude = data['runtimes']['claude']['blueprints']
        claude['high']['session']['effort'] = 'max'
        claude['high']['agents']['gsd-executor'] = {'effort': 'xhigh'}
        validate(data)
        PolicyFile.model_validate(data)


if __name__ == '__main__':
    unittest.main()
