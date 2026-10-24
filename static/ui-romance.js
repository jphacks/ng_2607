// Confession and lover UI shared by the application and UI preview.
(() => {
  const $ = selector => document.querySelector(selector);
  const card = document.createElement('section');
  card.className = 'romance-invitation'; card.hidden = true;
  card.innerHTML = '<div><small>A NEW CHAPTER</small><h3>ふたりの関係を、一歩先へ。</h3><p>あなたの気持ちを、言葉にして伝えてみませんか？</p></div><button type="button" class="romance-start">想いを伝える ♡</button><button type="button" class="romance-back" hidden>会話に戻る</button>';
  $('.composer-area').before(card);
  const memory = document.createElement('button');
  memory.type = 'button'; memory.className = 'romance-memory'; memory.textContent = '♡ 大切な思い出を見返す'; memory.hidden = true;
  $('.profile-content').append(memory);
  const scene = document.createElement('dialog'); scene.className = 'romance-scene';
  scene.setAttribute('aria-label','恋人になった日の思い出');
  scene.innerHTML = '<img class="romance-art" alt="ふたりの想いが重なった日の思い出"><div class="romance-shade"></div><div class="romance-particles" aria-hidden="true"></div><button type="button" class="romance-skip">演出をスキップ</button><div class="romance-story"><p class="romance-quote">「私も、あなたが好き。これからは、ずっと隣に。」</p><p>これからは恋人としての関係を楽しんでください。</p><button type="button" class="romance-continue">ふたりの時間を続ける <span>→</span></button></div>';
  document.body.append(scene);
  for(let i=0;i<38;i++) {
    const particle=document.createElement('i'); particle.textContent=i%3?'✦':'♥';
    particle.style.cssText=`--x:${(i*29)%100}%;--delay:${(i%9)*.17}s;--drift:${(i%2?1:-1)*(20+i%35)}px;--size:${12+i%17}px`;
    scene.querySelector('.romance-particles').append(particle);
  }
  let activeId=null, previousStatus=null, current=null, resolver=null, abort=null, signal=null;
  let imageURL=null;
  const fallbackReply=scene.querySelector(".romance-quote").textContent;
  const confessionReplies=new Map();
  const controller = {
    confessing:false,
    setImage(file) {
      if(!file || !['image/png','image/jpeg','image/webp'].includes(file.type)) throw new Error('PNG・JPEG・WebPの画像を選んでください。');
      if(imageURL) URL.revokeObjectURL(imageURL);
      imageURL=URL.createObjectURL(file);
      scene.querySelector('img').src=imageURL;
    },
    render(state) {
      current=state;
      const romance=state.snapshot?.romance;
      if(activeId!==state.selected?.id || previousStatus!==romance?.status) controller.confessing=false;
      activeId=state.selected?.id; previousStatus=romance?.status;
      const lovers=romance?.status==='lovers', ready=romance?.status==='ready';
      card.hidden=!ready && !lovers;
      card.classList.toggle('is-confessing',controller.confessing);
      card.classList.toggle('is-lovers',lovers);
      $('.chat').classList.toggle('confession-mode',controller.confessing);
      card.querySelector('small').textContent=lovers?'TO BE CONTINUED':controller.confessing?'YOUR WORDS, YOUR HEART':'A NEW CHAPTER';
      card.querySelector('h3').textContent=lovers?'♡ 恋人として、これからも。':controller.confessing?'想いを伝える時間':'ふたりの関係を、一歩先へ。';
      card.querySelector('p').textContent=lovers?'ふたりの時間は、これからも続いていきます。':controller.confessing?'あなた自身の言葉で、気持ちを届けてください。':romance?.declined?'焦らず、ふたりのペースで。いつもの会話も続けられます。':'あなたの気持ちを、言葉にして伝えてみませんか？';
      card.querySelector('.romance-start').hidden=!ready || controller.confessing;
      card.querySelector('.romance-back').hidden=!controller.confessing;
      card.querySelectorAll('button').forEach(button=>button.disabled=state.busy);
      memory.hidden=!lovers;
      state.input.placeholder=controller.confessing?'あなたへの想いを、ここに…':lovers?'恋人にメッセージを送る…':'Bluesky DMを送る…';
      state.send.setAttribute('aria-label',controller.confessing?'想いを届ける':'メッセージを送信');
      state.send.classList.toggle('confession-send',controller.confessing);
      if(controller.confessing) state.typing.textContent='あなたの言葉を、受け止めています…';
      else state.typing.textContent='返信を待っています…';
      if(lovers) $('.desktop-status').textContent='♡ 恋人';
      else $('.desktop-status').textContent='あなたとお話し中';
      $('.desktop-subtitle').textContent=lovers?'ふたりの時間は、これからも。':'ふたりの言葉を、少しずつ重ねて。';
    },
    celebrate(abortSignal, replyText) {
      const partnerId=current?.selected?.id;
      if(typeof replyText==='string' && replyText.trim() && partnerId) {
        confessionReplies.set(partnerId,replyText.trim());
      }
      scene.querySelector('.romance-quote').textContent=
        (typeof replyText==='string' && replyText.trim()) || confessionReplies.get(partnerId) || fallbackReply;
      controller.confessing=false;
      const artwork=scene.querySelector('img');
      artwork.onerror=()=>{artwork.alt='一枚絵を読み込めませんでした。static/ending-preview.png を確認してください。';};
      if(!imageURL) artwork.src='/ending-preview.png?v='+Date.now();
      scene.classList.remove('is-revealed');
      scene.showModal();
      scene.querySelector('.romance-skip').focus();
      return new Promise(resolve=>{
        resolver=resolve; signal=abortSignal; abort=()=>close();
        signal?.addEventListener('abort',abort,{once:true});
        if(signal?.aborted) close();
      });
    }
  };
  function close() {
    scene.close(); signal?.removeEventListener('abort',abort);
    const resolve=resolver; resolver=null; resolve?.();
    if(current) {controller.render(current); current.input.focus({preventScroll:true});}
  }
  card.querySelector('.romance-start').onclick=()=>{controller.confessing=true;controller.render(current);current.input.focus();};
  card.querySelector('.romance-back').onclick=()=>{controller.confessing=false;controller.render(current);};
  scene.querySelector('.romance-continue').onclick=close;
  scene.querySelector('.romance-skip').onclick=()=>{scene.classList.add('is-revealed');scene.querySelector('.romance-continue').focus();};
  scene.addEventListener('cancel',event=>{event.preventDefault();close();});
  memory.onclick=()=>controller.celebrate();
  globalThis.UIRomance=controller;
})();
