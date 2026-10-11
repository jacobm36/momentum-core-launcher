#!/usr/bin/env python3
"""Build a complete local acceptance bundle without personal runtime data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import packages
import compatibility

CANDIDATES = {
    "star-wars-trilogy-arcade": "0.2.1",
    "l-a-machineguns": "0.2.2",
    "quake-slave-zero-x": "0.3.0",
    "the-house-of-the-dead-2": "0.3.0",
}
PRIVATE_CANDIDATES = {**CANDIDATES, "brutal-doom": "0.3.0", "marvel-infinity-war": "0.2.0"}
NEW_FILES = (
    "start-candidate.sh", "window_handoff.py", "tests/test_window_handoff.py",
    "tests/test_priority_candidates.py", "tools/build-candidate.py",
    "compatibility.py", "tools/check-release.py", "tests/test_release_check.py",
    "launcher_probe.py", "tests/test_launcher_probe.py",
    "tests/test_build_candidate.py",
    "enyo.py", "tests/test_enyo.py",
    "engines.py", "tests/test_engines.py",
    "managed_flatpak.py", "tests/test_managed_flatpak.py",
    "docs/shared-engine-fallback.md", "docs/shared-engine-fallback-evidence.json",
    "start-isolated-test.sh",
    "tests/test_managed_installs.py", "tests/fixtures/managed-flatpak.py",
    "tests/test_managed_real.py",
    "tools/managed-flatpak-prototype.py", "tools/check-managed-flatpak-prototype.py",
    "tests/test_managed_flatpak_prototype.py",
    "game_import.py", "tests/test_game_import.py",
    "openbor.py", "tests/test_openbor.py", "tests/test_openbor_installs.py",
    "docs/openbor-runtime-index.json", "docs/openbor-installer-evidence.json",
    "docs/openbor.md",
    "tests/fixtures/library-media.html",
)
PRIVATE_ROOTS = {"jobs", "packages", "media", "backups", "logs", ".git", "__pycache__"}
PRIVATE_FILES = {"games.json", "stats.json", "playstats.json"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--package-repo", type=Path, default=HERE.parent / "momentum-packages")
    parser.add_argument("--package", choices=sorted(PRIVATE_CANDIDATES), action="append",
                        help="Include only these local candidates; repeat for each game. Never publishes.")
    args = parser.parse_args(argv)
    selected = args.package or list(CANDIDATES)
    if len(selected) != len(set(selected)):
        parser.error("Do not select the same package twice.")
    if args.output.exists():
        parser.error("Output already exists; use a new filename instead of overwriting it.")
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", "."], cwd=HERE)
    files = {Path(name.decode()) for name in tracked.split(b"\0") if name}
    files.update(Path(name) for name in NEW_FILES)
    files = sorted(p for p in files if p.parts[0] not in PRIVATE_ROOTS and p.name not in PRIVATE_FILES)
    for path in files:
        source = HERE / path
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f"Expected regular launcher file: {path}")
    prefix = args.output.stem.lower()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE, text=True).strip()
    launcher_files = {path.as_posix(): hashlib.sha256((HERE / path).read_bytes()).hexdigest()
                      for path in files}
    with tempfile.TemporaryDirectory(prefix="mcl-candidate-build-") as temporary:
        root = Path(temporary)
        delivery = []
        try:
            for game_id in selected:
                version = PRIVATE_CANDIDATES[game_id]
                archive = args.package_repo / "dist" / f"{game_id}-{version}.zip"
                info = packages.import_package(archive, root)
                if (info["id"], info["version"]) != (game_id, version):
                    raise ValueError(f"Archive identity differs from selected {game_id} {version}")
                evidence = compatibility.find_record(HERE, game_id, version, info["digest"])
                if not evidence or evidence.get("installer_validated") is not True:
                    raise ValueError(f"No exact installer evidence for {game_id} {version}")
                delivery.append({
                    "id": game_id, "version": version, "digest": info["digest"],
                    "zip_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "zip_size": archive.stat().st_size, "software": evidence["software"],
                    "supported_software_builds": compatibility.software_builds(evidence),
                    "gameplay": "manual-acceptance-required",
                })
                intake = root / "packages" / game_id / version / "intake.json"
                info.pop("status", None)
                info["source"] = f"bundled:{archive.name}"
                intake.write_text(json.dumps(info, indent=2) + "\n")
                print(f"Bundling {game_id} {version}: {info['digest']}")
            guide = (
                "Momentum private acceptance candidate\n\n"
                "Not a public release or gameplay certification. Do not redistribute this bundle.\n"
                "Close the old Momentum launcher/server. Extract into a NEW folder, then run\n"
                "bash start-candidate.sh from the extracted folder. Do not overwrite old folders\n"
                "or delete journals. No desktop shortcuts change until you run bash install.sh.\n\n"
                "Add game offers Import installed games, Add a game manually, and Browse\n"
                "the package store. Import reviews user .desktop game shortcuts, lets you\n"
                "select entries, and preserves existing library edits. It does not enumerate\n"
                "all Steam libraries, download games, or launch discovered commands.\n"
                "Use normal start-candidate.sh to find this user's installed game shortcuts.\n"
                "Isolated test mode sees only the separate acceptance HOME's shortcuts.\n\n"
                "Use Add game > Browse the package store > Local packages for bundled candidates. The online Store\n"
                "lists the five approved public games. Supply your own\n"
                "original media; source and destination must not overlap. Missing host\n"
                "prerequisites have manual system commands; no automatic administrator access.\n"
                "Review software preparation separately from the game installation plan.\n\n"
                "Isolated-engine acceptance: close the old launcher first, then run\n"
                "bash start-isolated-test.sh to exercise the isolated path without touching\n"
                "existing installations/receipts. It uses a separate acceptance HOME under\n"
                "your real ~/.local/share/momentum-core/isolated-acceptance-home-v1.\n"
                "Supply original media by absolute path; leave the default test games root.\n"
                "Use this same script for relaunch. Do not install desktop shortcuts in test mode.\n"
                "Normal start-candidate.sh reuses supported existing copies. No receipts are migrated.\n"
                "Allow at least 6 GiB for Flycast or 4 GiB for UZDoom, plus game copies.\n"
                "Check the saved plan's slot and per-game profile before approving preparation.\n\n"
                "After each install, confirm title/mod, display, aim/fire, movement or Start,\n"
                "audio, exit, save where supported, and relaunch/settings persistence.\n"
                "Existing engines, settings and saves are preserved, not replaced by laptop state.\n"
                "If blocked, preserve the job and record its error; do not bypass evidence or\n"
                "delete jobs. Startup errors: ~/.cache/momentum-core-launcher/server.log.\n\n"
                "Included candidates:\n"
                + "".join(f"- {p['id']} {p['version']}\n" for p in delivery)
                + "\nMarvel Infinity War: use bash start-isolated-test.sh on the debug PC.\n"
                "Use Local packages > Marvel Infinity War. Leave Download from ZVitor\n"
                "checked and the offline source blank for the pinned 503 MiB author download.\n"
                "Allow at least 2 GiB free temporary/destination space, plus this bundle.\n"
                "Approve bundled OpenBOR preparation first, then the game download/install.\n"
                "The engine is supplied in this package: no FUSE or engine network download.\n"
                "Connect your controller before launching. Confirm fullscreen, CRT scanlines\n"
                "TV, input/audio, tutorial-to-next-area progression, exit and relaunch.\n"
                "Different controllers may need Control Options > Player 1 remapping:\n"
                "press Enter on an action, release Enter, then press the controller button.\n"
                "Settings are seeded only when absent; no personal saves are bundled.\n"
                "Verify, repeat install, repair, and game-only removal/reinstall should\n"
                "preserve settings/progress and the engine. Edited managed content blocks\n"
                "removal for explicit reconciliation rather than silently deleting it.\n"
                "Do not publish this sixth-title private candidate.\n"
                "\nEnyo: supply Quake id1/pak0.pak and pak1.pak. Mod files are not bundled;\n"
                "reuse verified Enyo files or approve a direct publisher download separately.\n"
                "Fullscreen is requested on\n"
                "startup without copying display settings; pass -window for windowed startup.\n"
                "HOD2: supply USA CUE plus matching BIN tracks together. Confirm Flycast\n"
                "Start/trigger mappings; dedicated right-click reload is not yet verified.\n"
                "Brutal Doom, if included: supply DOOM2.WAD. Canonical three-mod order is\n"
                "bundled for private testing. Component redistribution rights remain unresolved;\n"
                "public publication is blocked. Shared UZDoom settings remain untouched.\n"
            )
            if selected == ["marvel-infinity-war"]:
                guide = ("Momentum private OpenBOR debug-PC candidate\n\n"
                         "Extract into a NEW folder. Do not overwrite your existing launcher.\n"
                         "Run bash start-isolated-test.sh from that extracted folder.\n"
                         "Only Marvel Infinity War 0.2.0 is included; nothing is published.\n\n"
                         + (HERE / "docs/openbor.md").read_text())
            fd, temporary_zip = tempfile.mkstemp(prefix=".momentum-candidate-", suffix=".zip",
                                                 dir=args.output.parent)
            os.close(fd)
            staged = Path(temporary_zip)
            try:
                with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                    for path in files:
                        bundle.write(HERE / path, f"{prefix}/{path.as_posix()}")
                    for path in sorted((root / "packages").rglob("*")):
                        if path.is_file() and path.name != ".lock":
                            bundle.write(path, f"{prefix}/{path.relative_to(root).as_posix()}")
                    bundle.writestr(f"{prefix}/ACCEPTANCE-GUIDE.txt", guide)
                    bundle.writestr(f"{prefix}/candidate-build.json",
                                    json.dumps({"scope": "private-acceptance-only",
                                                "launcher_base_revision": revision,
                                                "launcher_file_sha256": launcher_files,
                                                "packages": delivery}, indent=2) + "\n")
                os.link(staged, args.output)
            finally:
                staged.unlink(missing_ok=True)
            print(f"SHA256 {hashlib.sha256(args.output.read_bytes()).hexdigest()}")
            print(args.output.resolve())
        finally:
            packages._rmtree(root / "packages")


if __name__ == "__main__":
    main()
