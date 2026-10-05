// Footer hints and the splash screen.
function hints() {
  $("#rum").hidden = !padOn;
  $("#hints").innerHTML = padOn
    ? "<span><kbd>A</kbd>Play</span><span><kbd>LB</kbd><kbd>RB</kbd>Category</span><span><kbd>LT</kbd>Recent</span><span><kbd>RT</kbd>Favs</span><span><kbd>L3</kbd>Sort</span><span><kbd>R3</kbd>Stats</span><span><kbd>Back</kbd>★</span><span><kbd>X</kbd>Add</span><span><kbd>Y</kbd>Edit</span><span><kbd>Start</kbd>Menu</span>"
    : "<span><kbd>↑</kbd><kbd>↓</kbd>Select</span><span><kbd>Enter</kbd>Play</span><span><kbd>PgUp</kbd><kbd>PgDn</kbd>Category</span><span><kbd>F</kbd>★ Favorite</span><span><kbd>R</kbd>Recent</span><span><kbd>⇧F</kbd>Favorites</span><span><kbd>S</kbd>Sort</span><span><kbd>T</kbd>Stats</span>";
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
