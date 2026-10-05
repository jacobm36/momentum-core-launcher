#!/usr/bin/env python3
"""Seed games.json from ~/.local/share/applications *.desktop files (Category=Game).
Existing entries (matched by id) are preserved, so your edits are never overwritten.
With --update, existing entries also get their exec/cwd refreshed from the .desktop file."""
import fcntl, json, os, re, shutil, sys, tempfile, configparser
from pathlib import Path

HERE = Path(__file__).parent
APPS = Path.home() / ".local/share/applications"
SKIP = {"steam", "momentum-core-launcher"}
out = HERE / "games.json"
games = json.loads(out.read_text()) if out.exists() else []
known = {g["id"] for g in games}
UPDATE = "--update" in sys.argv[1:]
updates = {}  # id -> fields refreshed by --update
added = []

for f in sorted(APPS.glob("*.desktop")):
    if f.stem in SKIP or f.stem.startswith("chrome-"):
        continue
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    try:
        cp.read(f, encoding="utf-8")
        e = cp["Desktop Entry"]
    except Exception:
        continue
    if "Game" not in e.get("Categories", "") or e.get("NoDisplay") == "true":
        continue
    gid = re.sub(r"[^a-z0-9]+", "-", e["Name"].lower()).strip("-")
    exec_ = re.sub(r"\s%[a-zA-Z]", "", e["Exec"]).strip()
    if gid in known:
        if UPDATE:
            g = next(x for x in games if x["id"] == gid)
            # A missing Path in the .desktop file clears cwd (None means "remove the key").
            for key, val in (("exec", exec_), ("cwd", e.get("Path") or None)):
                if g.get(key) != val and (val or key == "cwd"):
                    updates.setdefault(gid, {})[key] = val
                    print("updated", gid, key)
        continue
    entry = {"id": gid, "name": e["Name"], "exec": exec_, "tagline": "", "description": "",
             "tags": [], "cover": None, "video": None}
    if e.get("Path"):
        entry["cwd"] = e["Path"]
    icon = Path(e.get("Icon", ""))
    if icon.is_file():
        d = HERE / "media" / gid
        d.mkdir(parents=True, exist_ok=True)
        dest = d / ("icon" + icon.suffix)
        shutil.copy(icon, dest)
        entry["icon"] = f"media/{gid}/{dest.name}"
    added.append(entry)
    print("added", gid)

# Re-read just before writing so edits saved by the launcher meanwhile are kept, then replace atomically.
# The flock is shared with the server, which holds it for every catalog save.
with open(HERE / "games.json.lock", "w") as lockf:
    fcntl.flock(lockf, fcntl.LOCK_EX)
    games = json.loads(out.read_text()) if out.exists() else []
    have = {g["id"] for g in games}
    for g in games:
        for key, val in updates.get(g["id"], {}).items():
            if val is None:
                g.pop(key, None)
            else:
                g[key] = val
    games += [g for g in added if g["id"] not in have]
    fd, name = tempfile.mkstemp(dir=HERE, prefix="games.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(games, indent=2, ensure_ascii=False) + "\n")
    os.replace(name, out)
