"""Read and review local game shortcuts; never execute discovery results."""
import configparser
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import unicodedata

MAX_SHORTCUTS = 2000
MAX_SHORTCUT_BYTES = 256 << 10
MAX_ICON_BYTES = 8 << 20
SKIP = {"steam", "momentum-core-launcher"}
EMULATOR_NAMES = {
    "mame", "uzdoom", "gzdoom", "lzdoom", "zdoom", "dsda-doom",
    "prboom", "prboom+", "chocolate doom", "crispy doom",
    "retroarch", "flycast", "dolphin", "dolphin emulator",
    "pcsx2", "rpcs3", "ppsspp", "duckstation", "dosbox", "dosbox staging",
    "dosbox-x", "scummvm", "mednafen", "snes9x", "fceux", "mgba",
    "vice", "yabause", "yabasanshiro", "melonds", "desmume",
}


def is_emulator(entry):
    # Match launcher names, not commands: a Doom mod can legitimately use UZDoom.
    name = entry.get("Name", "").strip().casefold()
    categories = entry.get("Categories", "").split(";")
    # Some individual arcade games also carry Game;Emulator, so that alone
    # cannot distinguish a game shortcut from an emulator frontend.
    return (name in EMULATOR_NAMES or "emulator" in name.split()
            or ("Emulator" in categories and "Game" not in categories))


class ImportError(ValueError):
    pass


def applications():
    value = os.environ.get("XDG_DATA_HOME", "")
    return (Path(value) if Path(value).is_absolute() else Path.home() / ".local/share") / "applications"


def application_directories():
    roots = [applications()]
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    roots.extend(Path(value) / "applications" for value in data_dirs.split(":")
                 if value and Path(value).is_absolute())
    roots.extend([
        Path("/usr/local/share/applications"), Path("/usr/share/applications"),
        Path.home() / ".local/share/flatpak/exports/share/applications",
        Path("/var/lib/flatpak/exports/share/applications"),
        Path("/var/lib/snapd/desktop/applications"),
    ])
    return list(dict.fromkeys(roots))


def command(value, name, source, icon):
    argv = []
    for token in shlex.split(value):
        if token in ("%f", "%F", "%u", "%U"):
            continue
        if token == "%i":
            if icon:
                argv.extend(["--icon", icon])
            continue
        def field(match):
            code = match.group(1)
            if code == "%":
                return "%"
            if code == "c":
                return name
            if code == "k":
                return str(source)
            raise ImportError(f"Unsupported launch field %{code}")
        argv.append(re.sub(r"%(.)", field, token))
    if not argv or not argv[0] or any(ord(c) < 32 for arg in argv for c in arg):
        raise ImportError("Missing or invalid launch command")
    return shlex.join(argv)


def _sort_name(name):
    return "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)).casefold()


def discover(games, directory=None, *, include_emulators=False):
    directories = [Path(directory)] if directory is not None else application_directories()
    files, desktop_ids, scanned = [], set(), 0
    try:
        for root in directories:
            if not root.exists():
                continue
            for source in sorted(root.rglob("*.desktop")):
                scanned += 1
                if scanned > MAX_SHORTCUTS:
                    raise ImportError(f"Too many shortcuts to review (maximum {MAX_SHORTCUTS})")
                desktop_id = source.relative_to(root).as_posix().replace("/", "-")
                if desktop_id in desktop_ids:
                    continue
                desktop_ids.add(desktop_id)
                files.append(source)
    except OSError as exc:
        raise ImportError(f"Cannot scan game shortcuts: {exc}") from exc
    known = {g["id"] for g in games}
    commands = {g.get("exec") for g in games}
    found, skipped, ignored, emulators_hidden = [], [], 0, 0
    for source in files:
        if source.stem in SKIP or source.stem.startswith("chrome-"):
            ignored += 1
            continue
        name = source.name
        try:
            with source.open("rb") as stream:
                raw = stream.read(MAX_SHORTCUT_BYTES + 1)
            if len(raw) > MAX_SHORTCUT_BYTES:
                raise ImportError("Shortcut is too large to read")
            parser = configparser.RawConfigParser(strict=False, interpolation=None)
            parser.optionxform = str
            parser.read_string(raw.decode("utf-8"))
            entry = parser["Desktop Entry"]
            emulator = is_emulator(entry)
            if "Game" not in entry.get("Categories", "").split(";") and not emulator:
                ignored += 1
                continue
            if emulator and not include_emulators:
                emulators_hidden += 1
                continue
            name = entry.get("Name", "").strip()
            if not name or any(ord(c) < 32 for c in name):
                raise ImportError("Missing or invalid game name")
            if entry.get("Hidden") == "true" or entry.get("NoDisplay") == "true":
                raise ImportError("Shortcut is hidden")
            if entry.get("Type", "Application") != "Application":
                raise ImportError("Shortcut is not an application")
            if entry.get("Terminal") == "true":
                raise ImportError("Requires a terminal; add its terminal launch command manually")
            executable = entry.get("TryExec")
            if executable and not shutil.which(executable):
                raise ImportError("Shortcut's required executable is not available")
            gid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64].rstrip("-")
            if not gid:
                raise ImportError("Name needs a manually assigned library entry")
            launch = command(entry.get("Exec", ""), name, source, entry.get("Icon", ""))
            cwd = entry.get("Path", "")
            if any(ord(c) < 32 for c in cwd):
                raise ImportError("Invalid working directory")
            reason = ("Already in your library; existing entry preserved" if gid in known or launch in commands
                      else "Duplicate of another discovered game" if any(
                          c["entry"]["id"] == gid or c["entry"]["exec"] == launch for c in found) else None)
            candidate = {"source": source.name if directory is not None else str(source),
                         "sha256": hashlib.sha256(raw).hexdigest(),
                         "entry": {"id": gid, "name": name, "exec": launch, "tagline": "",
                                   "description": "", "tags": [], "cover": None, "video": None},
                         "icon_source": entry.get("Icon", ""), "reason": reason}
            if cwd:
                candidate["entry"]["cwd"] = cwd
            found.append(candidate)
        except (OSError, UnicodeError, configparser.Error, KeyError, ValueError) as exc:
            skipped.append({"source": str(source), "name": name, "reason": str(exc)})
    # Sort after duplicate detection so directory precedence still decides which shortcut is available.
    found.sort(key=lambda c: (_sort_name(c["entry"]["name"]), c["source"]))
    skipped.sort(key=lambda c: (_sort_name(c["name"]), c["source"]))
    return {"directory": ", ".join(map(str, directories)), "directories": list(map(str, directories)),
            "candidates": found, "skipped": skipped, "ignored": ignored,
            "emulators_hidden": emulators_hidden}


def selected(scan, selection):
    if (not isinstance(selection, list) or not selection or len(selection) > MAX_SHORTCUTS
            or any(not isinstance(item, dict) or set(item) != {"source", "sha256"}
                   or not isinstance(item["source"], str) or not isinstance(item["sha256"], str)
                   for item in selection)):
        raise ImportError("Select one or more reviewed game shortcuts")
    if len({item["source"] for item in selection}) != len(selection):
        raise ImportError("Duplicate shortcut selection")
    by_source = {c["source"]: c for c in scan["candidates"]}
    result = []
    for item in selection:
        candidate = by_source.get(item["source"])
        if candidate is None or candidate["sha256"] != item["sha256"]:
            raise ImportError(f"Shortcut changed or disappeared: {item['source']}. Scan again before importing.")
        result.append(candidate)
    return result


def add(games, candidates, here):
    result = {"added": [], "skipped": [], "warnings": []}
    output = list(games)
    known, commands = {g["id"] for g in games}, {g.get("exec") for g in games}
    for candidate in candidates:
        entry = dict(candidate["entry"])
        if entry["id"] in known or entry["exec"] in commands:
            result["skipped"].append({"name": entry["name"], "reason": "Already in your library; existing entry preserved"})
            continue
        if candidate["reason"]:
            result["skipped"].append({"name": entry["name"], "reason": candidate["reason"]})
            continue
        icon = Path(candidate["icon_source"])
        if icon.is_absolute() and icon.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
            try:
                with icon.open("rb") as stream:
                    content = stream.read(MAX_ICON_BYTES + 1)
                if len(content) > MAX_ICON_BYTES:
                    raise ImportError("Icon exceeds 8 MiB")
                destination = Path(here) / "media" / entry["id"] / ("icon" + icon.suffix.lower())
                if any(p.is_symlink() for p in (destination, *destination.parents)):
                    raise ImportError("Icon destination contains a symlink")
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    raise ImportError("Existing icon preserved")
                with destination.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                entry["icon"] = destination.relative_to(here).as_posix()
            except (OSError, ImportError) as exc:
                result["warnings"].append({"name": entry["name"], "reason": f"Icon not copied: {exc}"})
        output.append(entry)
        known.add(entry["id"])
        commands.add(entry["exec"])
        result["added"].append({"id": entry["id"], "name": entry["name"]})
    return output, result
