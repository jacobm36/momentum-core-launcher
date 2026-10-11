#!/usr/bin/env python3
"""Opt-in fallback experiment; not imported or enabled by the launcher."""
import argparse
import configparser
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys


BUILDS = {
    "flycast": {
        "app": "org.flycast.Flycast", "command": "flycast",
        "commit": "86ec4d845a66ff07cdba8e003d8549e93cd7a814b519766e1f744e530c5d3e5b",
    },
    "uzdoom": {
        "app": "org.zdoom.UZDoom", "command": "uzdoom",
        "commit": "d7b8ce76e5480a28d1e07400093a20d47f56c201fd974b0a5dbfa3b26bbd587e",
    },
}
REMOTE = "https://dl.flathub.org/repo/"
DESCRIPTOR = "https://flathub.org/repo/flathub.flatpakrepo"


def safe_directory(path):
    path = Path(path).absolute()
    for parent in (*reversed(path.parents), path):
        if parent.is_symlink():
            raise ValueError(f"Symlink is not allowed: {parent}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_uid != os.getuid():
        raise ValueError(f"Directory belongs to another user: {path}")
    return path


def slot_path(root, engine):
    build = BUILDS[engine]
    return Path(root) / "software" / build["app"] / "x86_64" / "stable" / build["commit"]


def environment(slot):
    env = os.environ.copy()
    env["FLATPAK_USER_DIR"] = str(slot / "flatpak")
    env["HOME"] = str(slot / "bootstrap" / "home")
    for variable, name in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                           ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state")):
        env[variable] = str(slot / "bootstrap" / name)
    return env


def command(slot, *args):
    result = subprocess.run(["flatpak", *args], env=environment(slot),
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with (slot / "transactions.log").open("a") as log:
        log.write(json.dumps(["flatpak", *args]) + "\n" + result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"flatpak {args[0]} failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


def metadata(text, build):
    parsed = configparser.ConfigParser(interpolation=None)
    parsed.read_string(text)
    app = parsed["Application"]
    runtime = app["runtime"]
    if (app["name"] != build["app"] or app["command"] != build["command"]
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/x86_64/[A-Za-z0-9_.-]+", runtime)):
        raise ValueError("Unexpected app command or runtime in exact-build metadata.")
    return runtime


def inspect(slot, engine):
    build = BUILDS[engine]
    if command(slot, "info", "--user", "--show-commit", build["app"]) != build["commit"]:
        raise ValueError("App commit differs from the approved prototype build.")
    if command(slot, "info", "--user", "--show-ref", build["app"]) != (
            f"app/{build['app']}/x86_64/stable"):
        raise ValueError("Unexpected app ref.")
    if command(slot, "info", "--user", "--show-origin", build["app"]) != "flathub":
        raise ValueError("Unexpected app origin.")
    runtime = metadata(command(slot, "info", "--user", "--show-metadata", build["app"]), build)
    if command(slot, "info", "--user", "--show-runtime", build["app"]) != runtime:
        raise ValueError("Runtime metadata disagrees.")
    refs = command(slot, "list", "--user", "--columns=ref,active,origin").splitlines()
    if not any(row.split("\t")[0] == runtime for row in refs):
        raise ValueError("Required runtime is absent from this independent installation.")
    if command(slot, "info", "--user", "--show-ref", runtime) != "runtime/" + runtime:
        raise ValueError("Runtime deployment is incomplete.")
    if build["app"] not in command(slot, "mask", "--user").splitlines():
        raise ValueError("Managed app is not masked against updates.")
    remotes = command(slot, "remotes", "--user", "--columns=name,url,options").splitlines()
    if len(remotes) != 1:
        raise ValueError("Unexpected managed remotes.")
    fields = remotes[0].split("\t")
    if fields[:2] != ["flathub", REMOTE] or "no-gpg-verify" in fields[-1]:
        raise ValueError("Managed Flathub remote is not trusted.")
    return {"engine": engine, **build, "runtime": runtime, "installed_refs": refs,
            "installation": str(slot / "flatpak"), "contract": "prototype-1"}


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def prepare(root, engine):
    """Fresh final-path provisioning only; failures retained, never auto-recovered."""
    slot = slot_path(root, engine)
    safe_directory(slot)
    with (slot / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        descriptor = slot / "slot.json"
        if descriptor.exists():
            observed = inspect(slot, engine)
            if json.loads(descriptor.read_text()) != observed:
                raise ValueError("Slot changed since verification; inspect it manually.")
            return observed
        if any(p.name != "lock" for p in slot.iterdir()):
            raise ValueError(f"Incomplete/unknown slot retained; manual inspection required: {slot}")
        write_json(slot / "journal.json", {"state": "preparing", "build": BUILDS[engine]})
        env = environment(slot)
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
            safe_directory(env[key])
        build = BUILDS[engine]
        command(slot, "remote-add", "--user", "flathub", DESCRIPTOR)
        remote_metadata = command(slot, "remote-info", "--user", "--commit=" + build["commit"],
                                  "--show-metadata", "flathub", build["app"])
        runtime = metadata(remote_metadata, build)
        command(slot, "install", "--user", "--noninteractive", "-y", "flathub", build["app"])
        command(slot, "update", "--user", "--noninteractive", "-y",
                "--commit=" + build["commit"], build["app"])
        # A historical app can need a different runtime from the initially installed app.
        command(slot, "install", "--user", "--noninteractive", "-y", "--or-update",
                "flathub", runtime)
        command(slot, "mask", "--user", build["app"])
        observed = inspect(slot, engine)
        write_json(slot / "journal-complete.json", {"state": "metadata-verified", **observed})
        write_json(descriptor, observed)
        return observed


def launch(root, engine, profile_id, media, args, executable=None):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", profile_id):
        raise ValueError("Profile identity must be a simple stable identifier.")
    slot = slot_path(root, engine)
    if not slot.is_dir():
        raise ValueError("Prepare the experiment slot before launching it.")
    safe_directory(slot)
    if (slot / "slot.json").is_symlink():
        raise ValueError("Slot descriptor must not be a symlink.")
    if json.loads((slot / "slot.json").read_text()) != inspect(slot, engine):
        raise ValueError("Slot descriptor changed.")
    profile = safe_directory(Path(root) / "profiles" / profile_id)
    paths = {name: safe_directory(profile / name)
             for name in ("home", "config", "data", "cache", "state")}
    # Flycast does not create these parents consistently on its first media boot.
    if engine == "flycast":
        for name in ("data", "config"):
            safe_directory(paths[name] / "flycast")
    media = Path(media).absolute()
    if not media.is_dir() or media.resolve() != media:
        raise ValueError("Media must be an existing canonical directory.")
    if media == profile or media in profile.parents or profile in media.parents:
        raise ValueError("Writable profile and read-only media must not overlap.")
    argv = ["flatpak", "run", "--user", "--die-with-parent", "--nofilesystem=host:reset",
            "--filesystem=" + str(profile), "--filesystem=" + str(media) + ":ro",
            "--command=/usr/bin/env", BUILDS[engine]["app"],
            "HOME=" + str(paths["home"]), "XDG_CONFIG_HOME=" + str(paths["config"]),
            "XDG_DATA_HOME=" + str(paths["data"]), "XDG_CACHE_HOME=" + str(paths["cache"]),
            "XDG_STATE_HOME=" + str(paths["state"]),
            executable or BUILDS[engine]["command"], *args]
    return argv, environment(slot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True,
                        help="Dedicated experiment root, not your normal engine/game folders")
    parser.add_argument("--engine", choices=BUILDS, required=True)
    parser.add_argument("--prepare", action="store_true", help="Approve isolated engine downloads")
    parser.add_argument("--profile", default="probe-a")
    parser.add_argument("--media", type=Path)
    parser.add_argument("--probe-command", help="Run a sandbox diagnostic instead of the engine")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    root = safe_directory(options.root)
    if options.prepare:
        print(json.dumps(prepare(root, options.engine), indent=2), flush=True)
        return 0
    if options.media is None:
        parser.error("--media is required for launch")
    args = options.args[1:] if options.args[:1] == ["--"] else options.args
    argv, env = launch(root, options.engine, options.profile, options.media, args,
                       options.probe_command)
    return subprocess.call(argv, env=env)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError, configparser.Error) as exc:
        print(f"PROTOTYPE FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
