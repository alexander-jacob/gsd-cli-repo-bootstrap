"""Pydantic model of the project policy file and its JSON Schema."""
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, WithJsonSchema, model_validator

from . import policy as rules

Level = Literal[rules.LEVELS]
CodexEffort = Literal[rules.EFFORTS]
ClaudeEffort = Literal[rules.CLAUDE_EFFORTS]
ClaudeAgentModel = Literal[rules.CLAUDE_AGENT_MODELS]
TEXT_PATTERN = r'^[^\x00]*\S[^\x00]*$'
Text = Annotated[str, StringConstraints(pattern=TEXT_PATTERN)]
AgentName = Annotated[str, StringConstraints(pattern=rules.AGENT_NAME_PATTERN)]
BlueprintName = Annotated[str, StringConstraints(pattern=rules.BLUEPRINT_NAME_PATTERN)]

ModelId = TypeVar('ModelId')
Effort = TypeVar('Effort')
SessionSettings = TypeVar('SessionSettings')
AgentSettings = TypeVar('AgentSettings')
NamedOverride = TypeVar('NamedOverride')


def full_codex_model_id(value: str) -> str:
    if value in rules.CODEX_RESERVED_AGENT_MODELS:
        raise ValueError('expected a full Codex model ID')
    return value


CodexAgentModel = Annotated[
    Text,
    AfterValidator(full_codex_model_id),
    WithJsonSchema({
        'type': 'string',
        'pattern': TEXT_PATTERN,
        'not': {'enum': list(rules.CODEX_RESERVED_AGENT_MODELS)},
    }),
]


def unique(items: list) -> list:
    if len(items) != len(set(items)):
        raise ValueError('duplicate entries')
    return items


def omissible(*, schema_extra=None):
    """Publish an optional key without accepting or advertising null."""
    def update_schema(schema):
        schema.pop('default', None)
        if schema_extra:
            schema.update(schema_extra)

    return Field(default=None, json_schema_extra=update_schema)


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Gsd(Strict):
    min_version: Text


class ModelEffort(Strict, Generic[ModelId, Effort]):
    model: ModelId
    effort: Effort


class AgentOverride(Strict, Generic[ModelId, Effort]):
    model_config = ConfigDict(json_schema_extra={'minProperties': 1})

    model: ModelId = omissible()
    effort: Effort = omissible()

    @model_validator(mode='after')
    def at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError('expected at least one of model and effort')
        return self


class Phases(Strict, Generic[AgentSettings]):
    planning: AgentSettings
    discuss: AgentSettings
    research: AgentSettings
    execution: AgentSettings
    verification: AgentSettings


class Blueprint(Strict, Generic[SessionSettings, AgentSettings, NamedOverride]):
    session: SessionSettings
    phases: Phases[AgentSettings]
    agents: dict[AgentName, NamedOverride] = omissible(schema_extra={'additionalProperties': False})


CodexSession = ModelEffort[Text, CodexEffort]
CodexAgent = ModelEffort[CodexAgentModel, CodexEffort]
ClaudeSession = ModelEffort[Text, ClaudeEffort]
ClaudeAgent = ModelEffort[ClaudeAgentModel, ClaudeEffort]


class CodexBlueprint(Blueprint[CodexSession, CodexAgent, AgentOverride[CodexAgentModel, CodexEffort]]):
    pass


class ClaudeBlueprint(Blueprint[ClaudeSession, ClaudeAgent, AgentOverride[ClaudeAgentModel, ClaudeEffort]]):
    pass


class Reviewer(BaseModel):
    # Extra reviewer instance settings pass through to the GSD adapter.
    model_config = ConfigDict(extra='allow', strict=True)

    cli: Literal[rules.REVIEW_ADAPTERS]
    model: Text


class ReviewerEfforts(Strict):
    claude: Level
    codex: CodexEffort
    opencode: CodexEffort


class Review(Strict):
    reviewer_instances: dict[Text, Reviewer] = Field(json_schema_extra={'additionalProperties': False})
    default_reviewers: Annotated[list[str], AfterValidator(unique), Field(json_schema_extra={'uniqueItems': True})]
    effort: ReviewerEfforts
    parallel_lanes: bool


BlueprintSettings = TypeVar('BlueprintSettings')


class Runtime(Strict, Generic[BlueprintSettings]):
    blueprints: dict[BlueprintName, BlueprintSettings] = Field(
        min_length=1, json_schema_extra={'additionalProperties': False}
    )
    review: Review


class Runtimes(Strict):
    claude: Runtime[ClaudeBlueprint]
    codex: Runtime[CodexBlueprint]


class PolicyFile(Strict):
    """Complete gsd-cli.config.json input.

    The domain validator additionally checks that the minimum is a SemVer
    value and reviewer names refer to instances declared in the same runtime.
    """

    gsd: Gsd
    schema_version: Literal[2]
    runtimes: Runtimes
    gsd_defaults: dict[str, Any]
