#!/usr/bin/env python3
"""Approval-bound pinned vkQuake AppImage preparation; never starts the engine.

Detection verifies bytes, not gameplay. Host checks inspect the AppImage header
and host loaders only; they do not test graphics devices, FUSE mounts or game data.
"""
import ctypes
import ctypes.util
import errno
import hashlib
import json
import os
import platform
import secrets
import stat
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from dependencies import DependencyError, emit
from jobs import _fsync_dir, _write_durable

VERSION = "1.36.0"
ASSET_URL = "https://github.com/Novum/vkQuake/releases/download/1.36.0/vkQuake-1.36.0-x86_64.AppImage"
ASSET_SIZE = 9001464
ASSET_SHA256 = "f1824b12744b6b343c6155cf5f775df225b9e6c9ee606c95c9363f63f124992a"
PROC_ROOT = Path("/proc")
DOWNLOAD_TIMEOUT = 60


class Cancelled(DependencyError):
    pass


def target_root():
    return Path.home() / ".local/share/momentum-core/software/vkquake" / VERSION


def target_path():
    return target_root() / "vkquake.AppImage"


def supported():
    return platform.system() == "Linux" and platform.machine() in ("x86_64", "AMD64")


def _safe_path(path):
    return path.is_absolute() and not any(p.is_symlink() for p in (path, *path.parents))


def _verified(path):
    """Use an un-followed regular file descriptor, not a pathname hash."""
    if not _safe_path(path):
        return False
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or before.st_size != ASSET_SIZE or not before.st_mode & stat.S_IXUSR
                    or before.st_mode & (stat.S_IWOTH | stat.S_ISUID | stat.S_ISGID)
                    or (before.st_mode & stat.S_IWGRP and before.st_gid != os.getgid())):
                return False
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            current = path.stat(follow_symlinks=False)
            stable = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_size",
                      "st_mtime_ns", "st_ctime_ns")
            return (all(getattr(before, key) == getattr(after, key) == getattr(current, key)
                        for key in stable) and (after.st_dev, after.st_ino) ==
                    (current.st_dev, current.st_ino) and digest.hexdigest() == ASSET_SHA256
                    and _safe_path(path))
    except OSError:
        return False


def detect():
    """Reuse the user's verified AppImage in place; a different build there is recorded and left untouched."""
    existing, own = Path.home() / "Applications/vkquake.AppImage", target_path()
    skipped = []
    executable = own
    if os.path.lexists(existing) or os.path.lexists(existing.parent):
        if not _safe_path(existing):
            skipped.append({"path": str(existing), "reason": "Symlinked path; not followed and left untouched."})
        elif os.path.lexists(existing):
            if _verified(existing):
                executable = existing
            else:
                skipped.append({"path": str(existing),
                                "reason": f"Not the tested vkQuake {VERSION} AppImage; left untouched."})
    if executable == own:
        # Momentum's own copy must be exactly what it installed; never silently replace it.
        if not _safe_path(own):
            raise DependencyError(f"Unsafe vkQuake candidate path: {own}; reconcile manually.")
        if os.path.lexists(own) and not _verified(own):
            raise DependencyError(f"Unverified vkQuake candidate: {own}; reconcile manually.")
    installed = os.path.lexists(executable) and supported()
    return {"provider": "appimage", "scope": "user", "installed": installed,
            "version": VERSION if installed else None, "executable": str(executable),
            "sha256": ASSET_SHA256 if installed else None, "launch_argv": [str(executable)],
            "capabilities_checked": False, "location": str(executable), "skipped": skipped}


def _require_runtime(facts):
    executable = Path(facts.get("executable", ""))
    if (not supported() or not facts.get("installed") or facts.get("version") != VERSION
            or facts.get("provider") != "appimage" or facts.get("scope") != "user"
            or facts.get("sha256") != ASSET_SHA256
            or executable not in (Path.home() / "Applications/vkquake.AppImage", target_path())
            or facts.get("launch_argv") != [str(executable)] or not _verified(executable)):
        raise DependencyError("The verified pinned vkQuake runtime is not installed or changed.")
    return executable


def _loader(name):
    library = ctypes.util.find_library(name)
    if not library:
        raise DependencyError(f"Missing host {name} loader; install it using system tools. No elevation is attempted.")
    try:
        ctypes.CDLL(library)
    except OSError as e:
        raise DependencyError(f"Cannot load host {name} loader: {e}") from e
    return library


def check_host(facts):
    """Non-graphical prerequisites only. No AppImage or engine subprocess."""
    executable = _require_runtime(facts)
    with executable.open("rb") as stream:
        header = stream.read(64)
    if (len(header) != 64 or header[:7] != b"\x7fELF\x02\x01\x01"
            or header[8:11] != b"AI\x02" or header[18:20] != b"\x3e\x00"):
        raise DependencyError("vkQuake requires a type-2 Linux x86_64 ELF AppImage.")
    fuse = _loader("fuse")
    if "libfuse.so.2" not in fuse:
        raise DependencyError("The AppImage requires the FUSE2 loader (libfuse.so.2), not FUSE3.")
    vulkan = _loader("vulkan")
    return {"version": VERSION, "bytes_verified": True, "elf_checked": True,
            "architecture": "x86_64", "fuse2_loader_available": True,
            "vulkan_loader_available": True, "host_prerequisites_checked": True,
            "cli_checked": False, "capabilities_checked": False, "gameplay_checked": False,
            "fuse_mount_checked": False, "graphics_device_checked": False,
            "loaders": {"fuse2": fuse, "vulkan": vulkan}}


def missing_host_prerequisites(facts):
    """Report missing loader libraries without launching the AppImage or guessing about GPU drivers."""
    executable = _require_runtime(facts)
    with executable.open("rb") as stream:
        header = stream.read(64)
    if (len(header) != 64 or header[:7] != b"\x7fELF\x02\x01\x01"
            or header[8:11] != b"AI\x02" or header[18:20] != b"\x3e\x00"):
        raise DependencyError("vkQuake requires a type-2 Linux x86_64 ELF AppImage.")
    missing = []
    for library in ("fuse", "vulkan"):
        found = ctypes.util.find_library(library)
        if not found:
            missing.append(library)
            continue
        try:
            ctypes.CDLL(found)
        except OSError:
            missing.append(library)
    return missing


def _process_metadata(entry):
    """Return (comm, argv[0]); arbitrary later arguments are deliberately ignored."""
    try:
        comm = (entry / "comm").read_bytes().strip()
    except OSError:
        comm = None
    try:
        argv0 = (entry / "cmdline").read_bytes().split(b"\0", 1)[0]
    except OSError:
        argv0 = None
    return comm, argv0


def _runtime_marker(value):
    """Match a runtime basename or AppImage mount path, not text mentioning vkQuake."""
    if not value:
        return False
    path = Path(os.fsdecode(value).removesuffix(" (deleted)"))
    name = path.name.lower()
    return (name in ("vkquake", "vkquake.appimage")
            or (name.startswith("vkquake-") and name.endswith(".appimage"))
            or any(part.lower().startswith(".mount_vkqu") for part in path.parts[:-1]))


def _comm_marker(comm):
    # comm is truncated to 15 bytes, so vkquake.AppImage appears as vkquake.AppImag.
    return comm.lower() in (b"vkquake", b"vkquake.appimag") or comm.lower().startswith(b"vkquake-")


def running(facts):
    """Include the mounted AppImage's underlying vkquake, not just its launcher."""
    executable = _require_runtime(facts)
    identity = executable.stat()
    launch = os.fsencode(executable)
    found = False
    try:
        for entry in PROC_ROOT.iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                if entry.stat().st_uid != os.getuid():
                    continue
                try:
                    path = os.readlink(entry / "exe")
                    observed = (entry / "exe").stat()
                except PermissionError:
                    comm, argv0 = _process_metadata(entry)
                    if (comm and argv0 and not _comm_marker(comm) and argv0 != launch
                            and not _runtime_marker(argv0)):
                        continue
                    raise DependencyError(f"Cannot inspect suspect vkQuake process {entry.name}.")
                exact = ((observed.st_dev, observed.st_ino) == (identity.st_dev, identity.st_ino)
                         or path.removesuffix(" (deleted)") == str(executable))
                if exact or _runtime_marker(os.fsencode(path)):
                    found = True
                    continue
                comm, argv0 = _process_metadata(entry)
                if (comm and _comm_marker(comm)) or argv0 == launch or _runtime_marker(argv0):
                    found = True
            except FileNotFoundError:
                if entry.exists():
                    status = (entry / "status").read_text()
                    if not any(line.startswith(("Kthread:\t1", "State:\tZ", "State:\tX"))
                               for line in status.splitlines()):
                        raise DependencyError(f"Cannot inspect process {entry.name}.")
        return found
    except OSError as e:
        raise DependencyError(f"Cannot inspect vkQuake processes: {e}") from e


def make_plan(facts):
    return {"plan_version": 1, "operation": "prepare-dependency", "dependency": "vkquake",
            "scope": "user", "dependencies": {"vkquake": facts}, "actions": [],
            "dependency_commands": [], "dependency_download": None if facts["installed"] else {
                "url": ASSET_URL, "version": VERSION, "size": ASSET_SIZE,
                "sha256": ASSET_SHA256, "target": str(target_path())},
            "manual_actions": [{"action_id": "vkquake-capability-check",
                                "message": "Non-graphical host prerequisites and game setup must be checked separately."}],
            "notes": ["No upgrades, elevation, engine execution or personal/game file changes.",
                      "Only exact pinned official AppImage bytes are reused.",
                      "Host prerequisites do not establish gameplay readiness."]}


def _cancel(context):
    if Path(context["cancel_file"]).exists():
        raise Cancelled("Cancellation acknowledged; any published runtime is retained.")


def _check_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in {
            "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise DependencyError("Unsafe vkQuake download URL or redirect.")


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(context):
    _cancel(context)
    _check_url(ASSET_URL)
    deadline = time.monotonic() + DOWNLOAD_TIMEOUT
    with urllib.request.build_opener(_Redirects()).open(ASSET_URL, timeout=10) as response:
        _check_url(response.geturl())
        if response.headers.get("Content-Length") not in (None, str(ASSET_SIZE)):
            raise DependencyError("Unexpected vkQuake download size.")
        data = bytearray()
        while True:
            _cancel(context)
            if time.monotonic() >= deadline:
                raise DependencyError("vkQuake download timed out.")
            chunk = response.read(min(65536, ASSET_SIZE + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > ASSET_SIZE:
                raise DependencyError("vkQuake download exceeds pinned size.")
    _validate_bytes(data)
    return bytes(data)


def _validate_bytes(data):
    if len(data) != ASSET_SIZE or hashlib.sha256(data).hexdigest() != ASSET_SHA256:
        raise DependencyError("vkQuake AppImage size or SHA256 mismatch.")


def _publish(stage, target):
    # Hard linking a regular staged file is atomic and cannot replace any target.
    try:
        os.link(stage, target, follow_symlinks=False)
    except OSError as e:
        if e.errno == errno.EEXIST:
            raise DependencyError("vkQuake target already exists; nothing was replaced.") from e
        raise
    _fsync_dir(target.parent)
    stage.unlink()
    _fsync_dir(target.parent)


def _previous(journal, job_id):
    if not journal.exists():
        return []
    record = json.loads(journal.read_text())
    if (not isinstance(record, dict) or record.get("job_id") != job_id
            or "active_command" not in record or not isinstance(record.get("completed"), list)
            or not isinstance(record.get("attempts", []), list)
            or record.get("active_command") or record.get("detection_pending")):
        raise DependencyError("An earlier dependency transaction is uncertain; reconcile before retry.")
    return record.get("attempts", []) + [{"completed": record["completed"]}]


def _mkdir_durable(path):
    missing = []
    parent = path
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True)
        _fsync_dir(directory)
        _fsync_dir(directory.parent)


def run(context):
    phase, facts, plan, completed = context["phase"], None, None, []
    code, outcome, message = 0, "succeeded", "Pinned vkQuake prepared; host and gameplay checks remain."
    stage = None
    try:
        if phase not in ("preflight", "apply"):
            raise DependencyError("Unsupported dependency phase.")
        _cancel(context)
        journal = Path(context["result_file"]).parent / "dependency-transactions.json"
        attempts = _previous(journal, context["job_id"])
        facts = detect()
        if not supported():
            code, outcome, message = 20, "needs_action", "The pinned vkQuake AppImage requires Linux x86_64."
        elif phase == "preflight":
            plan = make_plan(facts)
            message = "Review the exact pinned user-scope AppImage download or verified reuse."
        else:
            raw = Path(context["approved_plan_file"]).read_bytes()
            if "sha256:" + hashlib.sha256(raw).hexdigest() != context["approved_plan_digest"]:
                raise DependencyError("The saved dependency plan changed; obtain a new approval.")
            envelope = json.loads(raw)
            if not isinstance(envelope, dict):
                raise DependencyError("Invalid approved dependency envelope.")
            plan = envelope.get("plan")
            if (envelope.get("job_id") != context["job_id"] or envelope.get("phase") != "preflight"
                    or envelope.get("outcome") != "succeeded" or plan != make_plan(facts)):
                code, outcome, message = 30, "conflicted", "Dependency facts changed; review a new preflight plan."
            elif not facts["installed"]:
                target = target_path()
                emit("step_started", "Downloading the pinned official vkQuake AppImage.", step="resolve")
                data = download(context)
                _validate_bytes(data)
                _cancel(context)
                if detect() != facts:
                    raise DependencyError("Dependency facts changed before publication; review a new plan.")
                record = {"job_id": context["job_id"], "attempts": attempts, "completed": completed,
                          "active_command": ["publish-vkquake", str(target)], "before": facts}
                _write_durable(journal, (json.dumps(record, sort_keys=True) + "\n").encode())
                _mkdir_durable(target.parent)
                if not _safe_path(target):
                    raise DependencyError("Unsafe vkQuake publication path.")
                stage = target.parent / f".vkquake.stage-{secrets.token_hex(8)}"
                with stage.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fchmod(stream.fileno(), 0o755)
                    os.fsync(stream.fileno())
                _fsync_dir(target.parent)
                if not _verified(stage):
                    raise DependencyError("Staged vkQuake AppImage failed verification.")
                _cancel(context)
                if detect() != facts:
                    raise DependencyError("Dependency facts changed before publication.")
                _publish(stage, target)
                stage = None
                completed.append({"target": str(target), "sha256": ASSET_SHA256})
                record.update(active_command=None, detection_pending=True)
                _write_durable(journal, (json.dumps(record, sort_keys=True) + "\n").encode())
                facts = detect()
                if not facts["installed"] or facts["executable"] != str(target):
                    raise DependencyError("Published vkQuake AppImage could not be detected.")
                record.update(after=facts, detection_pending=False)
                _write_durable(journal, (json.dumps(record, sort_keys=True) + "\n").encode())
                emit("step_completed", "Verified AppImage published; no engine was launched.", step="resolve")
                _cancel(context)
    except Cancelled as e:
        code, outcome, message = 130, "cancelled", str(e)
        if stage is not None:
            stage.unlink()
            stage = None
            _fsync_dir(target.parent)
            record.update(active_command=None, detection_pending=False)
            _write_durable(journal, (json.dumps(record, sort_keys=True) + "\n").encode())
    except (DependencyError, OSError, ValueError, KeyError) as e:
        code, outcome, message = 40, "failed", str(e)
        print(message, file=sys.stderr)
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)
            _fsync_dir(stage.parent)
    result = {"result_version": 1, "job_id": context["job_id"], "phase": phase,
              "operation": "prepare-dependency", "outcome": outcome, "message": message,
              "dependencies": {"vkquake": facts}, "completed_transactions": completed}
    if plan is not None:
        result["plan"] = plan
    _write_durable(Path(context["result_file"]), (json.dumps(result, sort_keys=True) + "\n").encode())
    if outcome == "needs_action" or (phase == "apply" and outcome == "succeeded"):
        emit("needs_action", message, action_id="vkquake-capability-check", blocks_play=True)
    emit("result", message, outcome=outcome)
    return code


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--context":
        sys.exit("Usage: vkquake.py --context /absolute/context.json")
    sys.exit(run(json.loads(Path(sys.argv[2]).read_text())))
