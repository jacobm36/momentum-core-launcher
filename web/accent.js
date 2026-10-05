// Per-game accent colour (set by hand or taken from the art).
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
