#!/usr/bin/env python3
"""Approval-bound native EDuke32 source preparation; never executes the engine.

Safe unknown builds are installed facts, not compatibility evidence. Host probing
reads ELF metadata and library files only: CLI, graphics and gameplay remain
unchecked. Shared software is retained and never written to game intent logs.
"""
import hashlib
import io
import json
import os
import platform
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

from dependencies import DependencyError, emit
from jobs import _fsync_dir, _write_durable

SOURCE_COMMIT = "ec5824db81817866f70da326d3811bb0f52b3517"
ARCHIVE_ROOT = "eduke32-" + SOURCE_COMMIT
ASSET_URL = f"https://voidpoint.io/terminx/eduke32/-/archive/{SOURCE_COMMIT}/{ARCHIVE_ROOT}.tar.gz"
ASSET_SHA256 = "1a29b509a1e752a3bc37860593028f08bc8cc980d988574a83575e951521f4f2"
ASSET_SIZE = 29551166
ENGINE_SHA256 = "bc3a5465c7e236f5f5662ccdc663c7f36ba375b70b4ccc5c2f3ca44f592e8270"
ENGINE_SIZE = 3742920
BUILD_ARGV = ["make", "-j2", "eduke32"]
BUILD_TOOLS = ("make", "c++", "nasm", "pkg-config")
BUILD_LIBRARIES = ("sdl2", "gl", "vpx", "flac", "gtk+-2.0")
DOWNLOAD_TIMEOUT = 90
MAX_ENGINE_SIZE = 128 * 1024 * 1024
MAX_SOURCE_SIZE = 512 * 1024 * 1024
MAX_SOURCE_MEMBERS = 30000
PROC_ROOT = Path("/proc")


class Cancelled(DependencyError):
    pass


class NeedsAction(DependencyError):
    pass


def target_root():
    return Path.home() / ".local/share/momentum-core/software/eduke32" / SOURCE_COMMIT


def target_path():
    return target_root() / "eduke32"


def supported():
    return platform.system() == "Linux" and platform.machine() in ("x86_64", "AMD64")


def _candidates():
    return (Path.home() / "Games/Duke-Nukem-3D/eduke32",
            Path.home() / "src/eduke32/eduke32", target_path())


def _safe_path(path):
    return (path.is_absolute() and ".." not in path.parts
            and not any(p.is_symlink() for p in (path, *path.parents)))


def _elf(header):
    return (len(header) >= 64 and header[:7] == b"\x7fELF\x02\x01\x01"
            and header[16:18] in (b"\x02\x00", b"\x03\x00")
            and header[18:20] == b"\x3e\x00")


def _inspect(path):
    """Hash an owned executable without following links or racing a replacement."""
    if not _safe_path(path):
        raise DependencyError(f"Unsafe EDuke32 path: {path}; reconcile manually.")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or not before.st_mode & stat.S_IXUSR
                    or before.st_mode & (stat.S_IWOTH | stat.S_ISUID | stat.S_ISGID)
                    or (before.st_mode & stat.S_IWGRP and before.st_gid != os.getgid())
                    or not 64 <= before.st_size <= MAX_ENGINE_SIZE):
                raise DependencyError(f"Unsafe or non-executable EDuke32 file: {path}.")
            if not _elf(stream.read(64)):
                raise DependencyError(f"EDuke32 must be a native Linux x86_64 ELF: {path}.")
            stream.seek(0)
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            current = path.stat(follow_symlinks=False)
            stable = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_size",
                      "st_mtime_ns", "st_ctime_ns")
            if (not _safe_path(path) or any(getattr(before, k) != getattr(after, k)
                    or getattr(before, k) != getattr(current, k) for k in stable)):
                raise DependencyError(f"EDuke32 changed during inspection: {path}.")
            return {"sha256": digest.hexdigest(), "size": before.st_size,
                    "mode": stat.S_IMODE(before.st_mode)}
    except OSError as e:
        raise DependencyError(f"Cannot inspect EDuke32 {path}: {e}") from e


def detect():
    inspected = {}
    for candidate in _candidates():
        if not _safe_path(candidate):
            raise DependencyError(f"Unsafe EDuke32 candidate: {candidate}; reconcile manually.")
        if os.path.lexists(candidate):
            inspected[candidate] = _inspect(candidate)
    executable = next(iter(inspected), target_path())
    metadata = inspected.get(executable, {})
    installed = bool(metadata) and supported()
    return {"provider": "native", "scope": "user", "installed": installed,
            "version": None, "executable": str(executable), "launch_argv": [str(executable)],
            "sha256": metadata.get("sha256"), "size": metadata.get("size"),
            "mode": metadata.get("mode"),
            "recognized_build": bool(installed and metadata["sha256"] == ENGINE_SHA256
                                     and metadata["size"] == ENGINE_SIZE),
            "capabilities_checked": False,
            "capability_note": "Exact target evidence must bind CLI flags, Polymost, voxels and music "
                               "to these bytes. Hash recognition and host libraries are not gameplay evidence."}


def _require_runtime(facts):
    executable = Path(facts.get("executable", ""))
    if (not supported() or facts.get("installed") is not True
            or facts.get("provider") != "native" or facts.get("scope") != "user"
            or executable not in _candidates()
            or facts.get("launch_argv") != [str(executable)]):
        raise DependencyError("An installed user-scope native EDuke32 runtime is required.")
    metadata = _inspect(executable)
    if any(facts.get(k) != metadata[k] for k in metadata):
        raise DependencyError("EDuke32 runtime changed; repeat detection and approval.")
    return executable


def _probe(argv):
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, timeout=15,
                                env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError, UnicodeError) as e:
        raise DependencyError(f"Cannot inspect EDuke32 prerequisites: {e}") from e
    if result.returncode:
        raise DependencyError(f"Prerequisite inspection failed: {argv[0]}: "
                              f"{result.stderr.strip() or result.returncode}")
    return result.stdout


def _host_elf(path):
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid not in (0, os.getuid())
                or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH | stat.S_ISUID | stat.S_ISGID)):
            raise DependencyError(f"Unsafe linked library or interpreter: {path}.")
        with resolved.open("rb") as stream:
            if not _elf(stream.read(64)):
                raise DependencyError(f"Non-x86_64 ELF linked library or interpreter: {path}.")
        return str(resolved)
    except OSError as e:
        raise DependencyError(f"Missing or unreadable linked library/interpreter {path}: {e}") from e


def check_host(facts):
    """Inspect readelf and ldconfig metadata; never use ldd or execute any ELF."""
    executable = _require_runtime(facts)
    if os.environ.get("LD_LIBRARY_PATH") or os.environ.get("LD_PRELOAD") or os.environ.get("LD_AUDIT"):
        raise DependencyError("Loader environment overrides prevent a reliable read-only host check.")
    readelf = shutil.which("readelf")
    ldconfig = shutil.which("ldconfig")
    if not readelf or not ldconfig:
        raise DependencyError("Host checks require readelf and ldconfig; install with system tools. No elevation.")
    headers = _probe([readelf, "-W", "-l", str(executable)])
    dynamic = _probe([readelf, "-W", "-d", str(executable)])
    interpreter = re.search(r"Requesting program interpreter:\s*([^\]]+)\]", headers)
    if not interpreter or not Path(interpreter[1]).is_absolute():
        raise DependencyError("Native EDuke32 ELF has no inspectable absolute interpreter.")
    interpreter_path = _host_elf(Path(interpreter[1]))
    needed = re.findall(r"\(NEEDED\).*Shared library: \[([^\]]+)\]", dynamic)
    if not needed or any("/" in name or name in (".", "..") for name in needed):
        raise DependencyError("Native EDuke32 has invalid or missing linked-library metadata.")
    search = []
    for entry in re.findall(r"\((?:RUNPATH|RPATH)\).*\[([^\]]*)\]", dynamic):
        for directory in entry.split(":"):
            directory = directory.replace("${ORIGIN}", str(executable.parent))
            directory = directory.replace("$ORIGIN", str(executable.parent))
            path = Path(directory)
            if not directory or "$" in directory or not _safe_path(path):
                raise DependencyError("Unsupported or unsafe native EDuke32 library search path.")
            search.append(path)
    cache = {}
    for name, path in re.findall(r"^\s*(\S+)\s+\([^)]*x86-64[^)]*\)\s+=>\s+(\S+)\s*$",
                                 _probe([ldconfig, "-p"]), re.MULTILINE):
        cache.setdefault(name, Path(path))
    libraries = {}
    for name in needed:
        path = next((directory / name for directory in search
                     if os.path.lexists(directory / name)), cache.get(name))
        if path is None:
            raise DependencyError(f"Missing linked library {name}; use system tools. No elevation is attempted.")
        libraries[name] = _host_elf(path)
    _require_runtime(facts)
    return {"sha256": facts["sha256"], "bytes_verified": True, "elf_checked": True,
            "architecture": "x86_64", "interpreter": interpreter_path,
            "linked_libraries": libraries, "host_prerequisites_checked": True,
            "cli_checked": False, "capabilities_checked": False, "gameplay_checked": False,
            "graphics_device_checked": False, "library_abi_checked": False,
            "note": "Read-only direct DT_NEEDED resolution only; no engine, loader, CLI or graphics execution."}


def _process_metadata(entry):
    try:
        comm = (entry / "comm").read_bytes().strip().lower()
    except OSError:
        comm = None
    try:
        argv0 = (entry / "cmdline").read_bytes().split(b"\0", 1)[0]
    except OSError:
        argv0 = None
    return comm, argv0


def _marker(value):
    return bool(value) and Path(os.fsdecode(value).removesuffix(" (deleted)")).name.lower() == "eduke32"


def running(facts):
    """Fail closed for suspect/uninspectable current-user processes."""
    executable = _require_runtime(facts)
    identity = executable.stat()
    found = False
    try:
        for entry in PROC_ROOT.iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                if entry.stat().st_uid != os.getuid():
                    continue
                comm, argv0 = _process_metadata(entry)
                try:
                    path = os.readlink(entry / "exe")
                    observed = (entry / "exe").stat()
                except PermissionError as e:
                    if comm and argv0 and not comm.startswith(b"eduke32") and not _marker(argv0):
                        continue
                    raise DependencyError(f"Cannot inspect suspect EDuke32 process {entry.name}.") from e
                if ((observed.st_dev, observed.st_ino) == (identity.st_dev, identity.st_ino)
                        or path.removesuffix(" (deleted)") == str(executable)
                        or _marker(os.fsencode(path)) or (comm and comm.startswith(b"eduke32")) or _marker(argv0)):
                    found = True
            except FileNotFoundError:
                if entry.exists():
                    status = (entry / "status").read_text()
                    if not any(line.startswith(("Kthread:\t1", "State:\tZ", "State:\tX"))
                               for line in status.splitlines()):
                        raise DependencyError(f"Cannot inspect live process {entry.name}.")
        _require_runtime(facts)
        return found
    except OSError as e:
        raise DependencyError(f"Cannot inspect native EDuke32 processes: {e}") from e


def commands_for(facts):
    return [] if facts["installed"] else [list(BUILD_ARGV)]


def make_plan(facts):
    return {"plan_version": 1, "operation": "prepare-dependency", "dependency": "eduke32",
            "scope": "user", "dependencies": {"eduke32": facts}, "actions": [],
            "dependency_commands": commands_for(facts),
            "dependency_download": None if facts["installed"] else {
                "url": ASSET_URL, "source_commit": SOURCE_COMMIT, "size": ASSET_SIZE,
                "sha256": ASSET_SHA256, "target": str(target_path())},
            "build_prerequisites": {"tools": list(BUILD_TOOLS), "pkg_config": list(BUILD_LIBRARIES)},
            "manual_actions": [{"action_id": "eduke32-capability-check",
                                "message": "Exact target evidence, host and gameplay checks remain required."}],
            "notes": ["No elevation, upgrades, engine execution or game/save/config changes.",
                      "Existing safe engines, including unknown builds, are never replaced or chmodded.",
                      "Only the separately approved pinned official source may be downloaded and built.",
                      "Cancellation waits for active make; failed/interrupted journals require reconciliation.",
                      "Shared runtime remains installed after game removal."]}


def _cancel(context):
    if os.path.lexists(context["cancel_file"]):
        raise Cancelled("Cancellation acknowledged; active make is allowed to finish and shared software retained.")


def _check_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "voidpoint.io"
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise DependencyError("Unsafe EDuke32 source URL or redirect.")


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_bytes(data):
    if len(data) != ASSET_SIZE or hashlib.sha256(data).hexdigest() != ASSET_SHA256:
        raise DependencyError("EDuke32 source archive size or SHA256 mismatch.")


def download(context):
    _cancel(context)
    _check_url(ASSET_URL)
    deadline = time.monotonic() + DOWNLOAD_TIMEOUT
    with urllib.request.build_opener(_Redirects()).open(ASSET_URL, timeout=10) as response:
        _check_url(response.geturl())
        if response.headers.get("Content-Length") not in (None, str(ASSET_SIZE)):
            raise DependencyError("Unexpected EDuke32 source download size.")
        data = bytearray()
        while True:
            _cancel(context)
            if time.monotonic() >= deadline:
                raise DependencyError("EDuke32 source download timed out.")
            chunk = response.read(min(65536, ASSET_SIZE + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > ASSET_SIZE:
                raise DependencyError("EDuke32 source download exceeds pinned size.")
    _validate_bytes(data)
    return bytes(data)


def extract_source(data, build, context):
    """Prevalidate a bounded single-root archive, then create regular files only."""
    _validate_bytes(data)
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            members, seen, total = [], set(), 0
            for member in archive:
                _cancel(context)
                parts = member.name.rstrip("/").split("/")
                if (not parts or parts[0] != ARCHIVE_ROOT or any(p in ("", ".", "..") for p in parts)
                        or member.name.startswith("/") or "\\" in member.name
                        or not (member.isfile() or member.isdir()) or member.linkname
                        or member.mode & 0o7000 or member.size < 0 or member.issparse()
                        or member.name.rstrip("/") in seen):
                    raise DependencyError("Unsafe or duplicate EDuke32 source archive member.")
                seen.add(member.name.rstrip("/"))
                total += member.size
                members.append(member)
                if total > MAX_SOURCE_SIZE or len(members) > MAX_SOURCE_MEMBERS:
                    raise DependencyError("EDuke32 extracted source exceeds safe bounds.")
            if not members or not any(m.isfile() for m in members):
                raise DependencyError("Empty EDuke32 source archive.")
            types = {m.name.rstrip("/"): m.isdir() for m in members}
            for member in members:
                if any(types.get(str(p)) is False for p in Path(member.name).parents):
                    raise DependencyError("EDuke32 archive file/directory collision.")
            if os.path.lexists(build) or not _safe_path(build):
                raise DependencyError("EDuke32 build area exists or is unsafe; reconcile before retry.")
            build.mkdir(mode=0o700)
            for member in members:
                _cancel(context)
                path = build / member.name
                if member.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source, path.open("xb") as out:
                        remaining = member.size
                        while remaining:
                            _cancel(context)
                            chunk = source.read(min(65536, remaining))
                            if not chunk:
                                raise DependencyError("Truncated EDuke32 source member.")
                            out.write(chunk)
                            remaining -= len(chunk)
                        out.flush()
                        os.fchmod(out.fileno(), 0o755 if member.mode & 0o111 else 0o644)
                        os.fsync(out.fileno())
            _fsync_dir(build)
            return build / ARCHIVE_ROOT
    except (tarfile.TarError, EOFError) as e:
        raise DependencyError(f"Invalid EDuke32 source archive: {e}") from e


def check_build_prerequisites():
    for tool in BUILD_TOOLS:
        if not shutil.which(tool):
            raise NeedsAction(f"Missing EDuke32 build tool {tool}; use system tools. No elevation is attempted.")
    for library in BUILD_LIBRARIES:
        try:
            _probe(["pkg-config", "--exists", library])
        except DependencyError as e:
            raise NeedsAction(f"Missing EDuke32 development library {library}; use system tools. {e}") from e


def _build(source):
    # A protocol runner requests cancellation via a file, not signals. Waiting
    # here deliberately lets make and all its children finish before checking it.
    try:
        result = subprocess.run(list(BUILD_ARGV), cwd=source, stdin=subprocess.DEVNULL,
                                stdout=sys.stderr, stderr=sys.stderr,
                                env={k: v for k, v in os.environ.items()
                                     if k not in ("MAKEFLAGS", "MFLAGS", "MAKEFILES")})
    except (OSError, subprocess.SubprocessError) as e:
        raise DependencyError(f"Cannot build native EDuke32: {e}") from e
    if result.returncode:
        raise DependencyError(f"Native EDuke32 build failed ({result.returncode}); "
                              "source/diagnostics retained. Reconcile before retry.")


def _publish(stage, target):
    if stage.parent != target.parent or not _safe_path(stage) or not _safe_path(target):
        raise DependencyError("Unsafe EDuke32 publication paths; nothing was replaced.")
    _inspect(stage)
    try:
        os.link(stage, target, follow_symlinks=False)
    except FileExistsError as e:
        raise DependencyError("EDuke32 target already exists; nothing was replaced.") from e
    _fsync_dir(target.parent)
    stage.unlink()
    _fsync_dir(target.parent)


def _previous(journal, job_id):
    if not os.path.lexists(journal):
        return []
    if not _safe_path(journal) or not journal.is_file():
        raise DependencyError("Unsafe dependency transaction journal; reconcile before retry.")
    record = json.loads(journal.read_text())
    metadata = journal.stat()
    if (metadata.st_uid != os.getuid() or metadata.st_mode & stat.S_IWOTH
            or (metadata.st_mode & stat.S_IWGRP and metadata.st_gid != os.getgid())):
        raise DependencyError("Unsafe dependency transaction journal ownership or permissions.")
    if (not isinstance(record, dict) or record.get("job_id") != job_id
            or "active_command" not in record or not isinstance(record.get("completed"), list)
            or not isinstance(record.get("attempts", []), list)
            or record.get("active_command") or record.get("detection_pending") or record.get("failed")):
        raise DependencyError("An earlier dependency transaction is uncertain; reconcile before retry.")
    return record.get("attempts", []) + [{"completed": record["completed"]}]


def _context_paths(context):
    fields = ["result_file", "cancel_file", "job_id"]
    if context["phase"] == "apply":
        fields += ["approved_plan_file", "approved_plan_digest"]
    if any(not isinstance(context.get(k), str) or not context[k] for k in fields):
        raise DependencyError("Missing or invalid dependency protocol fields.")
    result = Path(context["result_file"])
    cancel = Path(context["cancel_file"])
    jobdir = result.parent
    paths = [result, cancel]
    if context["phase"] == "apply":
        paths.append(Path(context["approved_plan_file"]))
    reserved = {jobdir / "dependency-transactions.json", jobdir / "eduke32-build"}
    if (len(set(paths)) != len(paths) or any(not _safe_path(p) or p.parent != jobdir for p in paths)
            or any(p in reserved for p in paths)
            or not jobdir.is_dir() or jobdir.stat().st_uid != os.getuid()
            or jobdir.stat().st_mode & stat.S_IWOTH
            or (jobdir.stat().st_mode & stat.S_IWGRP and jobdir.stat().st_gid != os.getgid())):
        raise DependencyError("Protocol files must be distinct, safe, owned and job-local.")
    for candidate in _candidates():
        if jobdir.is_relative_to(candidate.parent) or candidate.is_relative_to(jobdir):
            raise DependencyError("Dependency job area must not overlap engine/game/source paths.")
    for path in paths:
        if os.path.lexists(path):
            metadata = path.stat(follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise DependencyError("Unsafe protocol file.")
    return jobdir


def _mkdir_durable(path):
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    if not _safe_path(path) or not current.is_dir():
        raise DependencyError("Unsafe EDuke32 destination directory.")
    for directory in reversed(missing):
        directory.mkdir()
        _fsync_dir(directory)
        _fsync_dir(directory.parent)


def run(context):
    if not isinstance(context, dict):
        emit("result", "Dependency context must be an object.", outcome="failed")
        return 40
    phase, facts, plan, completed = context.get("phase"), None, None, []
    code, outcome, message = 0, "succeeded", "Native EDuke32 prepared; exact compatibility evidence remains required."
    stage, record, journal, paths_checked = None, None, None, False
    try:
        if phase not in ("preflight", "apply"):
            raise DependencyError("Unsupported dependency phase.")
        jobdir = _context_paths(context)
        paths_checked = True
        _cancel(context)
        journal = jobdir / "dependency-transactions.json"
        attempts = _previous(journal, context["job_id"])
        facts = detect()
        if not supported():
            raise NeedsAction("Native EDuke32 requires Linux x86_64; no provider fallback.")
        if facts["installed"] and running(facts):
            raise NeedsAction("Close EDuke32 before preparing or checking this runtime.")
        plan = make_plan(facts)
        if phase == "preflight":
            message = "Review native EDuke32 reuse or the separately approved pinned source download and build."
        else:
            raw = Path(context["approved_plan_file"]).read_bytes()
            if "sha256:" + hashlib.sha256(raw).hexdigest() != context["approved_plan_digest"]:
                raise DependencyError("The saved dependency plan changed; obtain new approval.")
            envelope = json.loads(raw)
            if (not isinstance(envelope, dict) or envelope.get("job_id") != context["job_id"]
                    or envelope.get("phase") != "preflight" or envelope.get("outcome") != "succeeded"
                    or envelope.get("plan") != plan):
                code, outcome, message = 30, "conflicted", "Dependency facts changed; review a new preflight plan."
            elif not facts["installed"]:
                check_build_prerequisites()
                _cancel(context)
                build = jobdir / "eduke32-build"
                if os.path.lexists(build):
                    raise DependencyError("Build area exists; reconcile earlier work before retry.")
                record = {"job_id": context["job_id"], "attempts": attempts,
                          "completed": completed, "before": facts,
                          "active_command": ["download-eduke32-source", ASSET_URL],
                          "detection_pending": False}

                def checkpoint(**fields):
                    record.update(fields)
                    _write_durable(journal, (json.dumps(record, sort_keys=True) + "\n").encode())

                checkpoint()
                emit("step_started", "Downloading and building approved EDuke32 source; no engine execution.", step="resolve")
                data = download(context)
                checkpoint(active_command=["extract-eduke32-source", str(build)])
                source = extract_source(data, build, context)
                _cancel(context)
                if detect() != facts:
                    raise DependencyError("Dependency facts changed before build.")
                checkpoint(active_command=list(BUILD_ARGV), build_directory=str(source))
                _build(source)
                checkpoint(active_command=None, detection_pending=True)
                _cancel(context)
                artifact = source / "eduke32"
                metadata = _inspect(artifact)
                if detect() != facts:
                    raise DependencyError("Dependency facts changed before publication.")
                checkpoint(active_command=["publish-eduke32", str(target_path())])
                _mkdir_durable(target_root())
                stage = target_root() / f".eduke32.stage-{secrets.token_hex(8)}"
                with artifact.open("rb") as src, stage.open("xb") as out:
                    shutil.copyfileobj(src, out, 65536)
                    out.flush()
                    os.fchmod(out.fileno(), 0o755)
                    os.fsync(out.fileno())
                _fsync_dir(stage.parent)
                staged = _inspect(stage)
                if staged["sha256"] != metadata["sha256"] or staged["size"] != metadata["size"]:
                    raise DependencyError("Built EDuke32 artifact changed during staging.")
                _cancel(context)
                if detect() != facts:
                    raise DependencyError("Dependency facts changed before publication; nothing replaced.")
                _publish(stage, target_path())
                stage = None
                completed.append({"target": str(target_path()), **staged})
                checkpoint(active_command=None, detection_pending=True)
                facts = detect()
                if (not facts["installed"] or facts["executable"] != str(target_path())
                        or any(facts[k] != staged[k] for k in staged)):
                    raise DependencyError("Published EDuke32 changed or could not be detected.")
                checkpoint(after=facts, detection_pending=False)
                emit("step_completed", "Native EDuke32 published; target compatibility remains gated.", step="resolve")
                _cancel(context)
    except Cancelled as e:
        code, outcome, message = 130, "cancelled", str(e)
    except NeedsAction as e:
        code, outcome, message = 20, "needs_action", str(e)
    except (DependencyError, OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
        code, outcome, message = 40, "failed", str(e)
        print(message, file=sys.stderr)
    finally:
        if record is not None and (record.get("active_command") or record.get("detection_pending")):
            record["failed"] = True
            _write_durable(journal, (json.dumps(record, sort_keys=True) + "\n").encode())
        if stage is not None:
            stage.unlink(missing_ok=True)
            _fsync_dir(stage.parent)
    result = {"result_version": 1, "job_id": context.get("job_id"), "phase": phase,
              "operation": "prepare-dependency", "outcome": outcome, "message": message,
              "dependencies": {"eduke32": facts}, "completed_transactions": completed}
    if plan is not None:
        result["plan"] = plan
    if paths_checked:
        _write_durable(Path(context["result_file"]), (json.dumps(result, sort_keys=True) + "\n").encode())
    if outcome == "needs_action" or (phase == "apply" and outcome == "succeeded"):
        emit("needs_action", message, action_id="eduke32-capability-check", blocks_play=True)
    emit("result", message, outcome=outcome)
    return code


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--context":
        sys.exit("Usage: eduke32.py --context /absolute/context.json")
    try:
        sys.exit(run(json.loads(Path(sys.argv[2]).read_text())))
    except (DependencyError, OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(40)
