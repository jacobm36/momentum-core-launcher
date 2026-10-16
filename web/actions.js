// Launching, favorites, removal, media upload and the game editor.
async function launch(g) {
  if (launchPending || running.has(g.id)) return;
  launchPending = true;
  try {
    $("#toast").textContent = "Launching…";
    const r = await fetch(`/api/launch/${g.id}`, { method: "POST", headers: { "X-Token": token } });
    const j = await r.json();
    if (j.error) { $("#toast").textContent = "Error: " + j.error; if (typeof notify === "function") notify(j.error, { kind: "error", title: "Launch failed" }); sfx("err"); return; }
    sfx("launch");
    const pb = $("#play")?.getBoundingClientRect();
    if (animOn()) {
      const f = $("#flash");
      if (pb) { f.style.setProperty("--fx", pb.left + pb.width / 2 + "px"); f.style.setProperty("--fy", pb.top + pb.height / 2 + "px"); }
      f.classList.remove("on"); void f.offsetWidth; f.classList.add("on");
      document.body.classList.add("blast"); setTimeout(() => document.body.classList.remove("blast"), 2800);
    }
    running.add(g.id); renderList(); renderDetail();
    if (animOn()) { $("#lname").textContent = g.name; const l = $("#launching"); l.classList.add("on"); setTimeout(() => l.classList.remove("on"), 2600); }
  } catch (error) {
    $("#toast").textContent = "Launch request failed: " + error.message;
    if (typeof notify === "function") notify(error.message, { kind: "error", title: "Launch request failed" });
    sfx("err");
  } finally {
    launchPending = false;
  }
}

const post = (path, body, raw) => fetch(path, { method: "POST", headers: { "X-Token": token }, body: raw || JSON.stringify(body || {}) });

async function toggleFav(g) {
  if (!g) return;
  const on = !g.favorite;
  await post(`/api/favorite/${g.id}`, { on });
  sfx(on ? "ok" : "tick");
  await refresh(); renderDetail();
}

async function removeGame(g) {
  if (!await ask("Remove game?", `Remove "${g.name}" from the launcher? Game files and media are not deleted.`, "Remove")) return;
  const l = flat(), i = l.findIndex(x => x.id === g.id), next = (l[i + 1] || l[i - 1])?.id;
  await post(`/api/delete/${g.id}`); sfx("del");
  await refresh(); select(next && next !== g.id ? next : flat()[0]?.id);
}

const ACCEPT = { cover: "image/*", icon: "image/*", video: "video/mp4,video/webm", shot: "image/*" };
const LABEL = { cover: "Background art", icon: "Icon", video: "Background video", shot: "Screenshot" };
const extOf = f => (f.name.split(".").pop() || "").toLowerCase();
const kindOfFile = f => f.type.startsWith("video/") ? "video" : f.type.startsWith("image/") ? "cover" : null;

async function sendMedia(id, kind, p) {
  const r = p.file
    ? await post(`/api/upload/${id}/${kind}?ext=${encodeURIComponent(extOf(p.file))}`, null, p.file)
    : await post(`/api/fetch/${id}/${kind}`, { url: p.url });
  return r.json();
}

function editor(g, manual = false) {
  if (!g && !manual) return openAddGame();
  const isNew = !g, d = $("#dlg"), f = $("#form"), pending = {}, blobs = [], shots = [];
  g = g || { tags: [] };
  const cats = [...new Set(games.map(x => x.category).filter(Boolean))];
  const allTags = [...new Map(games.flatMap(x => x.tags || []).map(t => [t.toLowerCase(), t])).values()].sort((a, b) => a.localeCompare(b)).slice(0, 40);
  const SWATCHES = ["#22b8ff", "#8a4dff", "#ff2d95", "#ff6a2b", "#ffc933", "#3ddc97", "#ff4d6d"];
  const chips = (kind, items) => items.length ? `<div class="chips" data-chips="${kind}">${items.map(c => `<button type="button" data-v="${esc(c)}">${esc(c)}</button>`).join("")}</div>` : "";
  const slot = k => `<div class="slot" data-kind="${k}"><div class="slot-h">${LABEL[k]}</div>
    <div class="preview" id="pv-${k}"></div>
    <div class="slot-in"><input type="file" name="${k}" accept="${ACCEPT[k]}"><input type="url" name="url-${k}" placeholder="…or paste a link (https://)"></div>
    <small class="drop-hint">Drop a file here${k === "cover" ? " or paste an image" : ""}.
    ${g[k] ? `<a href="#" data-clear="${k}">Remove current</a>` : ""}${k === "video" ? ' <a href="#" id="frame" hidden>Use current frame as cover</a>' : ""}</small></div>`;
  f.innerHTML = `<h2>${isNew ? "Add game" : "Edit " + esc(g.name)}</h2>
    <label>Name *<span class="row"><input name="name" required value="${esc(g.name || "")}"><button type="button" id="steam">Look up on Steam</button></span></label>
    <div id="steamres"></div>
    <label>Launch command or script path *<input name="exec" required value="${esc(g.exec || "")}" placeholder="/home/you/Games/game.sh"></label>
    <label>Working directory (optional)<input name="cwd" value="${esc(g.cwd || "")}"></label>
    <label>Category<input name="category" list="cats" value="${esc(g.category || "")}"><datalist id="cats">${cats.map(c => `<option value="${esc(c)}">`).join("")}</datalist></label>
    ${chips("category", cats)}
    <label>Accent color (optional, like #ff3030; blank = automatic from the art)<input name="accent" value="${esc(g.accent || "")}" placeholder="#ff3030" pattern="#[0-9a-fA-F]{6}"></label>
    <div class="chips swatches" data-chips="accent">${SWATCHES.map(c => `<button type="button" data-v="${c}" style="--sw:${c}" title="${c}" aria-label="Accent ${c}"></button>`).join("")}<button type="button" data-v="">Auto</button></div>
    <label>Tagline<input name="tagline" value="${esc(g.tagline || "")}"></label>
    <label>Runtime badge (optional, like UZDoom or OpenBOR 6391)<input name="runtime" maxlength="40" value="${esc(g.runtime || "")}"></label>
    <label>Description<textarea name="description" rows="4">${esc(g.description || "")}</textarea></label>
    <label>Tags (comma separated)<input name="tags" value="${esc((g.tags || []).join(", "))}"></label>
    ${chips("tags", allTags)}
    ${["cover", "icon", "video"].map(slot).join("")}
    <div class="slot" data-kind="shot"><div class="slot-h">Screenshots</div><div class="shotgrid" id="shotgrid"></div>
      <div class="slot-in"><input type="file" name="shot" accept="image/*" multiple><input type="url" name="url-shot" placeholder="…or paste an image link and press Enter"></div>
      <small class="drop-hint">Drop images here. Up to 24 per game.</small></div>
    <div class="err" id="ferr"></div>
    <div class="padhint" ${padOn ? "" : "hidden"}><kbd>D-pad</kbd>Move <kbd>A</kbd>Select / type <kbd>Start</kbd>Save <kbd>B</kbd>Cancel</div>
    <div class="btns"><button type="button" id="cancel">Cancel</button><button type="submit" class="primary">Save</button></div>`;

  const preview = k => {
    const el = $("#pv-" + k), p = pending[k], src = p ? (p.file ? (p.blobUrl ||= URL.createObjectURL(p.file)) : p.url) : g[k] ? url(g[k]) : "";
    if (p?.blobUrl) blobs.push(p.blobUrl);
    el.innerHTML = !src ? "" : k === "video" ? `<video src="${esc(src)}" controls muted preload="metadata"></video>` : `<img src="${esc(src)}" alt="">`;
    if (k === "video") $("#frame").hidden = !src;
  };
  const setPending = (k, p) => { pending[k] = p; if (!p.file) f.elements[k].value = ""; f.elements["url-" + k].value = p.url || ""; preview(k); };
  ["cover", "icon", "video"].forEach(k => {
    preview(k);
    f.elements[k].onchange = e => { const file = e.target.files[0]; if (file) setPending(k, { file }); };
    f.elements["url-" + k].onchange = e => { const v = e.target.value.trim(); if (v) setPending(k, { url: v }); else delete pending[k], preview(k); };
    const s = f.querySelector(`.slot[data-kind="${k}"]`);
    s.ondragover = e => { if ([...e.dataTransfer.types].includes("Files")) { e.preventDefault(); s.classList.add("over"); } };
    s.ondragleave = () => s.classList.remove("over");
    s.ondrop = e => { e.preventDefault(); e.stopPropagation(); s.classList.remove("over"); const file = e.dataTransfer.files[0]; if (file) setPending(k, { file }); };
  });
  f.onpaste = e => { const file = [...e.clipboardData.files].find(x => x.type.startsWith("image/")); if (file) { e.preventDefault(); setPending("cover", { file: new File([file], "pasted." + (file.type.split("/")[1] || "png"), { type: file.type }) }); } };
  f.querySelectorAll("[data-clear]").forEach(a => a.onclick = async e => {
    e.preventDefault(); const k = a.dataset.clear;
    await post(`/api/clear/${g.id}/${k}`, {}); g[k] = null; delete pending[k]; a.remove(); ver = Date.now(); preview(k); await refresh(); renderDetail();
  });
  $("#frame").onclick = e => {
    e.preventDefault();
    const v = $("#pv-video video"); if (!v) return;
    try {
      const c = document.createElement("canvas"); c.width = v.videoWidth; c.height = v.videoHeight;
      c.getContext("2d").drawImage(v, 0, 0);
      c.toBlob(b => b ? setPending("cover", { file: new File([b], "frame.jpg", { type: "image/jpeg" }) }) : ($("#ferr").textContent = "Couldn't grab a frame."), "image/jpeg", 0.92);
    } catch { $("#ferr").textContent = "Frames can only be grabbed from videos on this computer: upload the file, or save first."; }
  };

  const tagList = () => f.elements.tags.value.split(",").map(t => t.trim()).filter(Boolean);
  const syncChips = () => {
    const tl = tagList().map(t => t.toLowerCase());
    f.querySelectorAll("[data-chips]").forEach(box => box.querySelectorAll("button").forEach(b => {
      const k = box.dataset.chips, v = b.dataset.v;
      b.classList.toggle("on", k === "tags" ? tl.includes(v.toLowerCase()) : k === "category" ? f.elements.category.value === v : f.elements.accent.value.toLowerCase() === v.toLowerCase());
    }));
  };
  f.querySelectorAll("[data-chips]").forEach(box => box.onclick = e => {
    const b = e.target.closest("button"); if (!b) return;
    const v = b.dataset.v, k = box.dataset.chips;
    if (k === "tags") {
      const tl = tagList(), i = tl.findIndex(t => t.toLowerCase() === v.toLowerCase());
      if (i >= 0) tl.splice(i, 1); else tl.push(v);
      f.elements.tags.value = tl.join(", ");
    } else f.elements[k].value = v;
    syncChips(); sfx("tick");
  });
  ["category", "accent", "tags"].forEach(k => f.elements[k].addEventListener("input", syncChips));
  syncChips();

  const drawShots = () => {
    const have = (g.screenshots || []).map(p => ({ src: url(p), path: p })), add = shots.map((p, i) => ({ src: p.file ? (p.blobUrl ||= (blobs.push(URL.createObjectURL(p.file)), blobs.at(-1))) : p.url, i }));
    $("#shotgrid").innerHTML = [...have.map(s => `<div class="shot"><img src="${esc(s.src)}" alt=""><button type="button" data-del="${esc(s.path)}" title="Remove screenshot">✕</button></div>`),
      ...add.map(s => `<div class="shot new"><img src="${esc(s.src)}" alt=""><button type="button" data-drop="${s.i}" title="Don't add">✕</button></div>`)].join("") || '<small class="drop-hint">No screenshots yet.</small>';
  };
  const room = () => 24 - (g.screenshots?.length || 0) - shots.length;
  const addShots = list => { for (const file of list) if (file.type.startsWith("image/") && room() > 0) shots.push({ file }); drawShots(); };
  const addShotUrl = el => { const v = el.value.trim(); if (v && room() > 0 && !shots.some(s => s.url === v)) shots.push({ url: v }); el.value = ""; drawShots(); };
  $("#shotgrid").onclick = async e => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.drop) { shots.splice(+b.dataset.drop, 1); drawShots(); return; }
    if (!b.dataset.del || !g.id) return;
    await post(`/api/shot/delete/${g.id}`, { path: b.dataset.del });
    g.screenshots = (g.screenshots || []).filter(p => p !== b.dataset.del); drawShots(); await refresh(); renderDetail();
  };
  f.elements.shot.onchange = e => { addShots([...e.target.files]); e.target.value = ""; };
  f.elements["url-shot"].onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); addShotUrl(e.target); } };
  f.elements["url-shot"].onchange = e => addShotUrl(e.target);
  const shotSlot = f.querySelector('.slot[data-kind="shot"]');
  shotSlot.ondragover = e => { if ([...e.dataTransfer.types].includes("Files")) { e.preventDefault(); shotSlot.classList.add("over"); } };
  shotSlot.ondragleave = () => shotSlot.classList.remove("over");
  shotSlot.ondrop = e => { e.preventDefault(); e.stopPropagation(); shotSlot.classList.remove("over"); addShots([...e.dataTransfer.files]); };
  drawShots();

  $("#steam").onclick = async () => {
    const q = f.elements.name.value.trim(), box = $("#steamres");
    if (!q) { box.textContent = "Type the game's name first."; return; }
    box.textContent = "Searching Steam…";
    const j = await (await post("/api/steam/search", { q })).json();
    if (j.error || !j.results.length) { box.textContent = j.error || "No Steam matches."; return; }
    box.innerHTML = j.results.map(r => `<div class="sr" tabindex="0" data-id="${r.id}">${r.image ? `<img src="${esc(r.image)}" alt="">` : ""}<span>${esc(r.name)}</span></div>`).join("");
    box.onclick = async e => {
      const row = e.target.closest(".sr"); if (!row) return;
      box.textContent = "Fetching details…";
      const dd = await (await post("/api/steam/details", { appid: row.dataset.id })).json();
      if (dd.error) { box.textContent = dd.error; return; }
      f.elements.description.value = dd.description || f.elements.description.value;
      f.elements.tags.value = dd.tags.join(", ") || f.elements.tags.value;
      if (!f.elements.tagline.value) f.elements.tagline.value = dd.tagline || "";
      if (isNew && dd.name) f.elements.name.value = dd.name;
      box.innerHTML = `<div class="slot-h">Pick a background (click one)</div><div class="thumbs">${dd.covers.map((u, n) => `<img tabindex="0" src="${esc(u)}" data-u="${esc(u)}" class="${n ? "" : "picked"}" alt="">`).join("")}</div>${dd.covers.length > 1 ? '<button type="button" id="steamshots">Add these as screenshots</button>' : ""}`;
      if (dd.covers[0]) setPending("cover", { url: dd.covers[0] });
      if (dd.icon && !g.icon) setPending("icon", { url: dd.icon });
      box.onclick = ev => {
        if (ev.target.id === "steamshots") { for (const u of dd.covers.slice(0, 8)) if (!shots.some(s => s.url === u) && room() > 0) shots.push({ url: u }); drawShots(); ev.target.disabled = true; ev.target.textContent = "Added to screenshots"; return; }
        const im = ev.target.closest("img[data-u]"); if (!im) return; box.querySelectorAll("img").forEach(x => x.classList.toggle("picked", x === im)); setPending("cover", { url: im.dataset.u }); };
    };
  };

  const snap = () => JSON.stringify([...new FormData(f)].filter(([, v]) => typeof v === "string"));
  const before = snap();
  f.dirty = () => snap() !== before || Object.keys(pending).length > 0 || shots.length > 0;
  d.onclose = () => blobs.forEach(URL.revokeObjectURL);
  $("#cancel").onclick = () => d.close();
  f.onsubmit = async e => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(f).entries()), err = $("#ferr");
    const r = await post("/api/save", { id: g.id, ...v, tags: v.tags.split(",") }), j = await r.json();
    if (j.error) { err.textContent = j.error; sfx("err"); return; }
    g.id = j.id; // so a retry after a failed upload edits this game instead of adding another
    for (const k of Object.keys(pending)) {
      err.textContent = `Saving ${LABEL[k].toLowerCase()}…`;
      const u = await sendMedia(j.id, k, pending[k]);
      if (u.error) { err.textContent = `${LABEL[k]}: ${u.error}. Fix it or clear that field, then Save again.`; delete pending[k].file; return; }
      delete pending[k];
    }
    for (const p of [...shots]) {
      err.textContent = "Saving screenshots…";
      const u = await sendMedia(j.id, "shot", p);
      if (u.error) { err.textContent = `Screenshot: ${u.error}. Remove it or fix it, then Save again.`; sfx("err"); return; }
      shots.splice(shots.indexOf(p), 1);
    }
    d.close(); sfx("ok"); ver = Date.now(); await refresh(); select(j.id);
  };
  d.showModal(); sfx("open");
}
