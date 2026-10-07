"""Native folder selection without uploading files or running shell commands."""
import os
import shutil
import subprocess
import threading
from pathlib import Path

_lock = threading.Lock()


class PickerError(ValueError):
    pass


def choose_directory(initial=""):
    if not isinstance(initial, str) or "\0" in initial or (initial and not os.path.isabs(initial)):
        raise PickerError("The starting folder must be an absolute path")
    if not _lock.acquire(blocking=False):
        raise PickerError("A folder picker is already open")
    try:
        start = Path(initial) if initial else Path.home()
        while not start.is_dir() and start != start.parent:
            start = start.parent
        zenity, kdialog = shutil.which("zenity"), shutil.which("kdialog")
        if zenity:
            command = [zenity, "--file-selection", "--directory", "--title=Choose a game folder",
                       "--filename=" + str(start).rstrip("/") + "/"]
        elif kdialog:
            command = [kdialog, "--getexistingdirectory", str(start), "--title", "Choose a game folder"]
        else:
            raise PickerError("Folder selection needs Zenity or KDialog. Install one with your system tools, or type/paste the folder path.")
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired as e:
            raise PickerError("Folder selection timed out. Try again or type/paste the path.") from e
        except OSError as e:
            raise PickerError(f"Cannot open the folder picker: {e}") from e
        if result.returncode == 1 and not result.stderr.strip():
            return None
        if result.returncode != 0:
            raise PickerError(f"Cannot open the folder picker: {result.stderr.strip() or 'desktop dialog failed'}")
        path = result.stdout.removesuffix("\n")
        if not os.path.isabs(path) or not Path(path).is_dir():
            raise PickerError("The folder picker did not return an existing absolute folder")
        return path
    finally:
        _lock.release()
