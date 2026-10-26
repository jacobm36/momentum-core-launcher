// Game catalog, validated downloads, local intake and exact-plan review.
async function packageResponse(response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The package request failed.");
  return data;
}
function packageError(d, error) {
  const box = d.querySelector(".pkg-error");
  if (box) { box.textContent = error.message; box.hidden = false; }
  else notify(error.message, { kind: "error", title: "Packages" });
}
const packageJson = value => `<pre class="pkg-json">${esc(JSON.stringify(value, null, 2))}</pre>`;
let selectedPackage = null;
let downloadPoll = null;
const STORE_PILLARS = [
  { id: "openbor", title: "OpenBOR", note: "Fan-made beat 'em ups, packaged and made Linux-native. OpenBOR, without the setup." },
  { id: "mouse-arcade", title: "Momentum Mouse Arcade", note: "Arcade rail shooters become mouse games. Point, click, play." },
  { id: "boomer-shooters", title: "Boomer Shooters", note: "Quake • Doom • Duke • Community Mods. Classic engines. Modern mods. Less setup." },
];

function packageStoreState(game, imported) {
  const installation = (imported.installations || []).find(
    item => item.package_id === game.id && item.installation === "installed");
  if (installation) {
    const newer = game.version.split(".").map(Number);
    const installed = installation.package_version.split(".").map(Number);
    const different = newer.findIndex((part, i) => part !== installed[i]);
    return different >= 0 && newer[different] > installed[different] ? "New version available" : "Installed";
  }
  return imported.packages.some(p => p.id === game.id && p.version === game.version && p.digest === game.digest)
    ? "Installer ready" : "Set up game";
}

function openAddGame() {
  const d = $("#pdlg");
  if (d.open) return;
  d.innerHTML = `<h2>Add games to Momentum</h2>
    <p class="bnote">Your Linux games, together: Steam shortcuts, native games, and emulator launches. The store is optional.</p>
    <div class="add-game-choices">
      <button type="button" id="add-installed" class="primary">Import installed games</button>
      <p class="bnote">Review game shortcuts already on this computer. Nothing is launched or installed.</p>
      <button type="button" id="add-manual">Add a game manually</button>
      <p class="bnote">Use an existing launch command, script, or emulator wrapper.</p>
      <button type="button" id="add-store">Browse the package store</button>
      <p class="bnote">Get a game installer; provide any required original game files.</p>
    </div><div class="btns"><button type="button" id="add-close" autofocus>Close</button></div>`;
  d.onclick = e => {
    const id = e.target.id;
    if (!["add-installed", "add-manual", "add-store", "add-close"].includes(id)) return;
    d.close();
    if (id === "add-installed") openInstalledGames();
    if (id === "add-manual") editor(null, true);
    if (id === "add-store") openPackages();
  };
  d.showModal(); sfx("open");
}

async function openInstalledGames(includeEmulators = false) {
  const d = $("#pdlg");
  if (d.open) return;
  d.innerHTML = `<h2>Import installed games</h2>
    <p class="bnote">Review game shortcuts from user, system, Flatpak and Snap application menus. This includes Steam games with menu shortcuts, not every installed Steam game.
      No game is launched or installed. Existing entries and edited launch commands stay unchanged.</p>
    <label class="bnote"><input type="checkbox" id="discover-emulators" ${includeEmulators ? "checked" : ""}>
      Include emulators and game engines</label>
    <p class="pkg-error" role="alert" hidden></p>
    <div id="discovered-games"><p role="status">Finding game shortcuts...</p></div>
    <div class="btns"><button type="button" id="discover-back">Back</button>
      <button type="button" id="discover-close" autofocus>Close</button></div>`;
  d.onclick = e => {
    if (e.target.id === "discover-close") d.close();
    if (e.target.id === "discover-back") { d.close(); openAddGame(); }
  };
  d.showModal(); sfx("open");
  d.querySelector("#discover-emulators").onchange = e => {
    const include = e.target.checked;
    d.close(); openInstalledGames(include);
  };
  const panel = d.querySelector("#discovered-games");
  try {
    const scan = await packageResponse(await post("/api/library/discover", { include_emulators: includeEmulators }));
    if (!d.open || !panel.isConnected) return;
    const skipped = scan.skipped;
    panel.innerHTML = `<p class="bnote">Scanned: ${esc(scan.directory)}</p>
      <p role="status">${scan.candidates.length} game shortcut(s) found; ${skipped.length} skipped; ${scan.ignored} unrelated shortcut(s) ignored.
        ${scan.emulators_hidden || 0} emulator/game-engine shortcut(s) hidden. Changing the emulator option rescans and clears selections.</p>
      <form id="discover-form">
        <div class="btns"><button type="button" id="discover-all">Select all available</button>
          <button type="button" id="discover-none">Select none</button></div>
        <div class="discovered-list">${scan.candidates.map((c, i) => `<label class="discovered-game">
          <span><input type="checkbox" data-candidate="${i}" ${c.reason ? "disabled" : ""}> ${esc(c.entry.name)}</span>
          <small>${esc(c.source)}</small><code>${esc(c.entry.exec)}</code>
          ${c.entry.cwd ? `<small>Working directory: ${esc(c.entry.cwd)}</small>` : ""}
          ${c.reason ? `<small>${esc(c.reason)}</small>` : ""}</label>`).join("") || '<p>No importable game shortcuts found. You can add a game manually instead.</p>'}</div>
        ${skipped.length ? `<details><summary>Skipped shortcuts (${skipped.length})</summary><ul>${skipped.map(
          c => `<li>${esc(c.name)}: ${esc(c.reason)}</li>`).join("")}</ul></details>` : ""}
        <p class="bnote">Only import shortcuts you trust. Their launch commands will run as your user when you press Play.</p>
        <button type="submit" id="discover-import" class="primary" disabled>Import selected games</button>
      </form>`;
    const form = panel.querySelector("#discover-form"), button = panel.querySelector("#discover-import");
    const inputs = () => [...form.querySelectorAll("input[data-candidate]:not(:disabled)")];
    const update = () => { button.disabled = !inputs().some(input => input.checked); };
    form.onchange = update;
    panel.querySelector("#discover-all").onclick = () => { inputs().forEach(input => input.checked = true); update(); };
    panel.querySelector("#discover-none").onclick = () => { inputs().forEach(input => input.checked = false); update(); };
    form.onsubmit = async e => {
      e.preventDefault();
      const selection = inputs().filter(input => input.checked).map(input => {
        const c = scan.candidates[Number(input.dataset.candidate)];
        return { source: c.source, sha256: c.sha256 };
      });
      button.disabled = true;
      d.querySelector("#discover-emulators").disabled = true;
      form.querySelectorAll("input,button").forEach(input => input.disabled = true);
      d.querySelector(".pkg-error").hidden = true;
      try {
        const result = await packageResponse(await post("/api/library/import", { selection, include_emulators: includeEmulators }));
        if (!d.open || !panel.isConnected) return;
        panel.innerHTML = `<p role="status">${result.added.length} game(s) added; ${result.skipped.length} selected game(s) skipped.
          Existing entries were preserved.</p>
          <ul>${result.added.map(g => `<li>Added: ${esc(g.name)}</li>`).join("")}
          ${[...result.skipped, ...result.warnings].map(g => `<li>${esc(g.name)}: ${esc(g.reason)}</li>`).join("")}</ul>
          <button type="button" id="discover-again">Scan again</button>`;
        panel.querySelector("#discover-again").onclick = () => { d.close(); openInstalledGames(includeEmulators); };
        try { await refresh(true); }
        catch (error) {
          if (d.open && panel.isConnected) packageError(d, new Error(`Import finished, but the library could not refresh: ${error.message}. Reopen the launcher to see the saved entries.`));
        }
      } catch (error) {
        if (!d.open || !panel.isConnected) return;
        packageError(d, error);
        d.querySelector("#discover-emulators").disabled = false;
        form.querySelectorAll("input,button").forEach(input => input.disabled = false);
        form.querySelectorAll("input[data-candidate]").forEach(input => {
          input.disabled = !!scan.candidates[Number(input.dataset.candidate)].reason;
        });
        update();
      }
    };
  } catch (error) {
    if (d.open && panel.isConnected) {
      panel.innerHTML = '<p>Discovery did not finish. Go back and try again, or add a game manually.</p>';
      packageError(d, error);
    }
  }
}

function openPackages() {
  const d = $("#pdlg");
  if (d.open) return;
  selectedPackage = null;
  d.innerHTML = `<h2>Browse the package store</h2>
    <p class="bnote">Guided setups for community games, arcade oddities and boomer shooters, with more to come. Momentum gets the installer and guides the setup; you provide your own game files where required. Your library isn't limited to the store: import or add any game you can launch.</p>
    <p class="pkg-error" role="alert" hidden></p>
    <div id="catalog-games"><p class="bnote">Loading available games...</p></div>
    <div id="catalog-download" hidden><p id="catalog-status" role="status"></p>
      <progress id="catalog-progress" aria-label="Installer download progress"></progress>
      <button type="button" id="catalog-cancel">Cancel download</button></div>
    <div id="catalog-advanced" class="btns">
      <button type="button" id="catalog-installed">Import installed games</button>
      <button type="button" id="catalog-manual">Add a game manually</button></div>
    <div class="btns"><button type="button" id="catalog-import">Local packages / import...</button>
      <button type="button" id="catalog-retry">Refresh games</button>
      <button type="button" id="pkg-close" autofocus>Close</button></div>`;
  d.onclick = e => {
    if (e.target.id === "pkg-close") d.close();
    if (e.target.id === "catalog-retry") loadGameCatalog();
    if (e.target.id === "catalog-import") { d.close(); openImportedPackages(); }
    if (e.target.id === "catalog-manual") { d.close(); editor(null, true); }
    if (e.target.id === "catalog-installed") { d.close(); openInstalledGames(); }
  };
  d.onclose = () => { clearTimeout(downloadPoll); selectedPackage = null; };
  d.showModal(); sfx("open");
  loadGameCatalog();
}

async function loadGameCatalog() {
  const d = $("#pdlg"), list = d.querySelector("#catalog-games");
  if (!list) return;
  const retry = d.querySelector("#catalog-retry");
  retry.disabled = true;
  d.querySelector(".pkg-error").hidden = true;
  try {
    const [catalog, imported] = await Promise.all([
      fetch("/api/catalog").then(packageResponse), fetch("/api/packages").then(packageResponse)
    ]);
    if (!d.open || !list.isConnected) return;
    const card = g => {
      const status = packageStoreState(g, imported);
      const installed = (imported.installations || []).some(p => p.package_id === g.id && p.installation === "installed");
      return `<article class="catalog-card"><img src="${esc(g.icon_url)}" alt="" referrerpolicy="no-referrer">
        <div><h3>${esc(g.name)}</h3>${g.runtime ? `<span class="runtime-badge" title="Runtime">${esc(g.runtime)}</span>` : ""}
        <p class="bnote">${esc(g.description)}</p>
        ${g.platform_issues.length ? `<p class="pkg-warning">${esc(g.platform_issues.join("; "))}</p>` : ""}
        <button type="button" class="primary" data-game="${esc(g.id)}" ${g.platform_issues.length ? "disabled" : ""}>
          ${status}</button>${installed && status !== "Installed"
            ? `<button type="button" data-manage="${esc(g.id)}">Manage installation</button>` : ""}</div></article>`;
    };
    const sections = [...STORE_PILLARS, { id: null, title: "More games", note: "" }].map(p => ({
      ...p, games: catalog.games.filter(g => p.id ? g.pillar === p.id : !STORE_PILLARS.some(s => s.id === g.pillar))
    })).filter(p => p.games.length);
    list.innerHTML = sections.length ? sections.map(p => `<section class="catalog-pillar">
      <h3 class="pillar-title">${esc(p.title)}</h3>${p.note ? `<p class="pillar-note">${esc(p.note)}</p>` : ""}
      ${p.games.map(card).join("")}</section>`).join("") : '<p class="sempty">No games available yet.</p>';
    list.onclick = async e => {
      const manage = e.target.closest("[data-manage]");
      if (manage) { d.close(); return openPackageManagement(manage.dataset.manage); }
      const button = e.target.closest("[data-game]"); if (!button || button.disabled) return;
      const game = catalog.games.find(g => g.id === button.dataset.game);
      if (packageStoreState(game, imported) === "Installed") {
        d.close(); return openPackageManagement(game.id);
      }
      const ready = imported.packages.some(p => p.id === game.id && p.version === game.version && p.digest === game.digest);
      if (ready) return selectPackage(game.id, game.version);
      button.disabled = true;
      try {
        const job = await packageResponse(await post("/api/packages/download", { id: game.id }));
        if (d.open && list.isConnected) followDownload(job.id);
      } catch (error) { packageError(d, error); }
      finally { if (button.isConnected) button.disabled = false; }
    };
  } catch (error) {
    if (list.isConnected) { list.innerHTML = ""; packageError(d, error); }
  } finally { if (retry.isConnected) retry.disabled = false; }
}

function followDownload(id) {
  const d = $("#pdlg"), panel = d.querySelector("#catalog-download");
  if (!panel) return;
  clearTimeout(downloadPoll);
  panel.hidden = false;
  d.querySelector(".pkg-error").hidden = true;
  d.querySelector("#catalog-games").hidden = true;
  d.querySelector("#catalog-advanced").hidden = true;
  d.querySelector("#catalog-retry").hidden = true;
  const cancel = d.querySelector("#catalog-cancel");
  cancel.disabled = false;
  cancel.onclick = async () => {
    cancel.disabled = true;
    try { await packageResponse(await post(`/api/jobs/${id}/cancel`)); }
    catch (error) { packageError(d, error); cancel.disabled = false; }
  };
  const poll = async () => {
    if (!d.open || !panel.isConnected) return;
    try {
      const job = await packageResponse(await fetch(`/api/jobs/${id}`));
      if (!d.open || !panel.isConnected) return;
      if (job.status === "succeeded") return selectPackage(job.package_id, job.package_version);
      if (["failed", "interrupted", "cancelled"].includes(job.status)) {
        throw new Error(job.error || (job.status === "cancelled" ? "Download cancelled. You can try again." : "Download stopped. You can retry in Installs & jobs."));
      }
      d.querySelector("#catalog-status").textContent = job.status === "cancel-requested"
        ? "Cancelling download..." : "Getting your game installer. No installation changes are being made.";
      const progress = d.querySelector("#catalog-progress");
      if (job.progress?.total > 0) { progress.max = job.progress.total; progress.value = job.progress.current; }
      else progress.removeAttribute("value");
      downloadPoll = setTimeout(poll, 500);
    } catch (error) {
      if (!panel.isConnected) return;
      panel.hidden = true;
      d.querySelector("#catalog-games").hidden = false;
      d.querySelector("#catalog-advanced").hidden = false;
      d.querySelector("#catalog-retry").hidden = false;
      packageError(d, error);
    }
  };
  poll();
}

async function loadPackages() {
  const d = $("#pdlg");
  try {
    const data = await packageResponse(await fetch("/api/packages"));
    if (!d.open || selectedPackage) return;
    d.querySelector(".pkg-list").innerHTML = data.packages.length ? data.packages.map(p =>
      `<div class="pkg-row"><div><b>${esc(p.name)}</b><span class="bsub">Version ${esc(p.version)}</span>
      ${p.platform_issues.length ? `<p class="pkg-warning">${esc(p.platform_issues.join("; "))}</p>` : ""}</div>
      ${packageStoreState(p, data) === "Installed"
        ? `<button type="button" data-manage="${esc(p.id)}">Manage installation</button>`
        : `<button type="button" data-package="${esc(p.id)}" data-version="${esc(p.version)}">Set up</button>`}
      <button type="button" data-cache-id="${esc(p.id)}" data-version="${esc(p.version)}">Remove cached installer</button></div>`
    ).join("") : '<p class="sempty">No packages imported. Choose a ZIP or enter a local package folder.</p>';
  } catch (error) { packageError(d, error); }
}
function openImportedPackages() {
  const d = $("#pdlg");
  if (d.open) return;
  selectedPackage = null;
  d.innerHTML = `<h2>Install packages</h2>
    <p class="bnote">Download a package ZIP from a publisher you trust, then import it here.
    Packages contain installers and may include a bundled mod; required base-game files come from you.
    Use Add game for automatic downloads.</p>
    <p class="pkg-warning">Import only checks and copies the package. No scripts run until you approve trust and request preflight.</p>
    <p class="pkg-error" role="alert" hidden></p>
    <div class="pkg-import"><button type="button" id="pkg-zip">Choose package ZIP...</button>
      <input type="file" id="pkg-file" accept=".zip,application/zip" hidden>
      <label>Or an absolute local folder / ZIP path<input id="pkg-path" placeholder="/home/you/Downloads/package" autocomplete="off"></label>
      <button type="button" id="pkg-import-path">Import path</button></div>
    <h3>Imported packages</h3><div class="pkg-list"><p class="bnote">Loading...</p></div>
    <div class="btns"><button type="button" id="pkg-catalog">Back to games</button><button type="button" id="pkg-close" autofocus>Close</button></div>`;
  d.onclick = async e => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.id === "pkg-close") return d.close();
    if (b.id === "pkg-catalog") { d.close(); return openPackages(); }
    if (b.id === "pkg-zip") return d.querySelector("#pkg-file").click();
    if (b.dataset.manage) { d.close(); return openPackageManagement(b.dataset.manage); }
    if (b.dataset.cacheId) {
      if (!await ask("Remove cached installer?", "This removes only the downloaded installer. It does not uninstall a game or delete settings/saves. Installed versions and active recovery records are protected.", "Remove installer")) return;
      b.disabled = true;
      try {
        await packageResponse(await post("/api/packages/remove-cache", { id: b.dataset.cacheId, version: b.dataset.version }));
        await loadPackages();
      } catch (error) { packageError(d, error); }
      finally { if (b.isConnected) b.disabled = false; }
      return;
    }
    if (b.dataset.package) return selectPackage(b.dataset.package, b.dataset.version);
    if (b.id !== "pkg-import-path") return;
    b.disabled = true;
    try {
      const path = d.querySelector("#pkg-path").value.trim();
      if (!path.startsWith("/")) throw new Error("Enter an absolute folder or ZIP path.");
      await packageResponse(await post("/api/packages/import", { path }));
      d.querySelector(".pkg-error").hidden = true;
      await loadPackages();
    } catch (error) { packageError(d, error); }
    finally { b.disabled = false; }
  };
  d.querySelector("#pkg-file").onchange = async e => {
    const file = e.target.files[0]; e.target.value = "";
    if (!file) return;
    const b = d.querySelector("#pkg-zip"); b.disabled = true; b.textContent = "Importing...";
    try {
      await packageResponse(await post("/api/packages/import-upload", null, file));
      d.querySelector(".pkg-error").hidden = true;
      await loadPackages();
    } catch (error) { packageError(d, error); }
    finally { b.disabled = false; b.textContent = "Choose package ZIP..."; }
  };
  d.onclose = () => { selectedPackage = null; };
  d.showModal(); sfx("open");
  loadPackages();
}

async function openPackageManagement(packageId) {
  const d = $("#pdlg");
  if (d.open) return;
  d.innerHTML = '<h2>Manage installation</h2><p class="pkg-error" role="alert" hidden></p><p role="status">Reading installation receipt...</p><button id="manage-close">Close</button>';
  d.onclick = e => { if (e.target.id === "manage-close") d.close(); };
  d.showModal();
  try {
    const data = await packageResponse(await fetch("/api/packages"));
    if (!d.open) return;
    const receipt = (data.installations || []).find(item => item.package_id === packageId);
    if (!receipt) throw new Error("No package installation receipt was found. Removing a library entry is not an uninstall.");
    d.innerHTML = `<h2>Manage ${esc(games.find(g => g.package_id === packageId)?.name || packageId)}</h2>
      <p class="pkg-error" role="alert" hidden></p>
      <p>Package ${esc(receipt.package_version)} · ${esc(receipt.installation)}</p>
      <p class="pkg-path">${esc(receipt.game_directory)}</p>
      <p>Uninstall removes unchanged installer-owned files. Original sources, saves, settings,
        custom/modified files, shared engines and retained support stay intact.
        The library entry remains, without Play; remove it separately if desired.</p>
      ${receipt.installation === "installed" ? `<label class="pkg-check"><input id="uninstall-trust" type="checkbox">
        I trust this installed package's code to check an uninstall plan.</label>
      <p class="pkg-warning">Package scripts run as your user. No removal happens until you review and approve the exact plan.</p>` : ""}
      <div class="btns"><button type="button" id="manage-close" autofocus>Close</button>
        ${receipt.installation === "installed" ? '<button type="button" id="uninstall-check" disabled>Review uninstall</button>' : ""}</div>`;
    const button = d.querySelector("#uninstall-check");
    if (button) d.querySelector("#uninstall-trust").onchange = e => { button.disabled = !e.target.checked; };
    d.onclick = async e => {
      if (e.target.id === "manage-close") return d.close();
      if (e.target.id !== "uninstall-check" || button.disabled) return;
      button.disabled = true;
      try {
        const job = await packageResponse(await post("/api/packages/uninstall", {
          id: packageId, trusted_digest: receipt.package_digest
        }));
        d.close();
        await refresh();
        guidePackageSetup(job.id);
      } catch (error) { packageError(d, error); }
      finally { if (button.isConnected) button.disabled = !d.querySelector("#uninstall-trust").checked; }
    };
  } catch (error) { if (d.open) packageError(d, error); }
}

function packageInputLabel(field) {
  if (field.id === "mod_dir") return "Existing extracted mod folder (optional)";
  if (field.role === "source" || field.id === "source_dir") return "Where are your game files?";
  if (field.role === "destination" || field.id === "games_root") return "Install games in";
  return field.label || field.id.replace(/_/g, " ");
}
function packageFileHelp(field, detail) {
  if (field.help) return field.help;
  if (field.id === "source_dir" && detail.id === "the-house-of-the-dead-2") {
    return "Choose the folder containing the CUE file and all matching BIN tracks together. The package ZIP does not contain the game.";
  }
  return "Choose the folder containing the game files required by this package. Its preflight checks the contents before installation; a matching filename alone does not establish compatibility.";
}
function packageRequirements(detail) {
  const sources = detail.manifest.inputs.filter(field =>
    field.type === "directory" && (field.role === "source" || ["source_dir", "mod_dir"].includes(field.id)));
  const downloads = detail.manifest.inputs.filter(field => field.id === "download_game");
  const engines = (detail.manifest.requires || []).map(requirement => requirement.id).filter(Boolean);
  return `<section class="pkg-requirements" aria-labelledby="pkg-before-title">
    <h3 id="pkg-before-title">Before you install</h3>
    <p class="bnote">Check what you need before choosing your files. No installation changes are made on this screen.</p>
    <h4>${sources.some(field => field.required) ? "Game files you provide" : "Game content options"}</h4>
    ${sources.length ? `<ul>${sources.map(field => `<li><strong>${esc(packageInputLabel(field))}${field.required ? " (required)" : " (optional / alternate source)"}</strong>
      <p>${esc(packageFileHelp(field, detail))}</p></li>`).join("")}</ul>`
      : '<p>This package declares no game-file folder input. Review its content and download details below.</p>'}
    ${downloads.length ? `<p>${downloads.map(field => esc(field.help || field.label || "Review the package's game download option below.")).join(" ")}</p>` : ""}
    <h4>What Momentum handles</h4>
    <p>The installer guides setup and creates the game launch entry.${engines.length
      ? ` Required game software: ${esc(engines.join(", "))}. Existing compatible software is reused; any required preparation is reviewed separately.`
      : " Review the declared software and content details below."}
      Any declared bundled content comes with the package; other downloads are shown for approval.</p>
    <p class="pkg-warning">Only use ROMs and other game files you are legally entitled to use.
      Momentum does not supply the original commercial game files required by these setups.</p>
    <p class="bnote">Keep your originals where they are. Choose the source folder below; preflight verifies the files before you approve installation.</p>
  </section>`;
}
function packageInput(field, detail) {
  const id = `pkg-input-${field.id}`, label = packageInputLabel(field);
  const value = field.default === "home_games" ? detail.home_games : field.default;
  const required = field.required ? " required" : "";
  if (field.type === "boolean") return `<label class="pkg-check"><input id="${esc(id)}" type="checkbox" ${value === true ? "checked" : ""}>${esc(label)}</label>`;
  if (field.type === "choice") return `<label>${esc(label)}<select id="${esc(id)}"${required}>
    ${field.choices.map(v => `<option value="${esc(v)}" ${v === value ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>`;
  return `<label>${esc(label)}${field.required ? " (required)" : ""}
    <input id="${esc(id)}" value="${esc(value ?? "")}"${required} autocomplete="off"
    ${field.type === "directory" ? 'placeholder="/home/you/your-game-folder"' : ""}></label>
    ${field.type === "directory" ? `<button type="button" class="pkg-browse" data-input="${esc(id)}"
      aria-label="${esc(label)}: choose folder">Choose folder...</button>` : ""}`;
}

function softwareLocation(facts) {
  const where = facts.installed && facts.location
    ? `<p class="bnote">${facts.managed ? "Using Momentum's tested isolated engine" : "Using your existing copy"}: <span class="pkg-path">${esc(facts.location)}</span></p>` : "";
  const skipped = (facts.skipped || []).map(s => `<p class="bnote">Found <span class="pkg-path">${esc(s.path)}</span>: ${esc(s.reason)}
    ${facts.installed ? "" : ` Momentum will install its tested copy at <span class="pkg-path">${esc(facts.executable || facts.root || "")}</span> instead.`}</p>`).join("");
  return where + skipped;
}

function prerequisiteNotes(prerequisites) {
  return (prerequisites || []).map(item => `<section class="pkg-warning">
    <strong>${esc(item.title)}</strong><p>${esc(item.reason)}</p>
    ${item.commands?.length ? `<p>${esc(item.instruction)}</p>${item.commands.map(command =>
      `<pre><code>${esc(command.join(" "))}</code></pre>`).join("")}`
      : `<p>${esc(item.instruction)}${item.packages?.length
        ? ` Required packages: ${esc(item.packages.join(", "))}` : ""}</p>`}
  </section>`).join("");
}

function softwareEvidenceNote(facts, target) {
  if (!facts?.installed || !target?.commit || facts.commit === target.commit) return "";
  return `<p class="pkg-warning">This existing copy is not the build covered by this package's evidence.
    Momentum will leave it untouched and block this installation. Required: ${esc(target.version || "version unknown")}
    (${esc(target.commit)}); found: ${esc(facts.version || "version unknown")}
    (${esc(facts.commit || "commit unknown")}).</p>`;
}

function compatibilityNotice(detail) {
  if (detail.managed_fallback) {
    const fallback = detail.managed_fallback;
    return `<section class="pkg-warning"><strong>Prepare a tested engine for this game</strong>
      <p>${fallback.test_mode ? "Isolated-engine test mode is enabled." : "No tested existing copy was found."}
      Momentum can prepare ${esc(fallback.target.version)}
      separately, leaving your current engine untouched. Review and approve this first, then approve the game installation.</p>
      <p>Allow at least ${Math.ceil(fallback.space_required_bytes / 1073741824)} GiB free.
      This game will use separate settings and saves; existing profiles are not imported.</p>
      <details><summary>Engine and state locations</summary>${packageJson(fallback)}</details></section>`;
  }
  const guidance = detail.compatibility;
  if (!guidance) return "";
  return `<section class="pkg-warning"><strong>${esc(guidance.title)}</strong>
    <p>${esc(guidance.message)}</p>${guidance.reason === "missing-evidence"
      ? '<p><a href="https://github.com/jacobm36/momentum-core-launcher/releases" target="_blank" rel="noopener noreferrer">Get the latest Momentum launcher</a></p><p>Close this launcher before starting the updated copy. Keep your old folders and journals.</p>'
      : ""}${guidance.reason === "software-mismatch"
        ? `<details><summary>Required build and detected software</summary>${packageJson({
            required: detail.supported_software || {}, detected: detail.dependencies || {}
          })}</details>` : ""}</section>`;
}

async function selectPackage(id, version) {
  const d = $("#pdlg");
  try {
    const detail = await packageResponse(await fetch(`/api/packages/${encodeURIComponent(id)}/${encodeURIComponent(version)}`));
    if (!d.open) return;
    selectedPackage = detail;
    const m = detail.manifest;
    const bundledDuke = m.requires?.some(requirement => requirement.id === "eduke32" && requirement.delivery === "bundled");
    const flatpak = detail.dependencies?.flycast || detail.dependencies?.uzdoom || detail.dependencies?.mame;
    const flatpakId = detail.dependencies?.flycast ? "flycast" : detail.dependencies?.uzdoom ? "uzdoom" : "mame";
    const native = detail.dependencies?.supermodel || detail.dependencies?.vkquake || detail.dependencies?.eduke32 || detail.dependencies?.ironwail || detail.dependencies?.openbor;
    const source = m.inputs.find(f => f.id === "source_dir");
    const destination = m.inputs.find(f => f.id === "games_root");
    d.innerHTML = `<h2>${esc(detail.name)} <small>${esc(detail.version)}</small></h2>
      <p class="pkg-error" role="alert" hidden></p>
      <ol class="pkg-steps" aria-label="Installation steps"><li aria-current="step">Choose files &amp; trust package</li><li>Review software, if needed</li><li>Approve game installation</li></ol>
      ${packageRequirements(detail)}
      <details><summary>Package fingerprint (integrity, not proof of trust)</summary><code class="pkg-digest">${esc(detail.digest)}</code></details>
      ${detail.platform_issues.length ? `<p class="pkg-warning" role="alert">Installation blocked: ${esc(detail.platform_issues.join("; "))}</p>` : ""}
      <details><summary>Declared actions and test evidence</summary>
        ${packageJson({ platform: m.platform, actions: m.actions, dependencies: m.requires, testing: m.testing })}</details>
      ${flatpak ? `<details ${flatpak.flatpak_available === false ? "open" : ""}><summary>Required game software: ${flatpak.installed ? "already installed" : "preparation needed"}</summary>
        <p class="bnote">${!flatpak.flatpak_available ? "Flatpak is missing. Install it through your Ubuntu system tools first."
          : flatpak.installed ? `Required software is installed (${esc(flatpak.version || "version unknown")}). It will not be automatically upgraded.`
          : "Momentum will prepare the software this game needs. Review required downloads first; after compatibility checks, review the game files in the same setup job."}</p>
        ${softwareLocation(flatpak)}
        ${detail.managed_fallback ? "" : softwareEvidenceNote(flatpak, detail.dependency_targets?.[flatpakId])}
        <p class="pkg-warning">${detail.install_enabled
          ? "This game setup is supported by compatibility evidence. Installation still requires review and approval of this plan; confirm gameplay for your installation afterward."
          : "This package and software build need matching compatibility evidence. Momentum checks before changing game files."}</p>
        <details><summary>Technical software details</summary>${packageJson(flatpak)}</details></details>` : ""}
      ${native ? `<details><summary>Required game software: ${native.installed ? "already installed" : "preparation needed"}</summary>
        <p class="bnote">${native.installed ? "Required software is installed. Momentum will reuse it without upgrading or changing its settings."
          : detail.dependencies?.openbor
            ? "Momentum will prepare the exact OpenBOR 6391 runtime bundled in this package after your approval. No engine download or FUSE is required. Then review the separate game installation and download plan."
          : bundledDuke
            ? "Momentum will prepare the exact native EDuke32 build bundled in this package after your approval. No engine download or compilation is required. Then review the separate game installation plan."
          : detail.dependencies?.eduke32
            ? "Momentum will build the required software from pinned official source after your approval. Ubuntu build prerequisites must already be installed. Then review the game installation plan."
            : "Momentum will get the required software from its pinned official release after your approval. Then review the game installation plan."}</p>
        ${softwareLocation(native)}
        <p class="pkg-warning">Installer checks do not certify gameplay. Confirm controls, display and saved progress for this installation.</p>
        <details><summary>Technical software details</summary>${packageJson(native)}</details></details>` : ""}
      ${compatibilityNotice(detail)}
      ${detail.engine_selection ? `<details><summary>Engine selection and supported builds</summary>
        ${packageJson(detail.engine_selection)}</details>` : ""}
      ${prerequisiteNotes(detail.host_prerequisites)}
      <form id="pkg-setup">
        <h3>Your game files</h3>
        ${detail.dependencies?.ironwail ? '<p class="bnote">QBJ3 is downloaded separately from its official-site-linked mirror because its assets cannot be bundled. The pinned download is about 2.7 GB; allow about 17 GiB free for a fresh download and installation. A complete existing qbj3 folder is reused read-only. Review source/software preparation first, then approve the separate game installation plan.</p>' : ""}
        ${source ? `${packageInput(source, detail)}
          <p class="bnote">Choose a folder or paste its full path; Momentum copies them and leaves your originals untouched.</p>` : ""}
        ${m.inputs.filter(f => f !== source && f !== destination).map(f =>
          packageInput(f, detail) + (f.help ? `<p class="bnote">${esc(f.help)}</p>` : "")).join("")}
        ${destination ? `<p class="bnote">Momentum will install your game here:</p>
          <output id="pkg-destination" class="pkg-path" aria-live="polite"></output>
          <details><summary>Change installation folder</summary>${packageInput(destination, detail)}</details>` : ""}
        <details><summary>Use an existing library entry</summary>
        <label>Link to a library entry (does not take ownership of existing files)
          <select id="pkg-association"><option value="">Create a new library entry</option>
            ${games.map(g => `<option value="${esc(g.id)}">${esc(g.name)}</option>`).join("")}</select></label></details>
        <p class="bnote">This first permission lets the package check your setup. It does not approve installation.
          Required software and game changes are reviewed separately when needed.</p>
        <label class="pkg-check"><input type="checkbox" id="pkg-trust">I trust this package's publisher and permit its preflight code to run.</label>
        <p class="pkg-warning">Installer scripts run as your user and can access your files. Checksums and declared actions do not sandbox them.</p>
        <div class="btns"><button type="button" id="pkg-back">Back</button>
          <button type="submit" id="pkg-preflight" class="primary" disabled>Check installation plan</button></div>
      </form>`;
    const form = d.querySelector("#pkg-setup"), submit = d.querySelector("#pkg-preflight");
    if (destination) {
      const input = d.querySelector("#pkg-input-games_root"), preview = d.querySelector("#pkg-destination");
      const updateDestination = () => {
        const root = input.value;
        preview.textContent = root.startsWith("/")
          ? `${root.replace(/\/+$/, "")}/${m.destination_name}`
          : "Enter a full folder path starting with /.";
      };
      input.oninput = updateDestination;
      updateDestination();
    }
    d.onclick = async e => {
      if (e.target.id === "pkg-back") { d.close(); openPackages(); }
      const button = e.target.closest(".pkg-browse");
      if (!button || button.disabled) return;
      const input = document.getElementById(button.dataset.input);
      button.disabled = true;
      d.querySelector(".pkg-error").hidden = true;
      try {
        const result = await packageResponse(await post("/api/picker/directory", {
          initial: input.value.startsWith("/") ? input.value : ""
        }));
        if (d.open && input.isConnected && result.path !== null) {
          input.value = result.path;
          input.dispatchEvent(new Event("input", { bubbles: true }));
        }
      } catch (error) { if (d.open && input.isConnected) packageError(d, error); }
      finally { if (button.isConnected) button.disabled = false; }
    };
    d.querySelector("#pkg-trust").onchange = e => { submit.disabled = !e.target.checked || detail.platform_issues.length > 0; };
    form.onsubmit = async e => {
      e.preventDefault();
      if (!d.querySelector("#pkg-trust").checked || detail.platform_issues.length || submit.disabled) return;
      submit.disabled = true;
      try {
        const inputs = {};
        for (const f of m.inputs) {
          const input = d.querySelector(`#pkg-input-${f.id}`);
          if (!f.required && f.type !== "boolean" && input.value === "") continue;
          inputs[f.id] = f.type === "boolean" ? input.checked : input.value;
          if (f.type === "directory" && !input.value.startsWith("/")) throw new Error(`${packageInputLabel(f)} Enter a full folder path starting with /.`);
        }
        const data = await packageResponse(await post("/api/packages/install", {
          id, version, inputs, trusted_digest: detail.digest,
          catalog_entry_id: d.querySelector("#pkg-association").value || null
        }));
        d.close();
        notify("Checking your setup. Each approval step will open when ready; nothing is approved automatically.", { kind: "ok", title: detail.name });
        await refresh();
        guidePackageSetup(data.id);
        const row = $(`#idlg .job[data-id="${data.id}"]`);
        row?.scrollIntoView({ block: "nearest" });
      } catch (error) { packageError(d, error); }
      finally { if (submit.isConnected) submit.disabled = !d.querySelector("#pkg-trust").checked; }
    };
    d.querySelector("#pkg-back").focus();
  } catch (error) { packageError(d, error); }
}

async function reviewPackagePlan(id) {
  const d = $("#rdlg");
  if (d.open) return;
  d.innerHTML = '<h2>Review installation plan</h2><p class="pkg-error" role="alert" hidden></p><p>Loading saved plan...</p>';
  d.showModal();
  try {
    const job = await packageResponse(await fetch(`/api/jobs/${id}`));
    if (!d.open) return;
    if (job.status !== "awaiting-approval") throw new Error("This job is no longer waiting for approval.");
    if (job.plan_error || job.plan == null) throw new Error(job.plan_error || "No reviewable plan was supplied.");
    const plan = job.plan, actions = Array.isArray(plan.actions) ? plan.actions : [];
    const preparing = plan.operation === "prepare-dependency";
    d.innerHTML = `<h2>${plan.operation === "uninstall" ? "Review uninstall" : preparing ? "Review required software" : "Review game installation"}: ${esc(job.title)}</h2>
      <p class="pkg-error" role="alert" hidden></p>
      <p class="bnote">${plan.operation === "uninstall" ? "Remove unchanged installer-owned files; keep player state and modified files."
        : preparing ? "Prepare the software this game needs. You will review the game installation afterward."
        : "Check the destination and changes below. This approval installs the game using the saved plan."}
        Approval applies only to this exact plan, not future changes.</p>
      <p class="pkg-plan-summary">${preparing ? "Software preparation only. Review the required downloads and locations below."
        : `${actions.length} planned file change${actions.length === 1 ? "" : "s"}. Expand the file list to inspect paths and backups.`}</p>
      <details><summary>Plan fingerprint</summary><code class="pkg-digest">${esc(job.plan_digest)}</code></details>
      ${plan.game_directory ? `<h3>Game destination</h3><p class="pkg-path">${esc(plan.game_directory)}</p>` : ""}
      <details><summary>Planned file changes (${actions.length}), including backups</summary>
      ${actions.length ? `<div class="pkg-actions">${actions.map(a => `<article><b>${esc(a.op)} / ${esc(a.ownership)}</b>
        <p class="pkg-path">${esc(a.path)}</p><p class="bnote">${esc(a.before?.kind || "unknown")} → ${esc(a.after?.kind || "unknown")}</p>
        ${a.backup ? `<p class="bnote">Backup: <span class="pkg-path">${esc(a.backup)}</span></p>` : ""}</article>`).join("")}</div>`
        : '<p class="bnote">No file changes listed.</p>'}</details>
      <details><summary>Technical software and network details</summary>${packageJson(plan.dependencies || {})}</details>
      ${plan.package_id === "marvel-infinity-war" && Array.isArray(plan.network) && plan.network.length ? `<h3>Game content download</h3>
        <p class="bnote">The package will download this pinned game content only after you approve this game installation plan. Only the verified game PAK is extracted; upstream executables and settings are not imported.</p>
        ${packageJson(plan.network)}` : ""}
      ${Array.isArray(plan.downloads) ? `<h3>Required software and mod source</h3>
        <p class="bnote">These pinned downloads prepare shared software/source only. Original game files and saves are not changed. After preparation, review and approve the separate game installation plan.</p>
        ${packageJson(plan.downloads)}
        <p class="pkg-warning">Shared software and verified source caches remain after removal. QBJ3 source download is about 2.7 GB; allow about 17 GiB free for a fresh setup.</p>` : ""}
      ${Array.isArray(plan.dependency_commands) ? `<h3>Software required for this game</h3>
        ${plan.managed_engine ? `<p class="pkg-warning"><strong>Prepare a tested isolated engine</strong>
          Your existing engine is not changed. This download goes into a separate Momentum-owned installation,
          with separate settings and saves for this game. Allow at least ${Math.ceil(plan.space_required_bytes / 1073741824)} GiB free.</p>
          <p class="pkg-path">${esc(plan.slot)}</p>` : ""}
        <p class="bnote">${plan.runtime_publication
          ? plan.dependency === "eduke32"
            ? "Momentum will copy the exact verified EDuke32 runtime bundled in this package into the location below. No engine download or compilation is required."
            : "Momentum will extract the verified OpenBOR 6391 runtime already bundled in this package into the location below. No engine download or FUSE is required."
          : plan.dependency_download
          ? "Momentum will download the required software from its pinned official GitHub release for your account. No administrator access or automatic upgrade is requested."
          : plan.dependency_commands.length ? "Momentum will download the required software from Flathub for your account. No administrator access or automatic upgrade is requested."
          : "No downloads needed; reuse the installed software without upgrading it."}</p>
        ${plan.runtime_publication ? `<p class="pkg-path">${esc(plan.runtime_publication.target)}</p>` : ""}
        ${plan.runtime_publication?.preserve_altered ? `<p class="pkg-warning">The existing OpenBOR runtime copy was altered. Approving moves it aside unchanged to the location below, then publishes a fresh verified copy. Nothing is deleted.</p>
          <p class="pkg-path">${esc(plan.runtime_publication.preserve_altered.destination)}</p>` : ""}
        <details><summary>Exact software preparation</summary>${packageJson(plan.runtime_publication || plan.dependency_download || plan.dependency_commands)}</details>
        <p class="pkg-warning">${plan.dependency === "openbor"
          ? "The shared runtime is retained after game removal. Cancellation is checked at safe extraction/publication boundaries. After preparation, review the separate game installation plan."
          : "Shared software remains installed if later game work fails. Cancellation waits for an active download/install transaction to finish. After preparation, Momentum checks compatibility and asks you to review the game files."}</p>` : ""}
      <details><summary>Preserved files and state</summary>${packageJson({ preserve: plan.preserve || [], state: plan.state_destinations || [] })}</details>
      ${plan.manual_actions?.length ? `<h3>${plan.operation === "uninstall" ? "Removal notes" : "Manual setup after installation"}</h3>
        <ul>${plan.manual_actions.map(a => `<li>${esc(a.message || a.action_id)}</li>`).join("")}</ul>` : ""}
      <details><summary>Complete saved plan (including hashes and inventories)</summary>${packageJson(plan)}</details>
      ${job.approval_blocked ? (compatibilityNotice(job) || `<p class="pkg-warning">${esc(job.approval_blocked)}</p>`) : ""}
      ${prerequisiteNotes(job.host_prerequisites)}
      ${job.engine_selection ? `<details><summary>Engine selection and supported builds</summary>
        ${packageJson(job.engine_selection)}</details>` : ""}
      <label class="pkg-check"><input type="checkbox" id="plan-consent" ${job.approval_blocked ? "disabled" : ""}>I approve the listed changes.</label>
      <div class="btns"><button type="button" id="plan-close" autofocus>Close</button><button type="button" id="plan-cancel">Cancel job</button>
        <button type="button" id="plan-approve" class="primary" disabled>${plan.operation === "uninstall" ? "Approve and uninstall" : plan.managed_engine ? "Prepare tested isolated engine" : plan.operation === "prepare-dependency" ? (plan.downloads ? "Approve software / source preparation" : "Approve required software") : "Approve and install"}</button></div>`;
    const approve = d.querySelector("#plan-approve");
    d.querySelector("#plan-consent").onchange = e => { approve.disabled = !e.target.checked || Boolean(job.approval_blocked); };
    d.onclick = async e => {
      if (e.target.id === "plan-close") return d.close();
      const action = e.target.id === "plan-cancel" ? "cancel" : e.target.id === "plan-approve" ? "approve" : null;
      if (!action || e.target.disabled) return;
      const buttons = [...d.querySelectorAll("button")]; buttons.forEach(b => { b.disabled = true; });
      try {
        await packageResponse(await post(`/api/jobs/${id}/${action}`, action === "approve" ? { plan_digest: job.plan_digest } : {}));
        d.close(); await refresh();
      } catch (error) {
        packageError(d, error);
        buttons.forEach(b => { b.disabled = false; });
        approve.disabled = true;
        d.querySelector("#plan-consent").checked = false;
      }
    };
    d.querySelector("#plan-close").focus();
  } catch (error) {
    packageError(d, error);
    d.insertAdjacentHTML("beforeend", '<div class="btns"><button type="button" id="plan-close">Close</button></div>');
    d.onclick = e => { if (e.target.id === "plan-close") d.close(); };
  }
}
