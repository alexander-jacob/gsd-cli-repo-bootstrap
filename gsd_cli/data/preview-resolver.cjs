'use strict';
// Use installed GSD exports, without the public CLI's self-healing bootstrap.
// All cwd-relative writes (legacy config normalization) land in the disposable
// project. Original command JSON is framed directly, not reinterpreted here.
const fs = require('node:fs');
const path = require('node:path');
const request = JSON.parse(fs.readFileSync(0, 'utf8'));
const lib = path.join(request.installation, 'bin/lib');
const loader = require(path.join(lib, 'config-loader.cjs'));
const commands = require(path.join(lib, 'commands.cjs'));
if (typeof loader.loadConfigResolved !== 'function' || typeof commands.cmdResolveExecution !== 'function') {
  throw Error('Installed GSD lacks the required configuration/execution query exports');
}
const context = loader.loadConfigResolved(process.cwd(), {persist: false});
const names = new Set(request.agents);
// Keep raw override names even if GSD filters unknown keys from loaded config.
const addOverrides = c => {
  for (const name of Object.keys(c.model_overrides || {})) names.add(name);
  for (const name of Object.keys(c.effort?.agent_overrides || {})) names.add(name);
};
addOverrides(JSON.parse(fs.readFileSync('.planning/config.json', 'utf8')));
if (process.env.GSD_WORKSTREAM?.trim()) {
  const p = path.join('.planning/workstreams', process.env.GSD_WORKSTREAM.trim(), 'config.json');
  if (fs.existsSync(p)) addOverrides(JSON.parse(fs.readFileSync(p, 'utf8')));
}
addOverrides(context.config);
fs.writeSync(1, '{"context":' + JSON.stringify(context) + ',"rows":[');
let first = true;
for (const agent of [...names].sort()) {
  if (!first) fs.writeSync(1, ',');
  first = false;
  fs.writeSync(1, '{"agent":' + JSON.stringify(agent) + ',"result":');
  try {
    commands.cmdResolveExecution(process.cwd(), agent, false, {host: request.runtime});
    fs.writeSync(1, '}');
  } catch (error) {
    fs.writeSync(1, 'null,"error":' + JSON.stringify(String(error.message || error)) + '}');
  }
}
fs.writeSync(1, ']}');
