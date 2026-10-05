#!/usr/bin/env python3
"""Move per-game Desktop shortcuts that the launcher now replaces into a backup folder.
App-menu launchers are left alone unless you also pass --menu.
Dry run by default; pass --apply to move. Undo with --restore (restores whatever was backed up)."""
import configparser, json, re, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).parent
BACKUP = Path.home() / ".local/share/momentum-core-launcher-shortcut-backup"
desktop = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip() or str(Path.home() / "Desktop")
ALL_DIRS = {"desktop": Path(desktop), "menu": Path.home() / ".local/share/applications"}
DIRS = ALL_DIRS if "--menu" in sys.argv else {"desktop": ALL_DIRS["desktop"]}
KEEP = ("steam", "momentum-core-launcher", "chrome-", "discord")

def norm(cmd): return re.sub(r"\s%[a-zA-Z]", "", cmd).strip()

if "--restore" in sys.argv:
    for kind, d in ALL_DIRS.items():
        for f in (BACKUP / kind).glob("*.desktop") if (BACKUP / kind).exists() else []:
            shutil.move(f, d / f.name); print("restored", f.name)
    sys.exit()

execs = {norm(g["exec"]) for g in json.loads((HERE / "games.json").read_text())}
apply = "--apply" in sys.argv
for kind, d in DIRS.items():
    for f in sorted(d.glob("*.desktop")):
        if f.stem.startswith(KEEP):
            continue
        cp = configparser.RawConfigParser(strict=False, interpolation=None); cp.optionxform = str
        try:
            cp.read(f, encoding="utf-8"); e = norm(cp["Desktop Entry"]["Exec"])
        except Exception:
            continue
        if e in execs:
            print(("moving " if apply else "would move ") + f"[{kind}] {f.name}")
            if apply:
                (BACKUP / kind).mkdir(parents=True, exist_ok=True)
                shutil.move(f, BACKUP / kind / f.name)
if apply and "menu" in DIRS:
    subprocess.run(["update-desktop-database", str(DIRS["menu"])], stderr=subprocess.DEVNULL)
else:
    print("\nDry run only. Re-run with --apply to move them." + ("" if "menu" in DIRS else " (App-menu launchers are untouched; add --menu to include them.)"))
