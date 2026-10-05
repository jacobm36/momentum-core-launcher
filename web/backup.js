// Backup and restore dialog.
const fmtSize = n => n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
async function loadBackups() {
  const d = $("#bdlg"), box = d.querySelector(".blist");
  const j = await (await fetch("/api/backups")).json().catch(() => ({ backups: [] }));
  box.innerHTML = j.backups.length ? j.backups.map(b => `<div class="brow" data-n="${esc(b.name)}">
    <div><b>${esc(b.kind || b.name.split("-")[0])}</b> <time>${esc(new Date((b.time || 0) * 1000).toLocaleString())}</time><span class="bsub">${b.media ? "with artwork · " : ""}${fmtSize(b.size || 0)}</span></div>
    <span class="bbtns"><button type="button" data-a="restore">Restore</button><button type="button" data-a="download">Download</button><button type="button" data-a="delete">Delete</button></span></div>`).join("") : '<p class="sempty">No backups yet.</p>';
}
async function restoreDone(r) {
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { notify(j.error || "Restore failed.", { kind: "error", title: "Restore" }); return; }
  notify(`Restored ${j.games} games. Your previous library was saved as ${j.snapshot}.`, { kind: "ok", title: "Restore complete" });
  $("#bdlg").close(); await refresh(true);
}
const RESTORE_MSG = "This replaces your current games and playtime with the backup. A safety copy of the current library is saved first. Only restore backups you made yourself.";
function openBackup() {
  const d = $("#bdlg"); if (!d || topDlg()) return;
  d.innerHTML = `<h2>Backup &amp; restore</h2>
    <p class="bnote">Saves your game list, tags, favorites and playtime. Window settings (sound, sort order and so on) live in the browser and are not included.</p>
    <label class="bchk"><input type="checkbox" id="bmedia"> Include artwork &amp; videos (bigger)</label>
    <div class="btns bleft"><button type="button" id="bnow" class="primary">Save backup now</button><button type="button" id="bfile">Restore from file…</button><input type="file" id="bpick" accept=".zip" hidden></div>
    <h3>Snapshots</h3><div class="blist"></div>
    <div class="padhint pad-only"><kbd>A</kbd>Choose <kbd>B</kbd>Close</div>
    <div class="btns"><button type="button" id="bclose" class="primary" autofocus>Close</button></div>`;
  d.onclick = async e => {
    const id = e.target.id;
    if (id === "bclose") return d.close();
    if (id === "bfile") return $("#bpick").click();
    if (id === "bnow") {
      e.target.disabled = true;
      const r = await post("/api/backups/create", { media: $("#bmedia").checked }), j = await r.json().catch(() => ({}));
      e.target.disabled = false;
      notify(r.ok ? "Backup saved." : j.error || "Backup failed.", { kind: r.ok ? "ok" : "error", title: "Backup" });
      if (r.ok) sfx("ok");
      return loadBackups();
    }
    const b = e.target.closest("[data-a]"); if (!b) return;
    const name = b.closest(".brow").dataset.n, a = b.dataset.a;
    if (a === "delete") { if (await ask("Delete this backup?", name, "Delete")) { await post(`/api/backups/delete/${name}`); loadBackups(); } }
    else if (a === "restore") { if (await ask("Restore this backup?", RESTORE_MSG, "Restore")) await restoreDone(await post(`/api/backups/restore/${name}`)); }
    else if (a === "download") {
      const r = await post(`/api/backups/download/${name}`);
      if (!r.ok) return notify("Download failed.", { kind: "error" });
      const url = URL.createObjectURL(await r.blob()), l = Object.assign(document.createElement("a"), { href: url, download: name });
      document.body.append(l); l.click(); l.remove(); setTimeout(() => URL.revokeObjectURL(url), 5000);
    }
  };
  d.querySelector("#bpick").onchange = async e => {
    const f = e.target.files[0]; e.target.value = ""; if (!f) return;
    if (await ask("Restore from this file?", `${f.name}. ${RESTORE_MSG}`, "Restore")) await restoreDone(await post("/api/backups/restore-upload", null, f));
  };
  d.onkeydown = e => { if (e.key === "Escape" && !topDlg()?.matches("#qdlg")) { e.preventDefault(); d.close(); } };
  d.showModal(); sfx("open"); loadBackups();
}
if ($("#backupbtn")) $("#backupbtn").onclick = e => { e.currentTarget.blur(); openBackup(); };
