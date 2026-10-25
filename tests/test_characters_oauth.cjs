const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Exercise the real save function and reconnect handler without starting the page's initial network reads.
const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'characters.js'), 'utf8')
  .replace(/\nload\(\); loadConditions\(\);\s*$/, '\n');
const character = {id: 7, handle: 'character.bsky.social', atDid: 'did:plc:character2345', profile: 'profile'};
const response = (data, ok = true) => ({ok, json: async () => data});

function harness(handleRequest = async () => response({character})) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', disabled: false, textContent: '', handlers: {},
      classList: {toggle() {}},
      addEventListener(event, handler) { this.handlers[event] = handler; },
      reportValidity: () => true,
      querySelectorAll: () => [],
    });
    return elements.get(id);
  };
  const calls = [], navigations = [], refreshes = [];
  const context = {
    document: {getElementById: element},
    location: {assign: url => navigations.push(url)},
    fetch: async (url, options) => {
      calls.push({url, body: JSON.parse(options.body)});
      return handleRequest(url, options);
    },
    refreshes,
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  context.savedCharacter = character;
  vm.runInContext('state.selectedId = savedCharacter.id; state.characters = [savedCharacter]; select = id => refreshes.push(id);', context);
  element('character-handle-input').value = character.handle;
  element('character-profile-input').value = character.profile;
  return {context, calls, navigations, refreshes, element, click: element('connect-character').handlers.click};
}

(async () => {
  let releaseSave;
  const savePending = new Promise(resolve => { releaseSave = resolve; });
  const success = harness(async url => {
    if (url === '/api/characters/save') { await savePending; return response({character}); }
    assert.equal(url, '/api/oauth/start');
    return response({url: 'https://example.test/authorize'});
  });
  const firstClick = success.click();
  await success.click();
  vm.runInContext('updateConnectButton()', success.context);
  assert.equal(success.calls.length, 1, 'repeated clicks must not save or authorize twice');
  assert.equal(success.element('connect-character').disabled, true, 'input updates must not re-enable reconnect');
  releaseSave();
  await firstClick;
  assert.deepEqual(success.calls.map(call => call.url), ['/api/characters/save', '/api/oauth/start']);
  assert.deepEqual(success.calls[1].body, {role: 'character', characterId: 7});
  assert.deepEqual(success.refreshes, [], 'saving for reconnect must not reload the old OAuth connection');
  assert.deepEqual(success.navigations, ['https://example.test/authorize']);
  assert.equal(success.element('connect-character').disabled, true, 'keep reconnect disabled until navigation');

  for (const failureAt of ['/api/characters/save', '/api/oauth/start']) {
    const failure = harness(async url => url === failureAt
      ? response({error: 'connection failed'}, false)
      : response({character}));
    await failure.click();
    const message = failure.element('editor-notice').textContent;
    assert.ok(message.includes('connection failed'));
    assert.equal(message.includes('保存は完了'), failureAt === '/api/oauth/start');
    assert.equal(failure.element('connect-character').disabled, false, 'allow retry after a failed request');
    assert.equal(vm.runInContext('state.connecting', failure.context), false);
    assert.deepEqual(failure.refreshes, []);
    assert.deepEqual(failure.navigations, []);
    assert.equal(failure.calls.length, failureAt === '/api/characters/save' ? 1 : 2);
  }

  const normalSave = harness();
  await vm.runInContext('saveCharacter()', normalSave.context);
  assert.deepEqual(normalSave.refreshes, [7], 'ordinary saves retain the page refresh');
  console.log('Character OAuth reconnect passed (request order, duplicate clicks, errors, ordinary save)');
})().catch(error => { console.error(error); process.exitCode = 1; });
