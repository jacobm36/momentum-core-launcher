// Build details and explicitly recorded game locations.
function infoError(error) {
  notify(error.message, { kind: "error", title: "Momentum" });
  sfx("err");
}
async function infoRequest(path, method = "GET") {
  const response = await fetch(path, { method, headers: { "X-Token": token } });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
function showInfo(dialog, html) {
  dialog.innerHTML = html + '<div class="padhint pad-only"><kbd>A</kbd>Choose <kbd>B</kbd>Close</div><form method="dialog" class="btns"><button class="primary" autofocus>Close</button></form>';
  dialog.showModal(); sfx("open");
}
async function openAbout() {
  try {
    const info = await infoRequest("/api/about");
    showInfo($("#adlg"), `<h2>About Momentum</h2><p>Your games. Your Linux arcade.</p>
      <dl><dt>Version / build</dt><dd>${esc(info.version)}</dd><dt>Platform</dt><dd>${esc(info.platform)}</dd>
      <dt>Launcher folder</dt><dd>${esc(info.directory)}</dd></dl>
      <p>Supported baseline: Ubuntu 24.04 x86_64 with X11. Individual games have their own runtime and control requirements.</p>
      <p>Updates are explicit. Game packages run as your user: only approve installers you trust.</p>
      <p>Help and release information: README.md and USER-GUIDE.md in the launcher folder.</p>`);
  } catch (error) { infoError(error); }
}
async function openFolders(game) {
  try {
    const data = await infoRequest(`/api/games/${encodeURIComponent(game.id)}/folders`);
    const dialog = $("#fdlg");
    showInfo(dialog, `<h2>${esc(game.name)} folders</h2><p>Only recorded locations are shown. A working folder may not contain the game itself. Saves may be elsewhere if the engine manages them separately.</p>
      ${data.folders.length ? data.folders.map(folder => `<div class="folder-location"><button type="button" data-folder="${esc(folder.kind)}">Open ${esc(folder.label)}</button><p>${esc(folder.path)}</p></div>`).join("") : "<p>No game or save/settings folder is recorded for this entry.</p>"}`);
    dialog.onclick = async event => {
      const button = event.target.closest("[data-folder]");
      if (!button) return;
      button.disabled = true;
      try {
        await infoRequest(`/api/games/${encodeURIComponent(game.id)}/folders/${button.dataset.folder}`, "POST");
      } catch (error) { infoError(error); }
      finally { button.disabled = false; }
    };
  } catch (error) { infoError(error); }
}
$("#about").onclick = openAbout;
