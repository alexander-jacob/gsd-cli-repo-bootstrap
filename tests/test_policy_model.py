"""PolicyFile mirrors the structural rules of policy.validate."""
import copy
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from gsd_cli.policy import PolicyError, load_default, validate
from gsd_cli.policy_model import PolicyFile

EXAMPLE = Path(__file__).resolve().parent.parent / 'examples' / 'gsd-config-example.json'


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
        for data in (load_default(), json.loads(EXAMPLE.read_text(encoding='utf-8'))):
            validate(data)
            PolicyFile.model_validate(data)

    def test_structural_rejections_match_policy_validate(self):
        mutations = [
            ('schema_version', 2), ('phase_defaults.planning', 'huge'),
            ('runtimes.claude.high.agent_model', 'claude-opus-5-5'),
            ('runtimes.claude.high.session_effort', 'xhigh'),
            ('agent_levels.planner', 'high'), ('agent_efforts.gsd-planner', 'max'),
            ('reviewers.fable-review.cli', 'gemini'), ('reviewer_efforts.claude', 'xhigh'),
            ('workflows.plan.permissions.claude', 'yolo'), ('workflows.plan.parallel_reviews', 'yes'),
            ('extra_key', 1),
            ('workflows.plan.session_efforts', None), ('workflows.exec.session_efforts.claude', None),
            ('workflows.exec.session_efforts.codex', None),
        ]
        for path, value in mutations:
            with self.subTest(path):
                data = mutated(load_default(), path, value)
                with self.assertRaises(PolicyError):
                    validate(data)
                with self.assertRaises(ValidationError):
                    PolicyFile.model_validate(data)

    def test_missing_required_key_rejected(self):
        data = load_default()
        del data['gsd']
        with self.assertRaises(PolicyError):
            validate(data)
        with self.assertRaises(ValidationError):
            PolicyFile.model_validate(data)

    def test_optional_keys_may_be_omitted_but_schema_never_allows_null(self):
        data = mutated(load_default(), 'workflows.exec.session_efforts', {})
        validate(data)
        PolicyFile.model_validate(data)
        schema = json.dumps(PolicyFile.model_json_schema())
        self.assertNotIn('"null"', schema)
        self.assertNotIn('"default": null', schema)

    def test_codex_accepts_xhigh(self):
        data = mutated(load_default(), 'runtimes.codex.high.session_effort', 'xhigh')
        validate(data)
        PolicyFile.model_validate(data)


if __name__ == '__main__':
    unittest.main()
