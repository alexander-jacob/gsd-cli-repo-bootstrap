"""Small installed-GSD double; exercises the real Node bridge without AI CLIs."""
import json
from pathlib import Path
from test_versions import install_gsd


def install_resolver(directory: Path, model='fixture-model') -> Path:
    install_gsd(directory)
    core = directory / 'gsd-core'
    lib = core / 'bin/lib'
    lib.mkdir(parents=True, exist_ok=True)
    shared = core / 'bin/shared'
    shared.mkdir(parents=True, exist_ok=True)
    (shared / 'model-catalog.json').write_text(json.dumps({'agents': {
        'gsd-planner': {'phaseType': 'planning', 'routingTier': 'heavy'},
        'gsd-executor': {'phaseType': 'execution', 'routingTier': 'heavy'},
        'gsd-verifier': {'phaseType': 'verification', 'routingTier': 'heavy'},
    }}))
    # Invoking the public CLI would mutate the installation. The bridge must
    # require the command module directly instead.
    (core / 'bin/gsd-tools.cjs').write_text("require('fs').writeFileSync(__dirname + '/BOOTSTRAP-RAN', 'bad');")
    (lib / 'config-loader.cjs').write_text(r'''
const fs = require('fs'), path = require('path');
exports.loadConfigResolved = function(cwd, opts) {
  const file = path.join(cwd, '.planning/config.json');
  let data = JSON.parse(fs.readFileSync(file));
  let source = 'root';
  if (process.env.GSD_WORKSTREAM) {
    const w = path.join(cwd, '.planning/workstreams', process.env.GSD_WORKSTREAM, 'config.json');
    if (fs.existsSync(w)) { data = {...data, ...JSON.parse(fs.readFileSync(w))}; source = 'workstream'; }
  }
  if (!opts || opts.persist !== false) fs.writeFileSync(file, JSON.stringify(data));
  return {config: {...data, runtime: process.env.GSD_RUNTIME}, source, degraded: false};
};
''')
    (lib / 'commands.cjs').write_text(r'''
const fs = require('fs');
const loader = require('./config-loader.cjs');
exports.cmdResolveExecution = function(cwd, agent, raw, opts) {
  if (raw !== false || opts.host !== process.env.GSD_RUNTIME) throw Error('incorrect query contract');
  const c = loader.loadConfigResolved(cwd).config;
  if (c.fail_agent === agent) throw Error('fixture query failed');
  if (c.malformed_result) { fs.writeSync(1, '{}'); return; }
  const effort = c.effort?.agent_overrides?.[agent] || 'medium';
  fs.writeSync(1, JSON.stringify({
    model: c.model_overrides?.[agent] || MODEL,
    profile: 'balanced', effort, effort_rendered: effort,
    effort_param: effort === 'inherit' ? null : 'reasoning_effort',
    effort_propagation: effort === 'inherit' ? null : 'spawn',
    effort_requested: effort, effort_clamped: false, effort_clamp_reason: null,
    effort_effective: effort, effort_effective_source: 'resolved',
    fast_mode: false, fast_mode_supported: false,
    host: opts.host, effort_surface: 'spawn', effort_argv: [],
    effort_argv_string: '', effort_argv_value: effort
  }));
};
'''.replace('MODEL', json.dumps(model)))
    return core
