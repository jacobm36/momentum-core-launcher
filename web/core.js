// Shared helpers, saved settings and controller rumble.
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
  open: [[0, 45, 0.25, 0.05]],
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
