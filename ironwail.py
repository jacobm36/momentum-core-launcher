#!/usr/bin/env python3
"""Approved pinned Ironwail/QBJ3 preparation. Never invokes the engine."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

from dependencies import DependencyError, emit
from jobs import _fsync_dir, _write_durable
import packages
import vkquake

VERSION = "0.8.2"
URL = "https://github.com/andrei-drexler/ironwail/releases/download/v0.8.2/ironwail-0.8.2-linux-x64.tar.gz"
ARCHIVE_SIZE = 592534
ARCHIVE_SHA = "fcb0219d13c50f64728892f0558b4761ba5578319a6cc01021fad981c6333aa5"
ENGINE_SHA = "484913a479bc1ddb64b405ff55e5c31caead0af1f158f4f911aa57d2368971cf"
PAK_SHA = "be6a546c1b267837d5b6558e9349b1df302a825587b994309b1c955a561292a1"
INDEX_SHA = "ee2180f5fd474694278c0abd7cb8a4fa3554ab5137df7528c7bcd4a2800c656e"
MOD_URL = "https://us.22061996.xyz/qbj3/qbj3_1.3.zip"
MOD_SHA = "bdfd7313ea4231695c56bceac8f098f7cfe89a86f7398b7a212eb2e193006904"
MOD_SIZE = 2689872444
EXPANDED_SIZE = 6168990590
PROC_ROOT = Path("/proc")


def safe(path):
    path = Path(path)
    if (not path.is_absolute() or ".." in path.parts
            or any(ord(c) < 32 or ord(c) == 127 for c in str(path))
            or any(p.is_symlink() for p in (path, *path.parents))):
        raise DependencyError(f"Unsafe preparation path: {path}")
    return path


def filehash(path, cancel=lambda: None):
    safe(path)
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            cancel()
            digest.update(chunk)
    return digest.hexdigest()


def target_root():
    return Path.home() / ".local/share/momentum-core/software/ironwail" / VERSION


def cache_root():
    return Path.home() / ".cache/momentum-core/qbj3" / MOD_SHA


def _regular(path, size, digest, executable=False):
    safe(path)
    s = path.stat(follow_symlinks=False)
    if (not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid()
            or s.st_size != size or s.st_mode & (stat.S_IWOTH | stat.S_ISUID | stat.S_ISGID)
            or (s.st_mode & stat.S_IWGRP and s.st_gid != os.getgid())
            or (executable and not s.st_mode & stat.S_IXUSR) or filehash(path) != digest):
        raise DependencyError(f"Unverified Ironwail resource; reconcile without replacing it: {path}")


def detect():
    candidates = (Path.home() / "Games/Quake/ironwail",
                  Path.home() / "Games/Ironwail/0.8.2/ironwail",
                  Path.home() / "Games/Ironwail/ironwail", target_root() / "ironwail")
    found = None
    for p in candidates:
        safe(p)
        if os.path.lexists(p):
            _regular(p, 1106808, ENGINE_SHA, True)
            _regular(p.parent / "ironwail.pak", 23842, PAK_SHA)
            if found is None:
                found = p
    p = found or candidates[-1]
    return {"provider": "native", "scope": "user", "installed": found is not None,
            "version": VERSION if found else None, "executable": str(p),
            "sha256": ENGINE_SHA if found else None, "companion_sha256": PAK_SHA if found else None,
            "game_local_state": bool(found), "launch_argv": [str(p)],
            "capabilities_checked": False}


def check_host(facts):
    p = safe(facts["executable"])
    if (platform.system() != "Linux" or platform.machine() != "x86_64"
            or not facts.get("installed") or facts.get("version") != VERSION
            or facts.get("sha256") != ENGINE_SHA or facts.get("companion_sha256") != PAK_SHA
            or facts.get("launch_argv") != [str(p)] or not facts.get("game_local_state")):
        raise DependencyError("Exact Linux x86_64 Ironwail 0.8.2 runtime required.")
    _regular(p, 1106808, ENGINE_SHA, True)
    _regular(p.parent / "ironwail.pak", 23842, PAK_SHA)
    with p.open("rb") as f:
        head = f.read(20)
    if head[:7] != b"\x7fELF\x02\x01\x01" or head[18:20] != b"\x3e\x00":
        raise DependencyError("Ironwail is not an x86_64 ELF.")
    if not shutil.which("readelf") or not shutil.which("ldconfig"):
        raise DependencyError("Install binutils/libc-bin using Ubuntu system tools for read-only host checks.")
    elf = subprocess.run(["readelf", "-d", str(p)], capture_output=True, text=True, timeout=15, check=True)
    needed = re.findall(r"Shared library: \[([^\]]+)\]", elf.stdout)
    libs = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True, timeout=15, check=True)
    available = {m.group(1) for m in re.finditer(r"^\s*(\S+)\s+\(.*x86-64.*\)\s+=>", libs.stdout, re.M)}
    missing = set(needed) - available
    if not needed or missing:
        raise DependencyError("Ironwail host libraries missing: " + ", ".join(sorted(missing))
                              + ". Install prerequisites with Ubuntu system tools; no elevation attempted.")
    return {"bytes_verified": True, "elf_checked": True, "host_prerequisites_checked": True,
            "libraries": needed, "game_local_state": True, "cli_checked": False,
            "graphics_checked": False, "gameplay_checked": False}


def running(facts):
    found = False
    for entry in PROC_ROOT.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            comm, argv = vkquake._process_metadata(entry)
            try:
                name = Path(os.readlink(entry / "exe").removesuffix(" (deleted)")).name.lower()
            except PermissionError as exc:
                if comm == b"ironwail" or argv and Path(os.fsdecode(argv)).name.lower() == "ironwail":
                    raise DependencyError(f"Cannot inspect Ironwail process {entry.name}; close it first.") from exc
                continue
            if name == "ironwail" or comm == b"ironwail":
                found = True
        except FileNotFoundError:
            continue
    return found


def index_for(root, digest):
    root = safe(root)
    summary = packages.check(root)
    if summary["id"] != "quake-brutalist-jam-3" or summary["digest"] != digest:
        raise DependencyError("Source preparation must bind the exact approved QBJ3 package.")
    path = root / "mod-content.json"
    if filehash(path) != INDEX_SHA:
        raise DependencyError("Unsupported QBJ3 source inventory; no arbitrary source downloads.")
    index = json.loads(path.read_text())
    if (index["archive_sha256"], index["archive_bytes"], index["expanded_bytes"]) != (
            MOD_SHA, MOD_SIZE, EXPANDED_SIZE):
        raise DependencyError("Pinned QBJ3 archive facts differ.")
    return index


def validate_base(source):
    import struct
    source = safe(source)
    for name in ("pak0.pak", "pak1.pak"):
        p = safe(source / "id1" / name)
        if not p.is_file():
            raise DependencyError("Supply your licensed Quake id1/pak0.pak and id1/pak1.pak before preparation.")
        with p.open("rb") as f:
            header = f.read(12)
            if len(header) != 12 or header[:4] != b"PACK":
                raise DependencyError(f"Invalid Quake base PAK: {p}")
            offset, count = struct.unpack("<ii", header[4:])
            if offset < 12 or count <= 0 or count % 64 or offset + count > p.stat().st_size:
                raise DependencyError(f"Invalid Quake PAK bounds: {p}")
            f.seek(offset)
            seen = set()
            for _ in range(count // 64):
                raw, pos, size = struct.unpack("<56sii", f.read(64))
                path = raw.split(b"\0", 1)[0].decode("ascii")
                _archive_name(path)
                if path in seen or pos < 12 or size < 0 or pos + size > p.stat().st_size:
                    raise DependencyError(f"Invalid Quake PAK entry: {p}")
                seen.add(path)


def mod_matches(folder, index, cancel=lambda: None, exact_state=False):
    folder = safe(folder)
    if folder.name != "qbj3" or not folder.is_dir():
        raise DependencyError(f"Select a complete extracted qbj3 folder: {folder}")
    for base, dirs, files in os.walk(folder, followlinks=False):
        cancel()
        for name in dirs + files:
            p = safe(Path(base) / name)
            if not p.is_dir() and not p.is_file():
                raise DependencyError(f"Unsupported mod resource: {p}")
    for row in index["files"]:
        p = safe(folder.parent / row["relative_path"])
        if not p.is_file():
            raise DependencyError(f"Incomplete QBJ3 source preserved; missing {p}")
        if exact_state or p.suffix.lower() not in (".cfg", ".sav"):
            if p.stat().st_size != row["size"] or filehash(p, cancel) != row["sha256"]:
                raise DependencyError(f"Modified or wrong-version QBJ3 source preserved: {p}")
    return folder


def source_for(inputs, root, digest, cancel=lambda: None):
    validate_base(inputs["source_dir"])
    index = index_for(root, digest)
    explicit = inputs.get("mod_dir")
    source = safe(explicit or str(Path(inputs["source_dir"]) / "qbj3"))
    if explicit or os.path.lexists(source):
        return mod_matches(source, index, cancel)
    cached = safe(cache_root() / "qbj3")
    if os.path.lexists(cached):
        return mod_matches(cached, index, cancel)
    if os.path.lexists(cache_root()):
        raise DependencyError("Incomplete QBJ3 cache preserved; reconcile before retry.")
    return None


def _archive_name(name):
    rel = name.rstrip("/")
    if (not rel or name.startswith("/") or "\\" in name or ":" in name
            or any(p in ("", ".", "..") for p in rel.split("/"))
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise DependencyError(f"Unsafe archive member: {name}")
    return rel


class Cancelled(DependencyError):
    pass


class Conflict(DependencyError):
    pass


def cancel(context):
    if Path(context["cancel_file"]).exists():
        raise Cancelled("Preparation cancelled at a safe boundary; published shared resources are retained.")


def _url(url):
    p = urllib.parse.urlsplit(url)
    if (p.scheme != "https" or p.hostname not in {
            "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
            "us.22061996.xyz"} or p.username or p.password or p.port not in (None, 443)):
        raise DependencyError("Untrusted preparation download URL/redirect.")


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, url):
        _url(url)
        return super().redirect_request(req, fp, code, msg, headers, url)


def download(context, url, destination, size, digest):
    safe(destination)
    _url(url)
    cancel(context)
    deadline = time.monotonic() + 3600
    h = hashlib.sha256()
    count = 0
    request = urllib.request.Request(url, headers={"User-Agent": "Momentum-Core-QBJ3/0.1.0"})
    with urllib.request.build_opener(Redirects()).open(request, timeout=30) as response, destination.open("xb") as out:
        _url(response.geturl())
        if response.headers.get("Content-Length") not in (None, str(size)):
            raise DependencyError("Pinned download size differs.")
        while chunk := response.read(1024 * 1024):
            cancel(context)
            if time.monotonic() > deadline or count + len(chunk) > size:
                raise DependencyError("Pinned download time/size limit exceeded.")
            out.write(chunk)
            h.update(chunk)
            count += len(chunk)
            emit("progress", "Preparing pinned source/software", step="resolve",
                 current=count, total=size, unit="bytes")
        out.flush()
        os.fsync(out.fileno())
    if count != size or h.hexdigest() != digest:
        raise DependencyError("Pinned download size/SHA-256 mismatch; nothing published.")


def extract_engine(archive, stage):
    expected = {"ironwail", "ironwail.pak", "LICENSE.txt", "Quakespasm-Music.txt",
                "Quakespasm.html", "Quakespasm.txt"}
    with tarfile.open(archive) as tar:
        seen = set()
        members = tar.getmembers()
        if len(members) != 7 or sum(m.size for m in members) > 2 * 1024 * 1024:
            raise DependencyError("Unexpected Ironwail archive inventory/size.")
        for m in members:
            rel = _archive_name(m.name)
            if rel in seen or not (m.isdir() or m.isfile()):
                raise DependencyError("Unsupported/duplicate Ironwail archive resource.")
            seen.add(rel)
            if rel == "ironwail-0.8.2-linux-x64" and m.isdir():
                continue
            if Path(rel).parent.as_posix() != "ironwail-0.8.2-linux-x64" or Path(rel).name not in expected:
                raise DependencyError("Unexpected Ironwail archive path.")
            p = stage / Path(rel).name
            with tar.extractfile(m) as src, p.open("xb") as out:
                shutil.copyfileobj(src, out)
                out.flush()
                os.fchmod(out.fileno(), 0o755 if p.name == "ironwail" else 0o644)
                os.fsync(out.fileno())
    _regular(stage / "ironwail", 1106808, ENGINE_SHA, True)
    _regular(stage / "ironwail.pak", 23842, PAK_SHA)


def extract_mod(context, archive, stage, index):
    expected = {r["relative_path"]: r for r in index["files"]}
    with zipfile.ZipFile(archive) as z:
        seen, regular, total = set(), set(), 0
        if len(z.infolist()) > 5000:
            raise DependencyError("Too many mod archive entries.")
        for row in z.infolist():
            rel = _archive_name(row.filename)
            mode = stat.S_IFMT(row.external_attr >> 16)
            if (rel in seen or not rel.startswith("qbj3/") and rel != "qbj3"
                    or row.flag_bits & 1 or mode not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise DependencyError("Unsafe/duplicate mod archive entry.")
            seen.add(rel)
            if not row.is_dir():
                if rel not in expected or row.file_size != expected[rel]["size"]:
                    raise DependencyError("Mod archive inventory differs from pinned source.")
                regular.add(rel)
                total += row.file_size
        if regular != set(expected) or total != EXPANDED_SIZE:
            raise DependencyError("Mod archive expanded inventory/size mismatch.")
        for row in z.infolist():
            cancel(context)
            p = stage / row.filename
            if row.is_dir():
                p.mkdir(parents=True, exist_ok=True)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                with z.open(row) as src, p.open("xb") as out:
                    while chunk := src.read(1024 * 1024):
                        cancel(context)
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                p.chmod(0o644)
    mod_matches(stage / "qbj3", index, lambda: cancel(context), exact_state=True)


def make_plan(context, facts):
    inputs = context["inputs"]
    source = source_for(inputs, context["package_root"], context["package_digest"],
                        lambda: cancel(context))
    game = safe(context["game_directory"])
    if source and (source == game or source.is_relative_to(game) or game.is_relative_to(source)):
        raise DependencyError("Source and destination overlap.")
    target = safe(target_root())
    if not facts["installed"] and os.path.lexists(target):
        raise DependencyError("Incomplete Ironwail destination preserved; reconcile first.")
    downloads = []
    if not facts["installed"]:
        downloads.append({"url": URL, "bytes": ARCHIVE_SIZE, "sha256": ARCHIVE_SHA,
                          "destination": str(target), "purpose": "shared-software"})
    if source is None:
        downloads.append({"url": MOD_URL, "bytes": MOD_SIZE, "sha256": MOD_SHA,
                          "expanded_bytes": EXPANDED_SIZE, "destination": str(cache_root()),
                          "purpose": "mod-source", "provenance": "Official-site-linked mirror; observed pinned hash"})
    return {"plan_version": 1, "operation": "prepare-dependency", "provider": "native", "scope": "user",
            "package_digest": context["package_digest"], "inputs": inputs,
            "before": facts, "mod_source": str(source) if source else None,
            "downloads": downloads, "actions": [], "preserve": ["original source, settings and saves"],
            "notes": ["No game writes or engine invocation. Mod download requires licensed base files.",
                      "Fresh source plus destination needs about 17 GiB free; shared caches/software are retained.",
                      "Review a separate exact game installation plan after preparation. No upgrades or elevation."]}


def _context(context):
    if context.get("operation") != "prepare-dependency" or context.get("phase") not in ("preflight", "apply"):
        raise DependencyError("Invalid preparation operation/phase.")
    result = safe(context["result_file"])
    job = result.parent
    s = job.stat()
    if (not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & stat.S_IWOTH
            or (s.st_mode & stat.S_IWGRP and s.st_gid != os.getgid())):
        raise DependencyError("Preparation requires an owner-controlled runner job directory.")
    protocol_paths = [result, job / "dependency-transactions.json"]
    if context.get("context_file"):
        protocol_paths.append(safe(context["context_file"]))
    for name in ("cancel_file", "approved_plan_file"):
        if context.get(name):
            path = safe(context[name])
            if path.parent != job:
                raise DependencyError("Preparation protocol paths must share the runner job directory.")
            protocol_paths.append(path)
    if len(protocol_paths) != len(set(protocol_paths)):
        raise DependencyError("Preparation protocol files must not alias one another.")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", context.get("job_id", "")):
        raise DependencyError("Invalid job identity.")
    safe(context["package_root"])
    safe(context["game_directory"])


def _publish(stage, destination):
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(stage), -100, os.fsencode(destination), 1):
        raise DependencyError("Unexpected publication target/error; no existing destination replaced.")
    _fsync_dir(destination.parent)


def run(context):
    facts, plan, completed = None, None, []
    outcome, code, message = "succeeded", 0, "Preparation checked; game installation needs separate approval."
    valid_context = False
    try:
        _context(context)
        valid_context = True
        cancel(context)
        facts = detect()
        if facts["installed"] and running(facts):
            raise DependencyError("Close Ironwail before preparing software or mod sources.")
        journal = Path(context["result_file"]).parent / "dependency-transactions.json"
        attempts = vkquake._previous(journal, context["job_id"])
        plan = make_plan(context, facts)
        if context["phase"] == "apply":
            raw = safe(context["approved_plan_file"]).read_bytes()
            if "sha256:" + hashlib.sha256(raw).hexdigest() != context["approved_plan_digest"]:
                raise DependencyError("Approved preparation bytes changed.")
            envelope = json.loads(raw)
            if (envelope.get("job_id") != context["job_id"] or envelope.get("phase") != "preflight"
                    or envelope.get("outcome") != "succeeded" or envelope.get("plan") != plan):
                raise Conflict("Preparation facts changed; review a new plan.")
            index = index_for(context["package_root"], context["package_digest"])
            for action in plan["downloads"]:
                cancel(context)
                destination = safe(action["destination"])
                parent = destination.parent
                vkquake._mkdir_durable(parent)
                need = (MOD_SIZE + 2 * EXPANDED_SIZE + 1024**3
                        if action["purpose"] == "mod-source" else 4 * 1024**2)
                if shutil.disk_usage(parent).free < need:
                    raise DependencyError("Not enough free space for approved source preparation and separate game copy.")
                record = {"job_id": context["job_id"], "attempts": attempts, "completed": completed,
                          "active_command": ["prepare", action["purpose"], str(destination)],
                          "detection_pending": False}
                _write_durable(journal, (json.dumps(record) + "\n").encode())
                with tempfile.TemporaryDirectory(prefix=".momentum-prepare-", dir=parent) as tmp:
                    scratch = Path(tmp)
                    archive, stage = scratch / "download", scratch / "stage"
                    download(context, action["url"], archive, action["bytes"], action["sha256"])
                    stage.mkdir()
                    if action["purpose"] == "shared-software":
                        extract_engine(archive, stage)
                        observed = dict(facts, installed=True, executable=str(stage / "ironwail"),
                                        version=VERSION, sha256=ENGINE_SHA, companion_sha256=PAK_SHA,
                                        game_local_state=True, launch_argv=[str(stage / "ironwail")])
                        check_host(observed)
                    else:
                        extract_mod(context, archive, stage, index)
                    cancel(context)
                    if detect() != facts:
                        raise DependencyError("Runtime changed during preparation; no publication.")
                    _fsync_dir(stage)
                    _publish(stage, destination)
                completed.append(action)
                record.update(active_command=None, detection_pending=True)
                _write_durable(journal, (json.dumps(record) + "\n").encode())
                facts = detect()
                if action["purpose"] == "mod-source":
                    mod_matches(destination / "qbj3", index, lambda: cancel(context))
                else:
                    check_host(facts)
                record.update(detection_pending=False, after=facts)
                _write_durable(journal, (json.dumps(record) + "\n").encode())
                emit("step_completed", "Verified shared software/source published; no game launched.", step="resolve")
    except Cancelled as exc:
        outcome, code, message = "cancelled", 130, str(exc)
    except Conflict as exc:
        outcome, code, message = "conflicted", 30, str(exc)
    except (DependencyError, OSError, ValueError, KeyError, TypeError,
            subprocess.SubprocessError, tarfile.TarError, zipfile.BadZipFile) as exc:
        outcome, code, message = "failed", 40, str(exc)
        print(message, file=sys.stderr)
    if not valid_context:
        return code
    result = {"result_version": 1, "job_id": context["job_id"], "phase": context["phase"],
              "operation": "prepare-dependency", "outcome": outcome, "message": message,
              "dependencies": {"ironwail": facts}, "completed_transactions": completed}
    if plan is not None:
        result["plan"] = plan
    _write_durable(Path(context["result_file"]), (json.dumps(result) + "\n").encode())
    emit("result", message, outcome=outcome)
    return code


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--context":
        sys.exit("Usage: ironwail.py --context /absolute/context.json")
    sys.exit(run(json.loads(Path(sys.argv[2]).read_text())))
