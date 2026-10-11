#!/usr/bin/env python3
"""Opt-in real X11 engine/state checks against already prepared experiment slots."""
import argparse
import configparser
import ctypes
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import time


PROTOTYPE = runpy.run_path(str(Path(__file__).with_name("managed-flatpak-prototype.py")))


def fingerprint(root):
    result = {}
    if not root.exists():
        return result
    for directory, _, names in os.walk(root, followlinks=False):
        for name in names:
            path = Path(directory) / name
            relative = str(path.relative_to(root))
            if path.is_symlink():
                result[relative] = {"symlink": os.readlink(path)}
            elif path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                result[relative] = digest.hexdigest()
    return result


def normal_snapshot():
    return {
        "flatpak": subprocess.check_output(
            ["flatpak", "list", "--columns=ref,active,origin,installation"], text=True),
        "remotes": {scope: subprocess.check_output(
            ["flatpak", "remotes", "--" + scope, "--columns=name,url,options"], text=True)
                    for scope in ("user", "system")},
        "profiles": {build["app"]: fingerprint(Path.home() / ".var/app" / build["app"])
                     for build in PROTOTYPE["BUILDS"].values()},
    }


def windows():
    return {line.split()[0]: line for line in subprocess.check_output(
        ["wmctrl", "-l"], text=True).splitlines()}


class Keyboard:
    def __init__(self):
        self.x = ctypes.CDLL("libX11.so.6")
        self.xt = ctypes.CDLL("libXtst.so.6")
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.x.XStringToKeysym.argtypes = [ctypes.c_char_p]
        self.x.XStringToKeysym.restype = ctypes.c_ulong
        self.x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.x.XKeysymToKeycode.restype = ctypes.c_uint
        self.x.XFlush.argtypes = [ctypes.c_void_p]
        self.x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.xt.XTestFakeKeyEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self.display = self.x.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError("An X11 display is required for the real state checks.")

    def key(self, name):
        code = self.x.XKeysymToKeycode(self.display, self.x.XStringToKeysym(name.encode()))
        if not code:
            raise RuntimeError(f"Unavailable test key: {name}")
        self.xt.XTestFakeKeyEvent(self.display, code, 1, 0)
        self.xt.XTestFakeKeyEvent(self.display, code, 0, 0)
        self.x.XFlush(self.display)
        time.sleep(.05)

    def send(self, text):
        for character in text:
            self.key("space" if character == " " else character)
        self.key("Return")
        time.sleep(1)

    def close(self):
        self.x.XCloseDisplay(self.display)


def engine_run(root, engine, profile, media, args, label, console_commands=()):
    before = windows()
    argv, env = PROTOTYPE["launch"](root, engine, profile, media, args)
    path = root / (label + ".log")
    expected_class = "flycast" if engine == "flycast" else "org.zdoom.UZDoom"
    with path.open("w") as log:
        process = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            time.sleep(18)
            after = windows()
            new = [window for window in after if window not in before and
                   expected_class in subprocess.check_output(
                       ["xprop", "-id", window, "WM_CLASS"], text=True)]
            if len(new) != 1 or process.poll() is not None:
                raise RuntimeError(f"{label}: expected one live engine window, see {path}")
            if console_commands:
                subprocess.run(["wmctrl", "-ia", new[0]], check=True)
                time.sleep(1)
                keyboard = Keyboard()
                try:
                    keyboard.key("grave")
                    time.sleep(1)
                    for text in console_commands:
                        keyboard.send(text)
                finally:
                    keyboard.close()
            else:
                subprocess.run(["wmctrl", "-ic", new[0]], check=True)
            if process.wait(timeout=20) != 0:
                raise RuntimeError(f"{label}: nonzero engine exit, see {path}")
        finally:
            if process.poll() is None:
                for window in windows():
                    if window not in before and expected_class in subprocess.check_output(
                            ["xprop", "-id", window, "WM_CLASS"], text=True):
                        subprocess.run(["wmctrl", "-ic", window], check=True)
                time.sleep(2)
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    return path.read_text()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sandbox_checks(root):
    media = PROTOTYPE["safe_directory"](root / "probe-media")
    result = {}
    script = (
        'set -eu; for p in "$HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" '
        '"$XDG_CACHE_HOME" "$XDG_STATE_HOME"; do '
        'test -f "$p/sentinel" || printf "%s" "$1" > "$p/sentinel"; '
        'test "$(cat "$p/sentinel")" = "$1"; done; '
        'test ! -e "$2/home/sentinel"; '
        'if touch "$3/forbidden" 2>/dev/null; then exit 42; fi'
    )
    for engine in PROTOTYPE["BUILDS"]:
        for profile in (engine + "-a", engine + "-b", engine + "-a"):
            other = engine + ("-b" if profile.endswith("-a") else "-a")
            argv, env = PROTOTYPE["launch"](
                root, engine, profile, media,
                ["-c", script, "probe", profile, str(root / "profiles" / other), str(media)],
                "/bin/sh")
            subprocess.run(argv, env=env, check=True, timeout=30)
        argv, env = PROTOTYPE["launch"](root, engine, engine + "-metadata-probe",
                                       media, ["/.flatpak-info"], "/usr/bin/cat")
        parsed = configparser.ConfigParser(interpolation=None)
        parsed.read_string(subprocess.check_output(argv, env=env, text=True, timeout=30))
        instance = dict(parsed["Instance"])
        prefix = str(PROTOTYPE["slot_path"](root, engine) / "flatpak") + "/"
        for field in ("app-path", "runtime-path"):
            require(instance[field].startswith(prefix), f"Foreign sandbox deployment: {field}")
        result[engine] = {field: instance[field] for field in ("app-path", "runtime-path")}
    return result


def check(root, flycast_media, doom_media, package_repo):
    baseline = json.loads((root / "normal-before.json").read_text())
    require(normal_snapshot() == baseline, "Normal installs/profiles changed before state tests.")
    media_before = {str(media): fingerprint(media) for media in (flycast_media, doom_media)}
    checks = {"sandbox_state_and_deployments": sandbox_checks(root)}
    flags = runpy.run_path(str(package_repo / "the-house-of-the-dead-2/package/lifecycle.py"))["FLAGS"]
    flags = [argument.replace("window:fullscreen=yes", "window:fullscreen=no") for argument in flags]
    flycast_args = [*flags, str(flycast_media / "House of the Dead 2, The (USA).cue")]
    a = root / "profiles/flycast-a"
    for profile in ("flycast-a", "flycast-b", "flycast-a"):
        other = root / "profiles" / ("flycast-b" if profile == "flycast-a" else "flycast-a")
        other_before = fingerprint(other)
        label = "flycast-" + profile + ("-relaunch" if checks.get(profile) else "-first")
        text = engine_run(root, "flycast", profile, flycast_media, flycast_args, label)
        require("OpenGL version" in text and "REIOS: Booting up" in text,
                f"{label}: graphics/media boot missing.")
        require("Failed to create VMU" not in text and "Cannot save" not in text,
                f"{label}: VMU/state write failed.")
        require(fingerprint(other) == other_before, f"{label}: other profile changed.")
        require(any((root / "profiles" / profile / "data/flycast").glob("*vmu*")),
                f"{label}: no VMU created under profile.")
        if profile == "flycast-a" and checks.get(profile):
            current = {str(p.relative_to(a)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in a.rglob("*vmu*") if p.is_file()}
            require(current == checks["flycast_a_vmus"], "VMU bytes changed across idle relaunch.")
        checks[profile] = True
        if profile == "flycast-a":
            checks["flycast_a_vmus"] = {
                str(p.relative_to(a)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in a.rglob("*vmu*") if p.is_file()}
    doom_args = ["-iwad", str(doom_media / "DOOM2.WAD"), "-window", "-width", "800",
                 "-height", "600", "+set", "vid_fullscreen", "false"]
    for profile, name in (("uzdoom-a", "isolationa"), ("uzdoom-b", "isolationb")):
        other = root / "profiles" / ("uzdoom-b" if profile == "uzdoom-a" else "uzdoom-a")
        other_before = fingerprint(other)
        text = engine_run(root, "uzdoom", profile, doom_media, [*doom_args, "-warp", "1"],
                          profile + "-save", ["save " + name, "quit"])
        require("Game saved." in text and "MAP01 - Entryway" in text, "Real save creation failed.")
        require(fingerprint(other) == other_before, "Other UZDoom profile changed.")
        saves = list((root / "profiles" / profile).rglob(name + ".zds"))
        require(len(saves) == 1, "Save is not confined to the expected profile.")
        checks[profile + "_save"] = str(saves[0].relative_to(root))
    save = root / checks["uzdoom-a_save"]
    save_before = hashlib.sha256(save.read_bytes()).hexdigest()
    other_before = fingerprint(root / "profiles/uzdoom-b")
    text = engine_run(root, "uzdoom", "uzdoom-a", doom_media,
                      [*doom_args, "-loadgame", save.stem], "uzdoom-a-load", ["quit"])
    require("MAP01 - Entryway" in text, "Default-profile save discovery/reload failed.")
    require(hashlib.sha256(save.read_bytes()).hexdigest() == save_before, "Reload changed save bytes.")
    require(fingerprint(root / "profiles/uzdoom-b") == other_before, "Reload altered profile B.")
    checks["uzdoom_save_reloaded"] = True
    for media in (flycast_media, doom_media):
        require(fingerprint(media) == media_before[str(media)], f"Original media changed: {media}")
    require(normal_snapshot() == baseline, "Normal installations or profiles changed.")
    graph = {}
    for engine in PROTOTYPE["BUILDS"]:
        slot = PROTOTYPE["slot_path"](root, engine)
        observed = PROTOTYPE["inspect"](slot, engine)
        require(observed == json.loads((slot / "slot.json").read_text()), "Slot identity drifted.")
        graph[engine] = {line.split("\t")[0]: PROTOTYPE["command"](
            slot, "info", "--user", "--show-commit", line.split("\t")[0])
                        for line in observed["installed_refs"]}
    result = {
        "status": "passed", "checks": checks, "resolved_commits": graph,
        "normal_installs_remotes_profiles_unchanged": True, "original_media_unchanged": True,
        "limits": "Windowed X11 development checks. HOD2 boot and idle VMU persistence, not "
                  "Start/aim/fire/reload or in-game save. UZDoom save/load uses vanilla Doom II, "
                  "not Brutal Doom gameplay. No debug-PC or production helper/package acceptance.",
    }
    PROTOTYPE["write_json"](root / "engine-state-checks.json", result)
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--record-baseline", action="store_true",
                        help="Record normal state BEFORE preparing either experiment slot")
    parser.add_argument("--flycast-media", type=Path)
    parser.add_argument("--doom-media", type=Path)
    parser.add_argument("--package-repo", type=Path,
                        default=Path(__file__).resolve().parents[2] / "momentum-packages")
    args = parser.parse_args()
    args.root = PROTOTYPE["safe_directory"](args.root)
    if args.record_baseline:
        destination = args.root / "normal-before.json"
        if destination.exists() or (args.root / "software").exists():
            parser.error("Baseline must be recorded once, before experiment provisioning.")
        PROTOTYPE["write_json"](destination, normal_snapshot())
        print(f"Normal baseline recorded: {destination}")
        return
    if args.flycast_media is None or args.doom_media is None:
        parser.error("--flycast-media and --doom-media are required for state tests")
    check(args.root, args.flycast_media, args.doom_media, args.package_repo)


if __name__ == "__main__":
    main()
