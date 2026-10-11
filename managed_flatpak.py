#!/usr/bin/env python3
"""Approval-bound isolated Flycast/UZDoom preparation and retained launch binding."""
import configparser
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from contextlib import contextmanager

CONTRACT = "momentum-flatpak-1"
BUILDS = {
    "flycast": {"app_id": "org.flycast.Flycast", "command": "flycast", "version": "v2.7",
                "commit": "86ec4d845a66ff07cdba8e003d8549e93cd7a814b519766e1f744e530c5d3e5b"},
    "uzdoom": {"app_id": "org.zdoom.UZDoom", "command": "uzdoom", "version": "5.0.1",
               "commit": "d7b8ce76e5480a28d1e07400093a20d47f56c201fd974b0a5dbfa3b26bbd587e"},
}
REMOTE = "https://dl.flathub.org/repo/"
REMOTE_DESCRIPTOR = "https://flathub.org/repo/flathub.flatpakrepo"
SPACE = {"flycast": 6 << 30, "uzdoom": 4 << 30}


class ManagedError(ValueError):
    pass


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def safe(path):
    if not isinstance(path, (str, Path)):
        raise ManagedError("Expected an absolute managed path.")
    path = Path(path)
    if (not path.is_absolute() or ".." in path.parts or
            any(ord(c) < 32 or c in ":;" for c in str(path))):
        raise ManagedError("Unsupported managed path or Flatpak permission separator.")
    for node in (path, *path.parents):
        if node.is_symlink():
            raise ManagedError(f"Managed paths must not contain symlinks: {node}")
    if path.exists() and path.stat().st_uid != os.getuid():
        raise ManagedError(f"Managed path belongs to another user: {path}")
    return path


def root():
    return safe(str(Path.home() / ".local/share/momentum-core"))


def slot(runtime):
    build = BUILDS[runtime]
    return safe(str(root() / "software/flatpak" / build["app_id"] / "x86_64/stable" / build["commit"]))


def helper():
    content = Path(__file__).read_bytes()
    return root() / "software/helpers" / digest(content)[7:] / "managed_flatpak.py"


def write(path, data):
    path = safe(str(path))
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(8) + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def packed(value):
    return (json.dumps(value, sort_keys=True) + "\n").encode()


def environment(directory):
    env = {**os.environ, "LC_ALL": "C", "FLATPAK_USER_DIR": str(directory / "flatpak"),
           "HOME": str(directory / "bootstrap/home")}
    for key, name in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                      ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state")):
        env[key] = str(directory / "bootstrap" / name)
    return env


def probe(directory, *args):
    try:
        result = subprocess.run(["flatpak", *args], env=environment(directory),
                                stdin=subprocess.DEVNULL, text=True, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise ManagedError(f"Cannot inspect isolated Flatpak: {exc}") from exc
    if result.returncode:
        raise ManagedError(f"Isolated Flatpak {args[0]} failed: {result.stderr.strip() or result.returncode}")
    return result.stdout.strip()


def app_metadata(text, runtime):
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
        app = parser["Application"]
        declared = app["runtime"]
        build = BUILDS[runtime]
        if (app["name"] != build["app_id"] or app["command"] != build["command"] or
                not re.fullmatch(r"[A-Za-z0-9_.-]+/x86_64/[A-Za-z0-9_.-]+", declared)):
            raise ManagedError("Unexpected managed app command/runtime.")
        return declared
    except (configparser.Error, KeyError) as exc:
        raise ManagedError(f"Malformed managed app metadata: {exc}") from exc


def inspect(runtime):
    directory = slot(runtime)
    build = BUILDS[runtime]
    app = build["app_id"]
    if probe(directory, "info", "--user", "--show-ref", app) != f"app/{app}/x86_64/stable":
        raise ManagedError("Managed app ref changed; review repair before launching.")
    if probe(directory, "info", "--user", "--show-commit", app) != build["commit"]:
        raise ManagedError("Managed app commit changed; no alternative will be launched.")
    if probe(directory, "info", "--user", "--show-origin", app) != "flathub":
        raise ManagedError("Managed app origin changed.")
    version = re.search(r"^\s*Version:\s*(.*?)\s*$",
                       probe(directory, "info", "--user", app), re.M)
    if not version or version.group(1) != build["version"]:
        raise ManagedError("Managed app version changed.")
    declared = app_metadata(probe(directory, "info", "--user", "--show-metadata", app), runtime)
    if probe(directory, "info", "--user", "--show-runtime", app) != declared:
        raise ManagedError("Managed runtime metadata disagrees.")
    refs = probe(directory, "list", "--user", "--columns=ref,origin").splitlines()
    graph = {}
    for row in refs:
        fields = row.split("\t")
        if len(fields) != 2 or fields[1] != "flathub":
            raise ManagedError("Unexpected ref/origin in managed installation.")
        commit = probe(directory, "info", "--user", "--show-commit", fields[0])
        if not re.fullmatch(r"[a-f0-9]{64}", commit):
            raise ManagedError("Incomplete managed deployment identity.")
        graph[fields[0]] = commit
    if declared not in graph:
        raise ManagedError("Required runtime is missing from the isolated installation.")
    if probe(directory, "info", "--user", "--show-ref", declared) != "runtime/" + declared:
        raise ManagedError("Required isolated runtime is not deployed.")
    if app not in probe(directory, "mask", "--user").splitlines():
        raise ManagedError("Managed app update mask changed.")
    remotes = probe(directory, "remotes", "--user", "--columns=name,url,options").splitlines()
    fields = remotes[0].split("\t") if len(remotes) == 1 else []
    if len(fields) < 2 or fields[:2] != ["flathub", REMOTE] or "no-gpg-verify" in fields[-1]:
        raise ManagedError("Managed Flathub trust configuration changed.")
    return {"contract": CONTRACT, "runtime": runtime, "build": build,
            "installation": str(directory / "flatpak"), "declared_runtime": declared,
            "resolved_commits": graph}


def ready(runtime):
    directory = slot(runtime)
    descriptor = safe(str(directory / "slot.json"))
    if not descriptor.exists():
        if directory.exists():
            raise ManagedError(
                f"Incomplete isolated engine retained at {directory}. No game files were installed. "
                "Keep this folder and its journal; review recovery before retrying.")
        return None
    recorded = json.loads(descriptor.read_text())
    if recorded != inspect(runtime):
        raise ManagedError("Isolated dependency graph changed; review repair, do not bypass validation.")
    retained = safe(str(helper()))
    expected = Path(__file__).read_bytes()
    if not retained.is_file() or retained.read_bytes() != expected:
        raise ManagedError("Retained launch helper is missing or changed; review repair.")
    return recorded


def binding(runtime, package_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", package_id):
        raise ManagedError("Invalid game profile identity.")
    if ready(runtime) is None:
        return None
    return {"contract": CONTRACT, "runtime": runtime, "slot": str(slot(runtime)),
            "descriptor_sha256": digest((slot(runtime) / "slot.json").read_bytes()),
            "helper": str(helper()), "helper_sha256": digest(Path(__file__).read_bytes()),
            "profile": str(root() / "state" / package_id / "engine-profile-v1"),
            "package_id": package_id}


def facts(runtime, package_id):
    bound = binding(runtime, package_id)
    if bound is None:
        return None
    return {**BUILDS[runtime], "provider": "flatpak", "scope": "user", "arch": "x86_64",
            "branch": "stable", "origin": "flathub", "flatpak_available": True,
            "installed": True, "remote_present": True, "capabilities_checked": False,
            "running": False, "ownership": "managed", "managed": bound,
            "launch_argv": ["python3", bound["helper"], "--launch", json.dumps(bound, sort_keys=True)],
            "location": str(slot(runtime)), "capability_note": "Isolated tested build; confirm target gameplay."}


def validate_binding(bound):
    if not isinstance(bound, dict) or bound.get("runtime") not in BUILDS:
        raise ManagedError("Invalid managed launch binding.")
    expected = binding(bound["runtime"], bound.get("package_id", ""))
    if expected != bound:
        raise ManagedError("Engine/helper/profile binding changed; start a new review.")
    return bound


def launch(bound, media, args):
    validate_binding(bound)
    media = safe(media)
    profile = safe(bound["profile"])
    if not media.is_dir() or media == profile or media in profile.parents or profile in media.parents:
        raise ManagedError("Game media/profile overlap or media is missing.")
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    paths = {}
    for name in ("home", "config", "data", "cache", "state"):
        paths[name] = safe(str(profile / name))
        paths[name].mkdir(exist_ok=True, mode=0o700)
    if bound["runtime"] == "flycast":
        for name in ("config", "data"):
            safe(str(paths[name] / "flycast")).mkdir(exist_ok=True, mode=0o700)
    build = BUILDS[bound["runtime"]]
    argv = ["flatpak", "run", "--user", "--die-with-parent", "--nofilesystem=host:reset",
            "--filesystem=" + str(profile), "--filesystem=" + str(media) + ":ro",
            "--command=/usr/bin/env", build["app_id"], "HOME=" + str(paths["home"]),
            "XDG_CONFIG_HOME=" + str(paths["config"]), "XDG_DATA_HOME=" + str(paths["data"]),
            "XDG_CACHE_HOME=" + str(paths["cache"]), "XDG_STATE_HOME=" + str(paths["state"]),
            build["command"], *args]
    # Keep the supervisor alive: Flatpak's die-with-parent refers to this process.
    return subprocess.call(argv, env=environment(slot(bound["runtime"])))


def plan(runtime, package_id, existing):
    if ready(runtime):
        raise ManagedError("A completed isolated engine is now available; start a new setup review.")
    if not shutil.which("flatpak"):
        raise ManagedError("Install the host Flatpak client first; Momentum cannot elevate.")
    ancestor = slot(runtime)
    while not ancestor.exists():
        ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < SPACE[runtime]:
        raise ManagedError(f"Allow at least {SPACE[runtime] >> 30} GiB free for this isolated engine.")
    build = BUILDS[runtime]
    return {"plan_version": 1, "operation": "prepare-dependency", "managed_engine": CONTRACT,
            "runtime": runtime, "package_id": package_id, "target": build,
            "existing": existing, "slot": str(slot(runtime)), "helper": str(helper()),
            "helper_sha256": digest(Path(__file__).read_bytes()), "actions": [],
            "space_required_bytes": SPACE[runtime],
            "profile": str(root() / "state" / package_id / "engine-profile-v1"),
            "dependency_commands": [
                ["flatpak", "remote-add", "--user", "flathub", REMOTE_DESCRIPTOR],
                ["flatpak", "install", "--user", "--noninteractive", "-y", "flathub", build["app_id"]],
                ["flatpak", "update", "--user", "--noninteractive", "-y",
                 "--commit=" + build["commit"], build["app_id"]],
                ["flatpak", "install", "--user", "--noninteractive", "-y", "--or-update",
                 "flathub", "<runtime declared by approved app commit>"],
                ["flatpak", "mask", "--user", build["app_id"]]],
            "environment": {key: value for key, value in environment(slot(runtime)).items()
                            if key in ("FLATPAK_USER_DIR", "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
                                       "XDG_CACHE_HOME", "XDG_STATE_HOME", "LC_ALL")},
            "manual_actions": [{"action_id": "target-gameplay", "message": "Confirm target fullscreen, controls and saves."}],
            "notes": ["Existing engines and settings stay untouched. Game installation needs a separate approval.",
                      "Each game has separate settings and saves; no existing profile is imported.",
                      "The app and dependency graph are checked on launch; no automatic updates or cleanup.",
                      "Cancellation waits for the active Flatpak transaction. Partial work and journals are retained."]}


@contextmanager
def locked(runtime):
    parent = safe(str(root() / "software/locks"))
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = safe(str(parent / (runtime + "-" + BUILDS[runtime]["commit"] + ".lock")))
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ManagedError("Another process is preparing this isolated engine; wait and review again.") from exc
        yield


def provision(context, approved, completed):
    from jobs import _write_durable
    runtime = context["runtime"]
    directory = slot(runtime)
    cancel = Path(context["cancel_file"])
    journal = Path(context["result_file"]).parent / "dependency-transactions.json"

    def save(active=None, pending=False):
        record = {"job_id": context["job_id"], "slot": str(directory),
                  "completed": completed, "active_command": active, "detection_pending": pending}
        _write_durable(journal, packed(record))
        if directory.exists():
            write(directory / "journal.json", packed(record))

    def transaction(argv):
        if cancel.exists():
            raise InterruptedError("Cancelled at a safe boundary; isolated work is retained.")
        save(argv)
        emit("step_started", "Preparing isolated " + runtime + ": " + argv[1], step="resolve")
        result = subprocess.run(argv, env=environment(directory), stdin=subprocess.DEVNULL,
                                stdout=sys.stderr, stderr=sys.stderr)
        completed.append({"argv": argv, "exit_code": result.returncode})
        save(pending=result.returncode == 0)
        if result.returncode:
            raise ManagedError(f"Isolated Flatpak transaction failed ({result.returncode}). "
                               f"Partial work retained at {directory}; keep its journal for recovery.")
        completed[-1]["observed_refs"] = probe(directory, "list", "--user", "--columns=ref,origin")
        save()
        emit("step_completed", "Isolated transaction finished.", step="resolve")

    with locked(runtime):
        if directory.exists():
            raise ManagedError("Isolated slot appeared after review; start a new setup review.")
        if cancel.exists():
            raise InterruptedError("Cancelled before isolated engine preparation.")
        save(["create-isolated-slot", str(directory)])
        directory.mkdir(parents=True, mode=0o700)
        save()
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
            safe(environment(directory)[key]).mkdir(parents=True, exist_ok=True, mode=0o700)
        commands = approved["dependency_commands"]
        transaction(commands[0])
        declared = app_metadata(probe(directory, "remote-info", "--user",
                                "--commit=" + BUILDS[runtime]["commit"], "--show-metadata",
                                "flathub", BUILDS[runtime]["app_id"]), runtime)
        for argv in commands[1:3]:
            transaction(argv)
        transaction([*commands[3][:-1], declared])
        transaction(commands[4])
        if cancel.exists():
            raise InterruptedError("Cancelled after transaction; isolated work is retained.")
        observed = inspect(runtime)
        destination = safe(str(helper()))
        save(["publish-retained-helper", str(destination)])
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        content = Path(__file__).read_bytes()
        if destination.exists() and destination.read_bytes() != content:
            raise ManagedError("Retained helper collision; preserved without overwrite.")
        if not destination.exists():
            write(destination, content)
        save(["publish-verified-descriptor", str(directory / "slot.json")])
        write(directory / "slot.json", packed(observed))
        save()
        return facts(runtime, context["package_id"])


def emit(kind, message, **fields):
    print(json.dumps({"event_version": 1, "type": kind, "message": message, **fields}), flush=True)


def run(context):
    from jobs import _write_durable
    import engines
    import dependencies
    import uzdoom
    completed, proposed, observed = [], None, None
    phase = context["phase"]
    outcome, code, message = "succeeded", 0, "Tested isolated engine prepared; review game installation next."
    try:
        runtime = context["runtime"]
        if runtime not in BUILDS or phase not in ("preflight", "apply"):
            raise ManagedError("Unsupported managed engine preparation context.")
        adapter = dependencies if runtime == "flycast" else uzdoom
        current = adapter.detect()
        if engines.identity(current) != context["existing"]:
            raise ManagedError("Existing engine changed since setup; start a new review.")
        if BUILDS[runtime]["app_id"] in dependencies.probe("ps", "--columns=application").splitlines():
            raise ManagedError("Close the engine before preparing an isolated copy.")
        if Path(context["cancel_file"]).exists():
            raise InterruptedError("Cancelled before engine preparation.")
        proposed = plan(runtime, context["package_id"], context["existing"])
        if phase == "apply":
            raw = Path(context["approved_plan_file"]).read_bytes()
            envelope = json.loads(raw)
            if (digest(raw) != context["approved_plan_digest"] or envelope.get("job_id") != context["job_id"]
                    or envelope.get("phase") != "preflight" or envelope.get("outcome") != "succeeded"
                    or envelope.get("operation") != "prepare-dependency" or envelope.get("plan") != proposed):
                raise ManagedError("Isolated engine approval changed; obtain a new review.")
            observed = provision(context, proposed, completed)
    except InterruptedError as exc:
        outcome, code, message = "cancelled", 130, str(exc)
    except (ManagedError, OSError, KeyError, ValueError, dependencies.DependencyError) as exc:
        outcome, code, message = "failed", 40, str(exc)
        print(message, file=sys.stderr)
    result = {"result_version": 1, "job_id": context["job_id"], "operation": "prepare-dependency",
              "phase": phase, "outcome": outcome, "message": message,
              "dependencies": {context["runtime"]: observed}, "completed_transactions": completed}
    if proposed is not None:
        result["plan"] = proposed
    _write_durable(Path(context["result_file"]), packed(result))
    emit("result", message, outcome=outcome)
    return code


def main():
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--context":
            return run(json.loads(Path(sys.argv[2]).read_text()))
        if len(sys.argv) == 3 and sys.argv[1] == "--inspect":
            validate_binding(json.loads(sys.argv[2]))
            return 0
        if len(sys.argv) >= 5 and sys.argv[1] == "--launch" and sys.argv[3] == "--media":
            args = sys.argv[5:]
            if args[:1] == ["--"]:
                args = args[1:]
            return launch(json.loads(sys.argv[2]), sys.argv[4], args)
        raise ManagedError("Usage: managed_flatpak.py --context FILE | --inspect BINDING | "
                           "--launch BINDING --media DIRECTORY -- GAME_ARGS")
    except (ManagedError, OSError, ValueError, KeyError) as exc:
        print(f"Isolated engine: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
