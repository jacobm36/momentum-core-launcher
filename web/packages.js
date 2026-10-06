// Local package intake, trust, input collection and exact-plan review.
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
function openPackages() {
  const d = $("#pdlg");
  if (d.open) return;
  selectedPackage = null;
  d.innerHTML = `<h2>Install packages</h2>
    <p class="bnote">Download a package ZIP from a publisher you trust, then import it here.
    Packages contain installers, not game files. A built-in download catalog is planned separately.</p>
    <p class="pkg-warning">Import only checks and copies the package. No scripts run until you approve trust and request preflight.</p>
    <p class="pkg-error" role="alert" hidden></p>
    <div class="pkg-import"><button type="button" id="pkg-zip">Choose package ZIP...</button>
      <input type="file" id="pkg-file" accept=".zip,application/zip" hidden>
      <label>Or an absolute local folder / ZIP path<input id="pkg-path" placeholder="/home/you/Downloads/package" autocomplete="off"></label>
      <button type="button" id="pkg-import-path">Import path</button></div>
    <h3>Imported packages</h3><div class="pkg-list"><p class="bnote">Loading...</p></div>
    <div class="btns"><button type="button" id="pkg-close" autofocus>Close</button></div>`;
  d.onclick = async e => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.id === "pkg-close") return d.close();
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

function packageInput(field, detail) {
  const id = `pkg-input-${field.id}`, label = field.label || field.id.replace(/_/g, " ");
  const value = field.default === "home_games" ? detail.home_games : field.default;
  const required = field.required ? " required" : "";
  if (field.type === "boolean") return `<label class="pkg-check"><input id="${esc(id)}" type="checkbox" ${value === true ? "checked" : ""}>${esc(label)}</label>`;
  if (field.type === "choice") return `<label>${esc(label)}<select id="${esc(id)}"${required}>
    ${field.choices.map(v => `<option value="${esc(v)}" ${v === value ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>`;
  return `<label>${esc(label)}${field.required ? " (required)" : ""}
    <input id="${esc(id)}" value="${esc(value ?? "")}"${required} autocomplete="off"
    ${field.type === "directory" ? 'placeholder="/absolute/folder/path"' : ""}></label>`;
}

async function selectPackage(id, version) {
  const d = $("#pdlg");
  try {
    const detail = await packageResponse(await fetch(`/api/packages/${encodeURIComponent(id)}/${encodeURIComponent(version)}`));
    if (!d.open) return;
    selectedPackage = detail;
    const m = detail.manifest;
    const flycast = detail.dependencies?.flycast;
    d.innerHTML = `<h2>${esc(detail.name)} <small>${esc(detail.version)}</small></h2>
      <p class="pkg-error" role="alert" hidden></p>
      <p class="bnote">Package fingerprint (integrity, not proof of trust)</p><code class="pkg-digest">${esc(detail.digest)}</code>
      ${detail.platform_issues.length ? `<p class="pkg-warning" role="alert">Installation blocked: ${esc(detail.platform_issues.join("; "))}</p>` : ""}
      <details><summary>Declared actions and test evidence</summary>
        ${packageJson({ platform: m.platform, actions: m.actions, dependencies: m.requires, testing: m.testing })}</details>
      ${flycast ? `<h3>Flycast dependency</h3>
        <p class="bnote">${!flycast.flatpak_available ? "Flatpak is missing. Install it through your Ubuntu system tools first."
          : flycast.installed ? `User-scope Flycast is installed (${esc(flycast.version || "version unknown")}). It will not be automatically upgraded.`
          : "User-scope Flycast is missing. Use Prepare Flycast in Installs & jobs to review its installation commands."}</p>
        <p class="pkg-warning">${detail.install_enabled
          ? "This HOD2 package and Flycast build passed the target test. Installation still requires review and approval of this plan; confirm gameplay for your installation afterward."
          : "Dependency preparation is separate from game installation. Only the tested HOD2 package and verified Flycast build are enabled."}</p>
        <details><summary>Detected dependency facts</summary>${packageJson(flycast)}</details>` : ""}
      <form id="pkg-setup">
        <h3>Installation inputs</h3>${m.inputs.map(f => packageInput(f, detail)).join("")}
        <label>Library association (optional; does not adopt existing files)
          <select id="pkg-association"><option value="">Create a new library entry</option>
            ${games.map(g => `<option value="${esc(g.id)}">${esc(g.name)}</option>`).join("")}</select></label>
        <p class="bnote">Your source stays unchanged. Preflight shows the exact destination, files, backups and setup requirements before any installation changes.</p>
        <label class="pkg-check"><input type="checkbox" id="pkg-trust">I trust this package's publisher and permit its preflight code to run.</label>
        <p class="pkg-warning">Installer scripts run as your user and can access your files. Checksums and declared actions do not sandbox them.</p>
        <div class="btns"><button type="button" id="pkg-back">Back</button>
          <button type="submit" id="pkg-preflight" class="primary" disabled>Check installation plan</button></div>
      </form>`;
    const form = d.querySelector("#pkg-setup"), submit = d.querySelector("#pkg-preflight");
    d.onclick = e => { if (e.target.id === "pkg-back") { d.close(); openPackages(); } };
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
          if (f.type === "directory" && !input.value.startsWith("/")) throw new Error(`${f.id} must be an absolute directory path.`);
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
      <details open><summary>Dependencies and network decisions</summary>${packageJson(plan.dependencies || {})}</details>
      ${Array.isArray(plan.dependency_commands) ? `<h3>Exact dependency commands</h3>
        ${plan.dependency_commands.length ? packageJson(plan.dependency_commands) : '<p class="bnote">No commands needed; reuse the installed dependency without upgrading it.</p>'}
        <p class="pkg-warning">These user-scope changes are shared. Flycast and its runtime are retained if later game work fails. Cancellation waits for an active transaction to finish.</p>` : ""}
      <details><summary>Preserved files and state</summary>${packageJson({ preserve: plan.preserve || [], state: plan.state_destinations || [] })}</details>
      <h3>Manual setup after installation</h3>
      <ul>${(plan.manual_actions || []).map(a => `<li>${esc(a.message || a.action_id)}</li>`).join("") || "<li>No manual actions listed.</li>"}</ul>
      <details><summary>Complete saved plan (including hashes and inventories)</summary>${packageJson(plan)}</details>
      ${job.approval_blocked ? `<p class="pkg-warning">${esc(job.approval_blocked)}</p>` : ""}
      <label class="pkg-check"><input type="checkbox" id="plan-consent" ${job.approval_blocked ? "disabled" : ""}>I approve the listed changes.</label>
      <div class="btns"><button type="button" id="plan-close" autofocus>Close</button><button type="button" id="plan-cancel">Cancel job</button>
        <button type="button" id="plan-approve" class="primary" disabled>${plan.operation === "prepare-dependency" ? "Approve dependency preparation" : "Approve and install"}</button></div>`;
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
