// Hiyori player UI backed by the local OAuth/game server.
(() => {
  const DM_POLL_MS = 20000;
  const $ = selector => document.querySelector(selector);
  const $$ = selector => document.querySelectorAll(selector);
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const api = UIService.createService();
  const app = $('.app'), selection = $('.partner-selection'), cards = $('.partner-cards'), messages = $('.messages');
  const profile = $('#profile'), popup = $('.ui-update'), brand = $('.brand'), errorBox = $('.ui-error');
  const status = $('.ui-status'), live = $('.live-update'), switcher = $('.ui-switch');
  const input = $('.composer textarea'), send = $('.send-button'), count = $('.composer-count .count');
  const typing = $('.ui-typing'), newMessage = $('.new-message'), ending = $('.game-ending'), restart = $('.game-restart');
  const badge = $('.ui-profile-badge'), mobileBadge = $('.mobile-secret-badge');
  const secretsSection = $('.secret-section'), secretList = $('.secret-list');
  const player = new AffectionPlayer({messages, anchor: $('.sidebar .affinity'), background: app, brand});
  input.maxLength = UI_CONFIG.maxMessageLength;

  let partnerList = [], selected = null, epoch = 0, loading = false, busy = false;
  let mainAbort = null, readAbort = null, dmAbort = null, profileTrigger = null;
  const sessions = new Map(), revealAnimations = new Set();
  let revealVersion = 0;
  const current = () => selected ? sessions.get(selected.id) : null;
  const snapshot = () => current()?.snapshot;

  function showError(message, retry) {
    errorBox.replaceChildren(el('span', null, message));
    errorBox.hidden = false;
    if (retry) {
      const button = el('button', null, '再試行');
      button.type = 'button';
      button.onclick = () => { errorBox.hidden = true; retry(); };
      errorBox.append(button);
    }
  }
  function clearError() { errorBox.hidden = true; errorBox.replaceChildren(); }
  function cancel() {
    epoch++;
    mainAbort?.abort(); readAbort?.abort(); dmAbort?.abort(); player.cancel();
    revealVersion++;
    for (const animation of revealAnimations) animation.cancel();
    revealAnimations.clear();
    busy = false; loading = false; app.inert = brand.inert = false;
    if (profile.open) profile.close();
    if (popup.open) popup.close();
  }
  function setControls() {
    const pending = current()?.pending;
    input.disabled = !snapshot() || !selected?.oauthConnected || busy || loading || !!pending || !!snapshot()?.ending;
    send.disabled = input.disabled || !input.value.trim();
    $$('[data-open-profile]').forEach(button => button.disabled = busy || loading || !snapshot());
    typing.hidden = !busy || !pending || pending.status !== 'sending';
    count.textContent = `${input.value.length} / ${UI_CONFIG.maxMessageLength}`;
    $('.chat').setAttribute('aria-busy', String(loading || busy));
    const appeared = ending.hidden && !!snapshot()?.ending;
    ending.hidden = restart.hidden = !snapshot()?.ending;
    if (snapshot()?.ending) ending.textContent = snapshot().ending;
    // The ending panel shrinks the message area; keep the last reply in view.
    if (appeared) messages.scrollTop = messages.scrollHeight;
  }
  function resizeInput() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 140) + 'px';
  }

  function renderAffinity(value = snapshot()?.affinity, visual = value, relation = snapshot()?.relationship) {
    if (value === undefined) return;
    $$('.affinity').forEach(section => {
      section.querySelector('strong').textContent = value;
      section.querySelector('progress').value = visual;
      section.querySelector('p').textContent = `♡ ${relation}`;
      section.setAttribute('aria-label', `好感度${value}、100点満点、${relation}`);
    });
    $('.mobile-relation').textContent = `好感度 ${value} · ${relation}`;
  }
  const AXIS_LABELS = {affection: '好意', trust: '信頼', romance: '恋愛感情'};
  const signed = value => (value > 0 ? '+' : value < 0 ? '−' : '±') + Math.abs(value).toFixed(1);
  // The meter shows the overall value; this shows the three axes and the last change behind it.
  function renderAxes() {
    const axes = snapshot()?.axes, update = snapshot()?.lastUpdate;
    $$('.relationship-axes').forEach(section => {
      section.hidden = !axes;
      if (!axes) return;
      for (const [axis, value] of Object.entries(axes)) {
        const row = section.querySelector(`[data-axis="${axis}"]`);
        row.querySelector('progress').value = value;
        row.querySelector('b').textContent = Math.round(value);
        row.setAttribute('aria-label', `${AXIS_LABELS[axis]} ${Math.round(value)}`);
      }
      const change = section.querySelector('.axis-change');
      change.hidden = !update;
      if (update) change.textContent = (update.channel === 'bluesky' ? '前回の変化（Bluesky DM） ' : '前回の変化 ') + Object.entries(update.delta).map(([axis, value]) => `${AXIS_LABELS[axis]} ${signed(value)}`).join(' · ');
    });
    const detail = $('.axis-detail');
    detail.hidden = !update;
    if (!update) return;
    detail.querySelector('.axis-reason').textContent = update.evaluated === false ? update.reason : (update.reason || '理由は記録されていません。');
    detail.querySelector('ul').replaceChildren(...(update.breakdown.length ? update.breakdown.map(item => {
      const line = el('li', null, `${AXIS_LABELS[item.axis]} ${signed(item.contribution)}: ${item.label}（該当度 ${item.score}${item.multiplier < 1 ? `・繰り返しのため×${item.multiplier}` : ''}）`);
      if (item.evidence) line.append(el('q', null, item.evidence));
      return line;
    }) : [el('li', null, '当てはまる条件はありませんでした。')]));
  }
  function renderPartner() {
    const p = selected;
    $$('[data-partner-image]').forEach(img => { img.src = p.images.normal; img.alt = ''; });
    $$('.partner-name').forEach(node => node.textContent = p.name);
    $$('.partner-handle').forEach(node => { node.textContent = p.handle; node.hidden = !p.handle; });
    $('.description').textContent = p.bio;
    $('.profile-bio').textContent = p.bio;
    $('.sidebar').setAttribute('aria-label', p.name + 'の紹介');
    $('.chat').setAttribute('aria-label', p.name + 'とのチャット');
    input.placeholder = p.oauthConnected ? 'Bluesky DMを送る…' : 'キャラクターのOAuth接続が必要です';
    document.title = `Re:Al — ${p.name}との時間`;
  }

  // The conversation timeline is read from Bluesky DMs only.
  function timeline() {
    const session = current(), items = [];
    for (const dm of session.dm?.messages.values() || []) {
      const did = dm.sender?.did;
      const side = did === session.snapshot.playerDid ? 'user' : did && did === selected.did ? 'ai' : null;
      if (!side) continue;
      items.push({key: 'dm:' + dm.id, side, dm: true, text: typeof dm.text === 'string' && dm.text ? dm.text : '（テキスト以外のDM）', at: dm.sentAt});
    }
    return items.sort((a, b) => (Date.parse(a.at) || 0) - (Date.parse(b.at) || 0));
  }
  function messageNode(item, pending = null) {
    const article = el('article', `message ${item.side}${item.dm ? ' dm' : ''}`);
    article.dataset.key = item.key;
    if (item.side === 'ai') {
      const img = el('img', 'avatar');
      img.src = selected.images.normal; img.alt = '';
      article.append(img);
    }
    const body = el('div');
    if (item.side === 'ai') {
      const sender = el('span', 'sender', selected.name);
      if (item.dm) sender.append(el('span', 'dm-tag', 'Bluesky DM'));
      body.append(sender);
    } else if (item.dm) body.append(el('span', 'dm-tag', 'Bluesky DM'));
    body.append(el('div', 'bubble', item.text));
    if (pending) {
      const failed = pending.status === 'failed';
      body.append(el('span', 'message-state', failed ? '送信できませんでした' : '送信中…'));
      if (failed) {
        const retry = el('button', 'retry-message', '送信状況を確認');
        retry.type = 'button'; retry.onclick = () => submit(true);
        const edit = el('button', 'retry-message', '編集する');
        edit.type = 'button';
        edit.onclick = () => {
          input.value = pending.text; current().draft = pending.text; current().pending = null;
          renderMessages(); setControls(); resizeInput(); input.focus();
        };
        body.append(retry, edit);
      }
    }
    article.append(body);
    const stamp = el('time', null, new Date(item.at).toLocaleTimeString('ja-JP', {hour: '2-digit', minute: '2-digit'}));
    stamp.dateTime = item.at;
    article.append(stamp);
    return article;
  }
  function renderMessages({force = false, animate = false, keepBottomOffset = false} = {}) {
    const session = current();
    const fromBottom = messages.scrollHeight - messages.scrollTop;
    const nearBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 60;
    const previous = new Set([...messages.querySelectorAll('[data-key]')].map(node => node.dataset.key));
    messages.replaceChildren();
    if (session.dm?.cursor) {
      const older = el('button', 'dm-more', '古いDMを読み込む');
      older.type = 'button'; older.onclick = () => loadOlderDm();
      messages.append(older);
    }
    if (session.dm?.error) messages.append(el('p', 'dm-status', session.dm.error));
    let lastDay = '';
    for (const item of timeline()) {
      const day = new Date(item.at).toLocaleDateString('ja-JP', {year: 'numeric', month: 'long', day: 'numeric', weekday: 'short'});
      if (day !== lastDay) {
        const divider = el('div', 'date-divider');
        divider.append(el('span', null, day));
        messages.append(divider);
        lastDay = day;
      }
      const node = messageNode(item);
      if (animate && !previous.has(item.key)) node.classList.add('just-arrived');
      messages.append(node);
    }
    const pending = session.pending;
    if (pending && ![...(session.dm?.messages.values() || [])].some(item => item.sender?.did === session.snapshot.playerDid && item.text === pending.text && Date.parse(item.sentAt) >= Date.parse(pending.createdAt) - 5000)) {
      messages.append(messageNode({key: 'pending:' + pending.clientMessageId, side: 'user', text: pending.text, at: pending.createdAt}, pending));
    }
    if (!messages.querySelector('.message')) messages.append(el('p', 'ui-empty',
      selected?.oauthConnected ? 'Bluesky DMで話してみませんか。' : '会話を始めるにはキャラクターをOAuth接続してください。'));
    if (keepBottomOffset) messages.scrollTop = messages.scrollHeight - fromBottom;
    else if (force || nearBottom) { messages.scrollTop = messages.scrollHeight; newMessage.hidden = true; }
    else if (animate && [...messages.querySelectorAll('[data-key]')].some(node => !previous.has(node.dataset.key))) newMessage.hidden = false;
  }
  newMessage.onclick = () => { messages.scrollTop = messages.scrollHeight; newMessage.hidden = true; };
  messages.addEventListener('scroll', () => {
    if (messages.scrollHeight - messages.scrollTop - messages.clientHeight < 60) newMessage.hidden = true;
  });

  function mergeDm(session, page, {older = false} = {}) {
    const dm = session.dm || {messages: new Map(), cursor: null, convoId: null, error: null};
    let added = 0;
    for (const item of page.messages || []) {
      if (item?.id && !dm.messages.has(item.id)) { dm.messages.set(item.id, item); added++; }
    }
    if (older || !session.dm) dm.cursor = page.cursor || null;
    dm.convoId = page.convo?.id || dm.convoId;
    dm.error = null;
    session.dm = dm;
    return added;
  }
  async function refreshDm() {
    if (!selected?.oauthConnected || !snapshot()) return;
    const token = epoch, session = current();
    dmAbort?.abort(); dmAbort = new AbortController();
    try {
      const page = await api.loadDm(selected.id, null, null, dmAbort.signal);
      if (token !== epoch) return;
      const first = !session.dm;
      if (mergeDm(session, page) || first) renderMessages({animate: !first, force: first});
    } catch (error) {
      if (token !== epoch || error.name === 'AbortError') return;
      session.dm = {...(session.dm || {messages: new Map(), cursor: null, convoId: null}), error: 'Bluesky の DM を読み込めませんでした: ' + error.message};
      renderMessages();
    }
  }
  async function loadOlderDm() {
    const session = current(), dm = session?.dm;
    if (!dm?.cursor || !dm.convoId) return;
    const token = epoch;
    dmAbort?.abort(); dmAbort = new AbortController();
    try {
      const page = await api.loadDm(selected.id, dm.cursor, dm.convoId, dmAbort.signal);
      if (token !== epoch) return;
      mergeDm(session, page, {older: true});
      renderMessages({keepBottomOffset: true});
    } catch (error) {
      if (token === epoch && error.name !== 'AbortError') { dm.error = 'Bluesky の DM を読み込めませんでした: ' + error.message; renderMessages(); }
    }
  }
  setInterval(() => {
    if (!app.hidden && !busy && document.visibilityState === 'visible') refreshDm();
  }, DM_POLL_MS);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && !app.hidden && !busy) refreshDm();
  });

  function renderBadge() {
    const unread = snapshot()?.secrets.filter(s => s.unlocked && !s.read).length || 0;
    badge.hidden = mobileBadge.hidden = !unread;
    badge.textContent = `新しいヒミツ · ${unread}件`;
    mobileBadge.textContent = `NEW ${unread}`;
  }
  async function openSecret(secret, card) {
    if (!secret.unlocked || secret.read || card.dataset.reading === 'true') return;
    const token = epoch, version = revealVersion;
    card.dataset.reading = 'true';
    const body = card.querySelector('p');
    try {
      if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
        const animation = body.animate([
          {opacity: 0, clipPath: 'inset(0 100% 0 0)'},
          {opacity: 0, clipPath: 'inset(0 100% 0 0)', offset: 600 / 1400},
          {opacity: 1, clipPath: 'inset(0 0% 0 0)'},
        ], {duration: 1400, fill: 'backwards'});
        revealAnimations.add(animation);
        await animation.finished;
        revealAnimations.delete(animation);
      }
      if (token !== epoch || version !== revealVersion || !profile.open) return;
      readAbort = new AbortController();
      await api.markRead(snapshot(), secret.id, readAbort.signal);
      if (token !== epoch || version !== revealVersion) return;
      secret.read = true;
      card.querySelector('small').textContent = '公開済み';
      card.querySelector('summary').textContent = `◇ ${secret.title}`;
      renderBadge();
    } catch (error) {
      if (error.name !== 'AbortError' && token === epoch && version === revealVersion) {
        card.append(el('span', 'message-state', '閲覧状態を保存できませんでした。'));
        const retry = el('button', 'read-retry', '保存を再試行');
        retry.type = 'button';
        retry.onclick = () => { retry.remove(); openSecret(secret, card); };
        card.append(retry);
      }
    } finally { card.dataset.reading = 'false'; }
  }
  function renderSecrets() {
    secretsSection.hidden = !snapshot().secrets.length;
    secretList.replaceChildren();
    for (const secret of snapshot().secrets) {
      const card = el('details', `secret-card${secret.unlocked ? '' : ' locked'}`);
      card.dataset.secret = secret.id;
      card.append(
        el('summary', null, `${secret.unlocked ? '◇' : '♧'} ${secret.title}${secret.unlocked && !secret.read ? ' · NEW' : ''}`),
        el('small', null, secret.unlocked ? '公開済み' : `好感度${secret.requiredAffinity}で公開`),
        el('p', null, secret.unlocked ? secret.content : 'もう少し仲良くなると、知ることができます。'),
      );
      card.querySelector('summary').onclick = event => { if (!secret.unlocked) event.preventDefault(); };
      card.addEventListener('toggle', () => { if (card.open) openSecret(secret, card); });
      secretList.append(card);
    }
  }
  function openProfile(reveal = false, trigger = document.activeElement) {
    if (!snapshot() || busy || loading || !player.layer.hidden) return;
    profileTrigger = trigger;
    renderAffinity(); renderAxes(); renderSecrets();
    profile.showModal(); profile.scrollTop = 0; $('#close-profile').focus();
    const bio = $('.profile-bio');
    bio.classList.add('clamped');
    $('.bio-toggle').hidden = bio.scrollHeight <= bio.clientHeight + 1;
    $('.bio-toggle').textContent = '続きを読む';
    if (reveal) {
      const first = snapshot().secrets.find(s => s.unlocked && !s.read);
      const card = first && [...secretList.children].find(c => c.dataset.secret === first.id);
      if (card) { card.open = true; card.scrollIntoView({block: 'center'}); }
    }
    setControls();
  }
  $('#close-profile').onclick = () => profile.close();
  $('.bio-toggle').onclick = () => {
    const clamped = $('.profile-bio').classList.toggle('clamped');
    $('.bio-toggle').textContent = clamped ? '続きを読む' : '閉じる';
  };
  profile.addEventListener('click', event => {
    const r = profile.getBoundingClientRect();
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) profile.close();
  });
  profile.addEventListener('close', () => {
    revealVersion++; readAbort?.abort();
    for (const animation of revealAnimations) animation.cancel();
    revealAnimations.clear();
    if (profileTrigger?.isConnected) profileTrigger.focus({preventScroll: true});
    setControls();
  });
  $$('[data-open-profile]').forEach(button => button.onclick = () => openProfile(false, button));
  popup.querySelector('.update-later').onclick = () => popup.close();
  popup.querySelector('.update-read').onclick = () => { popup.close(); openProfile(true, send); };
  function showUpdate(unlocked) {
    if (!unlocked.length) return;
    popup.querySelector('img').src = selected.images.normal;
    popup.querySelector('h2').textContent = `${selected.name}の新しい一面が届きました`;
    popup.querySelector('.update-description').textContent = `新しいヒミツが${unlocked.length}件、公開されました。`;
    popup.showModal(); popup.querySelector('.update-read').focus();
  }

  function renderCards() {
    cards.replaceChildren(...partnerList.map(p => {
      const locked = !p.unlock.unlocked;
      const card = el('button', 'partner-card' + (locked ? ' locked' : ''));
      card.type = 'button';
      card.dataset.selectPartner = p.id;
      if (locked) card.setAttribute('aria-disabled', 'true');
      if (p.id === selected?.id) card.setAttribute('aria-current', 'true');
      const img = el('img'); img.src = p.images.normal; img.alt = '';
      const meta = el('span', 'partner-meta');
      meta.append(el('strong', null, p.name));
      if (p.handle) meta.append(el('small', null, p.handle));
      meta.append(el('span', 'partner-summary', p.summary));
      if (locked) {
        const lock = el('span', 'partner-lock', `🔒 まだ解放されていません。Blueskyで${p.handle || 'このキャラ'}にDMして仲良くなると解放されます`);
        const progress = el('progress', 'partner-lock-progress');
        progress.max = p.unlock.threshold; progress.value = Math.min(p.unlock.score, p.unlock.threshold);
        meta.append(lock, progress, el('small', 'partner-lock-score', `好感度 ${p.unlock.score} / ${p.unlock.threshold}`));
      }
      card.append(img, meta);
      card.onclick = () => { if (!locked) choose(p.id); };
      return card;
    }));
  }
  function showSelection() {
    app.hidden = true; selection.hidden = false; switcher.hidden = true;
    document.title = 'Re:Al — お話しする相手を選ぶ';
    history.replaceState(null, '', '/');
    renderCards();
  }
  async function choose(id) {
    cancel(); clearError();
    selected = partnerList.find(p => p.id === id);
    if (!selected || !selected.unlock.unlocked) { selected = null; return; }
    if (!sessions.has(id)) sessions.set(id, {snapshot: null, draft: '', pending: null, dm: null});
    const token = epoch;
    loading = true;
    status.textContent = `${selected.name}との会話を読み込んでいます…`;
    mainAbort = new AbortController();
    try {
      const data = await api.load(id, mainAbort.signal);
      if (token !== epoch) return;
      const session = current();
      session.snapshot = data;
      if (session.pending) session.pending.status = 'failed';
      renderPartner(); renderAffinity(); renderAxes(); renderBadge();
      input.value = session.draft; resizeInput();
      loading = false; selection.hidden = true; app.hidden = false; switcher.hidden = false; status.textContent = '';
      history.replaceState(null, '', '/?partner=' + encodeURIComponent(id));
      renderMessages({force: true}); setControls();
      $('.chat-title h2').focus({preventScroll: true});
      refreshDm();
    } catch (error) {
      if (token === epoch && error.name !== 'AbortError') {
        loading = false; status.textContent = '会話を読み込めませんでした。';
        showError(error.message, () => choose(id)); setControls();
      }
    }
  }
  async function submit(retry = false) {
    if (busy || loading || !snapshot() || snapshot().ending || profile.open || popup.open) return;
    const text = retry ? current().pending?.text : input.value.trim();
    if (!text || text.length > UI_CONFIG.maxMessageLength) return;
    if (current().pending && !retry) return;
    const token = epoch, before = snapshot(), session = current();
    clearError(); busy = true;
    const pending = retry ? session.pending : {clientMessageId: crypto.randomUUID(), text, createdAt: new Date().toISOString()};
    pending.status = 'sending'; session.pending = pending; session.draft = '';
    input.value = ''; resizeInput();
    renderMessages({force: true, animate: true}); setControls();
    mainAbort = new AbortController();
    try {
      const result = await api.send(before, {clientMessageId: pending.clientMessageId, text}, mainAbort.signal);
      if (token !== epoch) return;
      const data = result.game;
      session.snapshot = data; session.pending = null;
      mergeDm(session, {convo: {id: result.convoId}, messages: result.dmMessages});
      renderMessages({force: true, animate: true});
      renderAffinity(before.affinity, before.affinity, before.relationship);
      typing.hidden = true;
      await player.play(before.affinity, data.affinity, data.relationship, {
        signal: mainAbort.signal,
        onFrame: s => renderAffinity(s.affinity, s.visual, data.relationship),
      });
      if (token !== epoch) return;
      renderAffinity(); renderAxes(); renderBadge();
      const unlocked = data.secrets.filter(secret => secret.unlocked && !before.secrets.find(old => old.id === secret.id)?.unlocked);
      if (unlocked.length) {
        await new Promise(resolve => setTimeout(resolve, AFFECTION_CONFIG.popupGap));
        if (token !== epoch) return;
        showUpdate(unlocked);
      }
      const change = result.relationshipUpdate?.delta;
      live.textContent = '返信が届きました' + (change ? '。' + Object.entries(change).map(([axis, value]) => `${AXIS_LABELS[axis]} ${signed(value)}`).join('、') : '');
    } catch (error) {
      if (token !== epoch) return;
      if (session.pending) { pending.status = 'failed'; renderMessages(); }
      if (error.name !== 'AbortError') showError(error.message, () => submit(true));
    } finally {
      if (token === epoch) { busy = false; setControls(); if (!popup.open && !profile.open) input.focus({preventScroll: true}); }
    }
  }
  input.oninput = () => { if (current()) current().draft = input.value; resizeInput(); setControls(); };
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) { event.preventDefault(); submit(); }
  });
  send.onclick = () => submit();
  restart.onclick = async () => {
    if (!selected || busy || !confirm('物語の進行（往復数と結末）をリセットしますか？好感度とBluesky DMの履歴は残ります。')) return;
    const token = epoch;
    loading = true; setControls(); mainAbort = new AbortController();
    try {
      const data = await api.restart(selected.id, mainAbort.signal);
      if (token !== epoch) return;
      Object.assign(current(), {snapshot: data, pending: null, draft: ''});
      input.value = ''; resizeInput();
      renderMessages({force: true}); renderAffinity(); renderAxes(); renderBadge(); clearError();
    } catch (error) {
      if (token === epoch && error.name !== 'AbortError') showError(error.message);
    } finally {
      if (token === epoch) { loading = false; setControls(); }
    }
  };
  switcher.onclick = () => {
    if (current()?.pending) current().pending.status = 'failed';
    cancel(); clearError(); status.textContent = '';
    showSelection();
    cards.querySelector('[aria-current]')?.focus();
  };
  $('.ui-logout').onclick = async () => {
    cancel(); sessions.clear(); selected = null;
    try { await api.logout(); location.replace('/login'); } catch (error) { showError(error.message); }
  };
  async function bootstrap() {
    status.textContent = 'お話しする相手を読み込んでいます…';
    cards.replaceChildren();
    try {
      const token = epoch;
      mainAbort = new AbortController();
      const user = await api.auth(mainAbort.signal);
      if (!user) { location.replace('/login'); return; }
      $('.account-handle').textContent = user.handle === user.did ? user.did : '@' + user.handle;
      partnerList = await api.list(mainAbort.signal);
      if (token !== epoch) return;
      status.textContent = partnerList.length ? '' : '現在、お話しできる相手がいません。キャラクター管理から追加してください。';
      renderCards();
      const requested = new URLSearchParams(location.search).get('partner');
      if (partnerList.some(p => p.id === requested && p.unlock.unlocked)) choose(requested);
    } catch (error) {
      if (error.name !== 'AbortError') { status.textContent = '相手を読み込めませんでした。'; showError(error.message, bootstrap); }
    }
  }
  setControls();
  bootstrap();
})();
