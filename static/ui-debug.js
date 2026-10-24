// Loaded only by scripts/ui_debug.py. Production pages never include this file.
(async () => {
  const state = await fetch('/__debug/state').then(r => r.json());
  const panel = document.createElement('details');
  panel.style.cssText = 'position:fixed;bottom:12px;left:12px;z-index:99999;max-width:calc(100vw - 24px);max-height:70dvh;overflow:auto;background:#fff8ec;color:#312c28;border:1px solid #b88646;border-radius:12px;padding:10px 14px;box-shadow:0 4px 20px #0002;font:13px/1.6 system-ui';
  panel.innerHTML = `<summary style="cursor:pointer;font-weight:bold">🛠 UIプレビュー（外部送信なし）</summary>
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin:8px 0"><a href="/">会話画面</a><a href="/login" id="debug-login">ログイン</a><a href="/characters">管理画面</a></div>
    <fieldset style="border:1px solid #d8b987;border-radius:8px;margin:8px 0;padding:10px"><legend>演出だけを再生</legend><label>増減値 <input id="debug-effect-delta" type="number" min="-100" max="100" step="1" value="4" style="width:64px"></label><div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px"><button type="button" data-effect="heart">ハート演出</button><button type="button" data-effect="up">＋4</button><button type="button" data-effect="down">−3</button><button type="button" data-effect="secret">ヒミツ公開</button><button type="button" data-effect="ending">告白成立</button></div><small>送信不要・進行は変わりません。ヒミツは何度でも再生できます。</small></fieldset>
    <label>シナリオ <select id="debug-scenario"><option value="normal">通常</option><option value="secret">ヒミツ解放直前（74）</option><option value="ending">好感度100直前</option><option value="confession">告白できる状態（100）</option><option value="lovers">恋人として会話</option><option value="locked">キャラクター未解放</option><option value="empty">キャラクターなし</option><option value="login">未ログイン</option></select></label>
    <label style="display:block;margin:8px 0">返信の待ち時間 <select id="debug-delay"><option value="0">なし</option><option value="400">0.4秒</option><option value="3000">3秒</option><option value="10000">10秒</option></select></label>
    <label style="display:block;margin:8px 0">好感度の増減 <input id="debug-delta" type="number" min="-100" max="100" step="1" style="width:72px">（次の返信に適用）</label>
    <label style="display:block;margin:8px 0">告白の返事 <select id="debug-accept"><option value="yes">受け入れる</option><option value="no">まだ待ってほしい</option></select></label><label style="display:block;margin:8px 0">エンディングの一枚絵 <input id="debug-art" type="file" accept="image/png,image/jpeg,image/webp" style="max-width:220px"></label><button type="button" id="debug-error">次のAPIをエラーにする</button> <button type="button" id="debug-reset">初期状態に戻す</button>
    <p style="margin:6px 0 0">データはメモリ内のみ。再起動でリセットされます。</p><span role="status" id="debug-notice"></span>`;
  document.body.append(panel);
  const find = id => panel.querySelector('#debug-' + id);
  let playing = false;
  panel.querySelectorAll('[data-effect]').forEach(button => {
    button.disabled = !globalThis.UIEffects;
    button.onclick = async () => {
      if (playing) return;
      const delta = Number(find('effect-delta').value);
      if (!Number.isFinite(delta) || delta < -100 || delta > 100 || !Number.isInteger(delta)) {
        find('notice').textContent = '増減値は−100〜100の整数で入力してください。'; return;
      }
      playing = true;
      panel.querySelectorAll('[data-effect]').forEach(item => item.disabled = true);
      panel.open = false;
      find('notice').textContent = '演出を再生しています…';
      try {
        const effect = button.dataset.effect;
        if (effect === 'secret' || effect === 'ending') await UIEffects[effect]();
        else await UIEffects.heart(effect === 'up' ? 4 : effect === 'down' ? -3 : delta);
        find('notice').textContent = '再生完了。同じボタンで再び試せます。';
      } catch (error) { find('notice').textContent = error.message; panel.open = true; }
      finally { playing = false; panel.querySelectorAll('[data-effect]').forEach(item => item.disabled = false); }
    };
  });
  const config = async body => {
    const response = await fetch('/__debug/config', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    if (!response.ok) throw new Error('設定に失敗しました');
  };
  find('scenario').value = state.scenario;
  find('delay').value = String(state.delay);
  find('accept').value = state.acceptConfession ? 'yes' : 'no';
  find('accept').onchange = async event => {await config({acceptConfession:event.target.value==='yes'});};
  find('art').onchange = event => {
    try {
      if(!globalThis.UIRomance) {find('notice').textContent='会話画面で画像を選んでください。';return;}
      UIRomance.setImage(event.target.files[0]);
      find('notice').textContent='一枚絵を反映しました（このタブを開いている間有効）。';
    } catch(error) {find('notice').textContent=error.message;}
  };
  find('delta').value = String(state.delta);
  find('delta').onchange = async event => {await config({delta:Number(event.target.value)});};
  find('scenario').onchange = async event => {await config({scenario:event.target.value}); location.assign(event.target.value === 'login' ? '/login' : '/');};
  find('delay').onchange = async event => {await config({delay:Number(event.target.value)});};
  find('login').onclick = async event => {event.preventDefault(); await config({scenario:'login'}); location.assign('/login');};
  find('error').onclick = async () => {await config({failNext:true}); find('notice').textContent = '次のAPIでエラーを返します。送信や画面移動を試してください。';};
  find('reset').onclick = async () => {await config({reset:true}); location.assign('/');};
})();
