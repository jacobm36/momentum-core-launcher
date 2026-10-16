"""Hand off Momentum's kiosk window and opt in individual games to X11 fullscreen."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


class HandoffError(RuntimeError):
    pass


class KioskHandoff:
    def __init__(self, port):
        self.url = f"http://127.0.0.1:{port}/"
        self.profile = "--user-data-dir=" + str(Path.home() / ".cache/momentum-core-launcher/profile")
        self.window = None
        self.warning = None

    def _kiosk(self, pid):
        try:
            process = Path("/proc") / str(pid)
            if process.stat().st_uid != os.getuid():
                return False
            args = (process / "cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            return False
        return all(value.encode() in args for value in ("--kiosk", self.profile, self.url))

    @staticmethod
    def _run(*args):
        try:
            result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as e:
            raise HandoffError(f"Cannot control the Momentum kiosk window: {e}") from e
        if result.returncode:
            raise HandoffError(f"Kiosk window command failed: {result.stderr.strip() or result.returncode}")
        return result.stdout

    def _windows(self):
        rows = []
        for line in self._run("wmctrl", "-lp").splitlines():
            fields = line.split(None, 4)
            if len(fields) >= 3:
                try:
                    int(fields[0], 16)
                    pid = int(fields[2])
                except ValueError as e:
                    raise HandoffError("Unexpected X11 window inventory.") from e
                rows.append((fields[0], pid))
        return rows

    def _fullscreen(self, window):
        output = self._run("xprop", "-id", window, "_NET_WM_STATE")
        return "_NET_WM_STATE_FULLSCREEN" in output.replace(",", " ").split()

    def _set_fullscreen(self, window, enabled):
        self._run("wmctrl", "-ir", window, "-b", ("add" if enabled else "remove") + ",fullscreen")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self._fullscreen(window) == enabled:
                return
            time.sleep(.05)
        raise HandoffError("The window manager did not acknowledge the Momentum fullscreen handoff.")

    def release(self):
        if self.window or not os.environ.get("DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
            return
        try:
            kiosk_pids = {int(p.name) for p in Path("/proc").iterdir()
                          if p.name.isdigit() and self._kiosk(int(p.name))}
        except OSError as e:
            raise HandoffError(f"Cannot identify Momentum's kiosk process: {e}") from e
        if not kiosk_pids:
            return
        if not shutil.which("wmctrl") or not shutil.which("xprop"):
            raise HandoffError("X11 kiosk game handoff requires wmctrl and xprop. "
                               "Install them with your system tools or use MCL_WINDOWED=1.")
        candidates = [(window, pid) for window, pid in self._windows()
                      if pid in kiosk_pids and self._fullscreen(window)]
        if not candidates:
            return
        if len(candidates) != 1:
            raise HandoffError("Multiple Momentum kiosk windows found; close extra windows before playing.")
        self.window = candidates[0]
        self._set_fullscreen(self.window[0], False)
        self.warning = None

    def restore(self):
        if not self.window:
            return
        window, pid = self.window
        try:
            if self._kiosk(pid) and (window, pid) in self._windows():
                self._set_fullscreen(window, True)
        except HandoffError as e:
            self.warning = str(e)
            return
        self.window = None
        self.warning = None


def run_fullscreen(command):
    if not command:
        raise HandoffError("A game command is required.")
    if not os.environ.get("DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
        raise HandoffError("This per-game fullscreen wrapper requires an X11 session.")
    if not shutil.which("wmctrl") or not shutil.which("xprop"):
        raise HandoffError("This per-game fullscreen wrapper requires wmctrl and xprop.")
    process = subprocess.Popen(command)
    handoff = KioskHandoff(0)
    try:
        deadline = time.monotonic() + 15
        while process.poll() is None and time.monotonic() < deadline:
            windows = [window for window, pid in handoff._windows() if pid == process.pid]
            if len(windows) == 1:
                handoff._set_fullscreen(windows[0], True)
                break
            time.sleep(.1)
        else:
            if process.poll() is None:
                raise HandoffError("No unique game window appeared within 15 seconds; fullscreen was not applied.")
    except HandoffError as error:
        print(f"Fullscreen handoff failed: {error}. The game is still under its own control.", file=sys.stderr)
    return process.wait()


if __name__ == "__main__":
    try:
        sys.exit(run_fullscreen(sys.argv[1:]))
    except (HandoffError, OSError) as error:
        sys.exit(str(error))
