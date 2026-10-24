const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = name => fs.readFileSync(path.join(__dirname, '..', 'static', name), 'utf8');
const context = vm.createContext({});
vm.runInContext(read('hiyori-engine.js') + '\n' + read('hiyori-config.js') + '\nglobalThis.config = AFFECTION_CONFIG;', context);
const {evaluate, timeline} = context.AffectionEngine;
const {config} = context;
const state = (t, options) => evaluate(config, 68, 72, t, options);

assert.equal(timeline(config, 68, 72).eventEnd, 6500);
assert.equal(timeline(config, 68, 72).duration, 6500);
for (const [t, value] of [[0, 68], [2899, 68], [2900, 69], [3299, 69], [3300, 70], [3700, 71], [4100, 72]]) assert.equal(state(t).affinity, value, `arrival ${t}`);
assert.equal(state(4400).visual, 72);
assert.equal(state(6500).active, false);
assert.equal(state(1000).hearts.filter(h => h.visible).length, 4);
assert.equal(state(2900).hearts.filter(h => h.visible).length, 3);
assert.equal(state(200, {reduced: true}).visual, 72);
assert.equal(state(200, {reduced: true}).hearts.length, 0);
assert.equal(state(7000).active, false);
for (const [from, to, count] of [[69, 70, 1], [68, 72, 4], [60, 70, 10], [98, 105, 2], [100, 100, 0]]) {
  const tl = timeline(config, from, to);
  assert.equal(tl.count, count);
  assert.equal(tl.eventEnd, count ? 5300 + 400 * (count - 1) : 0);
  for (let t = 0; t <= tl.eventEnd; t += 37) {
    const s = evaluate(config, from, to, t);
    assert(s.hearts.filter(h => h.visible).length <= 4, 'max four visible hearts');
    assert(s.affinity <= 100);
    assert.deepEqual(evaluate(config, from, to, t), s, 'seek is deterministic');
  }
  assert.equal(evaluate(config, from, to, tl.duration).affinity, Math.min(100, to));
}
console.log('Hiyori engine passed');
