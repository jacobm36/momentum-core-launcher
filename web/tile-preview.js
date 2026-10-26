// Only the selected landscape tile owns a preview; artwork stays underneath it.
const tilePreviewDelay = 500;
const tileReducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
let tilePreviewIntent = true, tilePreviewKey = null, tilePreviewTimer = null, tilePreviewVideo = null;
function stopTilePreview() {
  clearTimeout(tilePreviewTimer);
  tilePreviewTimer = null;
  tilePreviewKey = null;
  if (tilePreviewVideo) {
    tilePreviewVideo.onplaying = null;
    tilePreviewVideo.onerror = null;
    tilePreviewVideo.pause();
    tilePreviewVideo.removeAttribute("src");
    tilePreviewVideo.load();
    tilePreviewVideo.remove();
    tilePreviewVideo = null;
  }
  document.querySelectorAll(".tile-preview-status").forEach(el => el.remove());
}
function tilePreviewTarget() {
  if (!tilePreviewIntent || libraryView() !== "tiles" || document.hidden || !document.hasFocus()
      || tileReducedMotion.matches || launchPending || running.size || document.querySelector("dialog[open]")) return null;
  const item = selectedItem(), game = games.find(g => g.id === sel);
  if (!item?.isConnected || !game?.video) return null;
  const r = item.getBoundingClientRect(), list = $("#list").getBoundingClientRect();
  if (r.bottom <= list.top || r.top >= list.bottom || r.right <= list.left || r.left >= list.right) return null;
  return {item, source:url(game.video), key:JSON.stringify([item.dataset.position, game.video, ver])};
}
function syncTilePreview() {
  const target = tilePreviewTarget();
  if (!target) { stopTilePreview(); return; }
  if (tilePreviewKey === target.key && (!tilePreviewVideo || target.item.contains(tilePreviewVideo))) return;
  stopTilePreview();
  tilePreviewKey = target.key;
  tilePreviewTimer = setTimeout(() => {
    tilePreviewTimer = null;
    const current = tilePreviewTarget();
    if (!current || current.key !== target.key) { stopTilePreview(); return; }
    const video = document.createElement("video");
    video.className = "tile-preview";
    video.muted = true; video.loop = true; video.playsInline = true;
    video.setAttribute("aria-hidden", "true");
    video.preload = "none";
    tilePreviewVideo = video;
    const fail = error => {
      if (tilePreviewVideo !== video) return;
      console.warn("Tile preview could not play; keeping artwork.", error);
      video.onplaying = null; video.onerror = null;
      video.pause(); video.removeAttribute("src"); video.load(); video.remove();
      tilePreviewVideo = null;
      const status = document.createElement("span");
      status.className = "tile-preview-status";
      status.setAttribute("role", "status");
      status.textContent = "Preview unavailable";
      current.item.querySelector(".tile-art").append(status);
    };
    video.onplaying = () => {
      if (tilePreviewVideo === video) video.classList.add("on");
    };
    video.onerror = () => fail(video.error?.message || "Video could not load.");
    current.item.querySelector(".tile-art").append(video);
    video.src = current.source;
    video.play().catch(fail);
  }, tilePreviewDelay);
}
function requestTilePreview() {
  tilePreviewIntent = true;
  syncTilePreview();
}
$("#list").addEventListener("pointerover", e => {
  if (e.pointerType !== "mouse" || libraryView() !== "tiles" || document.querySelector("dialog[open]")) return;
  const item = e.target.closest(".tile");
  if (!item || item.contains(e.relatedTarget)) return;
  if (item.dataset.id !== sel) select(item.dataset.id, item.dataset.position, false);
  requestTilePreview();
});
$("#list").addEventListener("pointerleave", e => {
  if (e.pointerType !== "mouse") return;
  tilePreviewIntent = false;
  stopTilePreview();
});
$("#list").addEventListener("pointerout", e => {
  const item = e.target.closest(".tile");
  if (e.pointerType !== "mouse" || !item || item.contains(e.relatedTarget)) return;
  tilePreviewIntent = false;
  stopTilePreview();
});
$("#list").addEventListener("focusin", e => {
  if (e.target.closest(".tile")) requestTilePreview();
});
$("#list").addEventListener("scroll", syncTilePreview);
addEventListener("blur", stopTilePreview);
addEventListener("focus", syncTilePreview);
addEventListener("pagehide", () => { tilePreviewIntent = false; stopTilePreview(); });
document.addEventListener("visibilitychange", syncTilePreview);
tileReducedMotion.addEventListener("change", syncTilePreview);
new MutationObserver(syncTilePreview).observe(document.body, {subtree:true, attributes:true, attributeFilter:["open"]});
