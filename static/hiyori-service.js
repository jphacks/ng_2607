// Adapter between the Hiyori screen and this app's existing OAuth/game API.
(() => {
  const PLACEHOLDER = '/avatar-placeholder.svg';
  const safeImage = value => {
    if (typeof value !== 'string') return PLACEHOLDER;
    try {
      const url = new URL(value, location.origin);
      return (url.protocol === 'https:' || url.origin === location.origin) ? value : PLACEHOLDER;
    } catch { return PLACEHOLDER; }
  };
  const short = (value, count) => value.length > count ? value.slice(0, count) + '…' : value;
  const asPartner = character => ({
    id: String(character.id),
    name: character.name,
    handle: character.handle ? '@' + character.handle : '',
    did: character.atDid || '',
    summary: short(character.profile.trim().replace(/\s+/g, ' '), 80),
    bio: character.profile,
    images: {normal: safeImage(character.iconUrl)},
    oauthConnected: character.oauthConnected,
    // Opened by getting close through Bluesky DMs; null means no lock information (treated as open).
    unlock: character.unlock || {required: false, unlocked: true, score: 0, threshold: 0},
  });
  const asSnapshot = (game, partnerId) => {
    if (!game || !Array.isArray(game.messages)) throw new Error('会話のデータを読み込めませんでした。');
    return {
      partnerId, playerDid: game.did,
      affinity: game.affinity, relationship: game.relationship || '気になる存在',
      axes: game.axes || null, lastUpdate: game.lastUpdate || null,
      ending: game.ending || null, turns: game.turns,
      messages: game.messages.map((item, index) => ({
        id: item.id || 'message-' + index, role: item.role, text: item.content,
        createdAt: item.createdAt || new Date().toISOString(),
      })),
      secrets: (game.secrets || []).map(item => ({
        id: String(item.level), requiredAffinity: item.level, title: item.title,
        unlocked: item.unlocked, read: item.read, content: item.content || '',
      })),
    };
  };
  async function request(path, {signal, method = 'GET', body, timeout = UI_CONFIG.timeout} = {}) {
    const controller = new AbortController();
    let expired = false;
    const abort = () => controller.abort();
    signal?.addEventListener('abort', abort, {once: true});
    if (signal?.aborted) controller.abort();
    const timer = setTimeout(() => {expired = true; controller.abort();}, timeout);
    try {
      const response = await fetch(path, {
        method, signal: controller.signal, credentials: 'same-origin',
        headers: body === undefined ? {} : {'Content-Type': 'application/json'},
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || '通信に失敗しました（HTTP ' + response.status + '）。');
      return data;
    } catch (error) {
      if (expired) throw new Error('応答がタイムアウトしました。再試行してください。');
      throw error;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
    }
  }
  function createService() {
    let identity = null;
    let characters = [];
    async function ensureIdentity(signal) {
      if (identity) return identity;
      const auth = await request('/api/auth', {signal, timeout: 15000});
      if (!auth.did) return null;
      identity = {did: auth.did, handle: auth.did, profileContext: '認証済みアカウント: ' + auth.did};
      try {
        const {profile} = await request('/api/profile?handle=' + encodeURIComponent(auth.did), {signal, timeout: 15000});
        identity.handle = profile.handle || auth.did;
        identity.profileContext = [
          '認証済みアカウント: @' + identity.handle,
          '表示名: ' + (profile.displayName || ''),
          '自己紹介: ' + (profile.description || ''),
        ].join('\n').slice(0, 3800);
      } catch (error) {
        if (error.name === 'AbortError') throw error;
      }
      return identity;
    }
    async function start(partnerId, signal) {
      const user = await ensureIdentity(signal);
      if (!user) throw new Error('ログインしてください。');
      const {game} = await request('/api/game/start', {
        method: 'POST', signal,
        body: {characterId: Number(partnerId), did: user.did, handle: user.handle, profileContext: user.profileContext},
      });
      return asSnapshot(game, partnerId);
    }
    return {
      auth: ensureIdentity,
      async logout() {
        await request('/api/auth/logout', {method: 'POST', body: {}});
        identity = null;
      },
      async list(signal) {
        const {characters: list} = await request('/api/characters', {signal, timeout: 15000});
        if (!Array.isArray(list)) throw new Error('キャラクター一覧を読み込めませんでした。');
        characters = list;
        return list.map(asPartner);
      },
      async load(partnerId, signal) {
        const user = await ensureIdentity(signal);
        if (!user) throw new Error('ログインしてください。');
        const {game} = await request('/api/game?characterId=' + encodeURIComponent(partnerId), {signal, timeout: 15000});
        return game ? asSnapshot(game, partnerId) : start(partnerId, signal);
      },
      async restart(partnerId, signal) { return start(partnerId, signal); },
      async send(before, payload, signal) {
        const user = await ensureIdentity(signal);
        if (!user) throw new Error('ログインしてください。');
        const result = await request('/api/game/chat', {
          method: 'POST', signal,
          body: {characterId: Number(before.partnerId), did: user.did,
                 message: payload.text, clientMessageId: payload.clientMessageId},
        });
        return {game: asSnapshot(result.game, before.partnerId),
                dmMessages: result.dmMessages || [], convoId: result.convoId,
                relationshipUpdate: result.relationshipUpdate || null};
      },
      async markRead(snapshot, secretId, signal) {
        await request('/api/game/secret/read', {
          method: 'POST', signal, timeout: 15000,
          body: {characterId: Number(snapshot.partnerId), level: Number(secretId)},
        });
      },
      async loadDm(partnerId, cursor, convoId, signal) {
        const character = characters.find(item => String(item.id) === partnerId);
        if (!character?.oauthConnected) return {messages: [], cursor: null, convo: null};
        const params = new URLSearchParams({characterId: partnerId});
        if (cursor && convoId) { params.set('cursor', cursor); params.set('convoId', convoId); }
        return request('/api/game/dm?' + params, {signal, timeout: 30000});
      },
    };
  }
  globalThis.UIService = Object.freeze({createService});
})();
