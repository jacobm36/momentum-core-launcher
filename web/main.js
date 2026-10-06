// Quit dialog, toolbar toggles and startup. Loaded last.
async function askQuit() {
  const n = running.size, ij = typeof jobs !== "undefined" ? jobs.filter(jobActive).length : 0;
  const msg = [n ? `${n} game${n > 1 ? "s are" : " is"} still running and will keep running after the launcher closes.` : "", ij ? `${ij} install${ij > 1 ? "s are" : " is"} in progress and will keep running; reopen the launcher to check on ${ij > 1 ? "them" : "it"}.` : ""].filter(Boolean).join(" ") || "The launcher will close.";
  if (!await ask("Exit launcher?", msg, "Exit")) return;
  try { await post("/api/quit"); } catch { /* server may already be gone */ }
  document.body.innerHTML = '<p style="margin:40vh auto;text-align:center;color:#8087a8">Launcher closed. You can close this window.</p>';
  window.close();
}
$("#qdlg").addEventListener("keydown", e => {
  const dir = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 }[e.key];
  if (dir) { e.preventDefault(); const b = [$("#qno"), $("#qyes")]; b[(b.indexOf(document.activeElement) + dir + 2) % 2].focus(); }
  else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); $("#qdlg").close("cancel"); }
});
$("#quit").onclick = e => { e.currentTarget.blur(); askQuit(); };
const toggleFull = () => document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen().catch(() => {});
$("#full").onclick = e => { toggleFull(); e.currentTarget.blur(); };
// In kiosk mode the browser itself is fullscreen and the page can't leave it, so the toggle is hidden.
if (!document.fullscreenElement && innerHeight >= screen.height - 2) $("#full").hidden = true;
document.addEventListener("fullscreenchange", () => { $("#full").classList.toggle("active", !!document.fullscreenElement); });
$("#snd").onclick = () => { localStorage.setItem("mcl-sound", soundOn() ? "off" : "on"); applySound(); sfx("tick"); };
$("#rum").onclick = () => { localStorage.setItem("mcl-rumble", rumbleOn() ? "off" : "on"); applyRumble(); rumble("ok"); };
$("#fx").onclick = () => { localStorage.setItem("mcl-anim", animOn() ? "off" : "on"); applyFx(); };
$("#dlg").addEventListener("keydown", e => { if ((e.key === "Enter" || e.key === " ") && e.target.matches(".sr, .thumbs img")) { e.preventDefault(); e.target.click(); } });
applyFx(); applySound(); applyRumble(); applyPanel(); applySort(); applyTheme(); splash();
hints();
refresh(true);
requestAnimationFrame(pollPad);
setInterval(refresh, 4000); // also keeps the server alive while the window is open
