// Gamepad input, focus handling, on-screen keyboard and confirm dialogs.
// Gamepad. Main screen: D-pad/stick = move, A = play, LB/RB = category, LT/RT = recent/favorites, L3 = sort, R3 = stats, X = add game, Y = edit game,
// Start = menu mode (move focus between every button), B = clear search / leave menu mode.
// In dialogs: D-pad moves focus, A presses or edits a text field (on-screen keyboard), Start = save/done, B = cancel.
const held = {};
let uiMode = false;
function pressed(key, on, fn, repeat = 180) {
  const now = performance.now();
  if (!on) { delete held[key]; return; }
  if (!held[key] || now - held[key].t > (held[key].n ? repeat : 400)) { held[key] = { t: now, n: true }; fn(); }
}
const topDlg = () => ["odlg", "qdlg", "rdlg", "pdlg", "gdlg", "bdlg", "idlg", "ndlg", "sdlg", "dlg"].map(i => $("#" + i)).find(d => d.open);
const FOCUSABLE = 'button,input:not([type=file]):not([type=hidden]),select,summary,textarea,a[href],[tabindex="0"]';
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
  if (el.tagName === "SELECT") {
    el.selectedIndex = (el.selectedIndex + 1) % el.options.length;
    el.dispatchEvent(new Event("change", { bubbles: true }));
  } else if (isText(el)) editField(el); else el.click();
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
  pressed("lb", b(4), () => { if (!d) jump(-1); else d.nav?.(-1); }, 300);
  pressed("rb", b(5), () => { if (!d) jump(1); else d.nav?.(1); }, 300);
  pressed("a", b(0), () => { if (d || uiMode) activate(); else { const g = games.find(x => x.id === sel); if (g) launch(g); } }, 1e9);
  pressed("b", b(1), () => {
    if (d) cancelDialog(d);
    else if (uiMode) leaveUi();
    else clearFilters();
  }, 1e9);
  pressed("x", b(2), () => { if (d?.id === "odlg") d.oskKey?.("back"); else if (!d) editor(); }, d?.id === "odlg" ? 120 : 1e9);
  pressed("y", b(3), () => { if (d?.id === "odlg") d.oskKey?.(" "); else if (!d) { const g = games.find(x => x.id === sel); if (g) editor(g); } }, d?.id === "odlg" ? 120 : 1e9);
  pressed("lt", b(6), () => { if (!d && !uiMode) jumpTo(recent()); }, 300);
  pressed("rt", b(7), () => { if (!d && !uiMode) jumpTo(favs()); }, 300);
  pressed("l3", b(10), () => { if (!d) cycleSort(); }, 1e9);
  pressed("r3", b(11), () => { if (!d) openStats(); }, 1e9);
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
const KEYROWS = ["1234567890", "qwertyuiop", "asdfghjkl-", "zxcvbnm,./", ":_~@?&=+'\"", "#!%()[]*;$"];
function oskPrompt(title, value = "", { multiline = false } = {}) {
  const d = $("#odlg");
  return new Promise(res => {
    let shift = false;
    d.innerHTML = `<form method="dialog" onsubmit="return false"><h2>${esc(title)}</h2>
      ${multiline ? '<textarea id="oinp" rows="4"></textarea>' : '<input id="oinp" autocomplete="off">'}
      <div id="okeys">${KEYROWS.map(r => `<div>${[...r].map(c => `<button type="button" data-k="${esc(c)}">${esc(c)}</button>`).join("")}</div>`).join("")}
        <div><button type="button" data-k="shift" class="wide">⇧ Shift</button><button type="button" data-k=" " class="space">Space</button>${multiline ? '<button type="button" data-k="\n" class="wide">↵</button>' : ""}<button type="button" data-k="back" class="wide">⌫</button><button type="button" data-k="clear" class="wide">Clear</button></div></div>
      <div class="padhint"><kbd>X</kbd>Backspace <kbd>Y</kbd>Space <kbd>Start</kbd>Done <kbd>B</kbd>Cancel</div>
      <div class="btns"><button type="button" id="ocancel">Cancel</button><button type="button" id="ook" class="primary">Done</button></div></form>`;
    const inp = $("#oinp"); inp.value = value;
    const key = k => {
      if (k === "shift") { shift = !shift; d.classList.toggle("shift", shift); return; }
      if (k === "back") inp.value = inp.value.slice(0, -1);
      else if (k === "clear") inp.value = "";
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
