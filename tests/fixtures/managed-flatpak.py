#!/usr/bin/env python3
"""Synthetic Flatpak for managed runner tests; normal engine writes are forbidden."""
import json
import os
from pathlib import Path
import sys

runtime = json.loads((Path.home() / "mock-engine.json").read_text())["runtime"] if (
    not os.environ.get("FLATPAK_USER_DIR")) else (
    "flycast" if "org.flycast.Flycast" in os.environ["FLATPAK_USER_DIR"] else "uzdoom")
app = "org.flycast.Flycast" if runtime == "flycast" else "org.zdoom.UZDoom"
version = "v2.7" if runtime == "flycast" else "5.0.1"
command = "flycast" if runtime == "flycast" else "uzdoom"
args = sys.argv[1:]
directory = Path(os.environ["FLATPAK_USER_DIR"]) if os.environ.get("FLATPAK_USER_DIR") else None
state = json.loads((directory / "mock-state.json").read_text()) if directory and (
    directory / "mock-state.json").exists() else {"commit": None, "runtime": False, "mask": False}
declared = "org.freedesktop.Platform/x86_64/25.08"
metadata = f"[Application]\nname={app}\ncommand={command}\nruntime={declared}"


def save():
    assert directory is not None, "Normal installations must never be mutated"
    directory.mkdir(exist_ok=True)
    (directory / "mock-state.json").write_text(json.dumps(state))


if args[0] == "ps":
    pass
elif args[0] == "remotes":
    print("flathub\thttps://dl.flathub.org/repo/" + ("\t" if directory else ""))
elif args[0] == "list":
    if directory:
        if state["commit"]:
            print(f"{app}/x86_64/stable\tflathub")
        if state["runtime"]:
            print(declared + "\tflathub")
    elif "--user" in args:
        print(app if "--columns=application" in args else app + "\tx86_64\tstable\tflathub")
elif args[0] == "info":
    is_runtime = args[-1] == declared
    commit = "1" * 64 if is_runtime else (state["commit"] if directory else "a" * 64)
    if directory and not commit:
        sys.exit(1)
    if "--show-ref" in args:
        print("runtime/" + declared if is_runtime else f"app/{app}/x86_64/stable")
    elif "--show-commit" in args:
        print(commit)
    elif "--show-runtime" in args:
        print(declared)
    elif "--show-origin" in args:
        print("flathub")
    elif "--show-metadata" in args:
        print(metadata)
    else:
        print(f"Ref: app/{app}/x86_64/stable\nVersion: {version}\nCommit: {commit}\n"
              "Arch: x86_64\nBranch: stable\nOrigin: flathub")
elif args[0] == "remote-info":
    assert directory is not None and any(a.startswith("--commit=") for a in args)
    print(metadata)
elif args[0] == "remote-add":
    assert directory is not None
    save()
elif args[0] == "install":
    assert directory is not None and "--user" in args
    if app in args:
        state["commit"] = "b" * 64
    else:
        assert declared in args
        state["runtime"] = True
    save()
elif args[0] == "update":
    assert directory is not None and "--user" in args and app in args
    state["commit"] = next(a.partition("=")[2] for a in args if a.startswith("--commit="))
    save()
elif args[0] == "mask":
    assert directory is not None
    if app in args:
        state["mask"] = True
        save()
    elif state["mask"]:
        print(app)
else:
    sys.exit("Unexpected operation: " + repr(args))
