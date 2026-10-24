const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const configCode = fs.readFileSync(path.join(__dirname, '..', 'static', 'hiyori-ui-config.js'), 'utf8');
const code = fs.readFileSync(path.join(__dirname, '..', 'static', 'hiyori-service.js'), 'utf8');
const did = 'did:plc:player2345';
let game = null;
let generated = 0;
const seen = new Set();
const calls = [];
const response = data => ({ok: true, json: async () => data});
const fetch = async (url, init = {}) => {
  calls.push([url, init.method]);
  if (url === '/api/auth') return response({did});
  if (url.startsWith('/api/profile')) return response({profile: {handle: 'player.bsky.social', displayName: 'プレイヤー', description: '読書が好き'}});
  if (url === '/api/characters') return response({characters: [
    {id: 7, name: '灯', profile: '星を見るのが好き。', handle: 'akari.bsky.social',
     iconUrl: 'https://cdn.bsky.app/avatar.png', oauthConnected: true},
    {id: 8, name: '凪', profile: 'まだ解放前。', handle: 'nagi.bsky.social', iconUrl: null, oauthConnected: true,
     unlock: {required: true, unlocked: false, score: 20, threshold: 40}},
  ]});
  if (url === '/api/game?characterId=7') return response({game});
  if (url === '/api/game/start') {
    game = {did, affinity: 50, relationship: '気になる存在', turns: 0, ending: null, messages: [], secrets: [
      {level: 50, title: '好きな場所', unlocked: true, read: false, content: '海'},
      {level: 75, title: '大切なこと', unlocked: false, read: false, content: null},
    ]};
    seen.clear();
    return response({game});
  }
  if (url === '/api/game/chat') {
    const body = JSON.parse(init.body);
    if (!seen.has(body.clientMessageId)) {
      generated++;
      seen.add(body.clientMessageId);
      game = {...game, turns: game.turns + 1, affinity: 19, axes: {affection: 33, trust: 20, romance: 0}};
    }
    return response({game, convoId: 'convo-7', relationshipUpdate: {delta: {affection: 3, trust: 0, romance: 0}}, dmMessages: [
      {id: body.clientMessageId, sender: {did}, text: body.message, sentAt: '2026-10-22T00:00:00Z'},
      {id: 'reply-' + generated, sender: {did: 'did:plc:character2345'}, text: 'こんばんは', sentAt: '2026-10-22T00:00:01Z'},
    ]});
  }
  if (url === '/api/game/secret/read') {
    assert.deepEqual(JSON.parse(init.body), {characterId: 7, level: 50});
    return response({ok: true});
  }
  if (url === '/api/game/dm?characterId=7') return response({convo: {id: 'convo-7'}, cursor: null, messages: [{text: 'DM原文'}]});
  throw new Error('Unexpected request: ' + url);
};
const context = {fetch, location: {origin: 'http://127.0.0.1:8765'}, URL, URLSearchParams, AbortController, setTimeout, clearTimeout};
vm.createContext(context);
vm.runInContext(configCode, context);
vm.runInContext(code, context);

(async () => {
  const service = context.UIService.createService();
  const auth = await service.auth();
  assert.equal(auth.handle, 'player.bsky.social');
  const partners = await service.list();
  assert.equal(partners[0].name, '灯');
  assert.equal(partners[0].images.normal, 'https://cdn.bsky.app/avatar.png');
  assert.equal(partners[0].unlock.unlocked, true, 'no lock information means open');
  assert.deepEqual({...partners[1].unlock}, {required: true, unlocked: false, score: 20, threshold: 40});
  const initial = await service.load('7');
  assert.equal(initial.affinity, 50);
  assert.equal(initial.messages.length, 0);
  assert.deepEqual(initial.secrets.map(item => [item.id, item.requiredAffinity, item.unlocked, item.content]), [['50', 50, true, '海'], ['75', 75, false, '']]);
  await service.markRead(initial, '50');
  assert.ok(calls.some(([url]) => url === '/api/game/secret/read'));
  const payload = {clientMessageId: 'client-1', text: 'こんにちは'};
  const after = await service.send(initial, payload);
  assert.equal(after.game.messages.length, 0);
  assert.equal(after.dmMessages[0].id, payload.clientMessageId);
  assert.equal(after.dmMessages[1].text, 'こんばんは');
  assert.deepEqual({...after.game.axes}, {affection: 33, trust: 20, romance: 0});
  assert.equal(after.relationshipUpdate.delta.affection, 3);
  await service.send(initial, payload);
  assert.equal(generated, 1);
  assert.equal((await service.load('7')).messages.length, 0);
  assert.equal((await service.loadDm('7')).messages[0].text, 'DM原文');
  assert.equal((await service.restart('7')).messages.length, 0);
  assert.ok(calls.some(([url]) => url === '/api/game/start'));
  console.log('Hiyori service integration passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
