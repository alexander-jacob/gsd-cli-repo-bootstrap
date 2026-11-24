"""Evidence-based comparisons and plain-text reporting for configuration previews."""
import json
import re
from pathlib import Path
from typing import NamedTuple

import click

from . import config


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
             session_effort: str, forwarded: bool, aliases: dict, *, project_definition=None) -> list[Finding]:
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
    if project_definition and project_definition['effort'] is not None:
        # The installed resolver inspects upstream frontmatter. A different
        # upstream default is expected when the launcher prepares a local copy.
        if result.get('effort_effective_source') not in ('frontmatter', 'frontmatter-absent'):
            add('installed_effort_unknown', 'unknown', 'installed Claude effort unknown; resolver supplied no file evidence')
        elif result.get('effort_effective') != project_definition['effort']:
            add('installed_effort_differs', 'note',
                f"installed effort {display(result.get('effort_effective'))}, "
                f"prospective project effort {display(project_definition['effort'])}")
        add('project_effort_unverified', 'unknown', 'Claude runtime effort for the project definition is unobserved')
    elif runtime == 'claude':
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
        source = f'models.{phase}={display(tier)}' if tier is not None else 'GSD default (no explicit model expectation)'
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


def agent_rows(runtime: str, resolved: dict, data: dict, inspection: dict, project_definitions: dict,
               forwarded: list[str]) -> list[dict]:
    agents = resolved['agents']
    catalog = inspection['catalog']
    results = inspection['agents']
    names = agents.keys() | catalog.keys() | results.keys() | project_definitions.keys()
    for key in (('model_overrides',), ('effort', 'agent_overrides')):
        configured = value_at(data, *key)
        if isinstance(configured, dict):
            names.update(configured)
    rows = []
    for agent in names:
        settings = agents.get(agent, {})
        meta = catalog.get(agent, {})
        phase = settings.get('phase') or meta.get('phaseType') or 'unknown'
        covered = settings.get('model') is not None
        if covered:
            model, effort = settings['model'], settings['effort']
            model_source, effort_source = settings['model_source'], settings['effort_source']
        else:
            model, effort, model_source, effort_source = expectations(data, agent, meta, runtime)
        definition = project_definitions.get(agent)
        result = results.get(agent)
        found = findings(model, effort, result or {}, runtime, resolved['effort'], bool(forwarded),
                         inspection.get('aliases', {}), project_definition=definition)
        rows.append(dict(agent=agent, phase=phase, covered=covered, project_definition=definition,
                         expected=dict(model=model, effort=effort, model_source=model_source, effort_source=effort_source),
                         resolved=result, check=CHECKS[status(found)], findings=[f._asdict() for f in found]))
    return sorted(rows, key=lambda row: (row['phase'], row['agent']))


def report(root: Path, runtime: str, blueprint: str, resolved: dict, data: dict | None, captured: list[str],
           argv: list[str], forwarded: list[str], inspection: dict, project_definitions: dict, *, secure: bool) -> dict:
    """Build the common text and JSON report from the preparation and the installed query."""
    rows = agent_rows(runtime, resolved, data or {}, inspection, project_definitions, forwarded)
    review = resolved['review']
    context = inspection['context']
    gsd_context = (dict(source=context['source'], workstream=inspection.get('workstream', ''),
                        loader_differences=config.changed_paths(data, context['config'])) if context else None)
    reviewers = []
    for name in review['default_reviewers']:
        entry = review['reviewer_instances'][name]
        reviewers.append(dict(name=name, cli=entry['cli'], model=entry['model'], effort=review['effort'][entry['cli']]))
    return dict(project=str(root.resolve()), runtime=runtime, blueprint=blueprint, complete=inspection['complete'],
                session=dict(model=resolved['model'], effort=resolved['effort'], permissions='normal' if secure else 'bypass',
                             argv=argv, forwarded=forwarded),
                installation=inspection['installation'], reviewers=reviewers, agents=rows,
                gsd_context=gsd_context, pending_capture=captured, diagnostics=inspection['diagnostics'], config=data)


def render(report: dict, details: bool, color: bool) -> str:
    state = 'COMPLETE' if report['complete'] else 'INCOMPLETE'
    heading = f"Configuration preview: {report['runtime']}/{display(report['blueprint'])} [{state}]"
    session = report['session']
    lines = [click.style(heading, fg='cyan', bold=True) if color else heading,
             'Project: ' + display(report['project']),
             f"Session request: {display(session['model'])} | effort {display(session['effort'])} | ? actual run unknown"]
    if details:
        install = report['installation']
        lines.append(f"GSD: {display(install['installed'])} | minimum {display(install['minimum'])} | {display(install['directory'])}")
        for label, path in [('Policy', config.POLICY), ('Defaults', config.DEFAULT), ('Working', config.WORKING)]:
            lines.append(f"{label}: {display(str(Path(report['project']) / path))}")
        lines.extend(['Child argv: ' + display(session['argv']), 'Permissions: ' + session['permissions']])
    if session['forwarded']:
        lines.append('Forwarded options may override launcher requests: ' + display(session['forwarded']))
    lines.extend(['', 'Agent | Coverage | Model/effort source | Requested model → GSD model | Requested effort → GSD effort | Check'])
    last_phase = None
    for row in report['agents']:
        phase = row['phase']
        if phase != last_phase:
            lines.append(f'[{display(phase)}]')
            last_phase = phase
        result = row['resolved'] or {}
        expected = row['expected']
        mark = {'ok': '✓', 'mismatch': '✗', 'unknown': '?'}[row['check']]
        if color:
            mark = click.style(mark, fg={'✓': 'green', '✗': 'red', '?': 'bright_black'}[mark], bold=True)
        coverage = 'covered' if row['covered'] else 'uncovered'
        sources = 'unmanaged'
        if row['covered']:
            sources = '/'.join(expected[field].rsplit('.', 3)[1].removesuffix('s')
                               for field in ('model_source', 'effort_source'))
        lines.append(f"{display(row['agent'])} | {coverage} | {sources} | "
                     f"{display(expected['model'])} → {display(result.get('model'))} | "
                     f"{display(expected['effort'])} → {display(result.get('effort'))} | {mark}")
        definition = row['project_definition']
        if definition:
            lines.append(f"  Project definition: {definition['action']} {display(definition['destination'])}"
                         + (f" | {display(definition['model'])}/{display(definition['effort'])}" if definition['model'] else ''))
            if definition['source']:
                lines.append(f"  Installed source: {display(definition['source'])}")
        if report['runtime'] == 'claude' and result:
            source = result['effort_effective_source']
            installed = result['effort_effective'] if source in ('frontmatter', 'frontmatter-absent') else None
            lines.append(f"  Installed frontmatter effort: {display(installed)} | resolver evidence: {display(source)}")
        if details:
            lines.append(f"  Inputs: {display(expected['model_source'])} | {display(expected['effort_source'])}")
            if result:
                lines.extend([f"  Rendered effort: {display(result.get('effort_rendered'))}"
                              f" | parameter={display(result.get('effort_param'))} | propagation={display(result.get('effort_propagation'))}",
                              f"  Host effort argv: {display(result.get('effort_argv'))}"
                              f" | fast mode={display(result.get('fast_mode'))} | supported={display(result.get('fast_mode_supported'))}"])
            lines.extend('  ' + finding['message'] for finding in row['findings'])
    context = report['gsd_context']
    if details and context:
        lines.append('GSD config source: ' + display(context['source']))
        if context['workstream']:
            lines.append('GSD_WORKSTREAM: ' + display(context['workstream']))
        lines.append('GSD loader differences (defaults/normalization/overlays): ' + display(context['loader_differences']))
    lines.extend(['', 'External reviewers (configured values, execution unknown)', 'Reviewer | Adapter | Model | Effort'])
    for row in report['reviewers']:
        lines.append(' | '.join(display(row[key]) for key in ('name', 'cli', 'model', 'effort')))
    lines.append('✓ matches resolver evidence | ✗ mismatch | ? insufficient evidence')
    if report['pending_capture']:
        lines.append('Pending persistent capture (not saved): ' + display(report['pending_capture']))
    for diagnostic in report['diagnostics']:
        lines.append('Diagnostic: ' + display(diagnostic))
    if details and report['config'] is not None:
        lines.extend(['', 'Launcher effective configuration:',
                      colorize_json(json.dumps(report['config'], indent=2, ensure_ascii=True, allow_nan=False), color)])
    elif not details:
        lines.append('Use --config --details for resolver inputs, findings, and effective JSON.')
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
