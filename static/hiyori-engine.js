// 好感度演出の状態を時刻から算出する純粋関数。DOM・タイマー・乱数は使用しない。
(function (root) {
  const clamp = (v, min = 0, max = 1) => Math.max(min, Math.min(max, v));
  const ease = p => 1 - (1 - p) ** 3;
  const REDUCED_DURATION = 200;
  function timeline(config, fromValue, toValue, options = {}) {
    const from = clamp(fromValue, 0, 100), to = clamp(toValue, from, 100), count = to - from;
    const launch = config.dim + config.appearGap * (config.capacity - 1) + config.appear + config.hold;
    const lastArrival = launch + config.launchGap * (count - 1) + config.flight;
    let duration = count ? lastArrival + config.bar + config.linger + config.fade : 0;
    if (options.reduced) duration = count ? REDUCED_DURATION : 0;
    return { from, to, count, launch, lastArrival, duration, eventEnd: duration };
  }
  function evaluate(config, from, to, time, options = {}) {
    const tl = timeline(config, from, to, options);
    const t = clamp(time, 0, tl.duration);
    const hearts = [];
    let arrivals = 0, visual = tl.from;
    for (let i = 0; i < tl.count; i++) {
      const depart = tl.launch + i * config.launchGap, arrive = depart + config.flight;
      // The first hearts appear together; later ones appear as earlier ones land.
      const birth = i < config.capacity ? config.dim + i * config.appearGap : tl.launch + (i - config.capacity) * config.launchGap + config.flight + config.appearGap;
      if (t >= arrive) arrivals++;
      visual += ease(clamp((t - arrive) / config.bar));
      hearts.push({ index: i, slot: i % config.capacity, appear: clamp((t - birth) / config.appear), flight: clamp((t - depart) / config.flight), visible: t >= birth && t < arrive });
    }
    let affinity = tl.from + arrivals;
    if (options.reduced) {
      visual = tl.from + (tl.to - tl.from) * clamp(t / REDUCED_DURATION);
      affinity = tl.to;
    }
    const active = tl.count > 0 && t < tl.eventEnd;
    const emphasis = active && !options.reduced;
    const out = clamp((tl.eventEnd - t) / config.fade);
    return {
      t, ...tl, affinity, visual, active,
      dim: emphasis ? clamp(t / config.dim) * out : 0,
      highlight: emphasis ? clamp((t - config.dim) / 300) * out : 0,
      hearts: emphasis ? hearts : [],
    };
  }
  const api = { evaluate, timeline, clamp };
  if (typeof module !== 'undefined') module.exports = api;
  else root.AffectionEngine = api;
})(globalThis);
