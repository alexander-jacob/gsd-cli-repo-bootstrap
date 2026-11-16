"""Evidence-based comparisons and plain-text reporting for configuration previews."""
import json
import re
from pathlib import Path
from typing import NamedTuple

import click

from . import config, models


def display(value) -> str:
    """Keep untrusted model names, paths and argv from controlling the terminal."""
    if value is None:
        return 'unknown'
    encoded = json.dumps(value, ensure_ascii=True)
    return encoded[1:-1] if isinstance(value, str) else encoded


def value_at(data: dict, *path):
    value = config.get_path(data, path)
    return None if value is config.MISSING else value


class Finding(NamedTuple):
    code: str
    severity: str  # 'mismatch' | 'unknown' | 'note'
    message: str


SEVERITY_ORDER = ('mismatch', 'unknown', 'note')
CHECKS = {'OK': 'ok', 'NOT OK': 'mismatch', 'UNKNOWN': 'unknown'}


def findings(model: str | None, effort: str | None, result: dict, runtime: str,
             session_effort: str, forwarded: bool, aliases: dict) -> list[Finding]:
    """Coded comparison findings, ordered mismatches, unknowns, then notes."""
    found = []

    def add(code, severity, message):
        found.append(Finding(code, severity, message))

    actual_model = result.get('model')
    if model is None or actual_model is None:
        add('model_unknown', 'unknown', 'model expectation or resolution unknown')
    elif model != actual_model:
        if runtime == 'claude' and aliases.get(actual_model) == model:
            add('alias_equivalent', 'note', 'model alias equivalence confirmed by installed GSD catalog')
        else:
            add('model_mismatch', 'mismatch', f'model expected {display(model)}, resolved {display(actual_model)}')
    if effort is None or result.get('effort') is None:
        add('effort_unknown', 'unknown', 'effort expectation or resolution unknown')
    elif effort != result['effort']:
        add('effort_mismatch', 'mismatch', f'effort expected {display(effort)}, resolved {display(result["effort"])}')
    if result.get('effort_clamped'):
        add('effort_clamped', 'mismatch', 'effort clamped to ' + display(result.get('effort_rendered'))
            + ': ' + display(result.get('effort_clamp_reason')))
    if runtime == 'claude':
        source = result.get('effort_effective_source')
        observed = result.get('effort_effective')
        if source == 'frontmatter-absent' or (source == 'frontmatter' and observed == 'inherit'):
            add('inherits_session_effort', 'note', 'installed effort inherits the session')
            if forwarded:
                observed = None
                add('forwarded_may_override', 'unknown', 'forwarded options may override inherited session effort')
            else:
                observed = session_effort
        elif source != 'frontmatter':
            observed = None
            add('installed_effort_unknown', 'unknown',
                'installed Claude effort unknown; resolver supplied no file evidence')
        expected_installed = effort
        if effort == 'inherit':
            expected_installed = None if forwarded else session_effort
            if forwarded:
                add('inherit_depends_on_forwarded', 'unknown',
                    'requested inherited effort depends on forwarded session options')
        if expected_installed is not None and observed is not None and expected_installed != observed:
            add('installed_effort_mismatch', 'mismatch',
                f'installed effort expected {display(expected_installed)}, found {display(observed)}')
    elif not result.get('effort_propagation') or result.get('effort_rendered') is None:
        add('propagation_unknown', 'unknown', 'runtime effort propagation unsupported or unknown')
    if result.get('unknown_agent'):
        add('unregistered_agent', 'unknown', 'agent is not registered in the installed GSD catalog')
    return sorted(found, key=lambda f: SEVERITY_ORDER.index(f.severity))


def status(found: list[Finding]) -> str:
    severities = {f.severity for f in found}
    return 'NOT OK' if 'mismatch' in severities else 'UNKNOWN' if 'unknown' in severities else 'OK'


def compare(model: str | None, effort: str | None, result: dict, runtime: str,
            session_effort: str, forwarded: bool, aliases: dict) -> tuple[str, list[str]]:
    found = findings(model, effort, result, runtime, session_effort, forwarded, aliases)
    return status(found), [f.message for f in found]


def expectations(data: dict, agent: str, meta: dict, runtime: str) -> tuple:
    """Describe explicit launcher inputs, not GSD's fallback resolver cascade."""
    model = value_at(data, 'model_overrides', agent)
    source = f'model_overrides.{agent}'
    if model is None:
        phase = meta.get('phaseType')
        tier = value_at(data, 'models', phase) if isinstance(phase, str) else None
        entry = value_at(data, 'model_policy', 'runtime_tiers', runtime, tier) if isinstance(tier, str) else None
        model = entry.get('model') if isinstance(entry, dict) else entry
        if tier == 'inherit':
            model = 'inherit'
        source = f'models.{phase}={display(tier)}'
    effort = value_at(data, 'effort', 'agent_overrides', agent)
    effort_source = f'effort.agent_overrides.{agent}'
    if effort is None:
        # A configured routing-tier default is an explicit expectation; an
        # absent value is left to GSD. effort.default alone does not override
        # GSD's built-in routing-tier defaults and is deliberately not guessed.
        tier = meta.get('routingTier')
        effort = value_at(data, 'effort', 'routing_tier_defaults', tier) if isinstance(tier, str) else None
        effort_source = f'effort.routing_tier_defaults.{tier}' if effort is not None else 'GSD default (no explicit effort expectation)'
    return model, effort, source, effort_source


def agent_names(data: dict, inspection: dict) -> list[str]:
    """Every registered or configured agent, sorted by phase and then name."""
    catalog = inspection['catalog']
    names = set(catalog) | set(inspection['agents'])
    for key in (('model_overrides',), ('effort', 'agent_overrides')):
        configured = value_at(data, *key)
        if isinstance(configured, dict):
            names.update(configured)
    return sorted(names, key=lambda a: (str(catalog.get(a, {}).get('phaseType', 'unknown')), a))


def reviewer_rows(data: dict, resolved: dict) -> list[tuple]:
    """(name, adapter, model, effort) for each selected reviewer, as configured."""
    rows = []
    for name in resolved['reviewers']:
        reviewer = value_at(data, 'review', 'reviewer_instances', name) or {}
        adapter = reviewer.get('cli')
        effort = value_at(data, 'review', 'effort', adapter) if isinstance(adapter, str) else None
        rows.append((name, adapter, reviewer.get('model'), effort))
    return rows


def workflow_phases(policy: dict, workflow: str) -> set:
    return set(policy['workflows'][workflow]['tasks']) | set(policy['workflows'][workflow]['task_levels'])


def report(root: Path, workflow: str, runtime: str, level: str, policy: dict,
           resolved: dict, data: dict, captured: list[str], argv: list[str],
           forwarded: list[str], inspection: dict) -> models.PreviewData:
    """The configuration preview as a machine-readable payload; same evidence as render."""
    catalog, results = inspection['catalog'], inspection['agents']
    phases = workflow_phases(policy, workflow)
    rows = []
    for agent in agent_names(data, inspection):
        meta = catalog.get(agent, {})
        phase = meta.get('phaseType', 'unknown')
        model, effort, model_source, effort_source = expectations(data, agent, meta, runtime)
        result = results.get(agent)
        found = findings(model, effort, result or {}, runtime, resolved['effort'], bool(forwarded),
                         inspection.get('aliases', {}))
        rows.append(models.AgentRow(
            agent=agent, phase=str(phase), in_workflow=phase in phases,
            expected=models.Expected(model=model, effort=effort, model_source=model_source,
                                     effort_source=effort_source),
            resolved=result, check=CHECKS[status(found)],
            findings=[models.FindingModel(**f._asdict()) for f in found]))
    context = inspection.get('context', {})
    gsd_context = None
    if context:
        gsd_context = models.GsdContext(source=context.get('source'), workstream=inspection.get('workstream', ''),
                                        loader_differences=config.changed_paths(data, context.get('config', {})))
    return models.PreviewData(
        project=str(root.resolve()), workflow=workflow, runtime=runtime, level=level,
        complete=inspection['complete'],
        session=models.SessionRequest(
            model=resolved['model'], effort=resolved['effort'],
            permissions='bypass' if any(a.startswith('--dangerously-') for a in argv) else 'normal',
            argv=argv, forwarded=forwarded),
        reviewers=[models.ReviewerRow(name=n, cli=c, model=m, effort=e) for n, c, m, e in reviewer_rows(data, resolved)],
        installation=models.CheckEntry(**inspection['installation']),
        agents=rows, gsd_context=gsd_context, pending_capture=captured,
        diagnostics=inspection['diagnostics'], config=data)


def render(root: Path, workflow: str, runtime: str, level: str, policy: dict,
           resolved: dict, data: dict, captured: list[str], argv: list[str],
           forwarded: list[str], inspection: dict) -> str:
    state = 'COMPLETE' if inspection['complete'] else 'INCOMPLETE'
    install = inspection['installation']
    lines = [f'Configuration preview: {display(workflow)}/{runtime}/{level} [{state}]',
             f'Project: {display(str(root))}',
             f'GSD: {display(install["installed"])}; minimum {display(install["minimum"])}; {display(install["directory"])}']
    for label, path in [('Policy', config.POLICY), ('Defaults', config.DEFAULT), ('Working', config.WORKING)]:
        lines.append(f'{label}: {display(str(root / path))}')
    lines += ['', 'Session (launcher requests; no AI session was run)',
              'Model | Effort | Check',
              f'{display(resolved["model"])} | {display(resolved["effort"])} | UNKNOWN',
              '  Configuration only; no independent session execution evidence.',
              'Child argv: ' + json.dumps(argv, ensure_ascii=True),
              'Permissions: ' + ('bypass requested' if any(a.startswith('--dangerously-') for a in argv) else 'normal requested')]
    if forwarded:
        lines.append('Forwarded arguments may override launcher requests; child precedence is not predicted.')
    lines += ['', 'Phase model settings: ' + display(data.get('models', {})),
              'GSD agents (all registered/configured roles; this is not a workflow execution trace)',
              'Agent | Requested model | GSD model | Requested effort | GSD effort | Installed effort | Check']
    catalog, agents = inspection['catalog'], inspection['agents']
    phase_before = None
    for agent in agent_names(data, inspection):
        meta = catalog.get(agent, {})
        phase = meta.get('phaseType', 'unknown')
        if phase != phase_before:
            lines.append(f'[{display(phase)}]')
            phase_before = phase
        model, effort, model_source, effort_source = expectations(data, agent, meta, runtime)
        result = agents.get(agent, {})
        check, notes = compare(model, effort, result, runtime, resolved['effort'], bool(forwarded), inspection.get('aliases', {}))
        installed = result.get('effort_effective') if result.get('effort_effective_source') in ('frontmatter', 'frontmatter-absent') else None
        lines.append(' | '.join(display(v) for v in (agent, model, result.get('model'), effort, result.get('effort'), installed, check)))
        lines.append(f'  Inputs: {display(model_source)}; {display(effort_source)}')
        if result:
            lines.append('  Rendered effort: ' + display(result.get('effort_rendered'))
                         + '; parameter=' + display(result.get('effort_param'))
                         + '; propagation=' + display(result.get('effort_propagation'))
                         + '; evidence=' + display(result.get('effort_effective_source')))
            lines.append('  Host effort argv: ' + display(result.get('effort_argv'))
                         + '; fast mode=' + display(result.get('fast_mode'))
                         + '; fast mode supported=' + display(result.get('fast_mode_supported')))
        if notes:
            # Notes already escape values at construction; do not double escape.
            lines.append('  ' + '; '.join(notes))
    context = inspection.get('context', {})
    if context:
        lines.append('GSD config source: ' + display(context.get('source')))
        if inspection.get('workstream'):
            lines.append('GSD_WORKSTREAM: ' + display(inspection['workstream']))
        loaded = context.get('config', {})
        differences = config.changed_paths(data, loaded)
        lines.append('GSD loader differences (defaults/normalization/overlays): ' + display(differences))
    lines += ['', 'External reviewers (configured values; provider execution is unknown)',
              'Reviewer | Adapter | Model | Effort | Check']
    for row in reviewer_rows(data, resolved):
        lines.append(' | '.join(display(v) for v in (*row, 'UNKNOWN')))
    lines += ['', 'Pending persistent capture (not saved): ' + display(captured),
              'Checks: OK=matches evidence; NOT OK=known mismatch; UNKNOWN=insufficient evidence.']
    for diagnostic in inspection['diagnostics']:
        lines.append('Diagnostic: ' + display(diagnostic))
    lines += ['', 'Launcher effective configuration:', json.dumps(data, indent=2, ensure_ascii=True, allow_nan=False)]
    return '\n'.join(lines) + '\n'


def colorize_json(value: str, enabled: bool) -> str:
    if not enabled:
        return value
    token = re.compile(r'"(?:\\.|[^"\\])*"(?=\s*:)|"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\b(?:true|false|null)\b')

    def style(match: re.Match) -> str:
        word = match.group()
        if word.startswith('"'):
            color = 'cyan' if value[match.end():].lstrip().startswith(':') else 'green'
        elif word in ('true', 'false', 'null'):
            color = 'magenta'
        else:
            color = 'yellow'
        return click.style(word, fg=color)

    return token.sub(style, value)


def use_color(stream, environ: dict) -> bool:
    return stream.isatty() and 'NO_COLOR' not in environ


def render_compact(root: Path, workflow: str, runtime: str, level: str, policy: dict,
                   resolved: dict, data: dict, captured: list[str], argv: list[str],
                   forwarded: list[str], inspection: dict, color: bool = False) -> str:
    state = 'COMPLETE' if inspection['complete'] else 'INCOMPLETE'
    heading = f'Configuration preview: {display(workflow)}/{display(runtime)}/{display(level)} [{state}]'
    lines = [click.style(heading, fg='cyan', bold=True) if color else heading,
             f'Project: {display(str(root))}',
             f'Session request: {display(resolved["model"])} | effort {display(resolved["effort"])} | ? actual run unknown',
             'Agents this workflow may use (configured → GSD resolved; no session was run)']
    phases = workflow_phases(policy, workflow)
    catalog, agents = inspection['catalog'], inspection['agents']
    configured = set()
    for key in (('model_overrides',), ('effort', 'agent_overrides')):
        values = value_at(data, *key)
        if isinstance(values, dict):
            configured.update(values)
    names = set(catalog) | set(agents) | configured
    rows = []
    for agent in names:
        meta = catalog.get(agent, {})
        phase = meta.get('phaseType', 'unknown')
        if phase not in phases:
            continue
        model, effort, _, _ = expectations(data, agent, meta, runtime)
        result = agents.get(agent, {})
        check, _ = compare(model, effort, result, runtime, resolved['effort'], bool(forwarded), inspection.get('aliases', {}))
        mark = {'OK': '✓', 'NOT OK': '✗', 'UNKNOWN': '?'}[check]
        rows.append((phase, agent, display(model), display(result.get('model')),
                     display(effort) + ' → ' + display(result.get('effort')), mark))
    widths = [max(len(str(row[i])) for row in rows) if rows else 0 for i in range(1, 5)]
    widths = [max(widths[i], len(label)) for i, label in enumerate(('Agent', 'Configured', 'GSD sees', 'Effort'))]
    lines.append(' | '.join(label.ljust(width) for label, width in zip(
        ('Agent', 'Configured', 'GSD sees', 'Effort'), widths)) + ' | Check')
    last_phase = None
    for phase, agent, model, gsd_model, effort, mark in sorted(rows):
        if phase != last_phase:
            phase_label = f'[{display(phase)}]'
            lines.append(click.style(phase_label, fg='cyan') if color else phase_label)
            last_phase = phase
        if color:
            mark = click.style(mark, fg={'✓': 'green', '✗': 'red', '?': 'bright_black'}[mark], bold=True)
        lines.append(' | '.join(str(cell).ljust(width) for cell, width in zip(
            (display(agent), model, gsd_model, effort), widths)) + ' | ' + mark)
    lines.extend(['', 'Reviewers (configured; execution unknown): ' + ', '.join(display(v) for v in resolved['reviewers']),
                  '✓ matches | ✗ mismatch | ? insufficient evidence',
                  'Use --config --details for resolver inputs, diagnostics, and effective JSON.'])
    if forwarded:
        lines.append('Forwarded options may override launcher requests: ' + display(forwarded))
    unclassified = configured - set(catalog)
    if unclassified:
        lines.append(f'{len(unclassified)} configured agents have no phase metadata; see --details.')
    if captured:
        lines.append('Pending persistent capture (not saved): ' + display(captured))
    for diagnostic in inspection['diagnostics']:
        lines.append('Diagnostic: ' + display(diagnostic))
    return '\n'.join(lines) + '\n'
