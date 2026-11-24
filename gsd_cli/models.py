"""Pydantic models that define machine-readable output; schemas derive from them."""
import json
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, JsonValue

from .policy_model import PolicyFile

SCHEMA_VERSION = 2
ErrorKind = Literal['usage', 'config', 'policy', 'version', 'os', 'requirements', 'incomplete']
JSON_COMMANDS = ('status', 'check', 'policy', 'sessions', 'preview')
DataT = TypeVar('DataT')


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ErrorInfo(Model):
    kind: ErrorKind
    message: str


class Envelope(Model, Generic[DataT]):
    schema_version: Literal[2] = SCHEMA_VERSION
    command: str | None  # Narrowed to a Literal in each subclass.
    ok: bool
    data: DataT | None = None
    error: ErrorInfo | None = None


class ErrorEnvelope(Envelope[None]):
    command: None = None


class StatusData(Model):
    project: str
    source: str
    pending_recovery: bool
    config: dict[str, Any]


class CheckEntry(Model):
    runtime: Literal['claude', 'codex']
    directory: str
    installed: str | None
    minimum: str
    ok: bool
    reason: Literal['ok', 'below_minimum', 'unverifiable']
    message: str


class CheckData(Model):
    minimum: str
    results: list[CheckEntry]


class PolicyData(Model):
    project: str
    path: str
    policy: dict[str, Any]
    differs_from_shipped: list[str]


FindingCode = Literal['model_mismatch', 'effort_mismatch', 'effort_clamped', 'installed_effort_mismatch',
                      'model_unknown', 'effort_unknown', 'forwarded_may_override', 'installed_effort_unknown',
                      'inherit_depends_on_forwarded', 'propagation_unknown', 'unregistered_agent',
                      'alias_equivalent', 'inherits_session_effort', 'installed_effort_differs',
                      'project_effort_unverified']


class FindingModel(Model):
    code: FindingCode
    severity: Literal['mismatch', 'unknown', 'note']
    message: str


class ResolvedRow(BaseModel):
    """Installed GSD resolver row: the keys resolver.validate_result requires, plus any it adds."""
    model_config = ConfigDict(extra='allow')
    model: str
    profile: str
    effort: str
    effort_effective: str
    effort_effective_source: Literal['resolved', 'frontmatter', 'frontmatter-absent']
    effort_propagation: str | None
    effort_param: str | None
    effort_rendered: str | None
    effort_clamped: bool
    fast_mode: bool
    fast_mode_supported: bool


class Expected(Model):
    # Working-config values are not policy-owned, so they are reported as configured, whatever their type.
    model: JsonValue
    effort: JsonValue
    model_source: str
    effort_source: str


class ProjectDefinition(Model):
    source: str | None
    destination: str
    action: Literal['create', 'update', 'unchanged', 'remove', 'forget']
    model: str | None
    effort: str | None


class AgentRow(Model):
    agent: str
    phase: str
    covered: bool
    project_definition: ProjectDefinition | None
    expected: Expected
    resolved: ResolvedRow | None
    check: Literal['ok', 'mismatch', 'unknown']
    findings: list[FindingModel]


class SessionRequest(Model):
    model: str
    effort: str
    permissions: Literal['bypass', 'normal']
    argv: list[str]
    forwarded: list[str]


class ReviewerRow(Model):
    name: str
    # As configured in the working config, whatever their type.
    cli: JsonValue
    model: JsonValue
    effort: JsonValue


class GsdContext(Model):
    source: str | None
    workstream: str
    loader_differences: list[str]


class PreviewData(Model):
    project: str
    blueprint: str
    runtime: Literal['claude', 'codex']
    complete: bool
    session: SessionRequest
    reviewers: list[ReviewerRow]
    installation: CheckEntry
    agents: list[AgentRow]
    gsd_context: GsdContext | None
    pending_capture: list[str]
    diagnostics: list[str]
    config: dict[str, Any] | None


class LaunchSummary(Model):
    """A launch record without its embedded config, policy and gsd_defaults."""
    time: str | None
    blueprint: str | None = None
    profile: str | None
    workflow: str | None
    level: str | None
    session_model: str | None
    session_effort: str | None
    forwarded_args: list[str]


class RunModel(Model):
    runtime: Literal['claude', 'codex']
    run_id: str
    kind: Literal['session', 'agent', 'reviewer']
    cwd: str
    start: str  # UTC, YYYY-MM-DDTHH:MM:SSZ
    end: str
    model: str | None
    effort: str | None
    effort_varied: bool
    advisor: str | None
    agent_type: str | None
    requested_model: str | None
    requested_effort: str | None
    resumed: bool
    cleared: bool
    marks: list[str]
    mismatch: bool
    launch: LaunchSummary | None
    children: list['RunModel']


class SessionsData(Model):
    project: str
    resolver_available: bool
    sessions: list[RunModel]
    older: list[RunModel]


class StatusEnvelope(Envelope[StatusData]):
    command: Literal['status'] = 'status'


class CheckEnvelope(Envelope[CheckData]):
    command: Literal['check'] = 'check'


class PolicyEnvelope(Envelope[PolicyData]):
    command: Literal['policy'] = 'policy'


class PreviewEnvelope(Envelope[PreviewData]):
    command: Literal['preview'] = 'preview'


class SessionsEnvelope(Envelope[SessionsData]):
    command: Literal['sessions'] = 'sessions'


# Schema name -> envelope model; later tasks register their commands here.
SCHEMAS: dict[str, type[BaseModel]] = {'error': ErrorEnvelope, 'status': StatusEnvelope, 'check': CheckEnvelope,
                                        'policy': PolicyEnvelope, 'preview': PreviewEnvelope, 'sessions': SessionsEnvelope,
                                        'policy-file': PolicyFile}


def dump(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode='json'), indent=2, ensure_ascii=True, allow_nan=False) + '\n'


def failure(command: str | None, kind: str, message: str) -> BaseModel:
    error = ErrorInfo(kind=kind, message=message)
    if command is None:
        return ErrorEnvelope(ok=False, error=error)
    return SCHEMAS[command](ok=False, error=error)  # Every JSON command has an envelope schema.
