#!/usr/bin/env python3
"""Read-only release checks. Exit 0 means PASS; exit 1 means FAIL; never publishes."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import catalog
import compatibility
import packages


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check(archive, package_repo, distribution, launcher, public=False):
    info = packages.check(archive)
    identity = f"{info['id']}-{info['version']}"
    with tempfile.TemporaryDirectory(prefix="momentum-release-check-") as temporary:
        root = Path(temporary)
        try:
            packages.import_package(archive, root)
            snapshot = packages.snapshot_path(root, info["id"], info["version"])
            source = package_repo / info["id"] / "package"
            def inventory(path):
                return {p.relative_to(path).as_posix(): (p.read_bytes(), bool(p.stat().st_mode & 0o111))
                        for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
            require(source.is_dir(), "Package source directory is missing")
            require(inventory(source) == inventory(snapshot), "Source bytes/modes differ from the ZIP")
            manifest = json.loads((snapshot / "package.json").read_text())
            repository_root = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=package_repo,
                                             capture_output=True, text=True, check=True).stdout.strip()
            require(Path(repository_root).resolve() == package_repo.resolve(),
                    "Package repository path is not its Git root")
            spec = importlib.util.spec_from_file_location("momentum_package_build",
                                                         package_repo / "tools/build.py")
            build = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(build)
            try:
                build.check_release(source, manifest, rebuild=True)
            except SystemExit as error:
                raise ValueError(str(error)) from error
            evidence = compatibility.find_record(launcher, info["id"], info["version"], info["digest"])
            require(evidence and evidence.get("installer_validated") is True,
                    "Launcher lacks approved evidence for this exact version/digest")
            requirements = manifest["requires"]
            require(len(requirements) == 1 and requirements[0]["id"] == evidence["runtime"],
                    "Evidence runtime does not match package requirements")
            requirement, software = requirements[0], evidence["software"]
            hashes = ("sha256", "games_xml_sha256") if evidence["runtime"] == "supermodel" else (
                ("commit",) if software.get("provider") == "flatpak" else ("sha256",))
            for key in hashes:
                require(isinstance(software.get(key), str) and re.fullmatch(r"[a-f0-9]{64}", software[key]),
                        f"Evidence lacks exact software {key}")
            for key in ("provider", "scope", "app_id"):
                if key in software:
                    require(requirement.get(key) == software[key], f"Evidence software {key} mismatch")
            for declared, expected_key in (("executable_sha256", "sha256"), ("companion_sha256", "companion_sha256")):
                if declared in requirement:
                    require(requirement[declared] == software.get(expected_key),
                            f"Evidence software {expected_key} mismatch")
            if "tested_version" in requirement:
                require(requirement["tested_version"] == software.get("version"), "Evidence software version mismatch")
            data = json.loads((distribution / "catalog.json").read_text())
            catalog.validate(data)
            entry = next((g for g in data["games"] if g["id"] == info["id"]), None)
            require(entry is not None, "Package is missing from proposed catalog")
            for key, expected in (("version", info["version"]), ("digest", info["digest"]),
                                  ("size", archive.stat().st_size),
                                  ("sha256", hashlib.sha256(archive.read_bytes()).hexdigest()),
                                  ("platform", manifest["platform"])):
                require(entry.get(key) == expected, f"Catalog {key} differs from final ZIP")
            checksum = distribution / f"{identity}.zip.sha256"
            require(checksum.read_text().split() == [entry["sha256"], f"{identity}.zip"],
                    "Release checksum sidecar differs from final ZIP")
            home = root / "home"
            home.mkdir()
            test_copy = root / "test-package"
            shutil.copytree(snapshot, test_copy)
            for path in [test_copy, *test_copy.rglob("*")]:
                path.chmod(path.stat().st_mode | 0o200)
            before = inventory(test_copy)
            env = dict(os.environ, HOME=str(home))
            for key in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"):
                env.pop(key, None)
            for command in ([sys.executable, "tests/check_package.py"],
                            [sys.executable, "-m", "unittest", "-q"]):
                completed = subprocess.run(command, cwd=test_copy, env=env, capture_output=True, text=True)
                require(completed.returncode == 0, "Package tests failed:\n" + completed.stdout + completed.stderr)
            require(inventory(test_copy) == before, "Package tests changed the snapshot")
            require(not list(test_copy.rglob("*.pyc")), "Package tests left generated bytecode in the snapshot")
            if public:
                downloaded = root / f"{identity}.zip"
                with catalog._open(entry["url"]) as response, downloaded.open("wb") as output:
                    size = 0
                    while chunk := response.read(1 << 20):
                        size += len(chunk)
                        require(size <= entry["size"], "Public asset exceeds expected size")
                        output.write(chunk)
                require(size == entry["size"], "Public asset size differs")
                require(hashlib.sha256(downloaded.read_bytes()).hexdigest() == entry["sha256"],
                        "Public asset checksum differs")
                require(packages.check(downloaded)["digest"] == info["digest"], "Public asset intake differs")
            return identity
        finally:
            packages._rmtree(root / "packages")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", type=Path, nargs="+")
    parser.add_argument("--package-repo", type=Path, default=HERE.parent / "momentum-packages")
    parser.add_argument("--distribution", type=Path, default=HERE.parent / "momentum-distribution")
    parser.add_argument("--launcher-archive", type=Path,
                        help="Also verify evidence in the actual shipped launcher ZIP")
    parser.add_argument("--public", action="store_true", help="Verify anonymous uploaded game assets too")
    args = parser.parse_args(argv)
    failures = 0
    with tempfile.TemporaryDirectory(prefix="momentum-launcher-check-") as temporary:
        launcher = HERE
        if args.launcher_archive:
            try:
                with zipfile.ZipFile(args.launcher_archive) as bundle:
                    require(bundle.testzip() is None, "Launcher ZIP integrity failed")
                    for name in bundle.namelist():
                        path = Path(name)
                        require(not path.is_absolute() and ".." not in path.parts, "Unsafe launcher ZIP path")
                    bundle.extractall(temporary)
                candidates = list(Path(temporary).glob("*/docs/hod2-target-evidence.json"))
                require(len(candidates) == 1, "Launcher ZIP must contain one complete launcher root")
                launcher = candidates[0].parents[1]
            except (OSError, ValueError, zipfile.BadZipFile) as error:
                print(f"FAIL: launcher archive: {error}")
                print("RELEASE CHECK: FAIL")
                return 1
        for archive in args.archives:
            try:
                identity = check(archive, args.package_repo, args.distribution, launcher, args.public)
                print(f"PASS: {identity}: source, immutable version, tests, exact evidence, software, catalog, checksum"
                      + (", public download" if args.public else ""))
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
                failures += 1
                print(f"FAIL: {archive.name}: {error}")
        print("RELEASE CHECK: FAIL" if failures else "RELEASE CHECK: PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
