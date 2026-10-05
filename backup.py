"""Library backups: zip snapshots of games.json, playstats.json and (optionally) media/.

Snapshots live in backups/ and are named <kind>-YYYYmmdd-HHMMSS.zip. Restoring never uses
extractall: every archive member is checked against a strict allow-list first.
"""
import json, os, re, tempfile, time, zipfile
from pathlib import Path

KINDS = ("manual", "auto", "pre-restore")
NAME_RE = re.compile(r"^(manual|auto|pre-restore)-\d{8}-\d{6}\.zip$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
MAX_TOTAL = 8 << 30
MAX_MEMBERS = 20000
MAX_JSON = 64 << 20
KEEP = {"auto": 10, "pre-restore": 10}
AUTO_EVERY = 7 * 86400


class BackupError(ValueError):
    pass


def _dir(here):
    d = Path(here) / "backups"
    d.mkdir(exist_ok=True)
    return d


def list_backups(here):
    out = []
    for f in _dir(here).iterdir():
        m = NAME_RE.match(f.name)
        if m:
            try:
                st = f.stat()
            except OSError:
                continue
            with_media = False
            try:
                with zipfile.ZipFile(f) as z:
                    with_media = json.loads(z.read("manifest.json")).get("media", False)
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                pass
            out.append({"name": f.name, "kind": m.group(1), "size": st.st_size, "time": st.st_mtime, "media": bool(with_media)})
    return sorted(out, key=lambda b: b["time"], reverse=True)


def make_backup(here, kind="manual", include_media=False):
    """Write a snapshot into backups/ and return its file name."""
    here = Path(here)
    name = f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    dest = _dir(here) / name
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".b.", suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps({"app": "momentum-core-launcher", "format": 1,
                                                    "created": time.time(), "media": bool(include_media)}))
            for fn in ("games.json", "playstats.json"):
                if (here / fn).is_file():
                    z.write(here / fn, fn)
            if include_media and (here / "media").is_dir():
                for f in sorted((here / "media").rglob("*")):
                    rel = f.relative_to(here / "media")
                    if f.is_file() and not f.is_symlink() and len(rel.parts) == 2 and not rel.name.startswith(".") \
                            and ID_RE.match(rel.parts[0]) and FILE_RE.match(rel.name):
                        z.write(f, f"media/{rel.parts[0]}/{rel.name}")
        os.replace(tmp, dest)
    finally:
        Path(tmp).unlink(missing_ok=True)
    prune(here, kind)
    return name


def prune(here, kind):
    keep = KEEP.get(kind)
    if keep:
        for b in [b for b in list_backups(here) if b["kind"] == kind][keep:]:
            (_dir(here) / b["name"]).unlink(missing_ok=True)


def auto_backup_if_due(here):
    """A small config-only snapshot at most once a week, so there is always a recent one."""
    here = Path(here)
    if not (here / "games.json").is_file():
        return None
    last = [b["time"] for b in list_backups(here) if b["kind"] == "auto"]
    if last and time.time() - last[0] < AUTO_EVERY:
        return None
    return make_backup(here, "auto")


def delete_backup(here, name):
    if not NAME_RE.match(name):
        raise BackupError("bad backup name")
    f = _dir(here) / name
    if not f.is_file():
        raise BackupError("no such backup")
    f.unlink()


def backup_path(here, name):
    if not NAME_RE.match(name):
        raise BackupError("bad backup name")
    f = _dir(here) / name
    if not f.is_file():
        raise BackupError("no such backup")
    return f


def _check_games(raw):
    try:
        games = json.loads(raw)
    except ValueError:
        raise BackupError("games.json in the backup is not valid JSON")
    if not isinstance(games, list):
        raise BackupError("games.json in the backup has the wrong shape")
    seen = set()
    for g in games:
        if not (isinstance(g, dict) and isinstance(g.get("id"), str) and ID_RE.match(g["id"])
                and isinstance(g.get("name"), str) and isinstance(g.get("exec"), str)) or g["id"] in seen:
            raise BackupError("games.json in the backup has an invalid or duplicate entry")
        seen.add(g["id"])
        for k in ("cover", "icon", "video"):
            v = g.get(k)
            if v is not None and not (isinstance(v, str) and v.startswith("media/") and ".." not in v):
                raise BackupError(f"invalid {k} path for {g['id']}")
    return games


def _read_json_member(z, info):
    if info.file_size > MAX_JSON:
        raise BackupError(f"{info.filename} is too large")
    data = z.open(info).read(MAX_JSON + 1)
    if len(data) > MAX_JSON:
        raise BackupError(f"{info.filename} is too large")
    return data


def read_backup(path):
    """Validate an archive; returns (games_json_bytes, stats_json_bytes_or_None, [(info, id, filename)])."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise BackupError("that file is not a valid backup")
    with z:
        infos = z.infolist()
        if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_TOTAL:
            raise BackupError("backup is too large")
        games = stats = None
        media = []
        for i in infos:
            n = i.filename
            if i.is_dir():
                continue
            if (i.external_attr >> 16) & 0o170000 == 0o120000:
                raise BackupError("backup contains a link, which is not allowed")
            if n == "manifest.json":
                try:
                    if json.loads(_read_json_member(z, i)).get("app") != "momentum-core-launcher":
                        raise ValueError
                except ValueError:
                    raise BackupError("that is not a Momentum Core Launcher backup")
            elif n == "games.json":
                games = _read_json_member(z, i)
            elif n == "playstats.json":
                stats = _read_json_member(z, i)
            else:
                parts = n.split("/")
                if len(parts) == 3 and parts[0] == "media" and ID_RE.match(parts[1]) and FILE_RE.match(parts[2]):
                    media.append((n, parts[1], parts[2]))
                else:
                    raise BackupError(f"unexpected file in backup: {n[:60]}")
        if games is None:
            raise BackupError("backup has no games.json")
        _check_games(games)
        if stats is not None:
            try:
                st = json.loads(stats)
                if not (isinstance(st, dict) and all(isinstance(v, dict) for v in st.values())):
                    raise ValueError
            except ValueError:
                raise BackupError("playstats.json in the backup is invalid")
    return games, stats, media


def restore(here, path, write_games, write_stats):
    """Apply a validated archive. The caller holds the catalog lock and has made a pre-restore snapshot."""
    here = Path(here)
    games, stats, media = read_backup(path)
    budget = MAX_TOTAL
    with zipfile.ZipFile(path) as z:
        for n, gid, fn in media:
            d = here / "media" / gid
            d.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".r.")
            try:
                with os.fdopen(fd, "wb") as out, z.open(n) as src:
                    while chunk := src.read(1 << 20):
                        budget -= len(chunk)
                        if budget < 0:
                            raise BackupError("backup is too large")
                        out.write(chunk)
                os.replace(tmp, d / fn)
            finally:
                Path(tmp).unlink(missing_ok=True)
    games = json.loads(games)
    write_games(games)
    if stats is not None:
        write_stats(json.loads(stats))
    return len(games)
