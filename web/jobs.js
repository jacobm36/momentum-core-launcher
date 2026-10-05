// Background jobs (installs): status badge, job list, live logs.
let jobs = [], jobState = {}, jobsReady = false, logPoll = null, openLog = null;
const jobActive = j => j.status === "queued" || j.status === "running";
function handleJobs(list) {
  jobs = list || [];
  for (const j of jobs) {
    const prev = jobState[j.id]; jobState[j.id] = j.status;
    if (!jobsReady || prev === j.status || !prev) continue;
    if (j.status === "done") { notify(`${j.title} finished.`, { kind: "ok", title: "Install complete" }); sfx("ok"); }
    else if (j.status === "failed") { notify(j.error || "A step failed.", { kind: "error", title: `${j.title} failed` }); sfx("err"); }
    else if (j.status === "interrupted") notify("Stopped when the launcher closed. You can retry it.", { kind: "warn", title: j.title });
  }
  jobsReady = true;
  const b = $("#jobsbtn"); if (b) { const n = jobs.filter(jobActive).length; b.dataset.badge = n || ""; b.classList.toggle("busy", n > 0); }
  if ($("#idlg")?.open) renderJobs();
}
const jobPct = j => j.total ? Math.round((j.status === "done" ? j.total : j.done) / j.total * 100) : 0;
let jobSig = "";
function renderJobs(force) {
  const sig = JSON.stringify([jobs, openLog]);
  if (!force && sig === jobSig) { if (openLog) fetchLog(); return; }
  jobSig = sig;
  const d = $("#idlg"), foc = document.activeElement?.closest?.(".job") && [document.activeElement.closest(".job").dataset.id, document.activeElement.dataset.a], keep = d.querySelector(".jlist")?.scrollTop || 0;
  d.querySelector(".jlist").innerHTML = jobs.length ? jobs.map(j => {
    const acts = jobActive(j) ? `<button type="button" data-a="cancel">Cancel</button>`
      : `${j.status === "done" ? "" : '<button type="button" data-a="retry">Retry</button>'}<button type="button" data-a="dismiss">Dismiss</button>`;
    return `<div class="job ${esc(j.status)}" data-id="${esc(j.id)}">
      <div class="jhead"><b>${esc(j.title)}</b><span class="jstat">${esc(j.status)}</span></div>
      <div class="jbar"><i style="width:${jobPct(j)}%"></i></div>
      <div class="jsub">${esc(j.error || (jobActive(j) && j.step ? `${j.step} (${j.done}/${j.total})` : `${j.done}/${j.total} steps`))}</div>
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
    if (stick) pre.scrollTop = pre.scrollHeight;
  } catch { /* transient */ }
}
function openJobs() {
  const d = $("#idlg"); if (!d || topDlg()) return;
  openLog = null;
  d.innerHTML = `<h2>Installs &amp; jobs</h2><div class="jlist"></div>
    <div class="padhint pad-only"><kbd>A</kbd>Choose <kbd>B</kbd>Close</div>
    <div class="btns"><button type="button" id="iclose" class="primary" autofocus>Close</button></div>`;
  d.onclick = async e => {
    if (e.target.id === "iclose") return d.close();
    const b = e.target.closest("[data-a]"); if (!b) return;
    const id = b.closest(".job").dataset.id, a = b.dataset.a;
    if (a === "log") { openLog = openLog === id ? null : id; return renderJobs(); }
    const r = await post(`/api/jobs/${id}/${a}`);
    if (!r.ok) notify((await r.json().catch(() => ({}))).error || "That didn't work.", { kind: "error" });
    sfx("tick"); refresh();
  };
  d.onkeydown = e => { if (e.key === "Escape") { e.preventDefault(); d.close(); } };
  d.onclose = () => { clearInterval(logPoll); openLog = null; };
  renderJobs(true); logPoll = setInterval(() => { refresh(); }, 1000);
  d.showModal(); sfx("open");
}
if ($("#jobsbtn")) $("#jobsbtn").onclick = e => { e.currentTarget.blur(); openJobs(); };
