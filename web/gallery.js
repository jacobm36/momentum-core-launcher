// Per-game screenshot strip and lightbox.
const galleryStrip = g => (g.screenshots || []).length
  ? `<div class="gallery" aria-label="Screenshots">${g.screenshots.map((p, i) => `<button type="button" data-shot="${i}" title="Screenshot ${i + 1}"><img src="${esc(url(p))}" alt="Screenshot ${i + 1}" loading="lazy"></button>`).join("")}</div>` : "";
function openGallery(g, start = 0) {
  const d = $("#gdlg"), list = g?.screenshots || [];
  if (!d || !list.length || (topDlg() && topDlg().id !== "game-details")) return;
  let i = Math.min(Math.max(start, 0), list.length - 1);
  d.innerHTML = `<div class="gimg"><img alt=""></div>
    <div class="padhint pad-only"><kbd>←</kbd><kbd>→</kbd>Browse <kbd>B</kbd>Close</div>
    <div class="gbar"><button type="button" id="gprev">← Prev</button><span class="gcount"></span><button type="button" id="gnext">Next →</button><button type="button" id="gclose" class="primary" autofocus>Close</button></div>`;
  const show = n => {
    i = (n + list.length) % list.length;
    d.querySelector("img").src = url(list[i]);
    d.querySelector(".gcount").textContent = `${esc(g.name)} · ${i + 1} / ${list.length}`;
    for (const k of [i + 1, i - 1]) new Image().src = url(list[(k + list.length) % list.length]);
  };
  d.nav = n => { if (list.length > 1) { show(i + n); sfx("tick"); } };
  d.onclick = e => {
    if (e.target.id === "gprev") d.nav(-1);
    else if (e.target.id === "gnext") d.nav(1);
    else if (e.target.id === "gclose" || e.target.closest(".gimg") === null && e.target === d) d.close();
  };
  d.onkeydown = e => {
    if (e.key === "Escape") { e.preventDefault(); d.close(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); d.nav(-1); }
    else if (e.key === "ArrowRight") { e.preventDefault(); d.nav(1); }
  };
  d.onclose = () => {
    d.nav = null;
    if (g.id === sel) $(`#detail [data-shot="${start}"]`)?.focus({preventScroll:true});
  };
  show(i); d.showModal(); sfx("open");
}
$("#detail").addEventListener("click", e => {
  const b = e.target.closest("[data-shot]"); if (b) openGallery(games.find(x => x.id === sel), +b.dataset.shot);
});
