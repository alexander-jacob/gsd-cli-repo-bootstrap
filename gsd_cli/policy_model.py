"""Pydantic model of the project policy file; its JSON Schema derives from it."""
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from . import policy as rules

Level = Literal[rules.LEVELS]
Effort = Literal[rules.EFFORTS]
Phase = Literal[rules.PHASES]
Text = Annotated[str, StringConstraints(pattern=r'^[^\x00]*\S[^\x00]*$')]
AgentName = Annotated[str, StringConstraints(pattern=r'^gsd-[a-z0-9-]+$')]
WorkflowName = Annotated[str, StringConstraints(pattern=r'^[a-z][a-z0-9-]*$')]


def unique(items: list) -> list:
    if len(items) != len(set(items)):
        raise ValueError('duplicate entries')
    return items


def omissible():
    """A key that may be left out but, when present, is never null.

    The None default is not validated, so explicit null is rejected as
    policy.validate rejects it, and the schema publishes no default.
    """
    return Field(default=None, json_schema_extra=lambda schema: schema.pop('default', None))


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Gsd(Strict):
    min_version: Text


class ClaudeEntry(Strict):
    session_model: Text
    agent_model: Literal['fable', 'opus', 'sonnet', 'haiku']
    session_effort: Level


class CodexEntry(Strict):
    session_model: Text
    agent_model: Text
    session_effort: Effort


class ClaudeLevels(Strict):
    high: ClaudeEntry
    medium: ClaudeEntry
    low: ClaudeEntry


class CodexLevels(Strict):
    high: CodexEntry
    medium: CodexEntry
    low: CodexEntry


class Runtimes(Strict):
    claude: ClaudeLevels
    codex: CodexLevels


class PhaseDefaults(Strict):
    planning: Level
    discuss: Level
    research: Level
    execution: Level
    verification: Level


class Reviewer(BaseModel):
    # policy.validate requires cli and model and tolerates other keys here.
    model_config = ConfigDict(extra='allow', strict=True)
    cli: Literal[rules.RUNTIMES + ('opencode',)]
    model: Text


class ReviewerEfforts(Strict):
    claude: Level
    codex: Effort
    opencode: Effort


class WorkflowReviewerGroups(Strict):
    claude: str
    codex: str


class WorkflowPermissions(Strict):
    claude: Literal['normal', 'bypass']
    codex: Literal['normal', 'bypass']


class SessionEfforts(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    claude: dict[Level, Level] = omissible()
    codex: dict[Level, Effort] = omissible()


class Workflow(Strict):
    tasks: Annotated[list[Phase], AfterValidator(unique), Field(json_schema_extra={'uniqueItems': True})]
    task_levels: dict[Phase, Level]
    reviewer_groups: WorkflowReviewerGroups
    parallel_reviews: bool
    permissions: WorkflowPermissions
    session_efforts: SessionEfforts = omissible()


class PolicyFile(Strict):
    """The complete gsd-cli project policy file (gsd-cli.config.json).

    The launcher validates the policy with policy.validate. This schema mirrors
    its structural rules only; cross-references (reviewer groups naming declared
    reviewers, workflow groups naming declared groups, tasks not overlapping
    task_levels, reserved workflow names, min_version being SemVer) are not
    expressed and are enforced by the launcher.
    """
    gsd: Gsd
    schema_version: Literal[1]
    runtimes: Runtimes
    phase_defaults: PhaseDefaults
    agent_levels: dict[AgentName, Level]
    agent_efforts: dict[AgentName, Effort]
    reviewers: dict[Text, Reviewer]
    reviewer_efforts: ReviewerEfforts
    reviewer_groups: dict[str, Annotated[list[str], AfterValidator(unique)]]
    workflows: dict[WorkflowName, Workflow]
    gsd_defaults: dict[str, Any]
