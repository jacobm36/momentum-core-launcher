// Toast stack and notification history.
const NKEY = "mcl-notes", NSEEN = "mcl-notes-seen";
const notes = () => { try { return JSON.parse(localStorage.getItem(NKEY) || "[]"); } catch { return []; } };
const unread = () => notes().filter(n => n.t > +(localStorage.getItem(NSEEN) || 0)).length;
function updateBell() {
  const b = $("#bell"); if (!b) return;
  const n = unread();
  b.dataset.badge = n > 9 ? "9+" : n || "";
}
function notify(msg, { kind = "info", title = "", sticky = false } = {}) {
  const list = notes();
  list.push({ t: Date.now(), kind, title, msg });
  try { localStorage.setItem(NKEY, JSON.stringify(list.slice(-50))); } catch { /* storage full */ }
  updateBell();
  const box = $("#toasts"); if (!box) return;
  const el = document.createElement("div");
  el.className = `toastc ${kind}`;
  el.setAttribute("role", kind === "error" ? "alert" : "status");
  el.innerHTML = `${title ? `<b>${esc(title)}</b>` : ""}<span>${esc(msg)}</span>`;
  el.onclick = () => el.remove();
  box.append(el);
  while (box.children.length > 4) box.firstChild.remove();
  // Re-show the popover so toasts sit above any open modal dialog.
  try { box.hidePopover(); box.showPopover(); } catch { /* popover unsupported */ }
  if (!sticky) setTimeout(() => el.remove(), kind === "error" ? 9000 : 5000);
}
function openNotes() {
  const d = $("#ndlg"); if (!d || topDlg()) return;
  const list = notes().reverse();
  const ago = t => { const s = (Date.now() - t) / 1000; return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)}m ago` : s < 86400 ? `${Math.floor(s / 3600)}h ago` : new Date(t).toLocaleDateString(); };
  d.innerHTML = `<h2>Notifications</h2>
    <div class="nlist">${list.length ? list.map(n => `<div class="nrow ${esc(n.kind)}"><span class="ndot"></span><div><b>${esc(n.title || "")}</b> ${esc(n.msg)}</div><time>${ago(n.t)}</time></div>`).join("") : '<p class="sempty">Nothing yet.</p>'}</div>
    <div class="padhint pad-only"><kbd>A</kbd>Choose <kbd>B</kbd>Close</div>
    <div class="btns">${list.length ? '<button type="button" id="nclear">Clear</button>' : ""}<button type="button" id="nclose" class="primary" autofocus>Close</button></div>`;
  d.onclick = e => {
    if (e.target.id === "nclear") { localStorage.removeItem(NKEY); openNotesAgain(d); }
    else if (e.target.id === "nclose") d.close();
  };
  d.onkeydown = e => { if (e.key === "Escape") { e.preventDefault(); d.close(); } };
  localStorage.setItem(NSEEN, Date.now()); updateBell();
  d.showModal(); sfx("open");
}
function openNotesAgain(d) { d.close(); openNotes(); }
if ($("#bell")) $("#bell").onclick = e => { e.currentTarget.blur(); openNotes(); };
updateBell();
