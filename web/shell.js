// Footer hints and the splash screen.
function syncPageMotion() {
  document.body.classList.toggle("page-hidden", document.hidden);
}
document.addEventListener("visibilitychange", syncPageMotion);
syncPageMotion();

function hints() {
  $("#rum").hidden = !padOn;
  if (tiledLibrary()) {
    $("#hints").innerHTML = padOn
      ? "<span><kbd>D-pad</kbd>Move</span><span><kbd>A</kbd>Details</span><span><kbd>Start</kbd>Menu</span>"
      : "<span><kbd>Arrows</kbd>Move</span><span><kbd>Enter</kbd>Details</span><span><kbd>Tab</kbd>Menu</span>";
    return;
  }
  const activation = tiledLibrary() ? "Details" : "Play";
  $("#hints").innerHTML = padOn
    ? `<span><kbd>A</kbd>${activation}</span><span><kbd>LB</kbd><kbd>RB</kbd>Category</span><span><kbd>LT</kbd>Recent</span><span><kbd>RT</kbd>Favs</span><span><kbd>L3</kbd>Sort</span><span><kbd>R3</kbd>Stats</span><span><kbd>Back</kbd>★</span><span><kbd>X</kbd>Add</span><span><kbd>Y</kbd>Edit</span><span><kbd>Start</kbd>Menu</span>`
    : `<span>${tiledLibrary() ? "<kbd>← ↑ ↓ →</kbd>" : "<kbd>↑</kbd><kbd>↓</kbd>"}Select</span><span><kbd>Enter</kbd>${activation}</span><span><kbd>PgUp</kbd><kbd>PgDn</kbd>Category</span><span><kbd>F</kbd>★ Favorite</span><span><kbd>R</kbd>Recent</span><span><kbd>⇧F</kbd>Favorites</span><span><kbd>S</kbd>Sort</span><span><kbd>T</kbd>Stats</span>`;
}
addEventListener("gamepaddisconnected", () => { padOn = false; hints(); });

function splash() {
  const s = $("#splash");
  if (!animOn()) { s.remove(); return; }
  let done = false;
  const end = () => {
    if (done) return; done = true;
    s.classList.add("out"); setTimeout(() => s.remove(), 600);
    removeEventListener("keydown", end); removeEventListener("pointerdown", end);
  };
  addEventListener("keydown", end); addEventListener("pointerdown", end);
  setTimeout(end, 1900);
  sfx("intro");
  const poll = () => { if (done) return; if ([...(navigator.getGamepads?.() || [])].some(p => p?.buttons.some(b => b.pressed))) end(); else requestAnimationFrame(poll); };
  poll();
}
