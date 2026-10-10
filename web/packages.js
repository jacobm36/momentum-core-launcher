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

function openPackages() {
  const d = $("#pdlg");
  if (d.open) return;
  selectedPackage = null;
  d.innerHTML = `<h2>Add game</h2>
    <p class="bnote">Choose a game. Momentum gets its installer; you provide your game files.</p>
    <p class="pkg-error" role="alert" hidden></p>
    <div id="catalog-games"><p class="bnote">Loading available games...</p></div>
    <div id="catalog-download" hidden><p id="catalog-status" role="status"></p>
      <progress id="catalog-progress" aria-label="Installer download progress"></progress>
      <button type="button" id="catalog-cancel">Cancel download</button></div>
    <details id="catalog-advanced"><summary>Advanced</summary><div class="btns">
      <button type="button" id="catalog-manual">Add an existing game manually...</button></div></details>
    <div class="btns"><button type="button" id="catalog-import">Local packages / import...</button>
      <button type="button" id="catalog-retry">Refresh games</button>
      <button type="button" id="pkg-close" autofocus>Close</button></div>`;
  d.onclick = e => {
    if (e.target.id === "pkg-close") d.close();
    if (e.target.id === "catalog-retry") loadGameCatalog();
    if (e.target.id === "catalog-import") { d.close(); openImportedPackages(); }
    if (e.target.id === "catalog-manual") { d.close(); editor(null, true); }
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
    list.innerHTML = catalog.games.length ? catalog.games.map(g => {
      const ready = imported.packages.some(p => p.id === g.id && p.version === g.version && p.digest === g.digest);
      return `<article class="catalog-card"><img src="${esc(g.icon_url)}" alt="" referrerpolicy="no-referrer">
        <div><h3>${esc(g.name)}</h3><p class="bnote">${esc(g.description)}</p>
        ${g.platform_issues.length ? `<p class="pkg-warning">${esc(g.platform_issues.join("; "))}</p>` : ""}
        <button type="button" class="primary" data-game="${esc(g.id)}" ${g.platform_issues.length ? "disabled" : ""}>
          ${ready ? "Continue setup" : "Set up game"}</button></div></article>`;
    }).join("") : '<p class="sempty">No games available yet.</p>';
    list.onclick = async e => {
      const button = e.target.closest("[data-game]"); if (!button || button.disabled) return;
      const game = catalog.games.find(g => g.id === button.dataset.game);
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
      <button type="button" data-package="${esc(p.id)}" data-version="${esc(p.version)}">Set up</button></div>`
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

function packageInputLabel(field) {
  if (field.id === "mod_dir") return "Existing extracted mod folder (optional)";
  if (field.role === "source" || field.id === "source_dir") return "Where are your game files?";
  if (field.role === "destination" || field.id === "games_root") return "Install games in";
  return field.label || field.id.replace(/_/g, " ");
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
    ? `<p class="bnote">Using your existing copy: <span class="pkg-path">${esc(facts.location)}</span></p>` : "";
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
  const guidance = detail.compatibility;
  if (!guidance) return "";
  return `<section class="pkg-warning"><strong>${esc(guidance.title)}</strong>
    <p>${esc(guidance.message)}</p>${guidance.reason === "missing-evidence"
      ? '<p><a href="https://github.com/jacobm36/momentum-distribution/releases/latest" target="_blank" rel="noopener noreferrer">Get the latest Momentum launcher</a></p><p>Close this launcher before starting the updated copy. Keep your old folders and journals.</p>'
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
    const flatpak = detail.dependencies?.flycast || detail.dependencies?.uzdoom;
    const flatpakId = detail.dependencies?.flycast ? "flycast" : "uzdoom";
    const native = detail.dependencies?.supermodel || detail.dependencies?.vkquake || detail.dependencies?.eduke32 || detail.dependencies?.ironwail;
    const source = m.inputs.find(f => f.id === "source_dir");
    const destination = m.inputs.find(f => f.id === "games_root");
    d.innerHTML = `<h2>${esc(detail.name)} <small>${esc(detail.version)}</small></h2>
      <p class="pkg-error" role="alert" hidden></p>
      <p class="bnote">Package fingerprint (integrity, not proof of trust)</p><code class="pkg-digest">${esc(detail.digest)}</code>
      ${detail.platform_issues.length ? `<p class="pkg-warning" role="alert">Installation blocked: ${esc(detail.platform_issues.join("; "))}</p>` : ""}
      <details><summary>Declared actions and test evidence</summary>
        ${packageJson({ platform: m.platform, actions: m.actions, dependencies: m.requires, testing: m.testing })}</details>
      ${flatpak ? `<h3>Required game software</h3>
        <p class="bnote">${!flatpak.flatpak_available ? "Flatpak is missing. Install it through your Ubuntu system tools first."
          : flatpak.installed ? `Required software is installed (${esc(flatpak.version || "version unknown")}). It will not be automatically upgraded.`
          : "Momentum will prepare the software this game needs. Review required downloads first; after compatibility checks, review the game files in the same setup job."}</p>
        ${softwareLocation(flatpak)}
        ${softwareEvidenceNote(flatpak, detail.dependency_targets?.[flatpakId])}
        <p class="pkg-warning">${detail.install_enabled
          ? "This game setup is supported by compatibility evidence. Installation still requires review and approval of this plan; confirm gameplay for your installation afterward."
          : "This package and software build need matching compatibility evidence. Momentum checks before changing game files."}</p>
        <details><summary>Technical software details</summary>${packageJson(flatpak)}</details>` : ""}
      ${native ? `<h3>Required game software</h3>
        <p class="bnote">${native.installed ? "Required software is installed. Momentum will reuse it without upgrading or changing its settings."
          : detail.dependencies?.eduke32
            ? "Momentum will build the required software from pinned official source after your approval. Ubuntu build prerequisites must already be installed. Then review the game installation plan."
            : "Momentum will get the required software from its pinned official release after your approval. Then review the game installation plan."}</p>
        ${softwareLocation(native)}
        <p class="pkg-warning">Installer checks do not certify gameplay. Confirm controls, display and saved progress for this installation.</p>
        <details><summary>Technical software details</summary>${packageJson(native)}</details>` : ""}
      ${compatibilityNotice(detail)}
      ${prerequisiteNotes(detail.host_prerequisites)}
      <form id="pkg-setup">
        <h3>Your game files</h3>
        ${detail.dependencies?.ironwail ? '<p class="bnote">QBJ3 is downloaded separately from its official-site-linked mirror because its assets cannot be bundled. The pinned download is about 2.7 GB; allow about 17 GiB free for a fresh download and installation. A complete existing qbj3 folder is reused read-only. Review source/software preparation first, then approve the separate game installation plan.</p>' : ""}
        ${source ? `${packageInput(source, detail)}
          <p class="bnote">Leave your game files where they are. Choose their folder, or type/paste its full path; Momentum copies them and leaves your originals untouched.
          ${source.help ? esc(source.help) : detail.id === "the-house-of-the-dead-2" ? "For HOD2, use the folder containing the CUE file and all matching BIN tracks together. The package ZIP does not contain the game." : ""}</p>` : ""}
        ${m.inputs.filter(f => f !== source && f !== destination).map(f =>
          packageInput(f, detail) + (f.help ? `<p class="bnote">${esc(f.help)}</p>` : "")).join("")}
        ${destination ? `<p class="bnote">Momentum will install your game here:</p>
          <output id="pkg-destination" class="pkg-path" aria-live="polite"></output>
          <details><summary>Change installation folder</summary>${packageInput(destination, detail)}</details>` : ""}
        <details><summary>Use an existing library entry</summary>
        <label>Link to a library entry (does not take ownership of existing files)
          <select id="pkg-association"><option value="">Create a new library entry</option>
            ${games.map(g => `<option value="${esc(g.id)}">${esc(g.name)}</option>`).join("")}</select></label></details>
        <p class="bnote">Nothing is installed yet. Next, review the exact changes before approving installation.</p>
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
        notify("Preflight started. Review its plan in Installs & jobs.", { kind: "ok", title: detail.name });
        await refresh();
        if (!$("#idlg").open) openJobs();
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
    d.innerHTML = `<h2>Review: ${esc(job.title)}</h2>
      <p class="pkg-error" role="alert" hidden></p>
      <p class="bnote">Approval is bound to these exact saved plan bytes. No installation changes have been authorized yet.</p>
      <code class="pkg-digest">${esc(job.plan_digest)}</code>
      ${plan.game_directory ? `<h3>Game destination</h3><p class="pkg-path">${esc(plan.game_directory)}</p>` : ""}
      <h3>Planned file changes (${actions.length})</h3>
      ${actions.length ? `<div class="pkg-actions">${actions.map(a => `<article><b>${esc(a.op)} / ${esc(a.ownership)}</b>
        <p class="pkg-path">${esc(a.path)}</p><p class="bnote">${esc(a.before?.kind || "unknown")} → ${esc(a.after?.kind || "unknown")}</p>
        ${a.backup ? `<p class="bnote">Backup: <span class="pkg-path">${esc(a.backup)}</span></p>` : ""}</article>`).join("")}</div>`
        : '<p class="bnote">No file changes listed.</p>'}
      <details><summary>Technical software and network details</summary>${packageJson(plan.dependencies || {})}</details>
      ${Array.isArray(plan.downloads) ? `<h3>Required software and mod source</h3>
        <p class="bnote">These pinned downloads prepare shared software/source only. Original game files and saves are not changed. After preparation, review and approve the separate game installation plan.</p>
        ${packageJson(plan.downloads)}
        <p class="pkg-warning">Shared software and verified source caches remain after removal. QBJ3 source download is about 2.7 GB; allow about 17 GiB free for a fresh setup.</p>` : ""}
      ${Array.isArray(plan.dependency_commands) ? `<h3>Software required for this game</h3>
        <p class="bnote">${plan.dependency_download
          ? "Momentum will download the required software from its pinned official GitHub release for your account. No administrator access or automatic upgrade is requested."
          : plan.dependency_commands.length ? "Momentum will download the required software from Flathub for your account. No administrator access or automatic upgrade is requested."
          : "No downloads needed; reuse the installed software without upgrading it."}</p>
        <details><summary>Exact software preparation</summary>${packageJson(plan.dependency_download || plan.dependency_commands)}</details>
        <p class="pkg-warning">Shared software remains installed if later game work fails. Cancellation waits for an active download/install transaction to finish. After preparation, Momentum checks compatibility and asks you to review the game files.</p>` : ""}
      <details><summary>Preserved files and state</summary>${packageJson({ preserve: plan.preserve || [], state: plan.state_destinations || [] })}</details>
      <h3>Manual setup after installation</h3>
      <ul>${(plan.manual_actions || []).map(a => `<li>${esc(a.message || a.action_id)}</li>`).join("") || "<li>No manual actions listed.</li>"}</ul>
      <details><summary>Complete saved plan (including hashes and inventories)</summary>${packageJson(plan)}</details>
      ${job.approval_blocked ? (compatibilityNotice(job) || `<p class="pkg-warning">${esc(job.approval_blocked)}</p>`) : ""}
      <label class="pkg-check"><input type="checkbox" id="plan-consent" ${job.approval_blocked ? "disabled" : ""}>I approve the listed changes.</label>
      <div class="btns"><button type="button" id="plan-close" autofocus>Close</button><button type="button" id="plan-cancel">Cancel job</button>
        <button type="button" id="plan-approve" class="primary" disabled>${plan.operation === "prepare-dependency" ? (plan.downloads ? "Approve software / source preparation" : "Approve required software") : "Approve and install"}</button></div>`;
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
