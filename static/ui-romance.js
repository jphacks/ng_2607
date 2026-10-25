// Confession and lover UI shared by the application and UI preview.
(() => {
  const $ = selector => document.querySelector(selector);
  const card = document.createElement('section');
  card.className = 'romance-invitation'; card.hidden = true;
  card.innerHTML = '<div><small>A NEW CHAPTER</small><h3>ふたりの関係を、一歩先へ。</h3><p></p></div>';
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
  let current=null, resolver=null, abort=null, signal=null;
  let imageURL=null;
  const fallbackReply=scene.querySelector(".romance-quote").textContent;
  const confessionReplies=new Map();
  const controller = {
    setImage(file) {
      if(!file || !['image/png','image/jpeg','image/webp'].includes(file.type)) throw new Error('PNG・JPEG・WebPの画像を選んでください。');
      if(imageURL) URL.revokeObjectURL(imageURL);
      imageURL=URL.createObjectURL(file);
      scene.querySelector('img').src=imageURL;
    },
    render(state) {
      current=state;
      const romance=state.snapshot?.romance;
      // A confession is read from the conversation itself; there is no confession button.
      const lovers=romance?.status==='lovers', declined=romance?.status==='ready' && romance?.declined;
      card.hidden=!lovers && !declined;
      card.classList.toggle('is-lovers',lovers);
      card.querySelector('small').textContent=lovers?'TO BE CONTINUED':'A NEW CHAPTER';
      card.querySelector('h3').textContent=lovers?'♡ 恋人として、これからも。':'ふたりの関係を、一歩先へ。';
      card.querySelector('p').textContent=lovers?'ふたりの時間は、これからも続いていきます。':'焦らず、ふたりのペースで。いつもの会話も続けられます。';
      memory.hidden=!lovers;
      state.input.placeholder=lovers?'恋人にメッセージを送る…':'Bluesky DMを送る…';
      state.typing.textContent='返信を待っています…';
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
  scene.querySelector('.romance-continue').onclick=close;
  scene.querySelector('.romance-skip').onclick=()=>{scene.classList.add('is-revealed');scene.querySelector('.romance-continue').focus();};
  scene.addEventListener('cancel',event=>{event.preventDefault();close();});
  memory.onclick=()=>controller.celebrate();
  globalThis.UIRomance=controller;
})();
