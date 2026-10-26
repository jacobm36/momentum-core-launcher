// Shared helpers, saved settings and controller rumble.
const $ = s => document.querySelector(s);
const animOn = () => localStorage.getItem("mcl-anim") !== "off";
function applySound() { $("#snd").textContent = soundOn() ? "🔊" : "🔇"; }
function applyFx() { document.body.classList.toggle("noanim", !animOn()); $("#fx").textContent = animOn() ? "✨ On" : "✨ Off"; }
const featuredPanel = () => localStorage.getItem("mcl-panel") === "featured";
const libraryView = () => ["tiles", "grid"].includes(localStorage.getItem("mcl-view")) ? localStorage.getItem("mcl-view") : "list";
const tiledLibrary = () => libraryView() !== "list";
const libraryScrollKey = () => libraryView() === "list" ? "mcl-scroll" : `mcl-scroll-${libraryView()}`;
function applyLibraryView() {
  const tiles = tiledLibrary(), list = $("#list"), stage = $("#stage"), button = $("#library-view");
  document.body.classList.toggle("tiles", tiles);
  document.body.classList.toggle("portrait-grid", libraryView() === "grid");
  stage.classList.toggle("featured", !tiles && featuredPanel());
  if (tiles) stage.insertBefore(list, $("#detail"));
  else document.querySelector("aside").insertBefore(list, $(".side-btns"));
  if (button) {
    button.value = libraryView();
    button.title = "Library layout: List, landscape Tiles, or portrait Grid";
  }
  if ($("#tile-help")) $("#tile-help").hidden = !tiles;
  if ($("#library-nav")) $("#library-nav").hidden = !tiles;
  if ($("#panel")) $("#panel").hidden = tiles;
}
function applyPanel() {
  const featured = featuredPanel(), button = $("#panel");
  $("#stage")?.classList.toggle("featured", featured && !tiledLibrary());
  if (!button) return;
  button.textContent = featured ? "▣ Featured" : "▣ Classic";
  button.title = `Selected-game panel: ${featured ? "Featured" : "Classic"} (click to switch)`;
  button.setAttribute("aria-pressed", String(featured));
}
let games = [], token = "", running = new Set(), sel = null, filter = "", tagSel = new Set(), padOn = false, dragging = null, failed = {};
let launchPending = false;
let restoredScroll = null, listFilterKey = null, browsingReady = false;
let libraryCollection = "all";
function restoreBrowsing() {
  filter = localStorage.getItem("mcl-search") || "";
  libraryCollection = localStorage.getItem("mcl-collection") || "all";
  if (!["all", "favorites", "recent"].includes(libraryCollection)
      && !games.some(g => `category:${g.category || "Other"}` === libraryCollection)) {
    console.warn("Saved library collection no longer exists.", libraryCollection);
    libraryCollection = "all";
  }
  try {
    const tags = JSON.parse(localStorage.getItem("mcl-tags") || "[]");
    if (!Array.isArray(tags) || !tags.every(t => typeof t === "string")) throw new Error("Invalid saved tags");
    tagSel = new Set(tags);
  } catch (error) {
    console.warn("Could not restore library tag filters.", error);
    tagSel.clear();
  }
  const scroll = Number(localStorage.getItem(libraryScrollKey()));
  restoredScroll = Number.isFinite(scroll) && scroll >= 0 ? scroll : 0;
  $("#search").value = filter;
  browsingReady = true;
}
function saveBrowsing() {
  const list = $("#list");
  if (!browsingReady || !list) return;
  localStorage.setItem("mcl-search", filter);
  localStorage.setItem("mcl-tags", JSON.stringify([...tagSel]));
  localStorage.setItem("mcl-collection", libraryCollection);
  localStorage.setItem(libraryScrollKey(), String(list.scrollTop));
}

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
