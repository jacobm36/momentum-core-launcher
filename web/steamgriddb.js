// Explicit artwork matches never alter game titles, commands or descriptions.
function wireSteamGridDB(form, setPending) {
  const status = $("#sgdb-status"), results = $("#sgdb-results");
  let generation = 0;
  const request = async (path, data) => {
    const response = await fetch("/api/steamgriddb/" + path, data === undefined ? {} : {
      method: "POST", headers: {"X-Token": token, "Content-Type": "application/json"},
      body: JSON.stringify(data),
    });
    const body = await response.json();
    if (!response.ok || body.error) throw new Error(body.error || `Request failed (${response.status})`);
    return body;
  };
  const run = async action => {
    const current = ++generation;
    status.textContent = "Contacting SteamGridDB…";
    try { await action(current); }
    catch (error) { if (current === generation) status.textContent = "Error: " + error.message; }
  };
  const load = () => run(async current => {
    const id = form.elements.steamgriddb_id.value.trim(), kind = $("#sgdb-kind").value;
    results.replaceChildren();
    const data = await request("artwork", {id, kind});
    if (current !== generation || !form.isConnected) return;
    status.textContent = data.images.length ? "Choose artwork, then Save the game to apply it."
      : "No artwork of this type. Try another type or match.";
    results.innerHTML = `<div class="thumbs">${data.images.map((image, i) =>
      `<button type="button" data-image="${i}" aria-label="Choose artwork ${i + 1}"><img src="${esc(image.thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer"></button>`).join("")}</div>`;
    results.onclick = event => {
      const button = event.target.closest("[data-image]");
      if (!button) return;
      const image = data.images[Number(button.dataset.image)];
      setPending(kind === "icons" ? "icon" : kind === "grids" ? "grid" : "cover", {url: image.url});
      results.querySelectorAll("button").forEach(item => item.classList.toggle("picked", item === button));
      status.textContent = "Artwork selected. Save the game to apply it.";
    };
  });
  $("#sgdb-search").onclick = () => run(async current => {
    results.replaceChildren();
    const q = form.elements.artwork_title.value.trim() || form.elements.name.value.trim();
    const data = await request("search", {q});
    if (current !== generation || !form.isConnected) return;
    status.textContent = data.results.length ? "Choose the matching game." : "No matches. Try an alternate title.";
    results.innerHTML = data.results.map(game =>
      `<button type="button" class="sgdb-match" data-id="${esc(game.id)}">${esc(game.name)} (#${esc(game.id)})</button>`).join("");
    results.onclick = event => {
      const button = event.target.closest("[data-id]");
      if (!button) return;
      form.elements.steamgriddb_id.value = button.dataset.id;
      load();
    };
  });
  $("#sgdb-load").onclick = load;
  $("#sgdb-kind").onchange = () => {
    if (form.elements.steamgriddb_id.value) load();
    else { ++generation; results.replaceChildren(); status.textContent = "Choose a game match first."; }
  };
  form.elements.steamgriddb_id.oninput = () => {
    ++generation; results.replaceChildren(); status.textContent = "Load this match to choose artwork.";
  };
  $("#sgdb-save-key").onclick = () => {
    const input = $("#sgdb-key"), key = input.value.trim();
    input.value = "";
    run(async current => {
      const data = await request("key", {key});
      if (current === generation) status.textContent = data.configured ? "API key saved locally." : "API key removed.";
    });
  };
  run(async current => {
    const data = await request("status");
    if (current === generation) status.textContent = data.configured
      ? "SteamGridDB is configured. Search or load your saved match." : "Open API key setup to enable SteamGridDB.";
  });
}
