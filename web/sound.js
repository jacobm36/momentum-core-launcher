// Synthesized sound effects (Web Audio).
// Sound effects are synthesized with Web Audio, so there are no audio files.
const soundOn = () => localStorage.getItem("mcl-sound") !== "off";
let actx = null;
// Each voice is built against a given context/destination so it can also be rendered offline.
function voices(ctx, out, t0) {
  const tone = (f, d, type = "sine", v = 0.08, to = null, at = 0, atk = 0.01) => {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type; o.frequency.setValueAtTime(f, t0 + at);
    if (to) o.frequency.exponentialRampToValueAtTime(to, t0 + at + d);
    g.gain.setValueAtTime(0.0001, t0 + at);
    g.gain.exponentialRampToValueAtTime(v, t0 + at + Math.min(atk, d / 2));
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + at + d);
    o.connect(g).connect(out); o.start(t0 + at); o.stop(t0 + at + d + 0.02);
  };
  // Band-passed noise whose centre frequency sweeps, for whooshes.
  const sweep = (f0, f1, d, v, at = 0) => {
    const n = Math.ceil(ctx.sampleRate * d), buf = ctx.createBuffer(1, n, ctx.sampleRate), ch = buf.getChannelData(0);
    for (let i = 0; i < n; i++) ch[i] = Math.random() * 2 - 1;
    const s = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    s.buffer = buf; f.type = "bandpass"; f.Q.value = 3;
    f.frequency.setValueAtTime(f0, t0 + at); f.frequency.exponentialRampToValueAtTime(f1, t0 + at + d);
    g.gain.setValueAtTime(0.0001, t0 + at);
    g.gain.exponentialRampToValueAtTime(v, t0 + at + d * 0.8);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + at + d);
    s.connect(f).connect(g).connect(out); s.start(t0 + at);
  };
  // Sawtooth through a low-pass filter whose cutoff opens from `from` to `to`, for a heavy, brassy tone.
  const dark = (f, d, v, atk, at = 0, to = 1000, from = 200) => {
    const o = ctx.createOscillator(), lp = ctx.createBiquadFilter(), g = ctx.createGain();
    o.type = "sawtooth"; o.frequency.setValueAtTime(f, t0 + at);
    lp.type = "lowpass"; lp.Q.value = 1;
    lp.frequency.setValueAtTime(from, t0 + at); lp.frequency.exponentialRampToValueAtTime(to, t0 + at + d * 0.6);
    g.gain.setValueAtTime(0.0001, t0 + at);
    g.gain.exponentialRampToValueAtTime(v, t0 + at + atk);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + at + d);
    o.connect(lp).connect(g).connect(out); o.start(t0 + at); o.stop(t0 + at + d + 0.02);
  };
  return {
    tick: () => tone(900, 0.05, "triangle", 0.05, 600),
    cat: () => tone(400, 0.14, "triangle", 0.06, 900),
    open: () => tone(500, 0.1, "sine", 0.06, 750),
    ok: () => { tone(660, 0.12, "sine", 0.07); tone(990, 0.2, "sine", 0.07, null, 0.09); },
    del: () => tone(300, 0.18, "triangle", 0.07, 120),
    err: () => { tone(200, 0.12, "square", 0.04); tone(160, 0.18, "square", 0.04, null, 0.1); },
    // A rising whoosh into a punchy impact as the flash blooms.
    launch: () => {
      tone(180, 0.7, "sawtooth", 0.05, 1400); tone(360, 0.7, "triangle", 0.05, 2400); tone(1760, 0.3, "sine", 0.05, null, 0.55);
      sweep(200, 6000, 0.45, 0.22); tone(70, 0.6, "sine", 0.3, 28, 0.42, 0.004); sweep(3000, 150, 0.5, 0.18, 0.42);
    },
    // Jet spool-up into an explosive arcade impact as the splash bar completes.
    intro: () => {
      const lim = ctx.createDynamicsCompressor();
      lim.threshold.value = -14; lim.ratio.value = 8; lim.attack.value = 0.003; lim.release.value = 0.24;
      const master = ctx.createGain(); master.gain.value = 0.95;
      lim.connect(master).connect(out);
      const echo = ctx.createDelay(1), fb = ctx.createGain(), wet = ctx.createGain(), damp = ctx.createBiquadFilter();
      echo.delayTime.value = 0.12; fb.gain.value = 0.18; wet.gain.value = 0.12; damp.type = "lowpass"; damp.frequency.value = 1600;
      echo.connect(damp).connect(fb).connect(echo); damp.connect(wet).connect(lim);
      const bus = ctx.createGain(); bus.connect(lim); bus.connect(echo); out = bus;
      const noise = (d, kind, f, v, at) => {
        const n = Math.ceil(ctx.sampleRate * d), buf = ctx.createBuffer(1, n, ctx.sampleRate), ch = buf.getChannelData(0);
        for (let i = 0; i < n; i++) ch[i] = Math.random() * 2 - 1;
        const src = ctx.createBufferSource(), flt = ctx.createBiquadFilter(), g = ctx.createGain();
        src.buffer = buf; flt.type = kind; flt.frequency.value = f;
        g.gain.setValueAtTime(0.0001, t0 + at); g.gain.exponentialRampToValueAtTime(v, t0 + at + 0.004); g.gain.exponentialRampToValueAtTime(0.0001, t0 + at + d);
        src.connect(flt).connect(g).connect(out); src.start(t0 + at);
      };
      const turbine = (f, detune, v) => {
        const o = ctx.createOscillator(), lp = ctx.createBiquadFilter(), g = ctx.createGain();
        o.type = "sawtooth"; o.frequency.setValueAtTime(f, t0); o.frequency.exponentialRampToValueAtTime(f * 2.6, t0 + 1.65); o.detune.value = detune;
        lp.type = "lowpass"; lp.Q.value = 1.4;
        lp.frequency.setValueAtTime(110, t0); lp.frequency.exponentialRampToValueAtTime(3200, t0 + 1.65);
        g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(v, t0 + 1.45); g.gain.exponentialRampToValueAtTime(0.0001, t0 + 2.35);
        o.connect(lp).connect(g).connect(out); o.start(t0); o.stop(t0 + 2.38);
      };
      const roar = (at, d, attack, v, from, to) => {
        const buf = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * d), ctx.sampleRate);
        const samples = buf.getChannelData(0);
        for (let i = 0; i < samples.length; i++) samples[i] = Math.random() * 2 - 1;
        const src = ctx.createBufferSource(), hp = ctx.createBiquadFilter();
        const lp = ctx.createBiquadFilter(), g = ctx.createGain();
        src.buffer = buf; hp.type = "highpass"; hp.frequency.value = 55;
        lp.type = "lowpass"; lp.Q.value = 0.7;
        lp.frequency.setValueAtTime(from, t0 + at);
        lp.frequency.exponentialRampToValueAtTime(to, t0 + at + attack);
        lp.frequency.exponentialRampToValueAtTime(180, t0 + at + d);
        g.gain.setValueAtTime(0.0001, t0 + at);
        g.gain.exponentialRampToValueAtTime(v, t0 + at + attack);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + at + d);
        src.connect(hp).connect(lp).connect(g).connect(out); src.start(t0 + at);
      };
      turbine(46.25, -9, 0.09); turbine(47, 9, 0.075);
      roar(0, 2.35, 1.57, 0.42, 220, 5600);
      tone(480, 1.68, "sine", 0.035, 2100, 0, 1.5);
      sweep(110, 4800, 1.65, 0.17, 0.02);
      tone(38, 1.7, "sine", 0.12, 65, 0, 1.3);
      [0.08, 0.67, 1.18, 1.46].forEach(at => {
        tone(125, 0.18, "sine", 0.22, 40, at, 0.003);
        dark(73.42, 0.22, 0.09, 0.004, at, 900, 1800);
        dark(110, 0.18, 0.045, 0.004, at, 650, 1400);
        noise(0.09, "bandpass", 1800, 0.075, at);
      });
      const hit = 1.65, D = 73.42;
      roar(hit, 1.05, 0.008, 0.65, 5200, 6200);
      noise(0.7, "lowpass", 320, 0.36, hit);
      tone(155, 0.36, "sine", 0.34, 28, hit, 0.003);
      tone(D / 2, 0.85, "sine", 0.24, 30, hit, 0.004);
      dark(D, 0.85, 0.13, 0.006, hit, 180, 2400);
      dark(D * 1.5, 0.75, 0.085, 0.006, hit, 150, 1800);
      dark(D * 2, 0.65, 0.055, 0.006, hit, 220, 2800);
      noise(0.14, "highpass", 1900, 0.12, hit);
      noise(0.45, "bandpass", 850, 0.13, hit);
      sweep(4200, 160, 0.65, 0.11, hit);
    },
  };
}
function sfx(name) {
  rumble(name);
  if (!soundOn()) return;
  try {
    actx ||= new (window.AudioContext || window.webkitAudioContext)();
    if (actx.state === "suspended") actx.resume();
    if (actx.state !== "running") return;
    voices(actx, actx.destination, actx.currentTime)[name]?.();
  } catch { /* audio is optional */ }
}
