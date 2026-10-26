// Drag/drop, reordering, selection, refresh loop and keyboard shortcuts.
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

function select(id, position = null, scroll = true) {
  const focused = document.activeElement?.classList.contains("tile");
  if (id !== sel) sfx("tick");
  tilePosition = position;
  sel = id; localStorage.setItem("mcl-last", id); renderList(); renderDetail();
  if (scroll) selectedItem()?.scrollIntoView({ block: "nearest", behavior: animOn() ? "smooth" : "auto" });
  if (focused && scroll) selectedItem()?.focus({preventScroll:true});
  if (typeof requestTilePreview === "function") requestTilePreview();
}
function moveTile(direction) {
  const current = selectedItem();
  if (!current) return;
  const rect = current.getBoundingClientRect(), vertical = direction === "up" || direction === "down";
  const sign = direction === "down" || direction === "right" ? 1 : -1;
  let best = null, score = Infinity, bestSide = Infinity;
  for (const item of document.querySelectorAll(".tile")) {
    if (item === current) continue;
    const r = item.getBoundingClientRect(), dx = r.left + r.width / 2 - rect.left - rect.width / 2;
    const dy = r.top + r.height / 2 - rect.top - rect.height / 2;
    const forward = (vertical ? dy : dx) * sign, side = Math.abs(vertical ? dx : dy);
    if (forward < 2 || (!vertical && side > 2)) continue;
    if (forward < score - 2 || (Math.abs(forward - score) <= 2 && side < bestSide)) {
      score = forward; bestSide = side; best = item;
    }
  }
  if (best) {
    select(best.dataset.id, best.dataset.position);
  }
}
function step(d) { const l = flat(), i = l.findIndex(g => g.id === sel); if (l.length) select(l[(i + d + l.length) % l.length].id); } // wraps around at either end
// Jump to the Favorites or Recently played section; pressing again steps through its games.
function jumpTo(list, collection) {
  if (filter || tagSel.size || !list.length) return;
  const previous = sel;
  if (tiledLibrary() && collection) {
    chooseCollection(collection);
    list = list.filter(g => visible().some(v => v.id === g.id));
    if (!list.length) return;
  }
  const i = list.findIndex(g => g.id === previous);
  select(list[(i + 1) % list.length].id); sfx("cat");
}
function jump(d) { // previous/next category
  const cs = ordered(); if (!cs.length) return;
  if (cs[0].sorted) { const l = cs[0].items, i = Math.max(0, l.findIndex(g => g.id === sel)); select(l[Math.min(l.length - 1, Math.max(0, i + d * 8))].id); sfx("cat"); return; }
  const ci = cs.findIndex(c => c.items.some(g => g.id === sel));
  select(cs[(ci + d + cs.length) % cs.length].items[0].id); sfx("cat");
}

let windowWarning = null;
async function refresh(first) {
  const j = await (await fetch("/api/games")).json();
  if (j.window_warning && j.window_warning !== windowWarning && typeof notify === "function") {
    notify(j.window_warning, { kind: "error", title: "Launcher window handoff" });
  }
  windowWarning = j.window_warning || null;
  token = j.token; games = j.games; stats = j.stats || {}; running = new Set(j.running); failed = j.failed || {};
  if (typeof handleJobs === "function") handleJobs(j.jobs);
  if (first) {
    restoreBrowsing();
    const last = localStorage.getItem("mcl-last");
    sel = flat().some(g => g.id === last) ? last : flat()[0]?.id;
  }
  if (!dragging) renderList();
  if (first || ($("#play") && $("#play").disabled !== running.has(sel)) || (sel && $("#detail .stats")?.textContent !== statText(sel))) renderDetail();
  const t = $("#toast");
  if (t && sel && failed[sel] !== undefined && !running.has(sel) && !t.textContent) {
    t.textContent = `Last launch exited with code ${failed[sel]} — see logs/${sel}.log`;
    if (typeof notify === "function") notify(`Exited with code ${failed[sel]}. See logs/${sel}.log`, { kind: "error", title: games.find(g => g.id === sel)?.name || "Game" });
  }
}

$("#list").onclick = e => {
  const b = e.target.closest("[data-act]");
  if (b) { const c = b.closest(".cat").dataset.cat, act = b.dataset.act; return act === "rename" ? renameCat(c) : moveCat(c, act === "up" ? -1 : 1); }
   const i = e.target.closest(".item");
   if (i) { select(i.dataset.id, i.dataset.position); if (tiledLibrary()) openGameDetails(); }
};
$("#library-view")?.addEventListener("change", e => {
  saveBrowsing();
  dragging = null; clearDrop();
  localStorage.setItem("mcl-view", e.target.value);
  const scroll = Number(localStorage.getItem(libraryScrollKey()));
  restoredScroll = Number.isFinite(scroll) && scroll >= 0 ? scroll : 0;
  applyLibraryView(); renderList(); renderDetail(); hints();
});
$("#library-nav")?.addEventListener("click", e => {
  const button = e.target.closest("[data-collection]");
  if (button) chooseCollection(button.dataset.collection);
});
$("#list").addEventListener("scroll", saveBrowsing);
addEventListener("pagehide", saveBrowsing);
if ($("#panel")) $("#panel").onclick = () => {
  localStorage.setItem("mcl-panel", featuredPanel() ? "classic" : "featured");
  applyPanel(); renderDetail();
};
const clearDrop = () => document.querySelectorAll(".drop-before,.drop-after,.drop-into").forEach(x => x.classList.remove("drop-before", "drop-after", "drop-into"));
$("#list").addEventListener("dragstart", e => {
  if (tiledLibrary()) { e.preventDefault(); return; }
  const i = e.target.closest(".item"); if (i) { dragging = i.dataset.id; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", dragging); }
});
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
if ($("#theme")) $("#theme").onclick = e => { e.currentTarget.blur(); cycleTheme(); };
if ($("#sort")) $("#sort").onclick = e => { e.currentTarget.blur(); cycleSort(); };
if ($("#stats")) $("#stats").onclick = e => { e.currentTarget.blur(); openStats(); };
$("#detail").addEventListener("click", e => {
  const t = e.target.closest("[data-tag]"); if (!t) return;
  toggleTag(t.dataset.tag);
});
$("#tagbar")?.addEventListener("click", e => {
  const b = e.target.closest("[data-untag]"); if (!b) return;
  if (b.dataset.untag === "*") { tagSel.clear(); renderList(); renderDetail(); sfx("tick"); } else toggleTag(b.dataset.untag);
});
$("#search").oninput = e => { filter = e.target.value; renderList(); };
document.addEventListener("keydown", e => {
  if (e.ctrlKey && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "q") {
    e.preventDefault();
    if (!$("#splash") && !topDlg()) { $("#search").blur(); askQuit(); }
    return;
  }
  if (topDlg()) return;
  if (e.target.closest("select")) return;
  const inSearch = e.target.id === "search";
  const onControl = e.target.closest("button, input, textarea, select, summary") && !e.target.closest(".tile");
  if (inSearch && !["ArrowDown", "ArrowUp", "Enter", "Escape"].includes(e.key)) return;
  if (tiledLibrary() && !inSearch && e.target.closest("button,input,textarea,select,summary") && !e.target.closest(".tile")
      && ["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Enter", " "].includes(e.key)) return;
  if (tiledLibrary() && ["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"].includes(e.key) && !inSearch) { moveTile(e.key.slice(5).toLowerCase()); e.preventDefault(); }
  else if (!tiledLibrary() && e.altKey && !filtering() && sortMode() === "cat" && (e.key === "ArrowDown" || e.key === "ArrowUp")) { nudge(sel, e.key === "ArrowDown" ? 1 : -1); e.preventDefault(); }
  else if (e.key === "ArrowDown") { tiledLibrary() ? moveTile("down") : step(1); e.preventDefault(); }
  else if (e.key === "ArrowUp") { tiledLibrary() ? moveTile("up") : step(-1); e.preventDefault(); }
  else if (e.key.toLowerCase() === "r" && !e.ctrlKey && !e.metaKey && !e.altKey && !inSearch && !onControl) jumpTo(recent(), "recent");
  else if (!e.ctrlKey && !e.metaKey && !e.altKey && !inSearch && !onControl && e.key.toLowerCase() === "s") cycleSort();
  else if (!e.ctrlKey && !e.metaKey && !e.altKey && !inSearch && !onControl && e.key.toLowerCase() === "t") openStats();
  else if (!e.ctrlKey && !e.metaKey && !e.altKey && !inSearch && !onControl && "nib".includes(e.key.toLowerCase()) && e.key.length === 1) ({ n: openNotes, i: openJobs, b: openBackup })[e.key.toLowerCase()]?.();
  else if (e.key === "F" && e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey && !inSearch && !onControl) jumpTo(favs(), "favorites");
  else if (e.key.toLowerCase() === "f" && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey && !inSearch && !onControl) toggleFav(games.find(x => x.id === sel));
  else if (e.key === "PageDown") jump(1);
  else if (e.key === "PageUp") jump(-1);
  else if (e.key === "Escape") {
    if ($("#splash")) return; // Esc just skips the intro
    $("#search").blur(); clearFilters();
  }
  else if ((e.key === "Enter" || e.key === " ") && e.target.closest("[data-act], [data-tag]")) { e.target.click(); e.preventDefault(); }
  else if ((e.key === "Enter" || e.key === " ") && e.target.closest(".tile")) { e.preventDefault(); openGameDetails(); }
  else if (e.key === "Enter" && !e.target.closest("button,select,summary")) { e.preventDefault(); const g = games.find(x => x.id === sel); if (g) tiledLibrary() ? openGameDetails() : launch(g); }
});
