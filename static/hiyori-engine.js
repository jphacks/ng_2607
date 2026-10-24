// 好感度演出の状態を時刻から算出する純粋関数。
(function (root) {
  const clamp = (v, min = 0, max = 1) => Math.max(min, Math.min(max, v));
  const ease = p => 1 - (1 - p) ** 3;
  const REDUCED_DURATION = 200;
  function timeline(config, fromValue, toValue, options = {}) {
    const from = clamp(fromValue, 0, 100), to = clamp(toValue, 0, 100);
    const delta = to - from, count = Math.abs(delta);
    const launch = config.dim + config.appear + config.hold;
    const lastArrival = launch + config.flight;
    let duration = count ? lastArrival + config.bar + config.linger + config.fade : 0;
    if (options.reduced) duration = count ? REDUCED_DURATION : 0;
    return {from, to, delta, count, launch, lastArrival, duration, eventEnd: duration};
  }
  function evaluate(config, from, to, time, options = {}) {
    const tl = timeline(config, from, to, options);
    const t = clamp(time, 0, tl.duration);
    const progress = options.reduced ? clamp(t / REDUCED_DURATION) : ease(clamp((t - tl.lastArrival) / config.bar));
    const visual = tl.from + tl.delta * progress;
    const active = tl.count > 0 && t < tl.eventEnd;
    const emphasis = active && !options.reduced;
    const out = clamp((tl.eventEnd - t) / config.fade);
    return {
      t, ...tl, visual, affinity: options.reduced ? tl.to : Math.round(visual), active,
      dim: emphasis ? clamp(t / config.dim) * out : 0,
      highlight: emphasis ? clamp((t - config.dim) / 300) * out : 0,
      hearts: emphasis ? [{index:0, slot:0, appear:clamp((t-config.dim)/config.appear),
        flight:clamp((t-tl.launch)/config.flight), visible:t>=config.dim && t<tl.lastArrival}] : [],
    };
  }
  const api = {evaluate, timeline, clamp};
  if (typeof module !== 'undefined') module.exports = api;
  else root.AffectionEngine = api;
})(globalThis);
