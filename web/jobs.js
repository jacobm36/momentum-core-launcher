// Background jobs (installs): status badge, job list, live logs.
let jobs = [], jobState = {}, jobsReady = false, logPoll = null, openLog = null;
const jobActive = j => ["queued", "running", "cancel-requested"].includes(j.status);
function handleJobs(list) {
  jobs = list || [];
  for (const j of jobs) {
    const prev = jobState[j.id]; jobState[j.id] = j.status;
    if (!jobsReady || prev === j.status || !prev) continue;
    if (j.status === "succeeded") { notify(j.kind === "dependency" ? "Required software prepared. No game installed." : j.readiness === "setup-required" ? `${j.title} installed; manual setup is still required.` : `${j.title} finished.`, { kind: "ok", title: j.kind === "dependency" ? "Software prepared" : "Install complete" }); sfx("ok"); }
    else if (j.status === "failed") { notify(j.error || "A step failed.", { kind: "error", title: `${j.title} failed` }); sfx("err"); }
    else if (j.status === "interrupted") notify(j.error || "Stopped unexpectedly. You can retry it.", { kind: "warn", title: j.title });
    else if (j.status === "awaiting-approval") notify("Review the plan and approve it to continue.", { kind: "warn", title: j.title });
    else if (j.status === "needs-action") notify(j.actions?.[0]?.message || j.error || "Something needs your attention.", { kind: "warn", title: j.title });
    else if (j.status === "conflicted") notify(j.error || "It conflicts with existing files.", { kind: "warn", title: j.title });
  }
  jobsReady = true;
  const b = $("#jobsbtn"); if (b) { const n = jobs.filter(jobActive).length; b.dataset.badge = n || ""; b.classList.toggle("busy", n > 0); }
  if ($("#idlg")?.open) renderJobs();
}
const jobPct = j => {
  if (j.status === "succeeded") return 100;
  const p = j.progress;
  return p?.total > 0 ? Math.round(Math.max(0, Math.min(1, p.current / p.total)) * 100) : 0;
};
const jobLabel = s => s.replace(/-/g, " ");
function jobSub(j) {
  if (j.status === "cancel-requested") return "Cancellation requested; finishing current step.";
  if (j.error) return j.error;
  if (j.status === "needs-action" && j.actions.length) return j.actions.map(a => a.message).join(" ");
  if (j.status === "awaiting-approval") return "Waiting for your approval.";
  if (j.status === "succeeded" && j.kind === "dependency") return "Required software prepared. No game installed.";
  if (j.installation === "installed" && j.readiness === "setup-required") return `Installed - setup required. ${(j.actions || []).map(a => a.message).join(" ")}`;
  const p = j.progress;
  if (jobActive(j) && p) return `${p.message}${p.total ? ` (${p.current}/${p.total}${p.unit ? " " + p.unit : ""})` : ""}`;
  return jobActive(j) && j.step ? `${j.step} (${j.done}/${j.total})` : `${j.done}/${j.total} steps`;
}
let jobSig = "";
function renderJobs(force) {
  const sig = JSON.stringify([jobs, openLog]);
  if (!force && sig === jobSig) { if (openLog) fetchLog(); return; }
  jobSig = sig;
  const d = $("#idlg"), foc = document.activeElement?.closest?.(".job") && [document.activeElement.closest(".job").dataset.id, document.activeElement.dataset.a], keep = d.querySelector(".jlist")?.scrollTop || 0;
  d.querySelector(".jlist").innerHTML = jobs.length ? jobs.map(j => {
    const acts = j.status === "cancel-requested" ? ""
      : jobActive(j) ? `<button type="button" data-a="cancel">Cancel</button>`
      : j.status === "awaiting-approval" ? `<button type="button" data-a="review">Review plan</button><button type="button" data-a="cancel">Cancel</button>`
      : j.surviving ? ""
      : `${j.status === "succeeded" || j.manual ? "" : '<button type="button" data-a="retry">Retry</button>'}<button type="button" data-a="dismiss">Dismiss</button>`;
    return `<div class="job ${esc(j.status)}" data-id="${esc(j.id)}">
      <div class="jhead"><b>${esc(j.title)}</b><span class="jstat">${esc(jobLabel(j.status))}</span></div>
      <div class="jbar ${jobActive(j) && !(j.progress?.total > 0) ? "indeterminate" : ""}" aria-label="Current step progress"><i style="width:${jobPct(j)}%"></i></div>
      <div class="jsub">${esc(jobSub(j))}</div>
      <div class="jbtns"><button type="button" data-a="log">${openLog === j.id ? "Hide log" : "Log"}</button>${acts}</div>
      ${openLog === j.id ? '<pre class="jlog"></pre>' : ""}</div>`;
  }).join("") : '<p class="sempty">No installs or background jobs yet.</p>';
  d.querySelector(".jlist").scrollTop = keep;
  if (foc) (d.querySelector(`.job[data-id="${foc[0]}"] [data-a="${foc[1]}"]`) || d.querySelector("#iclose"))?.focus();
  if (openLog) fetchLog();
}
async function fetchLog() {
  const id = openLog, pre = $("#idlg .jlog"); if (!id || !pre) return;
  try {
    const j = await (await fetch(`/api/jobs/${id}?tail=6000`)).json();
    if (openLog !== id || !pre.isConnected) return;
    const stick = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8;
    pre.textContent = j.log || "(no output yet)";
    if (j.dependency_result) pre.textContent += "\n\nRecorded dependency outcome:\n" + JSON.stringify(j.dependency_result, null, 2);
    if (j.dependency_error) pre.textContent += "\n\n" + j.dependency_error;
    if (stick) pre.scrollTop = pre.scrollHeight;
  } catch { /* transient */ }
}
function openJobs() {
  const d = $("#idlg"); if (!d || topDlg()) return;
  openLog = null;
  d.innerHTML = `<h2>Installs &amp; jobs</h2><div class="jlist"></div>
    <div class="padhint pad-only"><kbd>A</kbd>Choose <kbd>B</kbd>Close</div>
    <div class="btns"><button type="button" id="ipackages">Install package...</button><button type="button" id="iclose" class="primary" autofocus>Close</button></div>`;
  d.onclick = async e => {
    if (e.target.id === "iclose") return d.close();
    if (e.target.id === "ipackages") return openPackages();
    const b = e.target.closest("[data-a]"); if (!b) return;
    const id = b.closest(".job").dataset.id, a = b.dataset.a;
    if (a === "log") { openLog = openLog === id ? null : id; return renderJobs(); }
    if (a === "review") return reviewPackagePlan(id);
    b.disabled = true;
    try {
      const r = await post(`/api/jobs/${id}/${a}`);
      if (!r.ok) throw new Error((await r.json()).error || "That didn't work.");
      sfx("tick"); await refresh();
    } catch (error) { notify(error.message, { kind: "error", title: "Jobs" }); }
    finally { b.disabled = false; }
  };
  d.onkeydown = e => { if (e.key === "Escape") { e.preventDefault(); d.close(); } };
  d.onclose = () => { clearInterval(logPoll); openLog = null; };
  renderJobs(true); logPoll = setInterval(() => { refresh(); }, 1000);
  d.showModal(); sfx("open");
}
if ($("#jobsbtn")) $("#jobsbtn").onclick = e => { e.currentTarget.blur(); openJobs(); };
