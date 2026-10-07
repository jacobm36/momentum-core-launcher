#!/usr/bin/env python3
"""Pinned, approval-bound native Supermodel preparation; never executes the runtime.

Only immutable release files identify a reusable installation. Personal INI files,
NVRAM, saves and ROMs are neither inspected nor modified. Package launchers must
provide their own isolated working directory; software detection is not gameplay
or host-library compatibility validation.
"""
import ctypes
import errno
import hashlib
import io
import json
import os
import platform
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

from dependencies import DependencyError, emit
from jobs import _fsync_dir, _write_durable

VERSION = "v0.3a-20260928-git-8b4de23"
ARCHIVE_ROOT = "supermodel-0.3a-20260928-git-8b4de23"
ASSET_URL = f"https://github.com/trzy/Supermodel/releases/download/{VERSION}/{ARCHIVE_ROOT}-linux.tar.gz"
ASSET_SIZE = 1592846
ASSET_SHA256 = "7b94c2d9c54a829ebe9b6a7da9ed199dc78286c75f8c5113d63ed617d3e5173d"
# Exact public archive inventory: (size, mode, sha256); directories have no hash.
ASSET_INVENTORY = {
    "": (0, 0o755, None),
    "Saves": (0, 0o755, None),
    "Saves/DIR.txt": (21, 0o644, "4a209f0c7f79eef3c78055ca7fa8f7d83ce0f69e620218417d4e623b39f697fe"),
    "ROMs": (0, 0o755, None),
    "ROMs/DIR.txt": (55, 0o644, "9e1f4bc163d4e3194f55b8951b349a4d6c6e5ba8c7a32ada5b0e715ce084f0d2"),
    "supermodel": (3477752, 0o755, "4497b72c682d22f29b45d33607e07651240c2222a1e95e4b3f77846c9a7c1311"),
    "Assets": (0, 0o755, None),
    "Assets/p1crosshair.bmp": (295992, 0o644, "60920f5a98f37f1e0348df0bda0430e20327bea86bced7024f72f4ffddafc930"),
    "Assets/DIR.txt": (124, 0o644, "808aa0cf1d12c13e553dcfaad84ea2a5739037e4803a6add3a803ff88fc80014"),
    "Assets/p2crosshair.bmp": (295992, 0o644, "3dcc570b7728cfbff314a6305c9c0f933c5fa82153c6d50c3b1e780c3615f33e"),
    "Config": (0, 0o755, None),
    "Config/Music.xml": (9224, 0o644, "cf7555ca86e8640ee5bbb8e0c0897b073fc86647a93eda10b05065227610478c"),
    "Config/Games.xml": (151626, 0o644, "48c56b24ea720fb66188c0b2d94579a110be24971ac215ea808c563c665cf655"),
    "CHANGES.txt": (190776, 0o644, "a4ee5bc202ff5ddc7285302ef8cef29c69c5544f0911f922817ece624c0f3518"),
    "NVRAM": (0, 0o755, None),
    "NVRAM/DIR.txt": (21, 0o644, "f49bf258feb956f85fdfe1de3e30da6c031f15319e23e8a30087b9797868eced"),
    "README.txt": (85891, 0o644, "32684f5fbee9d7d9f72b05e6722670d99d5d6c8c94455569c66231a601da933a"),
    "LICENSE.txt": (36852, 0o644, "38029eb83f299d3baeed6440e3a992e16d235f818346e54eb8f7ff79d251775f"),
}
# The archive has no Supermodel.ini. Any supplied profile INI is mutable and unused.
RUNTIME_FILES = tuple(name for name, (_, _, digest) in ASSET_INVENTORY.items()
                      if digest and name.split("/")[0] not in ("NVRAM", "Saves", "ROMs"))
PROC_ROOT = Path("/proc")
DOWNLOAD_TIMEOUT = 60
HELP_VERSION = "Supermodel: A Sega Model 3 Arcade Emulator (Version 0.3a-20260928-git-8b4de23)"
REQUIRED_FLAGS = ("-game-xml-file=<file>", "-borderless", "-window-pos=<x>,<y>",
                  "-force-feedback", "-print-inputs")


class Cancelled(DependencyError):
    pass


def target_root():
    return Path.home() / ".local/share/momentum-core/software/supermodel" / VERSION


def supported():
    return platform.system() == "Linux" and platform.machine() in ("x86_64", "AMD64")


def _safe_path(path):
    return not any(p.is_symlink() for p in (path, *path.parents))


def _verified(root):
    if not _safe_path(root) or not root.is_dir():
        return False
    try:
        for name in RUNTIME_FILES:
            size, mode, digest = ASSET_INVENTORY[name]
            path = root / name
            if not _safe_path(path):
                return False
            metadata = path.stat()
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_size != size
                    or stat.S_IMODE(metadata.st_mode) != mode):
                return False
            with path.open("rb") as stream:
                hashed = hashlib.sha256()
                for chunk in iter(lambda: stream.read(65536), b""):
                    hashed.update(chunk)
                if hashed.hexdigest() != digest:
                    return False
    except OSError:
        return False
    return True


def detect():
    root = target_root()
    installed = False
    if supported():
        for candidate in (Path.home() / "Games/Supermodel", root):
            if _verified(candidate):
                root, installed = candidate, True
                break
    executable = str(root / "supermodel")
    return {"provider": "native", "scope": "user", "installed": installed,
            "version": VERSION if installed else None, "root": str(root),
            "executable": executable,
            "sha256": ASSET_INVENTORY["supermodel"][2] if installed else None,
            "games_xml_sha256": ASSET_INVENTORY["Config/Games.xml"][2] if installed else None,
            "capabilities_checked": False, "launch_argv": [executable]}


def _unrelated_protected(entry, executable):
    """Classify a same-user process whose exe is unreadable from comm and cmdline only.

    Metadata is never logged. Anything resembling Supermodel or unreadable metadata fails closed.
    """
    try:
        comm = (entry / "comm").read_bytes().strip().lower()
    except OSError:
        comm = None
    try:
        argv = [arg.lower() for arg in (entry / "cmdline").read_bytes().split(b"\0") if arg]
    except OSError:
        argv = None
    if comm is None and argv is None:
        return False
    markers = (b"supermodel", os.fsencode(executable).lower())
    if any(marker in value for value in [comm or b"", *(argv or [])] for marker in markers):
        return False
    return bool(comm) and bool(argv)


def running(facts):
    """Read-only Linux inode/path inspection; inaccessible processes fail closed."""
    if platform.system() != "Linux" or not facts.get("installed"):
        raise DependencyError("Cannot inspect native Supermodel processes without a verified Linux runtime.")
    try:
        executable = Path(facts["executable"])
        if executable != Path(facts["root"]) / "supermodel":
            raise DependencyError("Process inspection requires the verified runtime executable.")
        identity = executable.stat()
        if not _verified(Path(facts["root"])):
            raise DependencyError("Supermodel runtime changed before process inspection.")
        found = False
        for entry in PROC_ROOT.iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                # Other users' processes cannot use this user's isolated runtime state.
                if entry.stat().st_uid != os.getuid():
                    continue
                link = entry / "exe"
                try:
                    path = os.readlink(link)
                except PermissionError:
                    if _unrelated_protected(entry, executable):
                        continue
                    raise DependencyError(f"Cannot inspect process {entry.name}.")
                observed = link.stat()
                if ((observed.st_dev, observed.st_ino) == (identity.st_dev, identity.st_ino)
                        or path.removesuffix(" (deleted)") == str(executable)):
                    found = True
            except FileNotFoundError:
                # Kernel threads have no executable. A live userspace process
                # without an inspectable executable must not be mistaken for idle.
                if entry.exists():
                    status = (entry / "status").read_text()
                    if not any(line.startswith("Kthread:\t1") or line.startswith("State:\tZ")
                               or line.startswith("State:\tX") for line in status.splitlines()):
                        raise DependencyError(f"Cannot inspect process {entry.name}.")
        return found
    except OSError as e:
        raise DependencyError(f"Cannot inspect native Supermodel processes: {e}") from e


def check_host(facts):
    """Read-only CLI prerequisite probe; this does not validate a game, graphics or gameplay."""
    if not facts.get("installed") or facts.get("version") != VERSION:
        raise DependencyError("The verified pinned Supermodel runtime is not installed.")
    root = Path(facts["root"])
    executable = root / "supermodel"
    if facts.get("executable") != str(executable) or facts.get("launch_argv") != [str(executable)]:
        raise DependencyError("Supermodel facts do not identify the verified executable.")
    if not _verified(root):
        raise DependencyError("Supermodel runtime changed before the host check.")
    with tempfile.TemporaryDirectory(prefix="momentum-supermodel-check-") as folder:
        cwd = Path(folder)
        (cwd / "Config").mkdir()
        (cwd / "home").mkdir()
        env = {"PATH": "/usr/bin:/bin", "HOME": str(cwd / "home"), "LC_ALL": "C"}
        try:
            result = subprocess.run([str(executable), "-help"], cwd=cwd, env=env,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as e:
            raise DependencyError(f"Supermodel host check could not run: {e}") from e
    output = result.stdout + result.stderr
    if result.returncode == 127 or "error while loading shared libraries" in output:
        raise DependencyError("Supermodel cannot load required host libraries: " + output.strip())
    if result.returncode:
        raise DependencyError(f"Supermodel host check failed (exit {result.returncode}).")
    if HELP_VERSION not in output.splitlines():
        raise DependencyError("Supermodel reported an unexpected version.")
    words = set(output.split())
    missing = [flag for flag in REQUIRED_FLAGS if flag not in words]
    if missing:
        raise DependencyError("Supermodel lacks required command-line flags: " + ", ".join(missing))
    return {"cli_checked": True, "version": VERSION, "flags": list(REQUIRED_FLAGS),
            "gameplay_checked": False}


def make_plan(facts):
    return {"plan_version": 1, "operation": "prepare-dependency", "dependency": "supermodel",
            "scope": "user", "dependencies": {"supermodel": facts}, "actions": [],
            "dependency_commands": [],
            "dependency_download": None if facts["installed"] else {
                "url": ASSET_URL, "version": VERSION, "size": ASSET_SIZE,
                "sha256": ASSET_SHA256, "target": str(target_root())},
            "manual_actions": [{"action_id": "supermodel-capability-check",
                                "message": "Game setup and gameplay compatibility remain untested."}],
            "notes": ["No upgrades, system installation, game files or personal configuration changes.",
                      "Only the pinned official native runtime is reused.",
                      "Packages must use isolated Config, Assets, NVRAM and Saves state, not XDG paths."]}


def _cancel(context):
    if Path(context["cancel_file"]).exists():
        raise Cancelled("Cancelled before native dependency mutation.")


def _check_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in
            {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise DependencyError("Unsafe Supermodel download URL or redirect.")


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(context):
    _check_url(ASSET_URL)
    deadline = time.monotonic() + DOWNLOAD_TIMEOUT
    _cancel(context)
    opener = urllib.request.build_opener(_Redirects())
    with opener.open(ASSET_URL, timeout=10) as response:
        _check_url(response.geturl())
        if response.headers.get("Content-Length") not in (None, str(ASSET_SIZE)):
            raise DependencyError("Unexpected Supermodel download size.")
        data = bytearray()
        while True:
            _cancel(context)
            if time.monotonic() >= deadline:
                raise DependencyError("Supermodel download timed out.")
            chunk = response.read(min(65536, ASSET_SIZE + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > ASSET_SIZE:
                raise DependencyError("Supermodel download exceeds pinned size.")
    if len(data) != ASSET_SIZE or hashlib.sha256(data).hexdigest() != ASSET_SHA256:
        raise DependencyError("Supermodel archive size or SHA256 mismatch.")
    return bytes(data)


def validate_archive(data):
    """Validate everything in memory; never use tar extraction or execute code."""
    if len(data) != ASSET_SIZE or hashlib.sha256(data).hexdigest() != ASSET_SHA256:
        raise DependencyError("Supermodel archive size or SHA256 mismatch.")
    files, seen = {}, set()
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for member in archive:
                parts = member.name.split("/")
                if parts[0] != ARCHIVE_ROOT or any(p in (".", "..", "") for p in parts):
                    raise DependencyError("Unsafe archive path.")
                name = "/".join(parts[1:])
                if name in seen or name not in ASSET_INVENTORY:
                    raise DependencyError("Duplicate or unexpected archive entry.")
                seen.add(name)
                size, mode, digest = ASSET_INVENTORY[name]
                if (member.size != size or member.mode != mode or member.linkname
                        or (not member.isfile() if digest else not member.isdir())):
                    raise DependencyError("Unsafe archive type, size or permissions.")
                if digest:
                    content = archive.extractfile(member).read(size + 1)
                    if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                        raise DependencyError("Runtime asset SHA256 mismatch.")
                    files[name] = content
        if seen != set(ASSET_INVENTORY):
            raise DependencyError("Incomplete Supermodel archive.")
    except (tarfile.TarError, EOFError) as e:
        raise DependencyError(f"Invalid Supermodel archive: {e}") from e
    return files


def _publish(stage, target):
    # renameat2(RENAME_NOREPLACE) also protects against an empty target appearing
    # after preflight. Ordinary rename/os.replace would silently replace it.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise DependencyError("Atomic no-replace publication is unavailable.")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(stage), -100, os.fsencode(target), 1):
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise DependencyError("Supermodel target already exists; nothing was replaced.")
        raise OSError(error, os.strerror(error))
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


def run(context):
    phase, facts, plan, completed = context["phase"], None, None, []
    code, outcome, message = 0, "succeeded", "Native Supermodel prepared; game setup and compatibility remain."
    stage = None
    try:
        if phase not in ("preflight", "apply"):
            raise DependencyError("Unsupported dependency phase.")
        _cancel(context)
        journal = Path(context["result_file"]).parent / "dependency-transactions.json"
        attempts = _previous(journal, context["job_id"])
        facts = detect()
        if not supported():
            code, outcome, message = 20, "needs_action", "The pinned Supermodel runtime requires Linux x86_64."
        elif phase == "preflight":
            plan = make_plan(facts)
            if not facts["installed"] and os.path.lexists(target_root()):
                code, outcome, message = 20, "needs_action", "An unverified Supermodel target exists; reconcile manually."
            else:
                message = "Review the pinned user-scope native runtime download before proceeding."
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
                target = target_root()
                if os.path.lexists(target) or not _safe_path(target):
                    raise DependencyError("Uncertain Supermodel target; nothing will be replaced.")
                emit("step_started", "Downloading and verifying the pinned native Supermodel runtime.", step="resolve")
                files = validate_archive(download(context))
                _cancel(context)
                if detect() != facts or os.path.lexists(target) or not _safe_path(target):
                    raise DependencyError("Dependency facts changed before publication; review a new plan.")
                record = {"job_id": context["job_id"], "attempts": attempts, "completed": completed,
                          "active_command": ["publish-supermodel", str(target)], "before": facts}
                _write_durable(journal, (json.dumps(record, sort_keys=True) + "\n").encode())
                target.parent.mkdir(parents=True, exist_ok=True)
                stage = target.parent / f".{VERSION}.stage-{secrets.token_hex(8)}"
                stage.mkdir(mode=0o755)
                for name in RUNTIME_FILES:
                    _cancel(context)
                    path = stage / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("xb") as stream:
                        stream.write(files[name])
                        stream.flush()
                        os.fchmod(stream.fileno(), ASSET_INVENTORY[name][1])
                        os.fsync(stream.fileno())
                for directory in (stage / "Assets", stage / "Config", stage):
                    directory.chmod(0o755)
                    _fsync_dir(directory)
                if not _verified(stage):
                    raise DependencyError("Staged Supermodel runtime failed verification.")
                _cancel(context)
                _publish(stage, target)
                stage = None
                completed.append({"target": str(target), "sha256": ASSET_SHA256})
                record.update(active_command=None, detection_pending=True)
                _write_durable(journal, (json.dumps(record, sort_keys=True) + "\n").encode())
                facts = detect()
                if not facts["installed"]:
                    raise DependencyError("Published Supermodel runtime could not be detected.")
                record.update(after=facts, detection_pending=False)
                _write_durable(journal, (json.dumps(record, sort_keys=True) + "\n").encode())
                emit("step_completed", "Verified native runtime published; no game or emulator was launched.", step="resolve")
                _cancel(context)
    except Cancelled as e:
        code, outcome, message = 130, "cancelled", str(e)
        # Interrupted publication remains uncertain; a deliberate pre-publication
        # cancellation is reconciled only after the stage has been removed.
        if stage is not None:
            shutil.rmtree(stage)
            stage = None
            record.update(active_command=None, detection_pending=False)
            _write_durable(journal, (json.dumps(record, sort_keys=True) + "\n").encode())
    except (DependencyError, OSError, ValueError, KeyError) as e:
        code, outcome, message = 40, "failed", str(e)
        print(message, file=sys.stderr)
    finally:
        if stage is not None:
            try:
                shutil.rmtree(stage)
            except FileNotFoundError:
                pass
    result = {"result_version": 1, "job_id": context["job_id"], "phase": phase,
              "operation": "prepare-dependency", "outcome": outcome, "message": message,
              "dependencies": {"supermodel": facts}, "completed_transactions": completed}
    if plan is not None:
        result["plan"] = plan
    _write_durable(Path(context["result_file"]), (json.dumps(result, sort_keys=True) + "\n").encode())
    if outcome == "needs_action" or (phase == "apply" and outcome == "succeeded"):
        emit("needs_action", message, action_id="supermodel-capability-check", blocks_play=True)
    emit("result", message, outcome=outcome)
    return code


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--context":
        sys.exit("Usage: supermodel.py --context /absolute/context.json")
    sys.exit(run(json.loads(Path(sys.argv[2]).read_text())))
