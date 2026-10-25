const $ = id => document.getElementById(id);
const state = { characters: [], selectedId: null, postCursor: null, convoCursor: null, messageCursor: null, convoId: null, connecting: false };
async function api(path, options = {}) { const response = await fetch(path, { credentials: 'same-origin', ...options }); const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`); return data; }
function post(path, body) { return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); }
const SECRET_LEVELS = [25, 50, 75, 100];
function fillSecrets(secrets = []) { for (const level of SECRET_LEVELS) { const item = secrets.find(secret => secret.level === level); $(`secret-title-${level}`).value = item?.title || ''; $(`secret-content-${level}`).value = item?.content || ''; } }
const STAGE_FIELDS = { name: '段階の名前', call: '相手の呼び方', tone: '口調', allowed: 'してよいこと', forbidden: 'しないこと' };
function stageTitle(index) {
  const minimums = state.stageMinimums || [0, 25, 50, 75];
  if (index >= minimums.length) return '恋人 (4段階目で告白を受け入れたあと)';
  return `段階${index + 1} (総合 ${minimums[index]}〜${index + 1 < minimums.length ? minimums[index + 1] - 1 : 100})`;
}
function fillStages(stages = state.defaultStages || []) {
  $('stage-editor').replaceChildren(...stages.map((stage, index) => {
    const card = textNode('div', '', 'stage-card' + (index >= (state.stageMinimums || [0, 25, 50, 75]).length ? ' lover' : ''));
    card.append(textNode('strong', stageTitle(index)));
    for (const [key, label] of Object.entries(STAGE_FIELDS)) {
      const field = textNode('label', label);
      const input = document.createElement(key === 'name' ? 'input' : 'textarea');
      if (key !== 'name') input.rows = 2;
      input.maxLength = 300; input.value = stage[key] || ''; input.dataset.stage = index; input.dataset.key = key;
      field.append(input); card.append(field);
    }
    return card;
  }));
}
function readStages() {
  const stages = (state.defaultStages || []).map(() => ({}));
  for (const input of $('stage-editor').querySelectorAll('[data-stage]')) stages[Number(input.dataset.stage)][input.dataset.key] = input.value;
  return stages;
}
$('reset-stages').addEventListener('click', () => { fillStages(); notice('標準の振る舞いを入れました。保存すると反映されます。'); });
function renderBaseImage(id) {
  const target = $('base-image-preview'); target.replaceChildren(); target.textContent = id ? '読み込み中…' : '保存後に登録できます';
  $('base-image-input').disabled = !id; $('base-image-delete').classList.add('hidden');
  if (!id) return;
  const image = document.createElement('img'); image.alt = 'ベース画像';
  image.onload = () => { if (state.selectedId !== id) return; target.replaceChildren(image); $('base-image-delete').classList.remove('hidden'); };
  image.onerror = () => { if (state.selectedId === id) target.textContent = '未登録'; };
  image.src = `/api/characters/${id}/base-image?v=${Date.now()}`;
}
$('base-image-input').addEventListener('change', () => {
  const file = $('base-image-input').files[0], id = state.selectedId;
  $('base-image-input').value = '';
  if (!file || !id) return;
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) { notice('ベース画像は PNG・JPEG・WebP のいずれかにしてください。', true); return; }
  if (file.size > 2_000_000) { notice('ベース画像は2MBまでです。', true); return; }
  const reader = new FileReader();
  reader.onload = async () => {
    try { await post(`/api/characters/${id}/base-image`, { image: reader.result }); renderBaseImage(id); notice('ベース画像を保存しました。次のストーリーからこの絵柄で描きます。'); }
    catch (error) { notice(error.message, true); }
  };
  reader.readAsDataURL(file);
});
$('base-image-delete').addEventListener('click', async () => {
  const id = state.selectedId;
  if (!id || !confirm('ベース画像を削除しますか？ストーリーの画像は写真風に戻ります。')) return;
  try { await post(`/api/characters/${id}/base-image/delete`, {}); renderBaseImage(id); notice('ベース画像を削除しました。'); }
  catch (error) { notice(error.message, true); }
});
function readSecrets() { return SECRET_LEVELS.map(level => ({ level, title: $(`secret-title-${level}`).value, content: $(`secret-content-${level}`).value })); }
async function loadSecrets(id) { fillSecrets(); try { const { secrets } = await api(`/api/characters/${id}/secrets`); if (state.selectedId === id) fillSecrets(secrets); } catch (error) { if (state.selectedId === id) notice(error.message, true); } }
function notice(message, error = false) { $('editor-notice').textContent = message; $('editor-notice').classList.toggle('error', error); }
function updateConnectButton() { $('connect-character').disabled = state.connecting || !$('character-handle-input').value.trim(); }
function renderIcon(url, name = '') { const target = $('icon-preview'); target.replaceChildren(); if (url) { const img = document.createElement('img'); img.src = url; img.alt = ''; target.append(img); } else target.textContent = name.slice(0, 1) || '✦'; }
function renderIdentity(name = '表示名を取得します', url = null) { $('character-name-display').textContent = name; renderIcon(url, name === '表示名を取得します' ? '' : name); }
function renderList() {
  $('character-count').textContent = `${state.characters.length}人`;
  $('character-list').replaceChildren(...state.characters.map(character => {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'character-list-item' + (character.id === state.selectedId ? ' selected' : '');
    const icon = document.createElement('span'); icon.className = 'list-icon';
    if (character.iconUrl) { const img = document.createElement('img'); img.src = character.iconUrl; img.alt = ''; icon.append(img); } else icon.textContent = character.name.slice(0, 1);
    const info = document.createElement('span'); info.className = 'list-info'; const name = document.createElement('strong'); name.textContent = character.name; const handle = document.createElement('small'); handle.textContent = character.handle ? `@${character.handle}` : 'ハンドル未設定'; info.append(name, handle); button.append(icon, info);
    button.addEventListener('click', () => select(character.id)); return button;
  }));
}
function select(id) {
  const character = state.characters.find(item => item.id === id);
  if (!character) return;
  state.selectedId = id;
  $('editor-mode').textContent = `CHARACTER / ${id}`; $('editor-title').textContent = `${character.name}を編集`;
  $('character-profile-input').value = character.profile;
  for (const key of ['intro','personality','likes','basics','details','memories']) $('public-'+key).value = character.publicProfile?.[key] || '';
  $('character-handle-input').value = character.handle;
  $('relationship-weights').value = character.relationshipWeights || '';
  fillStages(character.relationshipStages); renderBaseImage(id);
  $('profile-length').textContent = character.profile.length.toLocaleString('ja-JP');
  renderIdentity(character.name, character.iconUrl);
  $('delete-character').classList.remove('hidden'); $('handle-result').textContent = character.atDid ? `公開アカウントを確認: ${character.atDid}` : 'ハンドルを保存すると公開プロフィールを照合できます。'; $('handle-result').className = character.atDid ? 'field-note ok' : 'field-note';
  updateConnectButton(); $('disconnect-character').classList.toggle('hidden', !character.oauthConnected);
  $('connect-character').textContent = character.oauthConnected ? '保存してOAuthを再接続' : '保存してOAuth認証へ';
  notice('編集内容を保存できます。'); renderList(); loadSecrets(id); loadAutomation(character); refreshAccount(character);
}
function newCharacter() {
  state.selectedId = null;
  $('editor-mode').textContent = 'NEW CHARACTER'; $('editor-title').textContent = 'キャラクターを作成';
  $('character-form').reset(); fillSecrets(); fillStages(); renderBaseImage(null); $('profile-length').textContent = '0'; renderIdentity();
  $('delete-character').classList.add('hidden'); $('handle-result').textContent = 'ハンドルを入力すると名前とアイコンを確認できます。'; $('handle-result').className = 'field-note';
  updateConnectButton(); $('connect-character').textContent = '保存してOAuth認証へ'; $('disconnect-character').classList.add('hidden'); $('account-preview').classList.add('hidden'); $('automation-panel').classList.add('hidden');
  notice('入力した内容はこのPC内の非公開DBに保存します。'); renderList();
}
async function load(preferredId = null) { try { const data = await api('/api/characters'); state.characters = data.characters; state.defaultStages = data.defaultStages; state.stageMinimums = data.stageMinimums; renderList(); const callback = new URLSearchParams(location.search); const requested = preferredId || Number(callback.get('characterId')); if (state.characters.length) select(state.characters.find(item => item.id === requested)?.id || state.characters[0].id); else newCharacter(); if (callback.get('oauth') === 'connected') notice('OAuth接続が完了しました。DMを読み、AIの返信を送信できます。'); } catch (error) { notice(error.message, true); } }

function clearAccount() {
  state.postCursor = state.convoCursor = state.messageCursor = state.convoId = null;
  $('account-profile').replaceChildren(); $('account-posts').replaceChildren(); $('account-convos').replaceChildren(); $('account-messages').replaceChildren();
  $('message-section').classList.add('hidden'); $('posts-more').classList.add('hidden'); $('convos-more').classList.add('hidden'); $('messages-more').classList.add('hidden');
}
function textNode(tag, content, className = '') { const element = document.createElement(tag); element.textContent = content ?? ''; if (className) element.className = className; return element; }
async function refreshAccount(character) {
  clearAccount(); $('account-preview').classList.toggle('hidden', !character.atDid);
  if (!character.atDid) return;
  $('account-status').textContent = character.oauthConnected ? 'OAuth接続済み' : '公開データのみ';
  $('convo-note').textContent = character.oauthConnected ? 'DMの会話を読み込んでいます…' : 'DMを見るには、このアカウントをOAuth接続してください。';
  const id = character.id;
  try {
    const { profile, character: refreshed } = await api(`/api/characters/${id}/profile`);
    if (state.selectedId !== id) return;
    if (refreshed) {
      const index = state.characters.findIndex(item => item.id === id);
      if (index >= 0) state.characters[index] = refreshed;
      renderList();
      if ($('character-handle-input').value.trim().replace(/^@/, '').toLowerCase() === refreshed.handle.toLowerCase()) {
        $('editor-title').textContent = `${refreshed.name}を編集`;
        renderIdentity(refreshed.name, refreshed.iconUrl);
      }
    }
    const avatar = document.createElement('img'); if (profile.avatar) avatar.src = profile.avatar; avatar.alt = '';
    const info = document.createElement('div'); info.append(textNode('strong', profile.displayName || profile.handle), textNode('small', `@${profile.handle} · ${profile.did}`), textNode('p', profile.description || '自己紹介なし'));
    $('account-profile').replaceChildren(avatar, info);
  } catch (error) { if (state.selectedId === id) $('account-profile').textContent = error.message; }
  await loadPosts(id);
  if (character.oauthConnected) await loadConvos(id);
}
async function loadPosts(id) {
  const params = new URLSearchParams(); if (state.postCursor) params.set('cursor', state.postCursor);
  try {
    const page = await api(`/api/characters/${id}/posts?${params}`);
    if (state.selectedId !== id) return;
    const posts = page.feed || [];
    for (const item of posts) {
      const card = textNode('div', '', 'account-item');
      card.append(textNode('time', item.post?.record?.createdAt ? new Date(item.post.record.createdAt).toLocaleString('ja-JP') : ''), textNode('p', item.post?.record?.text || 'テキストのない投稿'));
      $('account-posts').append(card);
    }
    if (!$('account-posts').children.length) $('account-posts').textContent = '投稿はありません。';
    state.postCursor = page.cursor || null; $('posts-more').classList.toggle('hidden', !state.postCursor);
  } catch (error) { if (state.selectedId === id) $('account-posts').textContent = error.message; }
}
async function loadConvos(id) {
  const params = new URLSearchParams(); if (state.convoCursor) params.set('cursor', state.convoCursor);
  try {
    const page = await api(`/api/characters/${id}/convos?${params}`);
    if (state.selectedId !== id) return;
    for (const convo of page.convos || []) {
      const button = textNode('button', '', 'convo-item'); button.type = 'button';
      const others = (convo.members || []).filter(member => member.did !== state.characters.find(c => c.id === id)?.atDid);
      button.append(textNode('strong', others.map(member => member.displayName || member.handle || member.did).join('、') || '会話'), textNode('small', convo.lastMessage?.text || convo.id));
      button.addEventListener('click', () => { state.convoId = convo.id; state.messageCursor = null; $('account-messages').replaceChildren(); $('message-section').classList.remove('hidden'); $('message-heading').textContent = `DM本文 · ${others.map(member => member.handle || member.did).join('、')}`; loadMessages(id); });
      $('account-convos').append(button);
    }
    state.convoCursor = page.cursor || null; $('convos-more').classList.toggle('hidden', !state.convoCursor);
    $('convo-note').textContent = $('account-convos').children.length ? `${$('account-convos').children.length}件の会話を表示中。選ぶと本文を取得します。` : 'DMの会話はありません。';
  } catch (error) { if (state.selectedId === id) $('convo-note').textContent = error.message; }
}
async function loadMessages(id) {
  if (!state.convoId) return;
  const convoId = state.convoId;
  const params = new URLSearchParams({ convoId }); if (state.messageCursor) params.set('cursor', state.messageCursor);
  try {
    const page = await api(`/api/characters/${id}/messages?${params}`);
    if (state.selectedId !== id || state.convoId !== convoId) return;
    for (const item of page.messages || []) {
      const card = textNode('article', '', 'account-item dm-item');
      card.append(textNode('strong', item.sender?.did || item.$type || '不明な送信者'), textNode('time', item.sentAt ? new Date(item.sentAt).toLocaleString('ja-JP') : ''), textNode('p', typeof item.text === 'string' ? item.text : 'テキスト以外のDM'));
      const details = document.createElement('details'); details.append(textNode('summary', '取得した全データ'), textNode('pre', JSON.stringify(item, null, 2))); card.append(details); $('account-messages').append(card);
    }
    if (!$('account-messages').children.length) $('account-messages').textContent = 'この会話にDMはありません。';
    state.messageCursor = page.cursor || null; $('messages-more').classList.toggle('hidden', !state.messageCursor);
  } catch (error) { if (state.selectedId === id) $('account-messages').textContent = error.message; }
}

const STATUS_LABELS = { free: '空き', busy: '忙しい', sleep: '睡眠' };
const SCOPE_LABELS = { reply: 'DMの自動返信', post: '自動投稿', story: 'ストーリー (画像のアップロード)' };
const POST_STATUS = { posted: '投稿済み', manual: '手動投稿', missed: '見送り' };
function automationNotice(message, error = false) { $('automation-notice').textContent = message; $('automation-notice').classList.toggle('error', error); }
const AXIS_NAMES = { affection: '好意', trust: '信頼', romance: '恋愛感情' };
function memoryRow(kinds, memory = { kind: 'event', text: '' }) {
  const row = textNode('div', '', 'memory-row');
  const kind = document.createElement('select');
  for (const [value, label] of Object.entries(kinds)) { const option = textNode('option', label); option.value = value; kind.append(option); }
  kind.value = memory.kind;
  const text = document.createElement('input'); text.type = 'text'; text.maxLength = 200; text.value = memory.text; text.placeholder = '覚えていること';
  const remove = textNode('button', '削除', 'text-button'); remove.type = 'button'; remove.addEventListener('click', () => row.remove());
  row.append(kind, text, remove);
  return row;
}
function relationshipEditor(item) {
  const details = document.createElement('details'); details.className = 'relationship-edit';
  details.append(textNode('summary', 'ステータスを編集'));
  const axes = textNode('div', '', 'axis-inputs');
  for (const [axis, name] of Object.entries(AXIS_NAMES)) {
    const label = textNode('label', name);
    const input = document.createElement('input'); input.type = 'number'; input.min = 0; input.max = 100; input.step = 0.1; input.value = item.axes[axis]; input.dataset.axis = axis;
    label.append(input); axes.append(label);
  }
  const unlock = textNode('label', '', 'unlock-toggle');
  const unlocked = document.createElement('input'); unlocked.type = 'checkbox'; unlocked.checked = item.unlocked;
  unlock.append(unlocked, document.createTextNode(' ReAl を解放する'));
  const loverLabel = textNode('label', '', 'unlock-toggle');
  const lover = document.createElement('input'); lover.type = 'checkbox'; lover.checked = item.lover;
  loverLabel.append(lover, document.createTextNode(' 恋人にする (告白を受け入れた状態。好感度に関係なく恋人の振る舞いになります)'));
  const memories = textNode('div', '', 'memory-list');
  memories.append(...(item.memories || []).map(memory => memoryRow(state.memoryKinds, memory)));
  const addMemory = textNode('button', '覚えていることを追加', 'text-button'); addMemory.type = 'button';
  addMemory.addEventListener('click', () => memories.append(memoryRow(state.memoryKinds)));
  const save = textNode('button', 'このステータスで保存', 'primary-action'); save.type = 'button';
  save.addEventListener('click', () => automationAction(save, `@${item.handle || item.did} のステータスを保存しています…`, async id => {
    const body = { did: item.did, unlocked: unlocked.checked, lover: lover.checked,
      axes: Object.fromEntries([...axes.querySelectorAll('input')].map(input => [input.dataset.axis, Number(input.value)])),
      memories: [...memories.querySelectorAll('.memory-row')].map(row => ({ kind: row.querySelector('select').value, text: row.querySelector('input').value.trim() })).filter(memory => memory.text) };
    const { relationships } = await post(`/api/characters/${id}/relationship`, body);
    if (state.selectedId !== id) return;
    renderRelationships(relationships, state.automationSettings); automationNotice(`@${item.handle || item.did} のステータスを保存しました。次の会話からこの値で続きます。`);
  }));
  const reset = textNode('button', '関係をリセット', 'text-button danger-text'); reset.type = 'button';
  reset.addEventListener('click', () => {
    if (!confirm(`@${item.handle || item.did} との好感度・解放状態・覚えていること・判定の記録をすべて消して、初対面に戻しますか？\nこれまでのDMも AI に渡さなくなります (Bluesky のDMは残ります)。`)) return;
    automationAction(reset, '関係をリセットしています…', async id => {
      const { relationships } = await post(`/api/characters/${id}/relationship/delete`, { did: item.did });
      if (state.selectedId !== id) return;
      renderRelationships(relationships, state.automationSettings); automationNotice(`@${item.handle || item.did} との関係をリセットしました。`);
    });
  });
  const context = textNode('button', '会話の文脈だけリセット', 'text-button'); context.type = 'button';
  context.addEventListener('click', () => {
    if (!confirm(`@${item.handle || item.did} とのこれまでのDMを、今後 AI に渡さないようにしますか？\n好感度・恋人・覚えていることはそのままです。Bluesky のDMは消えません。`)) return;
    automationAction(context, '会話の文脈をリセットしています…', async id => {
      const { relationships } = await post(`/api/characters/${id}/relationship/context`, { did: item.did });
      if (state.selectedId !== id) return;
      renderRelationships(relationships, state.automationSettings); automationNotice(`@${item.handle || item.did} とのこれまでのDMを、AI に渡さないようにしました。次の発言から新しい会話として扱います。`);
    });
  });
  const reach = textNode('button', '今すぐ話しかける (テスト)', 'text-button'); reach.type = 'button';
  reach.addEventListener('click', () => {
    const settings = state.automationSettings;
    const condition = settings?.reach_out_mode === 'hashtag' ? `#${settings.reach_out_hashtag || '結城めもり'} 付き` : 'なかよし以上の相手の';
    if (!confirm(`保存済みの条件「${condition}投稿」で、@${item.handle || item.did} にキャラから実際にDMを送りますか？\n空き時間・24時間の間隔・返信待ちの制限は適用しません。`)) return;
    automationAction(reach, '話しかけるDMを作っています…', async id => {
      const { record, relationships } = await post(`/api/characters/${id}/relationship/reach-out`, { did: item.did });
      if (state.selectedId !== id) return;
      renderRelationships(relationships, state.automationSettings); automationNotice(`@${record.handle} に話しかけました: ${record.text}`);
    });
  });
  const actions = textNode('div', '', 'manual-actions'); const left = textNode('span', ''); left.append(reset, context, reach); actions.append(left, save);
  details.append(axes, unlock, loverLabel, textNode('small', '覚えていること (返信と好感度の判定に渡されます)'), memories, addMemory, actions);
  return details;
}
function renderRelationships(relationships, settings) {
  const target = $('dm-relationships');
  if (!relationships.length) { target.replaceChildren(textNode('p', 'まだDMで話した相手はいません。自動返信で話すか、上の「相手を追加」で、相手ごとの好感度がここに表示されます。', 'schedule-meta')); return; }
  target.replaceChildren(...relationships.map(item => {
    const row = textNode('div', '', 'relationship-row');
    const head = textNode('div', '', 'relationship-head');
    head.append(textNode('strong', `@${item.handle || item.did}`), textNode('span', item.unlocked ? 'ReAl 解放済み' : `あと ${Math.max(0, settings.unlock_score - item.overall)}`, item.unlocked ? 'unlock-badge open' : 'unlock-badge'));
    const axes = Object.entries(item.axes).map(([axis, value]) => `${AXIS_NAMES[axis]} ${Math.round(value)}`).join(' · ');
    const delta = item.lastDelta ? ' ／ 前回 ' + Object.entries(item.lastDelta).map(([axis, value]) => `${AXIS_NAMES[axis]} ${value > 0 ? '+' : ''}${value}`).join(' ') : '';
    const stage = item.lover ? `💞 ${item.stage.name}` : `段階${item.stage.number}「${item.stage.name}」${item.stage.next ? ` (次は総合 ${item.stage.next})` : ' (告白されたら恋人に)'}`;
    const context = item.contextResetAt ? ` ／ 文脈リセット ${new Date(item.contextResetAt * 1000).toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })} 以降のDMだけ使用` : '';
    const reached = item.lastReachOutAt ? ` ／ 最後に話しかけた ${new Date(item.lastReachOutAt * 1000).toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}` : '';
    row.append(head, textNode('small', `${stage} · 総合 ${item.overall} / 解放 ${settings.unlock_score} · ${axes}${delta}${context}${reached}`), relationshipEditor(item));
    return row;
  }));
}
$('add-relationship').addEventListener('click', () => {
  const handle = $('relationship-handle').value.trim().replace(/^@/, '');
  if (!handle) { automationNotice('相手のハンドルを入力してください。', true); return; }
  automationAction($('add-relationship'), `@${handle} を追加しています…`, async id => {
    const { relationships } = await post(`/api/characters/${id}/relationship`, { handle, axes: state.initialAxes, unlocked: false, memories: [] });
    if (state.selectedId !== id) return;
    $('relationship-handle').value = '';
    renderRelationships(relationships, state.automationSettings); automationNotice(`@${handle} を初期値で追加しました。「ステータスを編集」で値を変えられます。`);
  });
});
function renderAutomationState(settings) { $('automation-state').textContent = `自動返信 ${settings.auto_reply ? 'ON' : 'OFF'} · 自動投稿 ${settings.auto_post ? 'ON' : 'OFF'} · ストーリー ${settings.auto_story ? 'ON' : 'OFF'} · 話しかけ ${settings.auto_reach_out ? 'ON' : 'OFF'} (${settings.reach_out_mode === 'hashtag' ? '#' + (settings.reach_out_hashtag || '結城めもり') : 'なかよし以上'}・24時間制限${settings.reach_out_cooldown_enabled === false ? 'なし' : 'あり'}・返信待ち${settings.reach_out_wait_for_reply === false ? 'なし' : 'あり'})`; }
function updateReachOutCondition() {
  const hashtagMode = $('reach-out-mode').value === 'hashtag';
  $('reach-out-hashtag').disabled = !hashtagMode;
  $('reach-out-hashtag').required = hashtagMode;
  $('reach-out-condition-note').textContent = hashtagMode
    ? 'これまでDMした相手の、指定タグが付いた投稿だけを対象にします。好感度の制限はありません。'
    : '総合好感度50以上、または恋人の相手を対象にします。';
}
function fillReachOutCondition(settings) {
  $('reach-out-mode').value = settings.reach_out_mode || 'close';
  $('reach-out-hashtag').value = '#' + (settings.reach_out_hashtag || '結城めもり');
  $('reach-out-cooldown-enabled').checked = settings.reach_out_cooldown_enabled !== false;
  $('reach-out-wait-for-reply').checked = settings.reach_out_wait_for_reply !== false;
  updateReachOutCondition();
}
$('reach-out-mode').addEventListener('change', updateReachOutCondition);
updateReachOutCondition();
function renderSchedule(today, now, settings = state.automationSettings) {
  const target = $('today-schedule'); target.replaceChildren();
  if (!today) { target.append(textNode('p', '今日の予定はまだありません。自動運用を有効にすると最初の確認時に作られます。「作る・作り直す」で今すぐ作れます (AIを使います)。', 'schedule-meta')); return; }
  for (const block of today.blocks) {
    const row = textNode('div', '', 'schedule-block' + (block.start <= now && now < block.end ? ' current' : ''));
    row.append(textNode('time', `${block.start}〜${block.end}`), textNode('span', STATUS_LABELS[block.status] || block.status, `status-tag status-${block.status}`), textNode('span', `${block.activity}: ${block.detail}`));
    target.append(row);
  }
  const lines = [];
  if (today.events?.length) lines.push('出来事: ' + today.events.map(event => `${event.time} ${event.text}`).join(' / '));
  const timeline = (label, times, log, enabled) => {
    const logs = Object.fromEntries((log || []).filter(item => item.status !== 'manual').map(item => [item.time, item]));
    lines.push(`${label}${enabled ? '' : ' (自動はオフ)'}: ` + (times.map(time => `${time}${logs[time] ? ` (${POST_STATUS[logs[time].status] || logs[time].status})` : time <= now ? ' (確認待ち)' : ''}`).join('、') || 'なし'));
  };
  timeline('投稿時刻', settings?.post_times || [], today.post_log, settings?.auto_post);
  timeline('ストーリーの時刻', settings?.story_times || [], today.story_log, settings?.auto_story);
  const at = item => item.at ? new Date(item.at).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }) : item.time;
  for (const item of (today.post_log || []).filter(item => item.text)) lines.push(`${at(item)} ${POST_STATUS[item.status] || item.status}: ${item.text}`);
  for (const item of (today.story_log || []).filter(item => item.uri)) lines.push(`${at(item)} ストーリー${item.status === 'manual' ? ' (手動)' : ''}: ${item.text || '(一言なし)'} ／ 画像: ${item.imagePrompt?.split('\n')[0] || ''}`);
  const replies = (today.dm_log || []).filter(item => !item.reachOut), reaches = (today.dm_log || []).filter(item => item.reachOut);
  lines.push(`今日のDM自動返信: ${replies.length}件` + (replies.length ? ` (${[...new Set(replies.map(item => '@' + item.handle))].join('、')})` : ''));
  for (const item of reaches) lines.push(`${new Date(item.at).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })} 話しかけた @${item.handle}: ${item.text}`);
  target.append(textNode('p', lines.join('\n'), 'schedule-meta'));
}
async function loadAutomation(character) {
  $('automation-panel').classList.toggle('hidden', !character.oauthConnected);
  if (!character.oauthConnected) return;
  const id = character.id;
  $('automation-body').classList.add('hidden'); $('automation-scope').classList.add('hidden'); $('automation-state').textContent = '';
  automationNotice('自動運用の設定を読み込んでいます…');
  try {
    const data = await api(`/api/characters/${id}/automation`);
    if (state.selectedId !== id) return;
    const { settings } = data;
    $('auto-reply').checked = settings.auto_reply; $('auto-post').checked = settings.auto_post;
    $('extra-persona').value = settings.extra_persona; $('post-prompt').value = settings.post_prompt; $('schedule-base').value = settings.schedule_base;
    $('require-unlock').checked = settings.require_unlock; $('unlock-score').value = settings.unlock_score;
    $('post-times').value = settings.post_times.join(', '); $('auto-story').checked = settings.auto_story; $('auto-reach-out').checked = settings.auto_reach_out; $('story-times').value = settings.story_times.join(', '); $('story-image-prompt').value = settings.story_image_prompt;
    fillReachOutCondition(settings);
    state.automationSettings = settings; state.memoryKinds = data.memoryKinds; state.initialAxes = data.initialAxes; $('story-preview').classList.add('hidden');
    renderAutomationState(settings); renderSchedule(data.today, data.now); renderRelationships(data.relationships, settings);
    const missing = Object.entries(data.missingScopes).filter(([, scopes]) => scopes.length).map(([kind]) => SCOPE_LABELS[kind]);
    $('automation-scope').textContent = missing.length ? `今のOAuth接続には ${missing.join('・')} の権限がありません。上の「保存してOAuthを再接続」から認証し直してください。` : '';
    $('automation-scope').classList.toggle('hidden', !missing.length);
    const status = data.status || {};
    const parts = [];
    if (status.lastCheckAt) parts.push(`最終確認 ${new Date(status.lastCheckAt).toLocaleTimeString('ja-JP')}`);
    if (data.gamePlayers) parts.push(`ゲームのプレイヤー${data.gamePlayers}人とのDMは自動返信の対象外`);
    if (settings.require_unlock && !settings.auto_reply) parts.push('ReAl の解放はDMの自動返信で好感度を上げたときだけ起きます。自動返信がオフのままだと、誰も解放されません。');
    if (status.lastError) parts.push(`直近のエラー (${new Date(status.lastErrorAt).toLocaleTimeString('ja-JP')}): ${status.lastError}`);
    automationNotice(parts.join('\n') || '設定を編集できます。', Boolean(status.lastError));
    $('automation-body').classList.remove('hidden');
  } catch (error) { if (state.selectedId === id) automationNotice(error.message, true); }
}
async function automationAction(button, message, run) {
  const id = state.selectedId; button.disabled = true; automationNotice(message);
  try { await run(id); } catch (error) { if (state.selectedId === id) automationNotice(error.message, true); }
  finally { button.disabled = false; }
}
$('automation-form').addEventListener('submit', event => {
  event.preventDefault();
  automationAction($('save-automation'), '自動運用の設定を保存しています…', async id => {
    const { settings } = await post(`/api/characters/${id}/automation`, { auto_reply: $('auto-reply').checked, auto_post: $('auto-post').checked, extra_persona: $('extra-persona').value, post_prompt: $('post-prompt').value, schedule_base: $('schedule-base').value, require_unlock: $('require-unlock').checked, unlock_score: Number($('unlock-score').value), post_times: $('post-times').value, auto_story: $('auto-story').checked, auto_reach_out: $('auto-reach-out').checked, reach_out_mode: $('reach-out-mode').value, reach_out_hashtag: $('reach-out-hashtag').value, reach_out_cooldown_enabled: $('reach-out-cooldown-enabled').checked, reach_out_wait_for_reply: $('reach-out-wait-for-reply').checked, story_times: $('story-times').value, story_image_prompt: $('story-image-prompt').value });
    if (state.selectedId !== id) return;
    $('schedule-base').value = settings.schedule_base; $('post-times').value = settings.post_times.join(', '); $('story-times').value = settings.story_times.join(', ');
    fillReachOutCondition(settings);
    state.automationSettings = settings; renderAutomationState(settings);
    automationNotice('自動運用の設定を保存しました。数秒以内にバックグラウンドの処理に反映されます。');
  });
});
$('regen-schedule').addEventListener('click', () => automationAction($('regen-schedule'), '今日の予定を作っています… (AIで数十秒かかることがあります)', async id => {
  const { today } = await post(`/api/characters/${id}/automation/schedule`, { regen: true });
  if (state.selectedId !== id) return;
  renderSchedule(today, new Date().toTimeString().slice(0, 5)); automationNotice('今日の予定を作り直しました。記録済みの投稿・DM返信は残ります。');
}));
$('preview-post').addEventListener('click', () => automationAction($('preview-post'), '投稿文を生成しています…', async id => {
  const { text, prompt } = await post(`/api/characters/${id}/automation/preview`, {});
  if (state.selectedId !== id) return;
  $('manual-post').value = text; $('manual-length').textContent = `${text.length} / 300`;
  renderPostPrompt(prompt, `この投稿文 (${new Date().toTimeString().slice(0, 5)} 生成) を作るときに AI に渡したプロンプトです。`);
  automationNotice('投稿文を生成しました。使ったプロンプトは下の「投稿のプロンプト」にあります。必要なら編集してから投稿してください。');
}));
function renderPostPrompt(sections, caption) {
  const items = sections.map(section => {
    const item = document.createElement('div'); item.className = `account-item prompt-${section.key}`;
    const body = textNode('pre', section.content || '(空欄のため渡しません)');
    if (section.key === 'profile') {
      // The profile is long; keep it folded so the parts that change per post stay visible.
      const details = document.createElement('details');
      details.append(textNode('summary', `${section.label} (${section.content.length}文字)`), body);
      item.append(details);
    } else item.append(textNode('strong', section.label), body);
    return item;
  });
  $('post-prompt-view').replaceChildren(textNode('p', caption, 'schedule-meta'), ...items);
}
$('show-post-prompt').addEventListener('click', () => automationAction($('show-post-prompt'), '投稿のプロンプトを組み立てています… (今日の予定がなければ先に作ります)', async id => {
  const { prompt } = await post(`/api/characters/${id}/automation/prompt`, {});
  if (state.selectedId !== id) return;
  renderPostPrompt(prompt, `今 (${new Date().toTimeString().slice(0, 5)}) 投稿を作るときに AI に渡すプロンプトです。上から順につないだものがシステムメッセージ、最後が依頼です。`);
  automationNotice('投稿のプロンプトを表示しました。保存前の編集内容は反映されません。');
}));
$('preview-story').addEventListener('click', () => automationAction($('preview-story'), 'ストーリーを生成しています… (文と画像を AI で作るので 1 分ほどかかることがあります)', async id => {
  const { caption, image, prompt } = await post(`/api/characters/${id}/automation/story-preview`, {});
  if (state.selectedId !== id) return;
  $('story-image').src = image; $('story-caption').value = caption; $('story-preview').classList.remove('hidden');
  renderPostPrompt(prompt, `このストーリー (${new Date().toTimeString().slice(0, 5)} 生成) を作るときに AI に渡したプロンプトです。紫が画像生成に渡したプロンプトです。`);
  automationNotice('ストーリーを生成しました。一言は編集できます。使ったプロンプトは下の「投稿のプロンプト」にあります。');
}));
$('send-story').addEventListener('click', () => {
  const caption = $('story-caption').value.trim();
  const character = state.characters.find(item => item.id === state.selectedId);
  if (!confirm(`@${character?.handle} として Pinksky のストーリー (画像投稿) を投稿しますか？\n\n${caption || '(一言なし)'}`)) return;
  automationAction($('send-story'), 'ストーリーを投稿しています…', async id => {
    await post(`/api/characters/${id}/automation/story`, { caption });
    if (state.selectedId !== id) return;
    $('story-preview').classList.add('hidden');
    await loadAutomation(state.characters.find(item => item.id === id)); automationNotice('ストーリーを投稿しました。');
    state.postCursor = null; $('account-posts').replaceChildren(); loadPosts(id);
  });
});
$('send-post').addEventListener('click', () => {
  const text = $('manual-post').value.trim();
  if (!text) { automationNotice('投稿文を入力してください。', true); return; }
  const character = state.characters.find(item => item.id === state.selectedId);
  if (!confirm(`@${character?.handle} として Bluesky に投稿しますか？\n\n${text}`)) return;
  automationAction($('send-post'), '投稿しています…', async id => {
    await post(`/api/characters/${id}/automation/post`, { text });
    if (state.selectedId !== id) return;
    $('manual-post').value = ''; $('manual-length').textContent = '0 / 300';
    await loadAutomation(state.characters.find(item => item.id === id)); automationNotice('Bluesky に投稿しました。');
    state.postCursor = null; $('account-posts').replaceChildren(); loadPosts(id);
  });
});
$('manual-post').addEventListener('input', () => { $('manual-length').textContent = `${$('manual-post').value.length} / 300`; });

$('new-character').addEventListener('click', newCharacter);
async function saveCharacter({ refresh = true } = {}) {
  const data = await post('/api/characters/save', { id: state.selectedId, profile: $('character-profile-input').value, handle: $('character-handle-input').value, relationshipWeights: $('relationship-weights').value, relationshipStages: readStages(), secrets: readSecrets(), publicProfile: Object.fromEntries(['intro','personality','likes','basics','details','memories'].map(key => [key, $('public-'+key).value])) });
  const index = state.characters.findIndex(item => item.id === data.character.id);
  if (index >= 0) state.characters[index] = data.character; else state.characters.push(data.character);
  if (refresh) select(data.character.id);
  else state.selectedId = data.character.id;
  return data.character;
}
$('connect-character').addEventListener('click', async () => {
  if (state.connecting || !$('character-form').reportValidity()) return;
  state.connecting = true; updateConnectButton();
  let step = 'save';
  try {
    notice('編集内容を保存しています…');
    const character = await saveCharacter({ refresh: false });
    step = 'oauth';
    if (!character.atDid) throw new Error('ハンドルを確認できません。入力内容を確認してください。');
    notice('OAuth認証画面を準備しています…');
    const { url } = await post('/api/oauth/start', { role: 'character', characterId: character.id });
    location.assign(url);
  } catch (error) {
    notice(`${step === 'save' ? '保存に失敗しました' : '保存は完了しましたが、OAuth認証の開始に失敗しました'}。${error.message}`, true);
    state.connecting = false; updateConnectButton();
  }
});
$('disconnect-character').addEventListener('click', async () => { try { await post('/api/characters/disconnect', { id: state.selectedId }); await load(state.selectedId); notice('OAuth接続を解除しました。'); } catch (error) { notice(error.message, true); } });
$('posts-more').addEventListener('click', () => loadPosts(state.selectedId));
$('convos-more').addEventListener('click', () => loadConvos(state.selectedId));
$('messages-more').addEventListener('click', () => loadMessages(state.selectedId));
$('character-profile-input').addEventListener('input', () => { $('profile-length').textContent = $('character-profile-input').value.length.toLocaleString('ja-JP'); });
$('character-handle-input').addEventListener('input', () => {
  updateConnectButton();
  const handle = $('character-handle-input').value.trim().replace(/^@/, '');
  const saved = state.characters.find(item => item.id === state.selectedId);
  if (saved && handle.toLowerCase() === saved.handle.toLowerCase()) renderIdentity(saved.name, saved.iconUrl);
  else renderIdentity();
  $('handle-result').textContent = handle ? '公開プロフィールを確認すると名前とアイコンを表示します。' : 'ハンドルを入力すると名前とアイコンを確認できます。';
  $('handle-result').className = 'field-note';
});
$('check-handle').addEventListener('click', async () => {
  const handle = $('character-handle-input').value.trim().replace(/^@/, '');
  if (!handle) { $('handle-result').textContent = 'ハンドルを入力してください。'; $('handle-result').className = 'field-note error'; return; }
  $('handle-result').textContent = '公開プロフィールを確認しています…'; $('handle-result').className = 'field-note';
  try {
    const { profile } = await api(`/api/profile?handle=${encodeURIComponent(handle)}`);
    if ($('character-handle-input').value.trim().replace(/^@/, '').toLowerCase() !== handle.toLowerCase()) return;
    const name = typeof profile.displayName === 'string' && profile.displayName.trim() ? profile.displayName.trim() : profile.handle;
    const avatar = typeof profile.avatar === 'string' && profile.avatar.startsWith('https://') ? profile.avatar : null;
    renderIdentity(name, avatar);
    $('handle-result').textContent = `公開プロフィールを確認: @${profile.handle} · ${profile.did}。保存すると名前とアイコンが反映されます。`;
    $('handle-result').className = 'field-note ok';
  } catch (error) {
    if ($('character-handle-input').value.trim().replace(/^@/, '').toLowerCase() !== handle.toLowerCase()) return;
    $('handle-result').textContent = error.message; $('handle-result').className = 'field-note error';
  }
});
$('character-form').addEventListener('submit', async event => {
  event.preventDefault(); $('save-character').disabled = true;
  try {
    await saveCharacter(); notice('キャラクターを保存しました。');
  } catch (error) { notice(error.message, true); }
  finally { $('save-character').disabled = false; }
});
$('delete-character').addEventListener('click', async () => {
  const character = state.characters.find(item => item.id === state.selectedId);
  if (!character || !confirm(`${character.name}を削除しますか？ このキャラの会話と好感度も削除されます。`)) return;
  try { await post('/api/characters/delete', { id: character.id }); state.characters = state.characters.filter(item => item.id !== character.id); state.characters.length ? select(state.characters[0].id) : newCharacter(); notice('キャラクターを削除しました。'); }
  catch (error) { notice(error.message, true); }
});
async function loadConditions() {
  try {
    const { conditions } = await api('/api/relationship/conditions');
    $('condition-table').replaceChildren(...conditions.map(item => { const row = textNode('div', '', 'condition-row'); row.append(textNode('code', item.id), textNode('span', `${item.axisLabel} ${item.weight > 0 ? '+' : ''}${item.weight}${item.major ? ' · 重要' : ''}`), textNode('span', item.label)); return row; }));
  } catch (error) { $('condition-table').textContent = error.message; }
}
load(); loadConditions();
