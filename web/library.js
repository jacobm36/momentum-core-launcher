// Library state, sorting and rendering of the list and detail panel.

const ago = t => {
  const s = Date.now() / 1000 - t;
  if (s < 90) return "just now";
  for (const [n, u] of [[86400, "day"], [3600, "hour"], [60, "minute"]]) if (s >= n) { const k = Math.floor(s / n); return `${k} ${u}${k > 1 ? "s" : ""} ago`; }
};
const dur = s => s < 60 ? "under a minute" : s < 3600 ? `${Math.round(s / 60)} min` : `${Math.floor(s / 3600)}h ${Math.round(s % 3600 / 60)}m`;
const statText = id => { const s = stats[id]; return s?.launches ? `Last played ${ago(s.last)} · ${s.launches} launch${s.launches > 1 ? "es" : ""}${s.seconds ? " · " + dur(s.seconds) + " played" : ""}` : "Not played yet"; };
const recent = () => games.filter(g => stats[g.id]?.last).sort((a, b) => stats[b.id].last - stats[a.id].last).slice(0, 5);
const url = p => `/${p}?v=${ver}`;
const thumb = g => g.icon ? `<img src="${url(g.icon)}" alt="">` : `<div class="ph">${esc(g.name[0])}</div>`;

const filtering = () => !!filter || tagSel.size > 0;
const tagKey = t => t.toLowerCase();
const tagLabel = k => games.flatMap(g => g.tags || []).find(t => tagKey(t) === k) || k;
function visible() {
  const q = filter.toLowerCase();
  return games.filter(g => (g.name.toLowerCase().includes(q) || (g.tags || []).some(t => t.toLowerCase().includes(q)))
    && [...tagSel].every(t => (g.tags || []).some(x => tagKey(x) === t)));
}
function clearFilters() { filter = ""; tagSel.clear(); const s = $("#search"); if (s) s.value = ""; renderList(); renderDetail(); }
function toggleTag(t) {
  const k = tagKey(t);
  if (!tagSel.delete(k)) tagSel.add(k);
  renderList(); renderDetail(); sfx("cat");
}
function renderTagBar() {
  const bar = $("#tagbar"); if (!bar) return;
  bar.hidden = !tagSel.size;
  bar.innerHTML = tagSel.size ? [...tagSel].map(t => `<button type="button" class="tagchip" data-untag="${esc(t)}" title="Remove this tag from the filter">${esc(tagLabel(t))} ✕</button>`).join("")
    + `<span class="tagcount">${visible().length} game${visible().length === 1 ? "" : "s"}</span><button type="button" class="tagclear" data-untag="*">Clear</button>` : "";
}

const SORTS = [["cat", "Category"], ["last", "Last played"], ["time", "Most played"], ["az", "A–Z"]];
const sortMode = () => SORTS.find(s => s[0] === localStorage.getItem("mcl-sort"))?.[0] || "cat";
function applySort() {
  const b = $("#sort"); if (!b) return;
  const [, label] = SORTS.find(s => s[0] === sortMode());
  b.textContent = "⇅ " + label; b.title = `Sorted by: ${label} (S to change)`; b.classList.toggle("on", sortMode() !== "cat");
}
function cycleSort() {
  const i = SORTS.findIndex(s => s[0] === sortMode());
  localStorage.setItem("mcl-sort", SORTS[(i + 1) % SORTS.length][0]);
  applySort(); renderList(); sfx("cat");
  [...document.querySelectorAll(".item.sel")].pop()?.scrollIntoView({ block: "nearest" });
}
const SORT_BY = {
  last: (a, b) => (stats[b.id]?.last || 0) - (stats[a.id]?.last || 0),
  time: (a, b) => (stats[b.id]?.seconds || 0) - (stats[a.id]?.seconds || 0),
  az: () => 0,
};

// Games grouped by category, in the order categories first appear in games.json.
// Other sort orders give a single flat group.
function ordered() {
  const m = sortMode();
  if (m !== "cat") {
    const items = [...visible()].sort((a, b) => SORT_BY[m](a, b) || a.name.localeCompare(b.name));
    return items.length ? [{ cat: SORTS.find(s => s[0] === m)[1], items, sorted: true }] : [];
  }
  const cats = [...new Set(visible().map(g => g.category || "Other"))];
  return cats.map(c => ({ cat: c, items: visible().filter(g => (g.category || "Other") === c) }));
}
const flat = () => ordered().flatMap(c => c.items);

const row = (g, drag = true) => `<div class="item ${g.id === sel ? "sel" : ""}" data-id="${g.id}" ${filtering() || !drag ? "" : 'draggable="true"'}>${thumb(g)}<span>${esc(g.name)}</span>${g.favorite ? '<i class="star" title="Favorite">★</i>' : ""}${running.has(g.id) ? '<i class="dot" title="Running"></i>' : ""}</div>`;
const favs = () => games.filter(g => g.favorite);
// Re-rendering replaces elements, so put gamepad/keyboard focus back on the equivalent one.
function keepFocus(fn) {
  const a = document.activeElement; let sel = null;
  if (a?.closest("#list, #detail")) sel = a.id ? "#" + a.id : a.dataset.act ? `.cat[data-cat="${CSS.escape(a.closest(".cat").dataset.cat)}"] [data-act="${a.dataset.act}"]` : null;
  fn();
  if (sel) document.querySelector(sel)?.focus();
}
function renderList() {
  const list = $("#list"), key = JSON.stringify([filter, [...tagSel], sortMode()]);
  const scroll = restoredScroll ?? (listFilterKey === key ? list.scrollTop : 0);
  keepFocus(() => { renderTagBar(); renderListInner(); });
  list.scrollTo({ top: scroll, behavior: "instant" });
  restoredScroll = null; listFilterKey = key;
  saveBrowsing();
}
function renderListInner() {
  const count = $("#library-count");
  if (count) count.textContent = `${filtering() ? visible().length + " of " : ""}${games.length} game${games.length === 1 ? "" : "s"}`;
  const rc = filtering() ? [] : recent(), fv = filtering() ? [] : favs();
  $("#list").innerHTML = (fv.length ? `<div class="cat favs"><span>★ Favorites</span></div>` + fv.map(g => row(g, false)).join("") : "") + (rc.length ? `<div class="cat recent"><span>Recently played</span></div>` + rc.map(g => row(g, false)).join("") : "") + ordered().map(c =>
    `<div class="cat" ${c.sorted ? "" : `data-cat="${esc(c.cat)}"`}><span>${c.sorted ? "Sorted: " : ""}${esc(c.cat)}</span>${filtering() || c.sorted ? "" : '<span class="catbtns"><b tabindex="0" role="button" data-act="up" title="Move category up">▲</b><b tabindex="0" role="button" data-act="down" title="Move category down">▼</b><b tabindex="0" role="button" data-act="rename" title="Rename category">✎</b></span>'}</div>` + c.items.map(g => row(g, !c.sorted)).join("")).join("");
}

function renderDetail() { keepFocus(renderDetailInner); }
function renderDetailInner() {
  const g = games.find(x => x.id === sel), el = $("#detail"), bg = $("#bg"), art = $("#art");
  if (!g) {
    el.innerHTML = games.length ? '<p class="empty">No games found.</p>'
      : `<div class="welcome"><h1>Welcome to Momentum</h1><p>Your Linux games, together: Steam shortcuts, native games, and emulator launches.</p>
        <p>Import existing game shortcuts, add a launch command, or get a game installer from the store.</p>
        <div class="btns"><button id="welcome-import" class="primary">Import installed games</button>
          <button id="welcome-manual">Add a game manually</button>
          <button id="welcome-store">Browse the package store</button></div>
        <p class="hint">Import finds user, system, Flatpak and Snap game menu shortcuts. It does not scan every Steam library or install games.</p></div>`;
    $("#welcome-import")?.addEventListener("click", () => openInstalledGames());
    $("#welcome-manual")?.addEventListener("click", () => editor(null, true));
    $("#welcome-store")?.addEventListener("click", openPackages);
    return;
  }
  const on = running.has(g.id);
  if (shown !== g.id) { shown = g.id; for (const n of [el, art]) { n.classList.remove("swap"); void n.offsetWidth; n.classList.add("swap"); } }
  const tagline = `<div class="tagline">${esc(g.tagline || g.category || "")}</div>`;
  const runtime = g.runtime ? `<span class="runtime-badge" title="Runtime">${esc(g.runtime)}</span>` : "";
  const tags = `<div class="tags">${(g.tags || []).map(t => `<span data-tag="${esc(t)}" tabindex="0" role="button" aria-pressed="${tagSel.has(tagKey(t))}" class="${tagSel.has(tagKey(t)) ? "on" : ""}" title="${tagSel.has(tagKey(t)) ? "Remove" : "Add"} tag filter: ${esc(t)}">${esc(t)}</span>`).join("")}</div>`;
  const play = `<button id="play" ${on ? "disabled" : ""}>${on ? "RUNNING" : "▶ PLAY"}</button>`;
  const actions = `${play}<span id="toast"></span><span class="manage"><button id="fav" aria-pressed="${!!g.favorite}">${g.favorite ? "★ Favorited" : "☆ Favorite"}</button><button id="folders">Folders</button><button id="edit">Edit</button><button id="del">Remove</button></span>`;
  if (featuredPanel()) {
    const image = g.cover || g.icon;
    const media = image
      ? `<img class="${g.cover ? "cover" : "icon"}" src="${esc(url(image))}" alt="">`
      : `<div class="feature-monogram">${esc(g.name[0] || "?")}</div>`;
    el.innerHTML = `<div class="feature-art">${media}</div><div class="feature-copy">
      <div class="feature-top">${tagline}<div class="feature-badges">${runtime}${on ? '<span class="running-badge">● Running</span>' : ""}${g.favorite ? '<span class="favorite-badge">★ Favorite</span>' : ""}</div></div>
      <h1>${esc(g.name)}</h1><p class="desc">${esc(g.description || "")}</p>${tags}
      ${galleryStrip(g)}<div class="stats">${statText(g.id)}</div><div class="feature-actions">${actions}</div>
    </div>`;
  } else {
    el.innerHTML = `${tagline}${runtime ? `<div class="feature-badges classic-badges">${runtime}</div>` : ""}<h1>${esc(g.name)}</h1>
      <p class="desc">${esc(g.description || "")}</p>${tags}
      ${galleryStrip(g)}<div class="stats">${statText(g.id)}</div>${actions}`;
  }
  $("#play").onclick = () => launch(g);
  $("#fav").onclick = () => toggleFav(g);
  $("#edit").onclick = () => editor(g);
  $("#del").onclick = () => removeGame(g);
  $("#folders").onclick = () => openFolders(g);
  applyAccent(g);
  if (g.cover) { art.classList.remove("fallback"); art.style.background = `center/cover url("${url(g.cover)}")`; }
  else { art.classList.add("fallback"); art.style.background = `radial-gradient(circle at 78% 25%, hsl(${hue(g.id)} 70% 28%), transparent 60%), radial-gradient(circle at 20% 90%, hsl(${(hue(g.id) + 80) % 360} 60% 18%), transparent 60%)`; }
  art.hidden = false;
  const videoSource = g.video ? new URL(url(g.video), location.href).href : null;
  const showArtwork = () => {
    if (bg.src !== videoSource) return;
    art.hidden = false;
    bg.classList.remove("on");
  };
  bg.onplaying = () => {
    if (bg.src !== videoSource) return;
    art.hidden = true;
    bg.classList.add("on");
  };
  bg.onerror = () => {
    if (!videoSource || bg.src !== videoSource) return;
    showArtwork();
    console.warn("Game preview video could not load; showing artwork instead.", g.video);
  };
  if (videoSource) {
    if (bg.src !== videoSource) {
      bg.classList.remove("on");
      bg.src = videoSource;
    }
    if (!bg.paused && bg.readyState >= 2) bg.onplaying();
    bg.play().catch(error => {
      showArtwork();
      console.warn("Game preview video could not play; showing artwork instead.", error);
    });
  } else {
    bg.pause();
    bg.classList.remove("on");
    bg.removeAttribute("src");
  }
}
