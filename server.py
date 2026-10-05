#!/usr/bin/env python3
"""Momentum Core Launcher: tiny local server (stdlib only, localhost only)."""
import fcntl, ipaddress, json, os, re, secrets, shlex, socket, subprocess, sys, tempfile, threading, time
import urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import backup
from jobs import Jobs

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("MCL_PORT", 47615))
TOKEN = secrets.token_urlsafe(24)
LAST_SEEN = time.time()


class CatalogLock:
    """Thread lock plus an flock on games.json.lock, so import_games.py can't interleave with a save."""
    def __init__(self):
        self.t = threading.Lock()

    def __enter__(self):
        self.t.acquire()
        try:
            self.f = open(HERE / "games.json.lock", "w")
            fcntl.flock(self.f, fcntl.LOCK_EX)
        except BaseException:
            self.t.release()
            raise

    def __exit__(self, *exc):
        try:
            self.f.close()
        finally:
            self.t.release()


lock = CatalogLock()
running = {}  # id -> Popen
started = {}  # id -> start time
failed = {}   # id -> exit code, for launches that died within FAIL_WINDOW seconds
LOGS = HERE / "logs"
FAIL_WINDOW = 5
stats_lock = threading.Lock()
STATS = HERE / "playstats.json"  # id -> {last, launches, seconds, days: {YYYY-MM-DD: seconds}}; kept apart from games.json


def load_stats():
    try:
        return json.loads(STATS.read_text())
    except (OSError, ValueError):
        return {}


def update_stats(gid, fn):
    with stats_lock:
        st = load_stats()
        fn(st.setdefault(gid, {"last": 0, "launches": 0, "seconds": 0}))
        tmp = STATS.with_suffix(".tmp")
        tmp.write_text(json.dumps(st))
        os.replace(tmp, STATS)


def add_time(e, start, end):
    """Add a play session to the totals and to the per-day history (split at local midnight)."""
    end = max(end, start)
    e["seconds"] = e.get("seconds", 0) + int(end - start)
    days = e.setdefault("days", {})
    t = start
    while True:
        d = datetime.fromtimestamp(t)
        midnight = (d.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()
        key = d.strftime("%Y-%m-%d")
        days[key] = days.get(key, 0) + int(min(end, midnight) - t)
        if end <= midnight:
            break
        t = midnight


def alive(p):
    """True while the launched process or anything else in its session (wrapper scripts, hand-offs) runs."""
    if p.poll() is None:
        return True
    try:
        os.killpg(p.pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def track(gid, p, t0):
    rc = p.wait()
    if rc != 0 and time.time() - t0 < FAIL_WINDOW:
        failed[gid] = rc
    while alive(p):
        time.sleep(2)
    # A quick relaunch may already have replaced started[gid]; only close out our own session.
    if started.get(gid) == t0:
        del started[gid]
    update_stats(gid, lambda e: add_time(e, t0, time.time()))


def read_raw():
    try:
        return json.loads((HERE / "games.json").read_text())
    except FileNotFoundError:
        return []


def load_games():
    games = read_raw()
    # Drop-in media: media/<id>/cover.(jpg|png|webp) and media/<id>/video.(mp4|webm)
    for g in games:
        for key, stem, exts in (("cover", "cover", ("jpg", "jpeg", "png", "webp")),
                                ("video", "video", ("mp4", "webm"))):
            if not g.get(key):
                for e in exts:
                    f = HERE / "media" / g["id"] / f"{stem}.{e}"
                    if f.is_file():
                        g[key] = f"media/{g['id']}/{f.name}"
                        break
    return games


FIELDS = ("name", "exec", "cwd", "tagline", "description", "tags", "category", "accent")
KINDS = {"cover": ("jpg", "jpeg", "png", "webp"), "icon": ("jpg", "jpeg", "png", "webp", "svg"),
         "video": ("mp4", "webm")}
MAX_UPLOAD = 1 << 30
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def write_games(games):
    fd, name = tempfile.mkstemp(dir=HERE, prefix="games.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(games, indent=2, ensure_ascii=False) + "\n")
    os.replace(name, HERE / "games.json")


def write_stats_obj(obj):
    with stats_lock:
        tmp = STATS.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj))
        os.replace(tmp, STATS)


JOBS = Jobs(HERE / "jobs")
DEV = os.environ.get("MCL_DEV") == "1"  # enables the harmless demo job endpoint


def do_restore(path):
    """Validate an archive, snapshot the current library, then replace it. Returns (games, snapshot)."""
    backup.read_backup(path)  # reject bad archives before touching anything
    with lock:
        snap = backup.make_backup(HERE, "pre-restore")
        n = backup.restore(HERE, path, write_games, write_stats_obj)
    return n, snap


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64]


def clean(data):
    g = {}
    for k in FIELDS:
        v = data.get(k)
        if k == "tags":
            v = [str(t).strip() for t in (v or []) if str(t).strip()]
        else:
            v = str(v).strip() if v is not None else ""
        if k == "accent" and not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            v = ""
        if v or k in ("name", "exec", "tags"):
            g[k] = v
    return g


def remove_media(gid, kind):
    d = HERE / "media" / gid
    for e in KINDS[kind]:
        (d / f"{kind}.{e}").unlink(missing_ok=True)


CTYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/svg+xml": "svg",
          "video/mp4": "mp4", "video/webm": "webm"}
MAX_IMAGE = 50 << 20


class FetchError(Exception):
    pass


def check_public(url):
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise FetchError("only http/https links are supported")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))
    except OSError:
        raise FetchError("could not resolve host")
    if not all(ipaddress.ip_address(i[4][0]).is_global for i in infos):
        raise FetchError("links to local/private addresses are not allowed")


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_Redirect)


def http_get(url, limit):
    """Fetch a public http(s) URL; returns (bytes, content-type)."""
    check_public(url)
    req = urllib.request.Request(url, headers={"User-Agent": "MomentumCoreLauncher/1.0"})
    try:
        with _opener.open(req, timeout=20) as r:
            ctype = r.headers.get_content_type()
            if int(r.headers.get("Content-Length") or 0) > limit:
                raise FetchError("file is too large")
            body = r.read(limit + 1)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise FetchError(f"download failed: {getattr(e, 'reason', e)}")
    if len(body) > limit:
        raise FetchError("file is too large")
    return body, ctype


def download_media(gid, kind, url):
    limit = MAX_UPLOAD if kind == "video" else MAX_IMAGE
    body, ctype = http_get(url, limit)
    ext = CTYPES.get(ctype) or urllib.parse.urlparse(url).path.rsplit(".", 1)[-1].lower().replace("jpeg", "jpg")
    if ext == "jpeg":
        ext = "jpg"
    if ext not in KINDS[kind]:
        raise FetchError(f"that link is not a supported {kind} file ({ctype})")
    (HERE / "media" / gid).mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=HERE / "media" / gid, prefix=".dl.", delete=False) as f:
        f.write(body)
    return Path(f.name), ext


def commit_media(gid, kind, tmp, ext):
    """Move a finished temp file into place and record it. Caller holds `lock`."""
    games = read_raw()
    game = next((x for x in games if x["id"] == gid), None)
    if not game:
        tmp.unlink(missing_ok=True)
        return False
    remove_media(gid, kind)
    dest = tmp.parent / f"{kind}.{ext}"
    os.replace(tmp, dest)
    game[kind] = f"media/{gid}/{dest.name}"
    write_games(games)
    return True


def steam_search(q):
    body, _ = http_get("https://store.steampowered.com/api/storesearch/?" +
                       urllib.parse.urlencode({"term": q, "cc": "us", "l": "en"}), 2 << 20)
    return [{"id": i["id"], "name": i["name"], "image": i.get("tiny_image")}
            for i in json.loads(body).get("items", [])[:8] if i.get("type") == "app"]


def steam_details(appid):
    body, _ = http_get("https://store.steampowered.com/api/appdetails?" +
                       urllib.parse.urlencode({"appids": int(appid), "l": "en"}), 4 << 20)
    d = (json.loads(body).get(str(int(appid))) or {}).get("data")
    if not d:
        raise FetchError("Steam has no details for that game")
    shots = d.get("screenshots") or []
    tags = [g["description"] for g in d.get("genres", [])]
    return {"name": d.get("name", ""), "description": d.get("short_description", ""),
            "tags": tags, "tagline": (d.get("developers") or [""])[0],
            "covers": [x["path_full"] for x in shots[:6]] + ([d["background_raw"]] if d.get("background_raw") else []),
            "icon": d.get("capsule_image") or d.get("header_image")}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE), **kw)

    def log_message(self, *a):
        pass

    def translate_path(self, path):
        # Only files inside web/ and media/ may be served, whatever the URL says (.., %2e%2e, symlinks).
        full = Path(super().translate_path(path)).resolve()
        if any(full.is_relative_to(HERE / d) for d in ("web", "media")):
            return str(full)
        return str(HERE / "web" / ".forbidden")

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # Always revalidate the UI files so a stale cached page can't mismatch a newer script.
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _host_ok(self):
        # Blocks DNS-rebinding and cross-site requests.
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def do_GET(self):
        global LAST_SEEN
        if not self._host_ok():
            return self.send_error(403)
        path = self.path.split("?")[0]
        if path == "/api/games":
            LAST_SEEN = time.time()
            with lock:
                state = {k for k, p in running.items() if alive(p)}
            return self._json({"token": TOKEN, "running": sorted(state), "failed": dict(failed), "games": load_games(), "stats": load_stats(), "jobs": JOBS.list()})
        if path == "/api/backups":
            return self._json({"backups": backup.list_backups(HERE)})
        m = re.fullmatch(r"/api/jobs/(j[0-9a-f]{8})", path)
        if m:
            tail = int((urllib.parse.parse_qs(self.path.partition("?")[2]).get("tail") or ["8000"])[0] or 8000)
            j = JOBS.get(m[1], tail)
            return self._json(j) if j else self._json({"error": "unknown job"}, 404)
        if path == "/":
            self.path = "/web/index.html"
        elif not (path.startswith("/web/") or path.startswith("/media/")):
            return self.send_error(404)
        return super().do_GET()

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Token") != TOKEN:
            return self.send_error(403)
        if self.path.startswith("/api/launch/"):
            gid = self.path.rsplit("/", 1)[1]
            game = next((g for g in load_games() if g["id"] == gid), None)
            if not game:
                return self._json({"error": "unknown game"}, 404)
            with lock:
                p = running.get(gid)
                if p and alive(p):
                    return self._json({"status": "already running"})
                failed.pop(gid, None)
                try:
                    LOGS.mkdir(exist_ok=True)
                    log = open(LOGS / f"{gid}.log", "wb")
                except OSError:
                    log = subprocess.DEVNULL
                try:
                    running[gid] = subprocess.Popen(
                        shlex.split(game["exec"]), cwd=game.get("cwd") or None,
                        stdin=subprocess.DEVNULL, stdout=log,
                        stderr=subprocess.STDOUT, start_new_session=True)
                except Exception as e:
                    if log is not subprocess.DEVNULL:
                        log.close()
                        (LOGS / f"{gid}.log").write_text(f"Launch failed: {e}\n")
                    return self._json({"error": str(e)}, 500)
                finally:
                    if log is not subprocess.DEVNULL:
                        log.close()
                t0 = started[gid] = time.time()
                update_stats(gid, lambda e: (e.update(last=int(t0), launches=e["launches"] + 1), add_time(e, t0, t0)))
                threading.Thread(target=track, args=(gid, running[gid], t0), daemon=True).start()
            return self._json({"status": "launched"})
        if self.path == "/api/quit":
            self._json({"status": "bye"})
            threading.Timer(0.3, lambda: (JOBS.shutdown(), close_browser(), os._exit(0))).start()
            return
        if self.path.startswith(("/api/jobs/", "/api/backups/")):
            return self._ops()
        if self.path.startswith("/api/upload/"):
            return self._upload()
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{}") if n < 1 << 20 else {}
        except ValueError:
            return self._json({"error": "bad json"}, 400)
        if self.path in ("/api/steam/search", "/api/steam/details") or self.path.startswith("/api/fetch/"):
            return self._net(data)
        with lock:
            games = read_raw()
            if self.path == "/api/save":
                g = clean(data)
                if not g.get("name") or not g.get("exec"):
                    return self._json({"error": "name and command are required"}, 400)
                gid = data.get("id")
                existing = next((x for x in games if x["id"] == gid), None) if gid else None
                if existing:
                    existing.update(g)
                    for k in ("tagline", "description", "cwd", "category", "accent"):
                        if k not in g:
                            existing.pop(k, None)
                else:
                    base = slugify(g["name"]) or "game"
                    gid, i = base, 2
                    while any(x["id"] == gid for x in games):
                        gid, i = f"{base}-{i}", i + 1
                    games.append({"id": gid, **g, "cover": None, "video": None, "icon": None})
                write_games(games)
                return self._json({"id": gid})
            if self.path == "/api/reorder":
                # items: [{id, category}] in the desired order; unknown ids are ignored.
                byid = {x["id"]: x for x in games}
                out, seen = [], set()
                for it in data.get("items") or []:
                    x = byid.get(it.get("id"))
                    if x and x["id"] not in seen:
                        seen.add(x["id"])
                        cat = str(it.get("category") or "").strip()
                        if cat and cat != "Other":
                            x["category"] = cat
                        else:
                            x.pop("category", None)
                        out.append(x)
                write_games(out + [x for x in games if x["id"] not in seen])
                return self._json({"status": "ok"})
            if self.path == "/api/category/rename":
                old, new = str(data.get("from") or ""), str(data.get("to") or "").strip()
                if not new:
                    return self._json({"error": "name required"}, 400)
                for x in games:
                    if (x.get("category") or "Other") == old:
                        x["category"] = new
                write_games(games)
                return self._json({"status": "ok"})
            m = re.fullmatch(r"/api/favorite/([a-z0-9-]+)", self.path)
            if m:
                game = next((x for x in games if x["id"] == m[1]), None)
                if not game:
                    return self._json({"error": "unknown game"}, 404)
                if data.get("on"):
                    game["favorite"] = True
                else:
                    game.pop("favorite", None)
                write_games(games)
                return self._json({"status": "ok"})
            m = re.fullmatch(r"/api/delete/([a-z0-9-]+)", self.path)
            if m:
                write_games([x for x in games if x["id"] != m[1]])
                with stats_lock:
                    st = load_stats()
                    if st.pop(m[1], None) is not None:
                        STATS.write_text(json.dumps(st))
                return self._json({"status": "deleted"})
            m = re.fullmatch(r"/api/clear/([a-z0-9-]+)/(cover|icon|video)", self.path)
            if m:
                game = next((x for x in games if x["id"] == m[1]), None)
                if not game:
                    return self._json({"error": "unknown game"}, 404)
                remove_media(m[1], m[2])
                game[m[2]] = None
                write_games(games)
                return self._json({"status": "cleared"})
        self.send_error(404)

    def _ops(self):
        """Background jobs and backups."""
        path = self.path
        try:
            if path == "/api/backups/restore-upload":
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 < n <= backup.MAX_TOTAL:
                    return self._json({"error": "unsupported file size"}, 400)
                d = HERE / "backups"
                d.mkdir(exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=d, prefix=".up.", suffix=".tmp", delete=False) as f:
                    tmp, left = Path(f.name), n
                    while left:
                        chunk = self.rfile.read(min(1 << 20, left))
                        if not chunk:
                            break
                        f.write(chunk)
                        left -= len(chunk)
                try:
                    if left:
                        return self._json({"error": "incomplete upload"}, 400)
                    count, snap = do_restore(tmp)
                finally:
                    tmp.unlink(missing_ok=True)
                return self._json({"status": "restored", "games": count, "snapshot": snap})
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{}") if n < 1 << 20 else {}
            if path == "/api/jobs/demo" and DEV:
                step = lambda name, secs, code=0: {"name": name, "argv": [sys.executable, "-u", "-c",
                    f"import time,sys\nfor i in range({int(secs * 4)}):\n    print('{name}', i, flush=True); time.sleep(.25)\nsys.exit({code})"]}
                steps = [step("Download files", 3), step("Unpack", 2), step("Configure", 3, 1 if data.get("fail") else 0), step("Create shortcut", 1)]
                return self._json({"id": JOBS.submit(str(data.get("title") or "Demo install"), steps)})
            m = re.fullmatch(r"/api/jobs/(j[0-9a-f]{8})/(cancel|retry|dismiss)", path)
            if m:
                ok = getattr(JOBS, m[2])(m[1])
                return self._json({"status": m[2]}) if ok else self._json({"error": f"cannot {m[2]} this job"}, 409)
            if path == "/api/backups/create":
                name = backup.make_backup(HERE, "manual", bool(data.get("media")))
                return self._json({"name": name})
            m = re.fullmatch(r"/api/backups/(restore|delete|download)/([A-Za-z0-9._-]+)", path)
            if m:
                action, name = m.groups()
                if action == "delete":
                    backup.delete_backup(HERE, name)
                    return self._json({"status": "deleted"})
                f = backup.backup_path(HERE, name)
                if action == "restore":
                    count, snap = do_restore(f)
                    return self._json({"status": "restored", "games": count, "snapshot": snap})
                size = f.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(size))
                self.end_headers()
                with open(f, "rb") as src:
                    while chunk := src.read(1 << 20):
                        self.wfile.write(chunk)
                return
        except backup.BackupError as e:
            return self._json({"error": str(e)}, 400)
        except (ValueError, TypeError, OSError) as e:
            return self._json({"error": str(e) or "bad request"}, 400)
        self.send_error(404)

    def _net(self, data):
        try:
            if self.path == "/api/steam/search":
                return self._json({"results": steam_search(str(data.get("q") or "")[:100])})
            if self.path == "/api/steam/details":
                return self._json(steam_details(data.get("appid")))
            m = re.fullmatch(r"/api/fetch/([a-z0-9-]+)/(cover|icon|video)", self.path)
            if not m:
                return self._json({"error": "not found"}, 404)
            gid, kind = m.groups()
            if not any(x["id"] == gid for x in read_raw()):
                return self._json({"error": "unknown game"}, 404)
            tmp, ext = download_media(gid, kind, str(data.get("url") or "").strip())
            with lock:
                if not commit_media(gid, kind, tmp, ext):
                    return self._json({"error": "unknown game"}, 404)
            return self._json({"status": "ok"})
        except (FetchError, ValueError, TypeError) as e:
            return self._json({"error": str(e) or "bad request"}, 400)

    def _upload(self):
        m = re.fullmatch(r"/api/upload/([a-z0-9-]+)/(cover|icon|video)", self.path.split("?")[0])
        if not m:
            return self.send_error(404)
        gid, kind = m.groups()
        ext = self.path.partition("?ext=")[2].lower().lstrip(".")
        n = int(self.headers.get("Content-Length") or 0)
        if ext not in KINDS[kind] or not 0 < n <= MAX_UPLOAD:
            return self._json({"error": "unsupported file type or size"}, 400)
        if not any(x["id"] == gid for x in read_raw()):
            return self._json({"error": "unknown game"}, 404)
        d = HERE / "media" / gid
        d.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=d, prefix=".up.", delete=False) as f:
            tmp, left = Path(f.name), n
            while left:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left:
            tmp.unlink(missing_ok=True)
            return self._json({"error": "incomplete upload"}, 400)
        with lock:
            if not commit_media(gid, kind, tmp, ext):
                return self._json({"error": "unknown game"}, 404)
        return self._json({"status": "ok"})


def close_browser():
    # The kiosk window has no close button, so end the launcher's own Chrome (matched by its private profile).
    me = os.getpid()
    for d in Path("/proc").iterdir():
        if d.name.isdigit() and int(d.name) != me:
            try:
                if b"momentum-core-launcher/profile" in (d / "cmdline").read_bytes():
                    os.kill(int(d.name), 15)
            except OSError:
                pass


def watchdog():
    # Exit shortly after the window closes (no polling from the page).
    while True:
        time.sleep(5)
        if time.time() - LAST_SEEN > 60 and not JOBS.active_count():
            # Credit time for games still running when the launcher closes.
            for gid, p in list(running.items()):
                if alive(p) and gid in started:
                    update_stats(gid, lambda e: add_time(e, started.get(gid, time.time()), time.time()))
            os._exit(0)


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=lambda: backup.auto_backup_if_due(HERE), daemon=True).start()
    if "--no-exit" not in sys.argv:
        threading.Thread(target=watchdog, daemon=True).start()
    srv.serve_forever()
