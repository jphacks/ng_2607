// 好感度が上がったときの演出。状態は AffectionEngine で計算し、サーバー値の判定や更新は行わない。
class AffectionPlayer {
  constructor({messages,anchor,background,brand}) {
    Object.assign(this,{messages,anchor,background,brand});
    this.layer=document.createElement('div');this.layer.className='affection-event';this.layer.hidden=true;
    this.layer.setAttribute('role','dialog');this.layer.setAttribute('aria-label','好感度が上がりました');
    this.layer.innerHTML='<div class="event-dim"></div><div class="event-hearts" aria-hidden="true"></div><div class="event-caption"><h2>気持ちが、少し近づいた。</h2><p></p></div><div class="event-meter"><div class="event-meter-title">好感度 <strong></strong></div><progress max="100"></progress><p></p></div><button class="event-skip">演出をスキップ</button>';
    document.body.append(this.layer);
    this.layer.querySelector('button').onclick=()=>this.finish();
    this.layer.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();this.finish();}if(event.key==='Tab'){event.preventDefault();this.layer.querySelector('button').focus();}};
  }
  play(from,to,relationship,{signal,onFrame=()=>{}}={}) {
    this.cancel();
    if(to<=from)return Promise.resolve();
    this.from=from;this.to=to;
    this.reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.duration=AffectionEngine.timeline(AFFECTION_CONFIG,from,to,{reduced:this.reduced}).duration;
    this.label=relationship;this.onFrame=onFrame;this.focusBefore=document.activeElement;
    return new Promise(resolve=>{
      this.resolve=resolve;this.abort=()=>this.cancel();this.signal=signal;signal?.addEventListener('abort',this.abort,{once:true});
      if(signal?.aborted){this.cancel();return;}
      this.started=performance.now();
      if(!this.reduced){this.layer.hidden=false;this.background.inert=this.brand.inert=true;this.layer.querySelector('button').focus({preventScroll:true});}
      const tick=now=>{this.paint(Math.min(this.duration,now-this.started));if(now-this.started<this.duration)this.frame=requestAnimationFrame(tick);else this.finish();};
      this.frame=requestAnimationFrame(tick);
    });
  }
  paint(time) {
    const s=AffectionEngine.evaluate(AFFECTION_CONFIG,this.from,this.to,time,{reduced:this.reduced});this.onFrame(s);
    if(this.reduced)return;
    const layer=this.layer,meter=layer.querySelector('.event-meter'),mobile=innerWidth<=700;
    const rect=this.anchor.getBoundingClientRect();
    Object.assign(meter.style,{left:mobile?'20px':`${rect.left-16}px`,top:mobile?'76px':`${rect.top-16}px`,width:mobile?'calc(100% - 40px)':`${rect.width+32}px`});
    meter.style.setProperty('--highlight',s.highlight);meter.style.setProperty('--earned-start',`${s.visual?s.from/s.visual*100:100}%`);
    meter.querySelector('strong').textContent=s.affinity;meter.querySelector('progress').value=s.visual;meter.querySelector('p').textContent=this.label;
    layer.querySelector('.event-dim').style.opacity=s.dim*.58;
    const bounds=this.messages.getBoundingClientRect(),bar=meter.querySelector('progress').getBoundingClientRect();
    const cx=bounds.left+bounds.width/2,cy=bounds.top+bounds.height*.45;
    const caption=layer.querySelector('.event-caption');Object.assign(caption.style,{left:`${bounds.left+16}px`,width:`${bounds.width-32}px`,top:`${cy+56}px`,opacity:Math.min(1,time/500,(s.eventEnd-time)/600)});
    caption.querySelector('p').textContent=`${s.from} → ${s.to}　好感度 +${s.count}`;
    const hearts=layer.querySelector('.event-hearts');hearts.replaceChildren();
    for(const h of s.hearts.filter(h=>h.visible)) {
      const el=document.createElement('span');el.className='flying-heart';el.textContent='♥';
      const sx=cx+(h.slot-(Math.min(AFFECTION_CONFIG.capacity,s.count)-1)/2)*(mobile?44:56),sy=cy;
      const ex=bar.left+bar.width*(s.from+h.index+1)/100,ey=bar.top+bar.height/2,p=h.flight,q=1-p;
      const vanish=Math.max(0,(p-(1-180/AFFECTION_CONFIG.flight))/(180/AFFECTION_CONFIG.flight));
      const scale=h.appear<.7?.6+.52*h.appear/.7:1.12-.12*(h.appear-.7)/.3;
      Object.assign(el.style,{left:`${q*q*sx+2*q*p*(sx+(ex-sx)*.25)+p*p*ex}px`,top:`${q*q*sy+2*q*p*(Math.min(sy,ey)-90)+p*p*ey}px`,transform:`translate(-50%,-50%) scale(${scale*(1-.75*vanish)})`,opacity:Math.min(1,h.appear*2)*(1-vanish)});hearts.append(el);
    }
    const arrival=time-s.launch-AFFECTION_CONFIG.flight;
    const pulse=arrival>=0&&arrival<AFFECTION_CONFIG.launchGap*s.count?Math.max(0,1-(arrival%AFFECTION_CONFIG.launchGap)/AFFECTION_CONFIG.bar):0;
    meter.style.transform=`scale(${1+.03*pulse})`;meter.style.boxShadow=`0 0 ${24*pulse}px #ff5c9373`;
  }
  finish() {if(!this.resolve)return;this.paint(this.duration);this.cleanup(false);}
  cancel() {if(this.resolve)this.cleanup(true);}
  cleanup(cancelled) {
    cancelAnimationFrame(this.frame);this.signal?.removeEventListener('abort',this.abort);
    this.layer.hidden=true;this.layer.querySelector('.event-hearts').replaceChildren();this.background.inert=this.brand.inert=false;
    if(this.focusBefore?.isConnected&&!this.focusBefore.closest('[hidden]'))this.focusBefore.focus({preventScroll:true});
    const resolve=this.resolve;this.resolve=null;resolve({cancelled});
  }
}
