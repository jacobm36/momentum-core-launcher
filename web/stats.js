// Playtime summary dialog.
const hm = s => s < 60 ? "0m" : s < 3600 ? `${Math.floor(s / 60)}m` : `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m`;
const dayKey = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
// Per-day playtime and streaks come from the "days" history, which only exists for play since it was added.
function dayStats() {
  const days = {};
  for (const s of Object.values(stats)) for (const [k, v] of Object.entries(s.days || {})) days[k] = (days[k] || 0) + v;
  const at = n => { const d = new Date(); d.setDate(d.getDate() - n); return dayKey(d); };
  let cur = 0, i = days[at(0)] !== undefined ? 0 : 1;
  while (days[at(i)] !== undefined) { cur++; i++; }
  let best = 0, run = 0, prev = null;
  for (const k of Object.keys(days).sort()) {
    const d = new Date(k + "T12:00:00");
    run = prev && Math.round((d - prev) / 864e5) === 1 ? run + 1 : 1;
    best = Math.max(best, run); prev = d;
  }
  const week = [6, 5, 4, 3, 2, 1, 0].map(n => { const d = new Date(); d.setDate(d.getDate() - n); return { label: d.toLocaleDateString(undefined, { weekday: "short" }), secs: days[dayKey(d)] || 0 }; });
  return { cur, best, week, any: Object.keys(days).length > 0 };
}
function openStats() {
  const d = $("#sdlg"); if (!d || topDlg()) return;
  const rows = games.map(g => ({ g, s: stats[g.id] || {} })), played = rows.filter(r => r.s.launches);
  const total = rows.reduce((n, r) => n + (r.s.seconds || 0), 0), launches = rows.reduce((n, r) => n + (r.s.launches || 0), 0);
  const top = [...played].filter(r => r.s.seconds).sort((a, b) => b.s.seconds - a.s.seconds).slice(0, 5), max = top[0]?.s.seconds || 1;
  const ds = dayStats(), wmax = Math.max(60, ...ds.week.map(w => w.secs));
  const tile = (v, l) => `<div class="stile"><b>${v}</b><span>${l}</span></div>`;
  d.innerHTML = `<h2>Playtime</h2>
    <div class="sgrid">${tile(hm(total), "Total playtime")}${tile(launches, "Launches")}${tile(`${played.length} of ${games.length}`, "Games played")}${tile(games.length - played.length, "Never played")}${tile(`${ds.cur} day${ds.cur === 1 ? "" : "s"}`, "Current streak")}${tile(`${ds.best} day${ds.best === 1 ? "" : "s"}`, "Best streak")}</div>
    <h3>Last 7 days</h3>
    <div class="week">${ds.week.map(w => `<div class="wday" title="${hm(w.secs)}"><span class="wval">${w.secs ? hm(w.secs) : ""}</span><span class="wbar"><i style="height:${w.secs ? Math.max(6, Math.round(w.secs / wmax * 100)) : 0}%"></i></span><span class="wlab">${esc(w.label)}</span></div>`).join("")}</div>
    ${ds.any ? "" : '<p class="sempty">Streaks and daily charts start building from your next play session.</p>'}
    ${top.length ? `<h3>Most played</h3><div class="stop">${top.map(r => `<button type="button" class="srow" data-id="${esc(r.g.id)}"><span class="sname">${esc(r.g.name)}</span><span class="sbar"><i style="width:${Math.max(4, Math.round(r.s.seconds / max * 100))}%"></i></span><span class="stime">${hm(r.s.seconds)}</span></button>`).join("")}</div>` : '<p class="sempty">No playtime recorded yet. Play a game and come back.</p>'}
    <div class="padhint pad-only"><kbd>A</kbd>Choose <kbd>B</kbd>Close</div>
    <div class="btns"><button type="button" id="sclose" class="primary" autofocus>Close</button></div>`;
  d.onclick = e => {
    const r = e.target.closest(".srow");
    if (r) { d.close(); filter = ""; $("#search").value = ""; select(r.dataset.id); }
    else if (e.target.id === "sclose") d.close();
  };
  d.onkeydown = e => { if (e.key === "Escape") { e.preventDefault(); d.close(); } };
  d.showModal(); sfx("open");
}
