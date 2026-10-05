const $ = s => document.querySelector(s);
const animOn = () => localStorage.getItem("mcl-anim") !== "off";
function applySound() { $("#snd").textContent = soundOn() ? "🔊" : "🔇"; }
function applyFx() { document.body.classList.toggle("noanim", !animOn()); $("#fx").textContent = animOn() ? "✨ On" : "✨ Off"; }
const featuredPanel = () => localStorage.getItem("mcl-panel") === "featured";
function applyPanel() {
  const featured = featuredPanel(), button = $("#panel");
  $("#stage")?.classList.toggle("featured", featured);
  if (!button) return;
  button.textContent = featured ? "▣ Featured" : "▣ Classic";
  button.title = `Selected-game panel: ${featured ? "Featured" : "Classic"} (click to switch)`;
  button.setAttribute("aria-pressed", String(featured));
}
let games = [], token = "", running = new Set(), sel = null, filter = "", padOn = false, dragging = null, failed = {};

const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hue = s => [...s].reduce((a, c) => a + c.charCodeAt(0) * 7, 0) % 360;
let ver = Date.now(), shown = null, stats = {};

// Controller rumble: [startDelay ms, duration ms, weak, strong] pulses per sound name.
const rumbleOn = () => localStorage.getItem("mcl-rumble") !== "off";
function applyRumble() { $("#rum").classList.toggle("off", !rumbleOn()); $("#rum").title = rumbleOn() ? "Controller rumble: on" : "Controller rumble: off"; }
const RUMBLE = {
  cat: [[0, 70, 0.3, 0.1]],
  ok: [[0, 60, 0.4, 0.2], [90, 90, 0.6, 0.3]],
  del: [[0, 140, 0.2, 0.6]],
  err: [[0, 90, 0.5, 0.5], [140, 90, 0.5, 0.5]],
  launch: [[0, 140, 0.4, 0.9], [200, 90, 0.2, 0.4], [330, 380, 0.7, 1]],
};
function rumble(name) {
  const act = [...(navigator.getGamepads?.() || [])].find(Boolean)?.vibrationActuator;
  if (!rumbleOn() || !act || !RUMBLE[name]) return;
  for (const [startDelay, duration, weakMagnitude, strongMagnitude] of RUMBLE[name])
    act.playEffect("dual-rumble", { startDelay, duration, weakMagnitude, strongMagnitude }).catch(() => {});
}

// Each game gets an accent color: one you set in the edit form, or the dominant hue of its art.
const accentCache = new Map();
let accentKey = "";
function dominantColor(src) {
  if (accentCache.has(src)) return Promise.resolve(accentCache.get(src));
  return new Promise(res => {
    const im = new Image();
    im.onload = () => {
      const c = document.createElement("canvas"); c.width = c.height = 48;
      const x = c.getContext("2d", { willReadFrequently: true }); x.drawImage(im, 0, 0, 48, 48);
      const d = x.getImageData(0, 0, 48, 48).data, bins = new Float32Array(36);
      let tot = 0;
      for (let i = 0; i < d.length; i += 4) {
        const [h, s, v] = rgb2hsv(d[i], d[i + 1], d[i + 2]);
        if (s < 0.3 || v < 0.25) continue;
        const w = s * v; bins[Math.floor(h / 10) % 36] += w; tot += w;
      }
      let best = 0; for (let i = 1; i < 36; i++) if (bins[i] > bins[best]) best = i;
      const out = tot > 48 * 48 * 0.03 ? best * 10 + 5 : null;
      accentCache.set(src, out); res(out);
    };
    im.onerror = () => res(null);
    im.src = src;
  });
}
function rgb2hsv(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0;
  if (d) h = mx === r ? ((g - b) / d + 6) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, mx ? d / mx : 0, mx];
}
function hexHue(hex) { const n = parseInt(hex.slice(1), 16); return rgb2hsv(n >> 16, (n >> 8) & 255, n & 255)[0]; }
function setAccent(h) {
  const r = document.documentElement.style;
  if (h == null) { for (const k of ["--blue", "--violet", "--orange"]) r.removeProperty(k); return; }
  r.setProperty("--blue", `hsl(${h} 100% 60%)`);
  r.setProperty("--violet", `hsl(${(h + 38) % 360} 85% 62%)`);
  r.setProperty("--orange", `hsl(${(h + 322) % 360} 100% 58%)`);
}
async function applyAccent(g) {
  const key = [g.id, g.accent, g.cover, g.icon].join("|");
  if (key === accentKey) return;
  accentKey = key;
  if (g.accent) return setAccent(hexHue(g.accent));
  const src = g.cover || g.icon;
  setAccent(src ? accentCache.get(url(src)) ?? null : null);
  if (!src) return;
  const h = await dominantColor(url(src));
  if (accentKey === key) setAccent(h);
}

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
    // A rising turbine rush and arcade arpeggio crest together as the splash bar completes.
    intro: () => {
      const lim = ctx.createDynamicsCompressor();
      lim.threshold.value = -14; lim.ratio.value = 8; lim.attack.value = 0.003; lim.release.value = 0.24;
      const master = ctx.createGain(); master.gain.value = 1.18;
      lim.connect(master).connect(out);
      const echo = ctx.createDelay(1), fb = ctx.createGain(), wet = ctx.createGain(), damp = ctx.createBiquadFilter();
      echo.delayTime.value = 0.19; fb.gain.value = 0.3; wet.gain.value = 0.24; damp.type = "lowpass"; damp.frequency.value = 2800;
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
      turbine(58, -7, 0.06); turbine(87, 7, 0.04);
      sweep(110, 6800, 1.65, 0.17, 0.02);
      tone(43, 1.8, "sine", 0.13, 92, 0, 1.4);
      [146.8, 174.6, 220, 261.6, 293.7, 349.2, 440].forEach((f, i) => {
        const at = 0.5 + i * 0.155;
        tone(f, 0.28, "square", 0.025, f * 1.015, at, 0.004);
      });
      const hit = 1.65, D = 73.42;
      tone(46, 0.7, "sine", 0.2, 30, hit, 0.003);
      tone(D, 0.9, "sine", 0.27, D / 2, hit, 0.004);
      tone(D * 4, 0.65, "triangle", 0.05, D * 8, hit, 0.008);
      tone(D * 6, 0.6, "square", 0.028, D * 8, hit, 0.008);
      noise(0.5, "highpass", 2400, 0.105, hit);
      sweep(6800, 260, 0.7, 0.1, hit);
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

const ago = t => {
  const s = Date.now() / 1000 - t;
  if (s < 90) return "just now";
  for (const [n, u] of [[86400, "day"], [3600, "hour"], [60, "minute"]]) if (s >= n) { const k = Math.floor(s / n); return `${k} ${u}${k > 1 ? "s" : ""} ago`; }
};
const dur = s => s < 60 ? "under a minute" : s < 3600 ? `${Math.round(s / 60)} min` : `${Math.floor(s / 3600)}h ${Math.round(s % 3600 / 60)}m`;
const statText = id => { const s = stats[id]; return s?.launches ? `Last played ${ago(s.last)} · ${s.launches} launch${s.launches > 1 ? "es" : ""}${s.seconds ? " · " + dur(s.seconds) + " played" : ""}` : "Not played yet"; };
const recent = () => games.filter(g => stats[g.id]?.last).sort((a, b) => stats[b.id].last - stats[a.id].last).slice(0, 5);
const url = p => `/${p}?v=${ver}`;
const thumb = g => g.icon ? `<img src="${url(g.icon)}" alt="">` : `<div class="ph">${esc(g.name[0])}</div>`;

function visible() {
  const q = filter.toLowerCase();
  return games.filter(g => g.name.toLowerCase().includes(q) || (g.tags || []).some(t => t.toLowerCase().includes(q)));
}

// Games grouped by category, in the order categories first appear in games.json.
function ordered() {
  const cats = [...new Set(visible().map(g => g.category || "Other"))];
  return cats.map(c => ({ cat: c, items: visible().filter(g => (g.category || "Other") === c) }));
}
const flat = () => ordered().flatMap(c => c.items);

const row = (g, drag = true) => `<div class="item ${g.id === sel ? "sel" : ""}" data-id="${g.id}" ${filter || !drag ? "" : 'draggable="true"'}>${thumb(g)}<span>${esc(g.name)}</span>${g.favorite ? '<i class="star" title="Favorite">★</i>' : ""}${running.has(g.id) ? '<i class="dot" title="Running"></i>' : ""}</div>`;
const favs = () => games.filter(g => g.favorite);
// Re-rendering replaces elements, so put gamepad/keyboard focus back on the equivalent one.
function keepFocus(fn) {
  const a = document.activeElement; let sel = null;
  if (a?.closest("#list, #detail")) sel = a.id ? "#" + a.id : a.dataset.act ? `.cat[data-cat="${CSS.escape(a.closest(".cat").dataset.cat)}"] [data-act="${a.dataset.act}"]` : null;
  fn();
  if (sel) document.querySelector(sel)?.focus();
}
function renderList() { keepFocus(renderListInner); }
function renderListInner() {
  const rc = filter ? [] : recent(), fv = filter ? [] : favs();
  $("#list").innerHTML = (fv.length ? `<div class="cat favs"><span>★ Favorites</span></div>` + fv.map(g => row(g, false)).join("") : "") + (rc.length ? `<div class="cat recent"><span>Recently played</span></div>` + rc.map(g => row(g, false)).join("") : "") + ordered().map(c =>
    `<div class="cat" data-cat="${esc(c.cat)}"><span>${esc(c.cat)}</span>${filter ? "" : '<span class="catbtns"><b tabindex="0" role="button" data-act="up" title="Move category up">▲</b><b tabindex="0" role="button" data-act="down" title="Move category down">▼</b><b tabindex="0" role="button" data-act="rename" title="Rename category">✎</b></span>'}</div>` + c.items.map(g => row(g)).join("")).join("");
}

function renderDetail() { keepFocus(renderDetailInner); }
function renderDetailInner() {
  const g = games.find(x => x.id === sel), el = $("#detail"), bg = $("#bg"), art = $("#art");
  if (!g) {
    el.innerHTML = games.length ? '<p class="empty">No games found.</p>'
      : `<div class="welcome"><h1>Welcome to Momentum</h1><p>Your library is empty. Add your first game, or import every game that already has a <code>.desktop</code> shortcut.</p><button id="welcome-add" class="primary">+ Add a game</button><p class="hint">Or run <code>./import_games.py</code> in the launcher folder, then reopen this window.</p></div>`;
    $("#welcome-add")?.addEventListener("click", () => editor());
    return;
  }
  const on = running.has(g.id);
  if (shown !== g.id) { shown = g.id; for (const n of [el, art]) { n.classList.remove("swap"); void n.offsetWidth; n.classList.add("swap"); } }
  const tagline = `<div class="tagline">${esc(g.tagline || g.category || "")}</div>`;
  const tags = `<div class="tags">${(g.tags || []).map(t => `<span>${esc(t)}</span>`).join("")}</div>`;
  const play = `<button id="play" ${on ? "disabled" : ""}>${on ? "RUNNING" : "▶ PLAY"}</button>`;
  const actions = `${play}<span id="toast"></span><span class="manage"><button id="fav" aria-pressed="${!!g.favorite}">${g.favorite ? "★ Favorited" : "☆ Favorite"}</button><button id="edit">Edit</button><button id="del">Remove</button></span>`;
  if (featuredPanel()) {
    const image = g.cover || g.icon;
    const media = image
      ? `<img class="${g.cover ? "cover" : "icon"}" src="${esc(url(image))}" alt="">`
      : `<div class="feature-monogram">${esc(g.name[0] || "?")}</div>`;
    el.innerHTML = `<div class="feature-art">${media}</div><div class="feature-copy">
      <div class="feature-top">${tagline}<div class="feature-badges">${on ? '<span class="running-badge">● Running</span>' : ""}${g.favorite ? '<span class="favorite-badge">★ Favorite</span>' : ""}</div></div>
      <h1>${esc(g.name)}</h1><p class="desc">${esc(g.description || "")}</p>${tags}
      <div class="stats">${statText(g.id)}</div><div class="feature-actions">${actions}</div>
    </div>`;
  } else {
    el.innerHTML = `${tagline}<h1>${esc(g.name)}</h1>
      <p class="desc">${esc(g.description || "")}</p>${tags}
      <div class="stats">${statText(g.id)}</div>${actions}`;
  }
  $("#play").onclick = () => launch(g);
  $("#fav").onclick = () => toggleFav(g);
  $("#edit").onclick = () => editor(g);
  $("#del").onclick = () => removeGame(g);
  if (g.video) { if (!bg.src.includes(g.video + "?v=" + ver)) bg.src = url(g.video); bg.play().catch(() => {}); bg.classList.add("on"); }
  else { bg.classList.remove("on"); bg.removeAttribute("src"); }
  applyAccent(g);
  if (g.cover) { art.classList.remove("fallback"); art.style.background = `center/cover url("${url(g.cover)}")`; }
  else { art.classList.add("fallback"); art.style.background = `radial-gradient(circle at 78% 25%, hsl(${hue(g.id)} 70% 28%), transparent 60%), radial-gradient(circle at 20% 90%, hsl(${(hue(g.id) + 80) % 360} 60% 18%), transparent 60%)`; }
}

async function launch(g) {
  if (running.has(g.id)) return;
  $("#toast").textContent = "Launching…";
  const r = await fetch(`/api/launch/${g.id}`, { method: "POST", headers: { "X-Token": token } });
  const j = await r.json();
  if (j.error) { $("#toast").textContent = "Error: " + j.error; sfx("err"); return; }
  sfx("launch");
  const pb = $("#play")?.getBoundingClientRect();
  if (animOn()) {
    const f = $("#flash");
    if (pb) { f.style.setProperty("--fx", pb.left + pb.width / 2 + "px"); f.style.setProperty("--fy", pb.top + pb.height / 2 + "px"); }
    f.classList.remove("on"); void f.offsetWidth; f.classList.add("on");
    document.body.classList.add("blast"); setTimeout(() => document.body.classList.remove("blast"), 2800);
  }
  running.add(g.id); renderList(); renderDetail();
  if (animOn()) { $("#lname").textContent = g.name; const l = $("#launching"); l.classList.add("on"); setTimeout(() => l.classList.remove("on"), 2600); }
}

const post = (path, body, raw) => fetch(path, { method: "POST", headers: { "X-Token": token }, body: raw || JSON.stringify(body || {}) });

async function toggleFav(g) {
  if (!g) return;
  const on = !g.favorite;
  await post(`/api/favorite/${g.id}`, { on });
  sfx(on ? "ok" : "tick");
  await refresh(); renderDetail();
}

async function removeGame(g) {
  if (!await ask("Remove game?", `Remove "${g.name}" from the launcher? Game files and media are not deleted.`, "Remove")) return;
  const l = flat(), i = l.findIndex(x => x.id === g.id), next = (l[i + 1] || l[i - 1])?.id;
  await post(`/api/delete/${g.id}`); sfx("del");
  await refresh(); select(next && next !== g.id ? next : flat()[0]?.id);
}

const ACCEPT = { cover: "image/*", icon: "image/*", video: "video/mp4,video/webm" };
const LABEL = { cover: "Background art", icon: "Icon", video: "Background video" };
const extOf = f => (f.name.split(".").pop() || "").toLowerCase();
const kindOfFile = f => f.type.startsWith("video/") ? "video" : f.type.startsWith("image/") ? "cover" : null;

async function sendMedia(id, kind, p) {
  const r = p.file
    ? await post(`/api/upload/${id}/${kind}?ext=${encodeURIComponent(extOf(p.file))}`, null, p.file)
    : await post(`/api/fetch/${id}/${kind}`, { url: p.url });
  return r.json();
}

function editor(g) {
  const isNew = !g, d = $("#dlg"), f = $("#form"), pending = {}, blobs = [];
  g = g || { tags: [] };
  const cats = [...new Set(games.map(x => x.category).filter(Boolean))];
  const slot = k => `<div class="slot" data-kind="${k}"><div class="slot-h">${LABEL[k]}</div>
    <div class="preview" id="pv-${k}"></div>
    <div class="slot-in"><input type="file" name="${k}" accept="${ACCEPT[k]}"><input type="url" name="url-${k}" placeholder="…or paste a link (https://)"></div>
    <small class="drop-hint">Drop a file here${k === "cover" ? " or paste an image" : ""}.
    ${g[k] ? `<a href="#" data-clear="${k}">Remove current</a>` : ""}${k === "video" ? ' <a href="#" id="frame" hidden>Use current frame as cover</a>' : ""}</small></div>`;
  f.innerHTML = `<h2>${isNew ? "Add game" : "Edit " + esc(g.name)}</h2>
    <label>Name *<span class="row"><input name="name" required value="${esc(g.name || "")}"><button type="button" id="steam">Look up on Steam</button></span></label>
    <div id="steamres"></div>
    <label>Launch command or script path *<input name="exec" required value="${esc(g.exec || "")}" placeholder="/home/you/Games/game.sh"></label>
    <label>Working directory (optional)<input name="cwd" value="${esc(g.cwd || "")}"></label>
    <label>Category<input name="category" list="cats" value="${esc(g.category || "")}"><datalist id="cats">${cats.map(c => `<option value="${esc(c)}">`).join("")}</datalist></label>
    <label>Accent color (optional, like #ff3030; blank = automatic from the art)<input name="accent" value="${esc(g.accent || "")}" placeholder="#ff3030" pattern="#[0-9a-fA-F]{6}"></label>
    <label>Tagline<input name="tagline" value="${esc(g.tagline || "")}"></label>
    <label>Description<textarea name="description" rows="4">${esc(g.description || "")}</textarea></label>
    <label>Tags (comma separated)<input name="tags" value="${esc((g.tags || []).join(", "))}"></label>
    ${["cover", "icon", "video"].map(slot).join("")}
    <div class="err" id="ferr"></div>
    <div class="padhint" ${padOn ? "" : "hidden"}><kbd>D-pad</kbd>Move <kbd>A</kbd>Select / type <kbd>Start</kbd>Save <kbd>B</kbd>Cancel</div>
    <div class="btns"><button type="button" id="cancel">Cancel</button><button type="submit" class="primary">Save</button></div>`;

  const preview = k => {
    const el = $("#pv-" + k), p = pending[k], src = p ? (p.file ? (p.blobUrl ||= URL.createObjectURL(p.file)) : p.url) : g[k] ? url(g[k]) : "";
    if (p?.blobUrl) blobs.push(p.blobUrl);
    el.innerHTML = !src ? "" : k === "video" ? `<video src="${esc(src)}" controls muted preload="metadata"></video>` : `<img src="${esc(src)}" alt="">`;
    if (k === "video") $("#frame").hidden = !src;
  };
  const setPending = (k, p) => { pending[k] = p; if (!p.file) f.elements[k].value = ""; f.elements["url-" + k].value = p.url || ""; preview(k); };
  ["cover", "icon", "video"].forEach(k => {
    preview(k);
    f.elements[k].onchange = e => { const file = e.target.files[0]; if (file) setPending(k, { file }); };
    f.elements["url-" + k].onchange = e => { const v = e.target.value.trim(); if (v) setPending(k, { url: v }); else delete pending[k], preview(k); };
    const s = f.querySelector(`.slot[data-kind="${k}"]`);
    s.ondragover = e => { if ([...e.dataTransfer.types].includes("Files")) { e.preventDefault(); s.classList.add("over"); } };
    s.ondragleave = () => s.classList.remove("over");
    s.ondrop = e => { e.preventDefault(); e.stopPropagation(); s.classList.remove("over"); const file = e.dataTransfer.files[0]; if (file) setPending(k, { file }); };
  });
  f.onpaste = e => { const file = [...e.clipboardData.files].find(x => x.type.startsWith("image/")); if (file) { e.preventDefault(); setPending("cover", { file: new File([file], "pasted." + (file.type.split("/")[1] || "png"), { type: file.type }) }); } };
  f.querySelectorAll("[data-clear]").forEach(a => a.onclick = async e => {
    e.preventDefault(); const k = a.dataset.clear;
    await post(`/api/clear/${g.id}/${k}`, {}); g[k] = null; delete pending[k]; a.remove(); ver = Date.now(); preview(k); await refresh(); renderDetail();
  });
  $("#frame").onclick = e => {
    e.preventDefault();
    const v = $("#pv-video video"); if (!v) return;
    try {
      const c = document.createElement("canvas"); c.width = v.videoWidth; c.height = v.videoHeight;
      c.getContext("2d").drawImage(v, 0, 0);
      c.toBlob(b => b ? setPending("cover", { file: new File([b], "frame.jpg", { type: "image/jpeg" }) }) : ($("#ferr").textContent = "Couldn't grab a frame."), "image/jpeg", 0.92);
    } catch { $("#ferr").textContent = "Frames can only be grabbed from videos on this computer: upload the file, or save first."; }
  };

  $("#steam").onclick = async () => {
    const q = f.elements.name.value.trim(), box = $("#steamres");
    if (!q) { box.textContent = "Type the game's name first."; return; }
    box.textContent = "Searching Steam…";
    const j = await (await post("/api/steam/search", { q })).json();
    if (j.error || !j.results.length) { box.textContent = j.error || "No Steam matches."; return; }
    box.innerHTML = j.results.map(r => `<div class="sr" tabindex="0" data-id="${r.id}">${r.image ? `<img src="${esc(r.image)}" alt="">` : ""}<span>${esc(r.name)}</span></div>`).join("");
    box.onclick = async e => {
      const row = e.target.closest(".sr"); if (!row) return;
      box.textContent = "Fetching details…";
      const dd = await (await post("/api/steam/details", { appid: row.dataset.id })).json();
      if (dd.error) { box.textContent = dd.error; return; }
      f.elements.description.value = dd.description || f.elements.description.value;
      f.elements.tags.value = dd.tags.join(", ") || f.elements.tags.value;
      if (!f.elements.tagline.value) f.elements.tagline.value = dd.tagline || "";
      if (isNew && dd.name) f.elements.name.value = dd.name;
      box.innerHTML = `<div class="slot-h">Pick a background (click one)</div><div class="thumbs">${dd.covers.map((u, n) => `<img tabindex="0" src="${esc(u)}" data-u="${esc(u)}" class="${n ? "" : "picked"}" alt="">`).join("")}</div>`;
      if (dd.covers[0]) setPending("cover", { url: dd.covers[0] });
      if (dd.icon && !g.icon) setPending("icon", { url: dd.icon });
      box.onclick = ev => { const im = ev.target.closest("img[data-u]"); if (!im) return; box.querySelectorAll("img").forEach(x => x.classList.toggle("picked", x === im)); setPending("cover", { url: im.dataset.u }); };
    };
  };

  const snap = () => JSON.stringify([...new FormData(f)].filter(([, v]) => typeof v === "string"));
  const before = snap();
  f.dirty = () => snap() !== before || Object.keys(pending).length > 0;
  d.onclose = () => blobs.forEach(URL.revokeObjectURL);
  $("#cancel").onclick = () => d.close();
  f.onsubmit = async e => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(f).entries()), err = $("#ferr");
    const r = await post("/api/save", { id: g.id, ...v, tags: v.tags.split(",") }), j = await r.json();
    if (j.error) { err.textContent = j.error; sfx("err"); return; }
    g.id = j.id; // so a retry after a failed upload edits this game instead of adding another
    for (const k of Object.keys(pending)) {
      err.textContent = `Saving ${LABEL[k].toLowerCase()}…`;
      const u = await sendMedia(j.id, k, pending[k]);
      if (u.error) { err.textContent = `${LABEL[k]}: ${u.error}. Fix it or clear that field, then Save again.`; delete pending[k].file; return; }
      delete pending[k];
    }
    d.close(); sfx("ok"); ver = Date.now(); await refresh(); select(j.id);
  };
  d.showModal(); sfx("open");
}

// Drop an image or video on the game page, or paste an image, to set that game's cover/video.
async function quickMedia(file) {
  const g = games.find(x => x.id === sel), k = kindOfFile(file);
  if (!g || !k) return;
  $("#toast").textContent = `Saving ${LABEL[k].toLowerCase()}…`;
  const j = await sendMedia(g.id, k, { file });
  if (j.error) { $("#toast").textContent = "Error: " + j.error; return; }
  ver = Date.now(); await refresh(); renderDetail();
}
const hasFiles = e => [...(e.dataTransfer?.types || [])].includes("Files");
$("#stage").addEventListener("dragover", e => { if (hasFiles(e) && !topDlg()) e.preventDefault(); });
$("#stage").addEventListener("drop", e => { if (hasFiles(e) && !topDlg()) { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) quickMedia(f); } });
document.addEventListener("paste", e => {
  if (topDlg() || /^(INPUT|TEXTAREA)$/.test(e.target.tagName)) return;
  const f = [...e.clipboardData.files].find(x => x.type.startsWith("image/"));
  if (f) quickMedia(new File([f], "pasted." + (f.type.split("/")[1] || "png"), { type: f.type }));
});
$("#add").onclick = () => editor();

// Reordering: games.json order is the source of truth; categories appear in order of first use.
function groups() {
  const m = new Map();
  for (const g of games) { const c = g.category || "Other"; if (!m.has(c)) m.set(c, []); m.get(c).push(g.id); }
  return m;
}
async function saveOrder(m) {
  const items = [...m].flatMap(([category, ids]) => ids.map(id => ({ id, category })));
  await post("/api/reorder", { items });
  await refresh(); renderDetail();
}
function moveGame(id, targetId, after, cat) {
  const m = groups();
  for (const ids of m.values()) { const i = ids.indexOf(id); if (i >= 0) ids.splice(i, 1); }
  if (targetId) {
    for (const [c, ids] of m) { const i = ids.indexOf(targetId); if (i >= 0) { ids.splice(i + (after ? 1 : 0), 0, id); break; } }
  } else m.set(cat, [id, ...(m.get(cat) || [])]);
  for (const [c, ids] of m) if (!ids.length) m.delete(c);
  return saveOrder(m);
}
function nudge(id, d) { // move within its category
  const m = groups();
  for (const ids of m.values()) {
    const i = ids.indexOf(id), j = i + d;
    if (i >= 0 && j >= 0 && j < ids.length) { [ids[i], ids[j]] = [ids[j], ids[i]]; return saveOrder(m); }
  }
}
function moveCat(cat, d) {
  const e = [...groups()], i = e.findIndex(x => x[0] === cat), j = i + d;
  if (j < 0 || j >= e.length) return;
  [e[i], e[j]] = [e[j], e[i]];
  return saveOrder(new Map(e));
}
async function renameCat(cat) {
  const to = await oskPrompt(`Rename category "${cat}"`, cat);
  if (!to || !to.trim() || to.trim() === cat) return;
  await post("/api/category/rename", { from: cat, to: to.trim() });
  await refresh(); renderDetail();
}

function select(id) {
  if (id !== sel) sfx("tick");
  sel = id; localStorage.setItem("mcl-last", id); renderList(); renderDetail();
  [...document.querySelectorAll(".item.sel")].pop()?.scrollIntoView({ block: "nearest", behavior: animOn() ? "smooth" : "auto" });
}
function step(d) { const l = flat(), i = l.findIndex(g => g.id === sel); if (l.length) select(l[(i + d + l.length) % l.length].id); } // wraps around at either end
// Jump to the Favorites or Recently played section; pressing again steps through its games.
function jumpTo(list) {
  if (filter || !list.length) return;
  const i = list.findIndex(g => g.id === sel);
  select(list[(i + 1) % list.length].id); sfx("cat");
}
function jump(d) { // previous/next category
  const cs = ordered(); if (!cs.length) return;
  const ci = cs.findIndex(c => c.items.some(g => g.id === sel));
  select(cs[(ci + d + cs.length) % cs.length].items[0].id); sfx("cat");
}

async function refresh(first) {
  const j = await (await fetch("/api/games")).json();
  token = j.token; games = j.games; stats = j.stats || {}; running = new Set(j.running); failed = j.failed || {};
  if (first) { const last = localStorage.getItem("mcl-last"); sel = games.some(g => g.id === last) ? last : flat()[0]?.id; }
  if (!dragging) renderList();
  if (first || ($("#play") && $("#play").disabled !== running.has(sel)) || (sel && $("#detail .stats")?.textContent !== statText(sel))) renderDetail();
  const t = $("#toast");
  if (t && sel && failed[sel] !== undefined && !running.has(sel) && !t.textContent) t.textContent = `Last launch exited with code ${failed[sel]} — see logs/${sel}.log`;
}

$("#list").onclick = e => {
  const b = e.target.closest("[data-act]");
  if (b) { const c = b.closest(".cat").dataset.cat, act = b.dataset.act; return act === "rename" ? renameCat(c) : moveCat(c, act === "up" ? -1 : 1); }
   const i = e.target.closest(".item"); if (i) select(i.dataset.id); };
if ($("#panel")) $("#panel").onclick = () => {
  localStorage.setItem("mcl-panel", featuredPanel() ? "classic" : "featured");
  applyPanel(); renderDetail();
};
const clearDrop = () => document.querySelectorAll(".drop-before,.drop-after,.drop-into").forEach(x => x.classList.remove("drop-before", "drop-after", "drop-into"));
$("#list").addEventListener("dragstart", e => { const i = e.target.closest(".item"); if (i) { dragging = i.dataset.id; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", dragging); } });
$("#list").addEventListener("dragend", () => { dragging = null; clearDrop(); });
$("#list").addEventListener("dragover", e => {
  if (!dragging) return;
  const i = e.target.closest(".item"), c = e.target.closest(".cat");
  if (!i && !c) return;
  e.preventDefault(); clearDrop();
  if (i) { const r = i.getBoundingClientRect(); i.classList.add(e.clientY > r.top + r.height / 2 ? "drop-after" : "drop-before"); }
  else c.classList.add("drop-into");
});
$("#list").addEventListener("drop", async e => {
  if (!dragging) return;
  const i = e.target.closest(".item"), c = e.target.closest(".cat"), id = dragging;
  e.preventDefault();
  const after = i && e.clientY > i.getBoundingClientRect().top + i.offsetHeight / 2;
  clearDrop(); dragging = null;
  if (i && i.dataset.id !== id) await moveGame(id, i.dataset.id, after);
  else if (c) await moveGame(id, null, false, c.dataset.cat);
});
$("#search").oninput = e => { filter = e.target.value; renderList(); };
document.addEventListener("keydown", e => {
  if (e.ctrlKey && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "q") {
    e.preventDefault();
    if (!$("#splash") && !topDlg()) { $("#search").blur(); askQuit(); }
    return;
  }
  if (topDlg()) return;
  const inSearch = e.target.id === "search";
  if (inSearch && !["ArrowDown", "ArrowUp", "Enter", "Escape"].includes(e.key)) return;
  if (e.altKey && !filter && (e.key === "ArrowDown" || e.key === "ArrowUp")) { nudge(sel, e.key === "ArrowDown" ? 1 : -1); e.preventDefault(); }
  else if (e.key === "ArrowDown") { step(1); e.preventDefault(); }
  else if (e.key === "ArrowUp") { step(-1); e.preventDefault(); }
  else if (e.key.toLowerCase() === "r" && !e.ctrlKey && !e.metaKey && !e.altKey && !inSearch && !e.target.closest("button, input, textarea")) jumpTo(recent());
  else if (e.key === "F" && e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey && !inSearch && !e.target.closest("button, input, textarea")) jumpTo(favs());
  else if (e.key.toLowerCase() === "f" && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey && !inSearch && !e.target.closest("button, input, textarea")) toggleFav(games.find(x => x.id === sel));
  else if (e.key === "PageDown") jump(1);
  else if (e.key === "PageUp") jump(-1);
  else if (e.key === "Escape") {
    if ($("#splash")) return; // Esc just skips the intro
    $("#search").value = ""; filter = ""; $("#search").blur(); renderList();
  }
  else if ((e.key === "Enter" || e.key === " ") && e.target.closest("[data-act]")) { e.target.click(); e.preventDefault(); }
  else if (e.key === "Enter" && !e.target.closest("button")) { const g = games.find(x => x.id === sel); if (g) launch(g); }
});

// Gamepad. Main screen: D-pad/stick = move, A = play, LB/RB = category, X = add game, Y = edit game,
// Start = menu mode (move focus between every button), B = clear search / leave menu mode.
// In dialogs: D-pad moves focus, A presses or edits a text field (on-screen keyboard), Start = save/done, B = cancel.
const held = {};
let uiMode = false;
function pressed(key, on, fn, repeat = 180) {
  const now = performance.now();
  if (!on) { delete held[key]; return; }
  if (!held[key] || now - held[key].t > (held[key].n ? repeat : 400)) { held[key] = { t: now, n: true }; fn(); }
}
const topDlg = () => ["odlg", "qdlg", "dlg"].map(i => $("#" + i)).find(d => d.open);
const FOCUSABLE = 'button,input:not([type=file]):not([type=hidden]),textarea,a[href],[tabindex="0"]';
const focusables = scope => [...scope.querySelectorAll(FOCUSABLE)].filter(e => !e.disabled && !e.hidden && e.getClientRects().length && !(e.closest("#odlg") && e.id === "oinp"));
function moveFocus(dir) {
  const scope = topDlg() || document.body, items = focusables(scope), cur = document.activeElement;
  if (!items.includes(cur)) { (items.find(e => e.id === "play") || items[0])?.focus(); return; }
  if (cur.closest("#list") && (dir === "up" || dir === "down")) { // the category buttons form one column, so step through them in order
    const col = items.filter(e => e.closest("#list")), n = col[col.indexOf(cur) + (dir === "down" ? 1 : -1)];
    if (n) { n.focus(); sfx("tick"); return; }
  }
  const r = cur.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  let best = null, bs = Infinity;
  for (const e of items) {
    if (e === cur) continue;
    const q = e.getBoundingClientRect(), dx = q.left + q.width / 2 - cx, dy = q.top + q.height / 2 - cy;
    const vert = dir === "up" || dir === "down", sign = dir === "down" || dir === "right" ? 1 : -1;
    const fwd = (vert ? dy : dx) * sign, side = Math.abs(vert ? dx : dy);
    if (fwd <= 2) continue;
    const score = fwd + side * 2;
    if (score < bs) { bs = score; best = e; }
  }
  if (best) { best.focus(); sfx("tick"); }
}
const isText = e => e.tagName === "TEXTAREA" || (e.tagName === "INPUT" && !/^(checkbox|radio|button|submit|file)$/.test(e.type));
async function editField(el) {
  const label = (el.closest("label")?.childNodes[0]?.textContent || el.placeholder || "Text").trim();
  const v = await oskPrompt(label, el.value, { multiline: el.tagName === "TEXTAREA" });
  if (v === null) return;
  el.value = v;
  for (const t of ["input", "change"]) el.dispatchEvent(new Event(t, { bubbles: true }));
}
function activate() {
  const el = document.activeElement;
  if (!focusables(topDlg() || document.body).includes(el)) { moveFocus("down"); return; }
  if (el.closest("#odlg") && isText(el)) return;
  if (isText(el)) editField(el); else el.click();
  if (el.id === "play") leaveUi();
}
function enterUi() { uiMode = true; moveFocus("down"); }
function leaveUi() { uiMode = false; document.activeElement?.blur(); }
async function cancelDialog(d) {
  if (d.id === "dlg" && $("#form").dirty?.() && !await ask("Discard changes?", "Your edits to this game won't be saved.", "Discard")) return;
  d.close("cancel");
}
function padAction(b, ax, ay) {
  const d = topDlg(), moves = { up: b(12) || ay < -0.55, down: b(13) || ay > 0.55, left: b(14) || ax < -0.55, right: b(15) || ax > 0.55 };
  if (!d && !uiMode) {
    pressed("up", moves.up, () => step(-1));
    pressed("down", moves.down, () => step(1));
  } else for (const k in moves) pressed(k, moves[k], () => moveFocus(k));
  pressed("lb", b(4), () => { if (!d) jump(-1); }, 300);
  pressed("rb", b(5), () => { if (!d) jump(1); }, 300);
  pressed("a", b(0), () => { if (d || uiMode) activate(); else { const g = games.find(x => x.id === sel); if (g) launch(g); } }, 1e9);
  pressed("b", b(1), () => {
    if (d) cancelDialog(d);
    else if (uiMode) leaveUi();
    else { $("#search").value = ""; filter = ""; renderList(); }
  }, 1e9);
  pressed("x", b(2), () => { if (d?.id === "odlg") d.oskKey?.("back"); else if (!d) editor(); }, d?.id === "odlg" ? 120 : 1e9);
  pressed("y", b(3), () => { if (d?.id === "odlg") d.oskKey?.(" "); else if (!d) { const g = games.find(x => x.id === sel); if (g) editor(g); } }, d?.id === "odlg" ? 120 : 1e9);
  pressed("fav", b(8), () => { if (!d && !uiMode) toggleFav(games.find(x => x.id === sel)); }, 1e9);
  pressed("start", b(9), () => {
    if (!d) uiMode ? leaveUi() : enterUi();
    else if (d.id === "dlg") $("#form").requestSubmit();
    else if (d.id === "odlg") d.close("ok");
  }, 1e9);
}
function pollPad() {
  const p = [...(navigator.getGamepads?.() || [])].find(Boolean);
  if (p) {
    if (!padOn) { padOn = true; hints(); }
    if (p.buttons.some(x => x.pressed) || Math.hypot(p.axes[0] || 0, p.axes[1] || 0) > 0.55) document.documentElement.classList.add("gp");
    padAction(i => p.buttons[i]?.pressed, p.axes[0] || 0, p.axes[1] || 0);
  }
  requestAnimationFrame(pollPad);
}
// Back to plain mouse/keyboard behaviour as soon as either is used.
for (const t of ["pointerdown", "keydown"]) addEventListener(t, () => { document.documentElement.classList.remove("gp"); if (t === "pointerdown") uiMode = false; }, true);

// On-screen keyboard. Also used for category rename; physical typing works in it too.
const KEYROWS = ["1234567890", "qwertyuiop", "asdfghjkl-", "zxcvbnm,./", ":_~@?&=+'\""];
function oskPrompt(title, value = "", { multiline = false } = {}) {
  const d = $("#odlg");
  return new Promise(res => {
    let shift = false;
    d.innerHTML = `<form method="dialog" onsubmit="return false"><h2>${esc(title)}</h2>
      ${multiline ? '<textarea id="oinp" rows="4"></textarea>' : '<input id="oinp" autocomplete="off">'}
      <div id="okeys">${KEYROWS.map(r => `<div>${[...r].map(c => `<button type="button" data-k="${esc(c)}">${esc(c)}</button>`).join("")}</div>`).join("")}
        <div><button type="button" data-k="shift" class="wide">⇧ Shift</button><button type="button" data-k=" " class="space">Space</button>${multiline ? '<button type="button" data-k="\n" class="wide">↵</button>' : ""}<button type="button" data-k="back" class="wide">⌫</button></div></div>
      <div class="padhint"><kbd>X</kbd>Backspace <kbd>Y</kbd>Space <kbd>Start</kbd>Done <kbd>B</kbd>Cancel</div>
      <div class="btns"><button type="button" id="ocancel">Cancel</button><button type="button" id="ook" class="primary">Done</button></div></form>`;
    const inp = $("#oinp"); inp.value = value;
    const key = k => {
      if (k === "shift") { shift = !shift; d.classList.toggle("shift", shift); return; }
      if (k === "back") inp.value = inp.value.slice(0, -1);
      else { inp.value += shift ? k.toUpperCase() : k; if (shift) { shift = false; d.classList.remove("shift"); } }
      sfx("tick");
    };
    d.oskKey = key;
    d.onclick = e => { const b = e.target.closest("[data-k]"); if (b) key(b.dataset.k); };
    $("#ocancel").onclick = () => d.close("cancel");
    $("#ook").onclick = () => d.close("ok");
    inp.onkeydown = e => { if (e.key === "Enter" && !multiline) { e.preventDefault(); d.close("ok"); } };
    d.returnValue = "";
    d.onclose = () => { d.oskKey = null; res(d.returnValue === "ok" ? inp.value : null); };
    d.classList.remove("shift"); d.showModal(); sfx("open");
  });
}

function ask(title, msg, ok) {
  return new Promise(res => {
    const d = $("#qdlg");
    $("#qtitle").textContent = title; $("#qmsg").textContent = msg; $("#qyes").textContent = ok;
    d.returnValue = "";
    d.addEventListener("close", () => res(d.returnValue === "ok"), { once: true });
    d.showModal(); sfx("open");
  });
}
function hints() {
  $("#rum").hidden = !padOn;
  $("#hints").innerHTML = padOn
    ? "<span><kbd>A</kbd>Play</span><span><kbd>LB</kbd><kbd>RB</kbd>Category</span><span><kbd>Back</kbd>★</span><span><kbd>X</kbd>Add</span><span><kbd>Y</kbd>Edit</span><span><kbd>Start</kbd>Menu</span>"
    : "<span><kbd>↑</kbd><kbd>↓</kbd>Select</span><span><kbd>Enter</kbd>Play</span><span><kbd>PgUp</kbd><kbd>PgDn</kbd>Category</span><span><kbd>F</kbd>★ Favorite</span><span><kbd>R</kbd>Recent</span><span><kbd>⇧F</kbd>Favorites</span>";
}
addEventListener("gamepaddisconnected", () => { padOn = false; hints(); });

function splash() {
  const s = $("#splash");
  if (!animOn()) { s.remove(); return; }
  let done = false;
  const end = () => {
    if (done) return; done = true;
    s.classList.add("out"); setTimeout(() => s.remove(), 600);
    removeEventListener("keydown", end); removeEventListener("pointerdown", end);
  };
  addEventListener("keydown", end); addEventListener("pointerdown", end);
  setTimeout(end, 1900);
  sfx("intro");
  const poll = () => { if (done) return; if ([...(navigator.getGamepads?.() || [])].some(p => p?.buttons.some(b => b.pressed))) end(); else requestAnimationFrame(poll); };
  poll();
}
async function askQuit() {
  const n = running.size;
  if (!await ask("Exit launcher?", n ? `${n} game${n > 1 ? "s are" : " is"} still running and will keep running after the launcher closes.` : "The launcher will close.", "Exit")) return;
  try { await post("/api/quit"); } catch { /* server may already be gone */ }
  document.body.innerHTML = '<p style="margin:40vh auto;text-align:center;color:#8087a8">Launcher closed. You can close this window.</p>';
  window.close();
}
$("#qdlg").addEventListener("keydown", e => {
  const dir = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 }[e.key];
  if (dir) { e.preventDefault(); const b = [$("#qno"), $("#qyes")]; b[(b.indexOf(document.activeElement) + dir + 2) % 2].focus(); }
  else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); $("#qdlg").close("cancel"); }
});
$("#quit").onclick = e => { e.currentTarget.blur(); askQuit(); };
const toggleFull = () => document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen().catch(() => {});
$("#full").onclick = e => { toggleFull(); e.currentTarget.blur(); };
// In kiosk mode the browser itself is fullscreen and the page can't leave it, so the toggle is hidden.
if (!document.fullscreenElement && innerHeight >= screen.height - 2) $("#full").hidden = true;
document.addEventListener("fullscreenchange", () => { $("#full").classList.toggle("active", !!document.fullscreenElement); });
$("#snd").onclick = () => { localStorage.setItem("mcl-sound", soundOn() ? "off" : "on"); applySound(); sfx("tick"); };
$("#rum").onclick = () => { localStorage.setItem("mcl-rumble", rumbleOn() ? "off" : "on"); applyRumble(); rumble("ok"); };
$("#fx").onclick = () => { localStorage.setItem("mcl-anim", animOn() ? "off" : "on"); applyFx(); };
$("#dlg").addEventListener("keydown", e => { if ((e.key === "Enter" || e.key === " ") && e.target.matches(".sr, .thumbs img")) { e.preventDefault(); e.target.click(); } });
applyFx(); applySound(); applyRumble(); applyPanel(); splash();
hints();
refresh(true);
requestAnimationFrame(pollPad);
setInterval(refresh, 4000); // also keeps the server alive while the window is open
