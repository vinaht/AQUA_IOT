// Run with: node test_monitor.js. Uses only built-in Node modules.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor() {
    this.children = []; this.textContent = ''; this.className = ''; this.checked = false;
    this.attributes = {};
    this.classList = {
      add: name => { this.className = name; },
      remove: name => { if (this.className === name) this.className = ''; }
    };
  }
  append(node) { this.children.push(node); }
  insertRow() { const row = new Element(); this.append(row); return row; }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this.attributes[key] = value; }
}
const ids = Object.fromEntries(['sound','status','cards','evaluation','data','events','csv','forecasts']
  .map(id => [id, new Element()]));
const calls = [], timers = [];
let fail = false, tones = 0;
const device = {
  device_id: 'esp32', state: 'ready', current_ph: 7, current_temperature_c: 30, tds_ppm: 400,
  thresholds: {ph_low:6.5, ph_high:7.5, temp_low:25, temp_high:35, tds_high:500},
  forecast: {ph:7, temperature_c:30, tds_ppm:400, target_utc:'2026-11-26T00:30:00Z'},
  channels: {ph:{state:'ready'}, temperature_c:{state:'ready'}, tds_ppm:{state:'ready'}}, warnings: []
};
const response = {
  devices: [device], recent_events: [],
  evaluation: {channels: Object.fromEntries(['ph','temperature_c','tds_ppm']
    .map(field => [field, {matched_count:0, mae:null}]))}
};
class AudioContext {
  constructor() { this.state = 'suspended'; this.currentTime = 0; this.destination = {}; }
  async resume() { this.state = 'running'; }
  createOscillator() {
    return {frequency:{}, connect(){}, disconnect(){}, start(){tones++;}, stop(){}};
  }
  createGain() { return {gain:{}, connect(){}, disconnect(){}}; }
}
const context = vm.createContext({
  document: {getElementById: id => {
    assert.ok(ids[id], 'Unexpected UI dependency: '+id); return ids[id];
  }, createElement: () => new Element()},
  AudioContext, AbortController,
  setTimeout: (fn, delay) => { timers.push({fn, delay}); return timers.length; }, clearTimeout(){},
  fetch: async (url, options) => {
    calls.push({url, options});
    if (fail) throw Error('offline');
    return {ok:true, json:async () => url==='/api/latest'?{latest:{ph:device.current_ph}}:response};
  }
});
const html = fs.readFileSync(path.join(__dirname, 'monitor.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
vm.runInContext(script, context);
context.fixture = device;
const run = code => vm.runInContext(code, context);
const text = node => node.textContent + node.children.map(text).join(' ');
const settle = () => new Promise(resolve => setImmediate(resolve));

async function main() {
  await settle();
  assert.deepEqual(calls.map(c=>c.url), ['/api/latest','/api/forecast']);
  assert.ok(calls.every(c=>!c.options.headers), 'Read requests must not send an API key');
  assert.ok(timers.some(t=>t.delay===3000), 'Refresh must be scheduled automatically');
  assert.equal(ids.sound.checked, false);
  assert.equal(ids.cards.children.length, 1);
  assert.ok(text(ids.cards).includes('7.00'));
  assert.equal(tones, 0);
  ids.sound.checked = true; await ids.sound.onchange();
  assert.equal(tones, 0, 'Enabling sound must not replay existing alarms');

  device.current_ph = 9.5; device.current_temperature_c = 40;
  device.forecast.ph = 9.5;
  await run('refresh()');
  assert.equal(tones, 1, 'Simultaneous threshold crossings produce one short beep');
  const table = ids.cards.children[0].children.find(n=>n.children.length===4);
  assert.equal(table.children[1].children[1].className, 'signal-alert');
  assert.equal(table.children[1].children[2].className, 'signal-alert');
  assert.equal(table.children[3].children[1].className, 'signal-ok');
  assert.ok(text(ids.cards).includes('9.50') && text(ids.cards).includes('40.00 °C'));
  assert.ok(!text(ids.cards).includes('ngoài khoảng'));
  await run('refresh()'); assert.equal(tones, 1, 'Persistent alerts must stay quiet');
  device.current_ph = 7;
  await run('refresh()'); assert.equal(tones, 1, 'Clearing one alert must not retrigger the others');
  device.current_ph = 9.5;
  await run('refresh()'); assert.equal(tones, 2, 'Returning outside must beep again');
  device.forecast.tds_ppm = 600;
  await run('refresh()'); assert.equal(tones, 3, 'Forecast-only crossing must beep');
  device.state = 'stale';
  await run('refresh()'); assert.equal(tones, 3);
  assert.equal(run("signal(fixture,'ph',fixture.current_ph)"), 'neutral');
  device.state = 'ready';
  await run('refresh()'); assert.equal(tones, 3, 'Stale data recovery must not replay the same alert');
  const previousCards = ids.cards.children;
  fail = true; await run('refresh()');
  assert.equal(ids.cards.children, previousCards, 'Keep previous values during a connection failure');
  assert.equal(ids.cards.className, 'disconnected');
  fail = false; await run('refresh()');
  assert.equal(ids.cards.className, ''); assert.equal(tones, 3);
  device.current_ph = null; device.channels.ph.state = 'sensor';
  await run('refresh()'); assert.equal(tones, 3);
  assert.ok(text(ids.cards).includes('—'));
  device.current_ph = 9.5; device.channels.ph.state = 'ready';
  await run('refresh()'); assert.equal(tones, 3);
  for(const [field,value] of [['ph',6.5],['ph',7.5],['temperature_c',25],['temperature_c',35],['tds_ppm',500]]) {
    context.value = value; context.field = field;
    assert.equal(run('signal(fixture,field,value)'), 'ok', 'Threshold boundaries are inclusive');
  }
  device.thresholds.tds_high = null;
  assert.equal(run("signal(fixture,'tds_ppm',800)"), 'neutral');
  device.thresholds.tds_high = 500;
  ids.sound.checked = false; device.tds_ppm = 800;
  await run('refresh()'); assert.equal(tones, 3);
  ids.sound.checked = true; await ids.sound.onchange();
  await run('refresh()'); assert.equal(tones, 3, 'Re-enabling sound must not replay old alerts');
  console.log('PASS: automatic polling, no browser key, displayed readings, per-cell signals, threshold boundaries, sound transitions, mute and connection recovery.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
