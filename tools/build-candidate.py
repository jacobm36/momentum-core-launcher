#!/usr/bin/env python3
"""Build a complete local acceptance bundle without personal runtime data."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import packages

CANDIDATES = {
    "star-wars-trilogy-arcade": "0.2.1",
    "l-a-machineguns": "0.2.2",
    "quake-slave-zero-x": "0.2.1",
    "the-house-of-the-dead-2": "0.2.0",
}
NEW_FILES = (
    "start-candidate.sh", "window_handoff.py", "tests/test_window_handoff.py",
    "tests/test_priority_candidates.py", "tools/build-candidate.py",
)
PRIVATE_ROOTS = {"jobs", "packages", "media", "backups", ".git", "__pycache__"}
PRIVATE_FILES = {"games.json", "stats.json"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--package-repo", type=Path, default=HERE.parent / "momentum-packages")
    args = parser.parse_args()
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
    with tempfile.TemporaryDirectory(prefix="mcl-candidate-build-") as temporary:
        root = Path(temporary)
        try:
            for game_id, version in CANDIDATES.items():
                archive = args.package_repo / "dist" / f"{game_id}-{version}.zip"
                info = packages.import_package(archive, root)
                intake = root / "packages" / game_id / version / "intake.json"
                info.pop("status", None)
                info["source"] = f"bundled:{archive.name}"
                intake.write_text(json.dumps(info, indent=2) + "\n")
                print(f"Bundling {game_id} {version}: {info['digest']}")
            with zipfile.ZipFile(args.output, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
                for path in files:
                    bundle.write(HERE / path, f"{prefix}/{path.as_posix()}")
                for path in sorted((root / "packages").rglob("*")):
                    if path.is_file() and path.name != ".lock":
                        bundle.write(path, f"{prefix}/{path.relative_to(root).as_posix()}")
            print(f"SHA256 {hashlib.sha256(args.output.read_bytes()).hexdigest()}")
            print(args.output.resolve())
        finally:
            packages._rmtree(root / "packages")


if __name__ == "__main__":
    main()
