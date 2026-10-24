const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const read = name => fs.readFileSync(path.join(__dirname, '..', 'static', name), 'utf8');
const context = vm.createContext({});
vm.runInContext(read('hiyori-engine.js') + '\n' + read('hiyori-config.js') + '\nglobalThis.config = AFFECTION_CONFIG;', context);
const {evaluate, timeline} = context.AffectionEngine;
const {config} = context;
for (const [from, to] of [[68,72],[68,65],[60,70],[98,105],[2,-4],[100,100],[18,18],[50,0],[0,100]]) {
  const tl = timeline(config,from,to);
  const target = Math.max(0,Math.min(100,to));
  assert.equal(tl.delta,target-from);
  assert.equal(tl.count,Math.abs(target-from));
  assert.equal(tl.duration,tl.count ? 4850 : 0);
  let previous = from;
  for (let t=0;t<=tl.duration;t+=37) {
    const s=evaluate(config,from,to,t);
    assert(s.hearts.filter(h=>h.visible).length<=1,'exactly one heart at most');
    assert(s.visual>=Math.min(from,target) && s.visual<=Math.max(from,target));
    assert(tl.delta>=0 ? s.visual>=previous : s.visual<=previous,'monotonic meter');
    assert.deepEqual(evaluate(config,from,to,t),s,'deterministic');
    previous=s.visual;
  }
  assert.equal(evaluate(config,from,to,tl.duration).affinity,target);
  const reduced=evaluate(config,from,to,200,{reduced:true});
  assert.equal(reduced.visual,target);
  assert.equal(reduced.hearts.length,0);
  assert.equal(reduced.active,false);
  if(tl.count) assert.equal(evaluate(config,from,to,1000).hearts.filter(h=>h.visible).length,1);
}
assert.equal(timeline(config,68,72).duration,timeline(config,68,65).duration);
console.log('Hiyori engine passed (increase, decrease, single heart, reduced motion)');
