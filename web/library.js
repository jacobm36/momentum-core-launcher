// Library state, sorting and rendering of the list and detail panel.

const ago = t => {
  const s = Date.now() / 1000 - t;
  if (s < 90) return "just now";
  for (const [n, u] of [[86400, "day"], [3600, "hour"], [60, "minute"]]) if (s >= n) { const k = Math.floor(s / n); return `${k} ${u}${k > 1 ? "s" : ""} ago`; }
};
const dur = s => s < 60 ? "under a minute" : s < 3600 ? `${Math.round(s / 60)} min` : `${Math.floor(s / 3600)}h ${Math.round(s % 3600 / 60)}m`;
const statText = id => { const s = stats[id]; return s?.launches ? `Last played ${ago(s.last)} · ${s.launches} launch${s.launches > 1 ? "es" : ""}${s.seconds ? " · " + dur(s.seconds) + " played" : ""}` : "Not played yet"; };
function detailsHistory(g) {
  const s = stats[g.id];
  if (!s?.launches) return '<section class="details-history" aria-label="Play history"><p class="details-unplayed">Not played yet</p></section>';
  return `<section class="details-history" aria-label="Play history"><dl class="details-facts">
    <div><dt>Time played</dt><dd>${s.seconds ? dur(s.seconds) : "0 min"}</dd></div>
    <div><dt>Last played</dt><dd>${s.last ? ago(s.last) : "Not recorded"}</dd></div>
    <div><dt>Launches</dt><dd>${s.launches}</dd></div>
    </dl><p class="details-note">Tracked by Momentum. Play time updates when the game closes.</p></section>`;
}
function detailsVersion(g) {
  const facts = [
    ["Engine / runtime", g.runtime],
    ["Package version", g.package_version],
  ].filter(([, value]) => value);
  if (!facts.length) return "";
  return `<section class="details-version" aria-labelledby="details-version-title"><h2 id="details-version-title">About this version</h2>
    <dl class="details-facts">${facts.map(([label, value]) => `<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl></section>`;
}
const recent = () => games.filter(g => stats[g.id]?.last).sort((a, b) => stats[b.id].last - stats[a.id].last).slice(0, 5);
const url = p => `/${p}?v=${ver}`;
const thumb = g => g.icon ? `<img src="${url(g.icon)}" alt="">` : `<div class="ph">${esc(g.name[0])}</div>`;
const previewImage = g => g.screenshots?.[0] || g.cover || g.icon;

const collectionMode = () => tiledLibrary() ? libraryCollection : "all";
const filtering = () => !!filter || tagSel.size > 0 || collectionMode() !== "all";
function collectionGames() {
  const mode = collectionMode();
  if (mode === "favorites") return favs();
  if (mode === "recent") return games.filter(g => stats[g.id]?.last);
  return mode.startsWith("category:") ? games.filter(g => `category:${g.category || "Other"}` === mode) : games;
}
function chooseCollection(mode) {
  if (!tiledLibrary() || mode === libraryCollection) return;
  libraryCollection = mode;
  tilePosition = null;
  renderList(); renderDetail(); sfx("cat");
}
function renderLibraryNav() {
  const nav = $("#library-nav");
  if (!nav || !tiledLibrary()) return;
  const categories = [...new Set(games.map(g => g.category || "Other"))];
  if (libraryCollection.startsWith("category:") && !categories.some(c => `category:${c}` === libraryCollection)) {
    libraryCollection = "all";
  }
  const entries = [
    ["all", "All games", games.length],
    ["favorites", "Favorites", favs().length],
    ["recent", "Recently played", games.filter(g => stats[g.id]?.last).length],
    ...categories.map(c => [`category:${c}`, c, games.filter(g => (g.category || "Other") === c).length]),
  ];
  const key = JSON.stringify([entries, libraryCollection]);
  if (nav.dataset.key === key) return;
  const focused = nav.contains(document.activeElement) ? document.activeElement.dataset.collection : null;
  const scroll = nav.scrollTop;
  nav.innerHTML = entries.map(([id, label, count], i) =>
    `${i === 3 ? '<h2 class="nav-heading">Categories</h2>' : ""}<button type="button" data-collection="${esc(id)}" ${libraryCollection === id ? 'aria-current="true"' : ""} aria-label="${esc(label)}: ${count} game${count === 1 ? "" : "s"}" title="${esc(label)} · ${count} game${count === 1 ? "" : "s"}"><span>${esc(label)}</span><span class="collection-count" aria-hidden="true">${count}</span></button>`).join("");
  nav.dataset.key = key;
  if (focused) ([...nav.querySelectorAll("button")].find(b => b.dataset.collection === focused) || nav.querySelector('[aria-current]'))?.focus({preventScroll:true});
  nav.scrollTop = scroll;
}
const tagKey = t => t.toLowerCase();
const tagLabel = k => games.flatMap(g => g.tags || []).find(t => tagKey(t) === k) || k;
function visible() {
  const q = filter.toLowerCase();
  return collectionGames().filter(g => (g.name.toLowerCase().includes(q) || (g.tags || []).some(t => t.toLowerCase().includes(q)))
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
  selectedItem()?.scrollIntoView({ block: "nearest" });
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
  if (collectionMode() === "recent" && m === "cat") {
    const items = [...visible()].sort((a, b) => SORT_BY.last(a, b) || a.name.localeCompare(b.name));
    return items.length ? [{cat:"Recently played", items, sorted:true}] : [];
  }
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
let tilePosition = null;
let renderedTileDetail = null;
let renderedTilesMarkup = null;
const tileDetailKey = () => JSON.stringify([games.length, games.find(g => g.id === sel), running.has(sel), statText(sel), [...tagSel]]);
const selectedItem = () => tiledLibrary()
  ? [...document.querySelectorAll(".tile.sel")].find(e => e.dataset.position === tilePosition) || document.querySelector(".tile.sel")
  : [...document.querySelectorAll(".item.sel")].pop();
const gameDetailsOpen = () => !!$("#game-details")?.open;
function stopDetailsPreview() {
  const video = $("#game-details video");
  if (video) { video.pause(); video.removeAttribute("src"); video.load(); }
}
function restoreGameDetails() {
  const d = $("#game-details");
  if (d?.open || !d?.contains($("#detail"))) return;
  stopDetailsPreview();
  $("#stage").append($("#detail"));
  renderDetail();
  (selectedItem() || $("#library-nav [aria-current]"))?.focus({preventScroll:true});
}
function closeGameDetails() {
  $("#game-details")?.close();
  restoreGameDetails();
}
function openGameDetails() {
  if (!tiledLibrary() || !games.some(g => g.id === sel) || topDlg()) return;
  if (typeof stopTilePreview === "function") stopTilePreview();
  let d = $("#game-details");
  if (!d) {
    d = document.createElement("dialog");
    d.id = "game-details";
    d.setAttribute("aria-labelledby", "game-details-title");
    d.innerHTML = '<div class="details-header"><span>Game details</span><button type="button" id="details-close">Close</button></div>';
    document.body.append(d);
    $("#details-close").onclick = closeGameDetails;
    d.addEventListener("close", restoreGameDetails);
    d.addEventListener("cancel", e => { e.preventDefault(); closeGameDetails(); });
    d.addEventListener("keydown", e => {
      if (e.repeat && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); return; }
      const tag = e.target.closest("[data-tag]");
      if (tag && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); tag.click(); }
    });
  }
  d.dataset.id = sel;
  d.append($("#detail"));
  d.showModal();
  renderDetail();
  ($("#play:not(:disabled)") || $("#details-close")).focus();
  sfx("open");
}
function tile(g, section) {
  const position = `${section}:${g.id}`, image = (libraryView() === "grid" && g.grid) || g.cover || g.icon;
  return `<button type="button" class="item tile ${g.id === sel ? "sel" : ""}" data-id="${g.id}" data-position="${esc(position)}" tabindex="${g.id === sel ? "0" : "-1"}" aria-pressed="${g.id === sel}" title="${esc(g.name)}">
    <span class="tile-art" style="--tile-hue:${hue(g.id)}"><span class="tile-initial">${esc(g.name[0] || "?")}</span>${image ? `<img src="${esc(url(image))}" ${image === g.icon ? 'class="tile-icon"' : ""} alt="" loading="lazy" data-icon="${esc(g.icon || "")}" data-cover="${esc(image === g.grid ? g.cover || "" : "")}">` : ""}</span>
    <span class="tile-title">${esc(g.name)}</span><span class="tile-badges">${g.favorite ? '<i class="star" title="Favorite">★</i>' : ""}${running.has(g.id) ? '<i class="dot" title="Running"></i><span>Running</span>' : ""}</span></button>`;
}
function renderTiles() {
  const sections = ordered().map(c => ({...c, key:`category:${c.cat}`}));
  const markup = sections.length ? sections.map(c => `<section class="tile-section"><h2 class="cat">${esc(c.cat)}</h2><div class="tile-group">${c.items.map(g => tile(g, c.key)).join("")}</div></section>`).join("") : '<p class="empty">No games found.</p>';
  if (renderedTilesMarkup === markup) return;
  if (typeof stopTilePreview === "function") stopTilePreview();
  $("#list").innerHTML = markup;
  renderedTilesMarkup = markup;
  const active = selectedItem();
  $("#list").querySelectorAll(".tile").forEach(item => { item.tabIndex = item === active ? 0 : -1; });
  $("#list").querySelectorAll(".tile img").forEach(img => img.addEventListener("error", () => {
    console.warn("Tile artwork could not load.", img.getAttribute("src"));
    const cover = img.dataset.cover;
    if (cover) { img.dataset.cover = ""; img.src = url(cover); return; }
    const icon = img.dataset.icon;
    if (icon && !img.classList.contains("tile-icon")) {
      img.classList.add("tile-icon"); img.src = url(icon);
    } else img.remove();
  }));
}
// Re-rendering replaces elements, so put gamepad/keyboard focus back on the equivalent one.
function keepFocus(fn) {
  const a = document.activeElement; let sel = null;
  if (a?.closest("#list, #detail")) sel = a.id ? "#" + a.id : a.dataset.position ? `[data-position="${CSS.escape(a.dataset.position)}"]` : a.dataset.tag ? `[data-tag="${CSS.escape(a.dataset.tag)}"]` : a.dataset.act ? `.cat[data-cat="${CSS.escape(a.closest(".cat").dataset.cat)}"] [data-act="${a.dataset.act}"]` : null;
  fn();
  if (sel) document.querySelector(sel)?.focus({preventScroll:true});
}
function renderList() {
  renderLibraryNav();
  const list = $("#list"), key = JSON.stringify([filter, [...tagSel], sortMode(), libraryView(), collectionMode()]);
  if (tiledLibrary() && !visible().some(g => g.id === sel)) {
    sel = flat()[0]?.id;
    if (sel) localStorage.setItem("mcl-last", sel);
  }
  const scroll = restoredScroll ?? (listFilterKey === key ? list.scrollTop : 0);
  keepFocus(() => { renderTagBar(); renderListInner(); });
  list.scrollTo({ top: scroll, behavior: "instant" });
  restoredScroll = null; listFilterKey = key;
  saveBrowsing();
  if (tiledLibrary() && renderedTileDetail !== tileDetailKey()) renderDetail();
  if (typeof syncTilePreview === "function") syncTilePreview();
}
function renderListInner() {
  const count = $("#library-count");
  if (count) count.textContent = `${filtering() ? visible().length + " of " : ""}${games.length} game${games.length === 1 ? "" : "s"}`;
  if (tiledLibrary()) { renderTiles(); return; }
  renderedTilesMarkup = null;
  const rc = filtering() ? [] : recent(), fv = filtering() ? [] : favs();
  $("#list").innerHTML = (fv.length ? `<div class="cat favs"><span>★ Favorites</span></div>` + fv.map(g => row(g, false)).join("") : "") + (rc.length ? `<div class="cat recent"><span>Recently played</span></div>` + rc.map(g => row(g, false)).join("") : "") + ordered().map(c =>
    `<div class="cat" ${c.sorted ? "" : `data-cat="${esc(c.cat)}"`}><span>${c.sorted ? "Sorted: " : ""}${esc(c.cat)}</span>${filtering() || c.sorted ? "" : '<span class="catbtns"><b tabindex="0" role="button" data-act="up" title="Move category up">▲</b><b tabindex="0" role="button" data-act="down" title="Move category down">▼</b><b tabindex="0" role="button" data-act="rename" title="Rename category">✎</b></span>'}</div>` + c.items.map(g => row(g, !c.sorted)).join("")).join("");
}

function renderDetail() {
  if (gameDetailsOpen() && $("#game-details").dataset.id !== sel) { closeGameDetails(); return; }
  const video = $("#game-details video"), previewStatus = $("#preview-status")?.textContent, feedback = $("#toast")?.textContent;
  keepFocus(renderDetailInner);
  if (gameDetailsOpen()) {
    const replacement = $("#game-details video");
    if (video && replacement && video.dataset.path === replacement.dataset.path) {
      replacement.replaceWith(video);
      wireDetailsPreview(video, false);
      $("#preview-status").textContent = previewStatus;
    }
    else {
      if (video) { video.pause(); video.removeAttribute("src"); video.load(); }
      if (replacement) wireDetailsPreview(replacement);
    }
    if (feedback) $("#toast").textContent = feedback;
    if (topDlg() === $("#game-details") && !$("#game-details").contains(document.activeElement)) {
      ($("#play:not(:disabled)") || $("#details-close")).focus({preventScroll:true});
    }
  }
  renderedTileDetail = tiledLibrary() ? tileDetailKey() : null;
}
function wireDetailsPreview(video, autoplay = true) {
  const artwork = $("#game-details .feature-art img, #game-details .feature-monogram");
  const toggle = $("#preview-toggle");
  const update = () => {
    if ($("#game-details video") !== video) return;
    const label = video.paused ? "Play preview" : "Pause preview";
    toggle.setAttribute("aria-label", label);
    toggle.title = label;
    toggle.classList.toggle("is-paused", video.paused);
    toggle.innerHTML = video.paused
      ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>'
      : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>';
    artwork.hidden = !video.hidden && video.dataset.started === "true";
  };
  const failure = message => {
    if ($("#game-details video") !== video) return;
    video.hidden = true;
    $("#preview-toggle").hidden = true;
    $("#preview-status").textContent = message;
    video.pause();
    artwork.hidden = false;
  };
  video.onplaying = () => {
    if ($("#game-details video") !== video) return;
    video.dataset.started = "true";
    video.hidden = false;
    $("#preview-status").textContent = "";
    update();
  };
  video.onpause = update;
  video.onerror = () => {
    console.warn("Game details preview could not load.", video.dataset.path);
    failure("Preview unavailable. Showing artwork instead.");
  };
  update();
  toggle.hidden = video.hidden;
  toggle.disabled = running.has(sel);
  toggle.onclick = () => {
    delete video.dataset.pageResume;
    if (video.paused) video.play().catch(error => {
      console.warn("Game details preview could not play.", error);
      failure("Preview could not play. Showing artwork instead.");
    });
    else video.pause();
  };
  if (running.has(sel)) video.pause();
  else if (autoplay && !document.hidden) video.play().catch(error => {
    if ($("#game-details video") !== video || video.hidden) return;
    console.warn("Game details preview autoplay was blocked.", error);
    $("#preview-status").textContent = "Preview paused. Choose Play preview to try again.";
  });
}
document.addEventListener("visibilitychange", () => {
  for (const video of [$("#bg"), $("#game-details video")].filter(Boolean)) {
    if (document.hidden) {
      if (!video.paused) { video.dataset.pageResume = "true"; video.pause(); }
    } else if (video.dataset.pageResume) {
      delete video.dataset.pageResume;
      if (!running.has(sel) && video.getAttribute("src") && !video.hidden) {
        video.play().catch(error => {
          console.warn("Game preview could not resume.", error);
          if ($("#preview-status") && video.closest("#game-details")) {
            $("#preview-status").textContent = "Preview paused. Choose Play preview to try again.";
          }
        });
      }
    }
  }
});
function renderDetailInner() {
  const g = games.find(x => x.id === sel), el = $("#detail"), bg = $("#bg"), art = $("#art");
  if (!g) {
    if (tiledLibrary()) { bg.pause(); bg.removeAttribute("src"); bg.classList.remove("on"); }
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
  const removed = g.install_status === "removed";
  const play = `<button id="play" ${on || removed ? "disabled" : ""}>${removed ? "UNINSTALLED" : on ? "RUNNING" : "▶ PLAY"}</button>`;
  const actions = `${play}<span id="toast"></span><span class="manage"><button id="fav" aria-pressed="${!!g.favorite}">${g.favorite ? "★ Favorited" : "☆ Favorite"}</button><button id="folders">Folders</button><button id="edit">Edit</button>${g.package_id ? '<button id="manage-package">Manage installation</button>' : ""}<button id="del">Remove from library</button></span>`;
  if (tiledLibrary() && !gameDetailsOpen()) {
    el.innerHTML = `<div class="tile-summary"><h1>${esc(g.name)}</h1>${tags}<div class="stats">${statText(g.id)}</div></div><div class="tile-actions">${actions}</div>`;
  } else if (featuredPanel() || gameDetailsOpen()) {
    const image = gameDetailsOpen() ? previewImage(g) : g.cover || g.icon;
    const media = image
      ? `<img class="${image === g.icon ? "icon" : "cover"}" src="${esc(url(image))}" alt="">`
      : `<div class="feature-monogram">${esc(g.name[0] || "?")}</div>`;
    const preview = gameDetailsOpen() && g.video ? `<video class="details-preview" muted loop playsinline preload="metadata" data-path="${esc(g.video)}" src="${esc(url(g.video))}" aria-label="${esc(g.name)} preview"></video><button type="button" id="preview-toggle" class="preview-control" aria-label="Play preview" title="Play preview"></button>` : "";
    const history = `${galleryStrip(g)}<div class="stats">${statText(g.id)}</div>`;
    const artwork = `<div class="feature-art">${media}${preview}</div>${preview ? '<p id="preview-status" role="status"></p>' : ""}`;
    el.innerHTML = `${gameDetailsOpen() ? `<div class="details-media">${artwork}${detailsVersion(g)}</div>` : artwork}<div class="feature-copy">
      <div class="feature-top">${tagline}<div class="feature-badges">${gameDetailsOpen() ? "" : runtime}${on ? '<span class="running-badge">● Running</span>' : ""}${g.favorite ? '<span class="favorite-badge">★ Favorite</span>' : ""}</div></div>
      <h1 ${gameDetailsOpen() ? 'id="game-details-title"' : ""}>${esc(g.name)}</h1>${gameDetailsOpen() && g.category ? `<p class="details-category">${esc(g.category)}</p>` : ""}
      ${gameDetailsOpen() ? `<div class="feature-actions">${actions}</div>${detailsHistory(g)}` : ""}<p class="desc">${esc(g.description || "")}</p>${tags}
      ${gameDetailsOpen() ? galleryStrip(g) : ""}
      ${!gameDetailsOpen() ? `${history}<div class="feature-actions">${actions}</div>` : ""}
    </div>`;
  } else {
    el.innerHTML = `${tagline}${runtime ? `<div class="feature-badges classic-badges">${runtime}</div>` : ""}<h1>${esc(g.name)}</h1>
      <p class="desc">${esc(g.description || "")}</p>${tags}
      ${galleryStrip(g)}<div class="stats">${statText(g.id)}</div>${actions}`;
  }
  $("#play").onclick = () => launch(g);
  $("#fav").onclick = () => toggleFav(g);
  $("#edit").onclick = () => { if (gameDetailsOpen()) closeGameDetails(); editor(g); };
  $("#del").onclick = () => removeGame(g);
  if ($("#manage-package")) $("#manage-package").onclick = () => {
    if (gameDetailsOpen()) closeGameDetails();
    openPackageManagement(g.package_id);
  };
  $("#folders").onclick = () => openFolders(g);
  applyAccent(g);
  if (tiledLibrary()) {
    bg.pause(); bg.removeAttribute("src"); bg.classList.remove("on");
    bg.onplaying = null; bg.onerror = null;
    return;
  }
  const image = previewImage(g);
  if (image) { art.classList.toggle("fallback", image === g.icon); art.style.background = `center/${image === g.icon ? "contain no-repeat" : "cover"} url("${url(image)}")`; }
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
      delete bg.dataset.pageResume;
      bg.classList.remove("on");
      bg.src = videoSource;
    }
    if (!bg.paused && bg.readyState >= 2) bg.onplaying();
    if (!document.hidden && !on) bg.play().catch(error => {
      showArtwork();
      console.warn("Game preview video could not play; showing artwork instead.", error);
    });
    else bg.pause();
  } else {
    bg.pause();
    bg.classList.remove("on");
    bg.removeAttribute("src");
  }
}
