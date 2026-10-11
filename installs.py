#!/usr/bin/env python3
"""Package install orchestration, receipt commits and catalog merge (Contract v1 session 3)."""
import copy
import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
import sys
import shlex
import fcntl
import platform
from contextlib import contextmanager
from pathlib import Path

import packages
import compatibility
import dependencies
import supermodel
import vkquake
import enyo
import engines
import managed_flatpak
import uzdoom
import eduke32
import ironwail
import ownership

DESC_FIELDS = ("name", "description", "tagline", "category", "tags")
ART_FIELDS = ("icon", "cover", "video", "screenshots")
OWNERSHIP = {"managed", "borrowed", "user-state", "shared-dependency"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RUNTIME_RESOLVERS = {
    "flycast": dependencies, "supermodel": supermodel, "vkquake": vkquake, "uzdoom": uzdoom,
    "eduke32": eduke32, "ironwail": ironwail,
}
UBUNTU_2404_RUNTIME_PACKAGES = {
    "libSDL2-2.0.so.0": "libsdl2-2.0-0", "libSDL2_net-2.0.so.0": "libsdl2-net-2.0-0",
    "libGL.so.1": "libgl1", "libGLU.so.1": "libglu1-mesa",
    "libasound.so.2": "libasound2t64", "libpulse.so.0": "libpulse0",
    "libsamplerate.so.0": "libsamplerate0", "libX11.so.6": "libx11-6",
    "libXext.so.6": "libxext6", "libXcursor.so.1": "libxcursor1",
    "libXi.so.6": "libxi6", "libXfixes.so.3": "libxfixes3",
    "libXrandr.so.2": "libxrandr2", "libXss.so.1": "libxss1",
    "libdrm.so.2": "libdrm2", "libgbm.so.1": "libgbm1",
    "libwayland-egl.so.1": "libwayland-egl1", "libwayland-client.so.0": "libwayland-client0",
    "libwayland-cursor.so.0": "libwayland-cursor0", "libxkbcommon.so.0": "libxkbcommon0",
    "libdecor-0.so.0": "libdecor-0-0", "libGLdispatch.so.0": "libglvnd0",
    "libGLX.so.0": "libglx0", "libOpenGL.so.0": "libopengl0",
    "libXrender.so.1": "libxrender1", "libX11-xcb.so.1": "libx11-xcb1",
    "libxcb.so.1": "libxcb1", "libXau.so.6": "libxau6", "libXdmcp.so.6": "libxdmcp6",
    "libexpat.so.1": "libexpat1", "libffi.so.8": "libffi8",
    "libsndfile.so.1": "libsndfile1", "libsystemd.so.0": "libsystemd0",
    "libdbus-1.so.3": "libdbus-1-3", "libasyncns.so.0": "libasyncns0",
    "libapparmor.so.1": "libapparmor1", "libFLAC.so.12": "libflac12t64",
    "libvorbis.so.0": "libvorbis0a", "libvorbisenc.so.2": "libvorbisenc2",
    "libopus.so.0": "libopus0", "libogg.so.0": "libogg0", "libmpg123.so.0": "libmpg123-0t64",
    "libcap.so.2": "libcap2", "libgcrypt.so.20": "libgcrypt20",
    "liblz4.so.1": "liblz4-1", "liblzma.so.5": "liblzma5",
    "libzstd.so.1": "libzstd1", "libbsd.so.0": "libbsd0",
    "libgpg-error.so.0": "libgpg-error0", "libmd.so.0": "libmd0",
    "libgcc_s.so.1": "libgcc-s1", "libstdc++.so.6": "libstdc++6",
    "libc.so.6": "libc6", "libz.so.1": "zlib1g",
    "libopenal.so.1": "libopenal1", "libvulkan.so.1": "libvulkan1",
    "libfuse.so.2": "libfuse2t64",
}


class InstallError(ValueError):
    pass


def _safe_abs(p):
    return isinstance(p, str) and os.path.isabs(p) and not any(c in p for c in "\0\n\r")


def _json_copy(v):
    return json.loads(json.dumps(v))


def _ubuntu_apt_prerequisite(title, reason, packages):
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        release = {}
    if release.get("ID") == "ubuntu" and release.get("VERSION_ID", "").startswith("24.04"):
        commands = [["sudo", "apt", "update"],
                    ["sudo", "apt", "install", "-y", *packages]]
        instruction = "Run these commands in a terminal yourself, then retry. Momentum never requests elevation."
    else:
        commands = []
        instruction = "Install the listed host packages with your operating system's package manager, then retry."
    return {"title": title, "reason": reason, "packages": packages,
            "commands": commands, "instruction": instruction}


def _library_prerequisite(title, reason, libraries):
    libraries = sorted(set(libraries))
    packages = sorted({UBUNTU_2404_RUNTIME_PACKAGES[name] for name in libraries
                       if name in UBUNTU_2404_RUNTIME_PACKAGES})
    unknown = sorted(set(libraries) - UBUNTU_2404_RUNTIME_PACKAGES.keys())
    if unknown:
        return {"title": title, "reason": reason + " No safe Ubuntu 24.04 package mapping is known for: "
                + ", ".join(unknown), "packages": packages, "commands": [],
                "instruction": "Use Ubuntu's package search to identify the exact provider, then retry."}
    return _ubuntu_apt_prerequisite(title, reason, packages)


def _runtime_prerequisite(runtime, error):
    if runtime == "supermodel":
        missing = re.search(r"error while loading shared libraries:\s*([^:\s]+)", error)
        if missing:
            return _library_prerequisite(
                "Supermodel host libraries are missing",
                "Ubuntu needs to provide the missing runtime library before Supermodel can start.",
                [missing.group(1)])
    elif runtime == "ironwail":
        if "readelf and ldconfig" in error or "binutils/libc-bin" in error:
            return _ubuntu_apt_prerequisite(
                "Ironwail host-check tools are missing",
                "Read-only compatibility checks require readelf and ldconfig.", ["binutils", "libc-bin"])
        missing = re.search(r"Ironwail host libraries missing:\s*(.*?)\.\s*Install prerequisites", error)
        if missing:
            return _library_prerequisite(
                "Ironwail host libraries are missing",
                "Ubuntu needs to provide the missing runtime libraries before Ironwail can start.",
                [name.strip() for name in missing.group(1).split(",") if name.strip()])
    elif runtime == "eduke32":
        if "Host checks require readelf and ldconfig" in error:
            return _ubuntu_apt_prerequisite(
                "EDuke32 host-check tools are missing",
                "Read-only compatibility checks require readelf and ldconfig.", ["binutils", "libc-bin"])
        missing = re.search(r"Missing linked library ([^\s;]+)", error)
        if missing:
            return _library_prerequisite(
                "EDuke32 host library is missing",
                "Ubuntu needs to provide the missing runtime library before EDuke32 can start.",
                [missing.group(1)])
    return None


def _hash_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _normalize_desc(v):
    if isinstance(v, list):
        return list(v)
    return v


def _is_missing(v):
    return v is None or v == "" or v == []


def _merge_catalog(entry, defaults, prev_defaults, first_association):
    out = copy.deepcopy(entry)
    if first_association:
        for k in DESC_FIELDS:
            if k not in out and k in defaults:
                out[k] = _json_copy(defaults[k])
        for k in ART_FIELDS:
            cur, new = out.get(k), defaults.get(k)
            if _is_missing(cur) and not _is_missing(new):
                out[k] = _json_copy(new)
        return out
    for k in DESC_FIELDS:
        cur = out.get(k)
        has_prev = k in prev_defaults
        prev = prev_defaults.get(k)
        has_new = k in defaults
        new = defaults.get(k)
        if k not in out:
            if has_new:
                out[k] = _json_copy(new)
            continue
        if has_prev and _normalize_desc(cur) == _normalize_desc(prev):
            if has_new:
                out[k] = _json_copy(new)
            else:
                out.pop(k, None)
    return out


def _write_atomic(path, data):
    ownership.safe_path(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        Path(name).unlink(missing_ok=True)


class Installs:
    def __init__(self, here, catalog_lock, read_raw_games, write_games, jobs):
        self.here = Path(here)
        self.catalog_lock = catalog_lock
        self.read_raw_games = read_raw_games
        self.write_games = write_games
        self.jobs = jobs
        self.submit_lock = threading.Lock()

    def _receipt_path(self, package_id):
        if not isinstance(package_id, str) or not ID_RE.fullmatch(package_id):
            raise InstallError("Invalid receipt package ID")
        home = Path.home()
        return home / ".local" / "share" / "momentum-core" / "installations" / f"{package_id}.json"

    @contextmanager
    def _receipt_guard(self, package_id):
        path = self._receipt_path(package_id).with_suffix(".lock")
        ownership.safe_path(str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _load_receipt(self, package_id):
        p = self._receipt_path(package_id)
        ownership.safe_path(str(p))
        try:
            rec = json.loads(p.read_text())
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            raise InstallError(f"Cannot read installation receipt: {e}") from e
        if not isinstance(rec, dict) or rec.get("receipt_version") != 1 or rec.get("package_id") != package_id:
            raise InstallError("Invalid installation receipt; reconcile it before starting another install")
        if not isinstance(rec.get("resources"), list) or not isinstance(rec.get("paths"), dict):
            raise InstallError("Receipt is missing resource or path records")
        if set(rec["paths"]) != {"launcher", "desktop_entry", "icon", "support", "state", "backup"}:
            raise InstallError("Receipt has unsupported integration paths")
        roots = {k: ownership.safe_path(value) for k, value in rec["paths"].items()}
        game = ownership.safe_path(rec.get("game_directory"))
        seen = set()
        for resource in rec["resources"]:
            if not isinstance(resource, dict) or resource.get("path") in seen:
                raise InstallError("Receipt has invalid or duplicate resources")
            resource_path = ownership.safe_path(resource.get("path"))
            if not (resource_path == game or resource_path.is_relative_to(game)
                    or resource_path == roots["support"] or resource_path.is_relative_to(roots["support"])
                    or resource_path in (roots["launcher"], roots["desktop_entry"], roots["icon"])):
                raise InstallError("Receipt ownership extends outside installation resources")
            if resource.get("ownership") not in OWNERSHIP or resource.get("kind") not in ("file", "directory"):
                raise InstallError("Receipt has unsupported resource ownership/kind")
            if resource["kind"] == "file" and resource["ownership"] == "managed" and not (
                    isinstance(resource.get("sha256"), str) and HEX64.fullmatch(resource["sha256"])):
                raise InstallError("Receipt has invalid managed file hash")
            seen.add(resource["path"])
        return rec

    def _defaults_path(self, package_id):
        home = Path.home()
        return {
            "launcher": str(home / ".local" / "bin" / package_id),
            "desktop_entry": str(home / ".local" / "share" / "applications" / f"{package_id}.desktop"),
            "icon": str(home / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps" / f"{package_id}.png"),
            "support": str(home / ".local" / "share" / "momentum-core" / "packages" / package_id),
            "state": str(home / ".local" / "share" / "momentum-core" / "state" / package_id),
            "backup": str(home / ".local" / "share" / "momentum-core" / "backups" / package_id),
        }

    @staticmethod
    def _flycast_facts(req):
        if (req.get("provider"), req.get("scope"), req.get("app_id")) != (
                "flatpak", "user", dependencies.APP):
            raise InstallError("Only explicit user-scope org.flycast.Flycast dependencies are supported")
        if req.get("source", "flathub") != "flathub":
            raise InstallError("Unsupported Flycast source; no provider or remote substitution is permitted")
        try:
            return dependencies.detect()
        except dependencies.DependencyError as e:
            raise InstallError(str(e)) from e

    def package_details(self, package_id, version):
        snap = packages.snapshot_path(self.here, package_id, version)
        summary = packages.check(snap)
        man = json.loads((snap / "package.json").read_text())
        facts = {}
        dependency_targets = {}
        supported_software = {}
        engine_selection = {}
        host_prerequisites = []
        managed_fallback = None
        flatpak_prerequisite_added = False
        for req in man["requires"]:
            runtime = req["id"]
            if runtime == "flycast":
                facts[runtime] = self._flycast_facts(req)
                if facts[runtime].get("flatpak_available") is False:
                    host_prerequisites.append(_ubuntu_apt_prerequisite(
                        "Flatpak is required", "Momentum needs the Ubuntu Flatpak client before it can prepare Flycast.",
                        ["flatpak"]))
                    flatpak_prerequisite_added = True
                continue
            if runtime == "supermodel":
                if (req.get("provider"), req.get("scope"), req.get("source"), req.get("tested_version")) != (
                        "native", "user", "github:trzy/Supermodel", supermodel.VERSION):
                    raise InstallError("Only the pinned official user-scope Supermodel build is supported")
            elif runtime == "vkquake":
                if (req.get("provider"), req.get("scope"), req.get("source"), req.get("tested_version")) != (
                        "appimage", "user", "github:Novum/vkQuake", vkquake.VERSION):
                    raise InstallError("Only the pinned official user-scope vkQuake AppImage is supported")
            elif runtime == "uzdoom":
                if (req.get("provider"), req.get("scope"), req.get("source"), req.get("app_id"),
                        req.get("tested_version")) != (
                        "flatpak", "user", "flathub", uzdoom.APP, "5.0.1"):
                    raise InstallError("Only the approved Flathub UZDoom setup is supported")
            elif runtime == "eduke32":
                if (req.get("provider"), req.get("scope"), req.get("source"), req.get("source_commit")) != (
                        "native", "user", "https://voidpoint.io/terminx/eduke32", eduke32.SOURCE_COMMIT):
                    raise InstallError("Only the approved official user-scope EDuke32 setup is supported")
            elif runtime == "ironwail":
                if (req.get("provider"), req.get("scope"), req.get("source"), req.get("tested_version")) != (
                        "native", "user", "github:andrei-drexler/ironwail", ironwail.VERSION):
                    raise InstallError("Only the pinned official user-scope Ironwail release is supported")
            else:
                raise InstallError(f"Unsupported dependency resolver: {runtime}")
            try:
                facts[runtime] = RUNTIME_RESOLVERS[runtime].detect()
            except dependencies.DependencyError as e:
                raise InstallError(str(e)) from e
            if runtime == "uzdoom" and facts[runtime].get("flatpak_available") is False:
                host_prerequisites.append(_ubuntu_apt_prerequisite(
                    "Flatpak is required", "Momentum needs the Ubuntu Flatpak client before it can prepare UZDoom.",
                    ["flatpak"]))
                flatpak_prerequisite_added = True
            elif runtime == "eduke32" and not facts[runtime].get("installed"):
                missing = eduke32.missing_build_prerequisites()
                if missing["tools"] or missing["libraries"]:
                    host_prerequisites.append(_ubuntu_apt_prerequisite(
                        "EDuke32 build prerequisites are missing",
                        "The pinned source build requires a compiler, NASM, pkg-config and these development libraries: "
                        + ", ".join(missing["libraries"] or eduke32.BUILD_LIBRARIES),
                        ["build-essential", "nasm", "pkg-config", "libsdl2-dev", "libgl-dev",
                         "libvpx-dev", "libflac-dev", "libgtk2.0-dev"]))
        evidence = json.loads((Path(__file__).parent / "docs/hod2-target-evidence.json").read_text())
        flycast = facts.get("flycast", {})
        approved_packages = [(evidence["package_version"], evidence["package_digest"])]
        approved_packages.extend((p["version"], p["digest"]) for p in evidence.get("derived_packages", []))
        supported = (
            package_id == evidence["package_id"] and (version, summary["digest"]) in approved_packages
            and not summary["platform_issues"])
        revision = next((p for p in evidence.get("derived_packages", [])
                         if (p["version"], p["digest"]) == (version, summary["digest"])), {})
        flycast_builds = [{"version": evidence["emulator_version"], "commit": evidence["emulator_commit"]},
                         *[{key: build[key] for key in ("version", "commit")}
                           for build in revision.get("additional_software", [])]]
        selection = engines.select(flycast, flycast_builds, dependencies.discover if supported else None)
        expected_flycast = selection.build
        if supported:
            flycast = selection.facts
            facts["flycast"] = flycast
            engine_selection["flycast"] = selection.details()
        enabled = (
            supported
            and flycast.get("installed") is True
            and flycast.get("version") == expected_flycast["version"]
            and flycast.get("commit") == expected_flycast["commit"])
        if supported:
            supported_software["flycast"] = {
                "version": expected_flycast["version"], "commit": expected_flycast["commit"]}
            dependency_targets["flycast"] = {
                "version": expected_flycast["version"], "commit": expected_flycast["commit"]}
        if enabled:
            flycast["capabilities_checked"] = True
            flycast["capability_note"] = (
                revision["basis"] if revision.get("gameplay") == "not-tested-for-this-package" else
                "HOD2 gameplay was validated on this Flycast build. Approved artwork-only package revisions "
                "inherit unchanged executable-code evidence; confirm gameplay for each installation.")
            flycast["capability_evidence"] = "docs/hod2-target-evidence.json"
        if package_id != evidence["package_id"]:
            evidence_file = {
                "quake-slave-zero-x": "docs/quake-installer-evidence.json",
                "brutal-doom-64": "docs/doom-installer-evidence.json",
                "brutal-doom": "docs/doom-installer-evidence.json",
                "aliens-eradication": "docs/doom-installer-evidence.json",
                "ashes-2063": "docs/doom-installer-evidence.json",
                "quake-brutalist-jam-3": "docs/qbj3-installer-evidence.json",
                "duke-nukem-3d": "docs/duke-installer-evidence.json"
            }.get(package_id, "docs/arcade-installer-evidence.json")
            path = Path(__file__).parent / evidence_file
            record = compatibility.find_record(Path(__file__).parent, package_id, version, summary["digest"])
            supported = bool(record and record.get("installer_validated") is True and not summary["platform_issues"])
            enabled = False
            if supported:
                runtime = record["runtime"]
                current = facts.get(runtime, {})
                builds = compatibility.software_builds(record)
                selection = engines.select(current, builds,
                    RUNTIME_RESOLVERS[runtime].discover if runtime == "uzdoom" else None)
                expected = selection.build
                current = selection.facts
                facts[runtime] = current
                engine_selection[runtime] = selection.details()
                supported_software[runtime] = expected
                if isinstance(expected.get("commit"), str):
                    dependency_targets[runtime] = {
                        key: expected[key] for key in ("version", "commit") if key in expected}
                enabled = (len(facts) == 1 and current.get("installed") is True
                           and engines.matches(current, expected))
                if enabled:
                    if runtime in ("supermodel", "vkquake", "uzdoom", "eduke32", "ironwail"):
                        if runtime == "vkquake":
                            missing = vkquake.missing_host_prerequisites(current)
                            package_by_loader = {"fuse": "libfuse2t64", "vulkan": "libvulkan1"}
                            if missing:
                                host_prerequisites.append(_ubuntu_apt_prerequisite(
                                    "vkQuake host libraries are missing",
                                    "The pinned AppImage requires the FUSE2 and Vulkan loader libraries.",
                                    [package_by_loader[name] for name in missing]))
                                enabled = False
                    if enabled and runtime in ("supermodel", "vkquake", "uzdoom", "eduke32", "ironwail"):
                        try:
                            current["host_checks"] = RUNTIME_RESOLVERS[runtime].check_host(current)
                        except dependencies.DependencyError as e:
                            requirement = _runtime_prerequisite(runtime, str(e))
                            if requirement is None:
                                raise InstallError(str(e)) from e
                            host_prerequisites.append(requirement)
                            enabled = False
                    if enabled:
                        current["capabilities_checked"] = True
                        current["capability_note"] = record["limits"]
                        current["capability_evidence"] = str(path.relative_to(Path(__file__).parent))
        runtime = next(iter(facts), None)
        contract = man.get("extensions", {}).get("managed_engine")
        if supported and runtime in managed_flatpak.BUILDS and contract == managed_flatpak.CONTRACT:
            if man["extensions"].get("managed_helper_sha256") != _hash_file(Path(managed_flatpak.__file__)):
                raise InstallError("This package's retained engine helper differs from this launcher. "
                                   "Use the matching private candidate; no engine preparation was started.")
            previous = self._load_receipt(package_id)
            old = (previous or {}).get("dependencies", {}).get(runtime, {})
            try:
                if old.get("managed"):
                    managed_flatpak.validate_binding(old["managed"])
                    current = managed_flatpak.facts(runtime, package_id)
                elif (not enabled or os.environ.get("MCL_TEST_ISOLATED_ENGINES") == "1") and (
                        (facts[runtime].get("installed") or os.environ.get("MCL_TEST_ISOLATED_ENGINES") == "1")
                        and facts[runtime].get("flatpak_available") and not previous):
                    enabled = False
                    current = managed_flatpak.facts(runtime, package_id)
                    if current is None:
                        managed_fallback = {
                            "runtime": runtime, "target": managed_flatpak.BUILDS[runtime],
                            "slot": str(managed_flatpak.slot(runtime)),
                            "profile": str(managed_flatpak.root() / "state" / package_id / "engine-profile-v1"),
                            "space_required_bytes": managed_flatpak.SPACE[runtime],
                            "test_mode": os.environ.get("MCL_TEST_ISOLATED_ENGINES") == "1",
                            "existing": engines.identity(facts[runtime])}
                else:
                    current = None
                if current is not None:
                    current["capabilities_checked"] = True
                    current["capability_evidence"] = "docs/shared-engine-fallback-evidence.json"
                    facts[runtime] = current
                    supported_software[runtime] = {
                        key: current[key] for key in ("version", "commit")}
                    engine_selection[runtime]["status"] = "managed"
                    engine_selection[runtime]["selected"] = engines.identity(current)
                    enabled = True
                elif previous and old and engines.identity(old) != engines.identity(facts[runtime]):
                    enabled = False
                    host_prerequisites.append({
                        "title": "Existing engine binding must be preserved",
                        "reason": "This installation's recorded engine is not the selected copy. "
                                  "Engine/profile migration is not automatic.",
                        "instruction": "Keep the existing installation. Review repair or migration before changing its engine.",
                        "packages": [], "commands": []})
            except managed_flatpak.ManagedError as exc:
                raise InstallError(str(exc)) from exc
        if not flatpak_prerequisite_added:
            for runtime in ("flycast", "uzdoom"):
                current = facts.get(runtime)
                if isinstance(current, dict) and current.get("flatpak_available") is False:
                    host_prerequisites.append(_ubuntu_apt_prerequisite(
                        "Flatpak is required", f"Momentum needs the Ubuntu Flatpak client before it can prepare {runtime}.",
                        ["flatpak"]))
                    break
        return dict(summary, manifest=man, home_games=str(Path.home() / "Games"), dependencies=facts,
                    dependency_targets=dependency_targets,
                    supported_software=supported_software,
                    engine_selection=engine_selection,
                    managed_fallback=managed_fallback,
                    host_prerequisites=host_prerequisites,
                    compatibility=compatibility.guidance(summary["platform_issues"], supported, enabled,
                                                         host_prerequisites, facts),
                    install_enabled=enabled, package_supported=supported)

    @staticmethod
    def _dependency_steps(runtime="flycast", target=None, fallback=None, package_id=None):
        if runtime not in RUNTIME_RESOLVERS:
            raise InstallError(f"Unsupported dependency resolver: {runtime}")
        helper = str(Path(__file__).with_name(RUNTIME_RESOLVERS[runtime].__name__ + ".py"))
        steps = [{"name": name, "protocol": True, "approve_after": phase == "preflight",
                 "declared_steps": ["resolve"],
                 "argv": [sys.executable, helper, "--context", "{context_file}"],
                 "context": {"operation": "prepare-dependency", "phase": phase}}
                for name, phase in [("Check required game software", "preflight"),
                                    ("Prepare required game software", "apply")]]
        if runtime in ("flycast", "uzdoom") and target and target.get("commit"):
            for step in steps:
                step["context"]["target_commit"] = target["commit"]
        if fallback is not None:
            for step in steps:
                step["argv"][1] = str(Path(__file__).with_name("managed_flatpak.py"))
                step["context"].update(runtime=runtime, package_id=package_id,
                                       existing=fallback["existing"])
                step["name"] = ("Review tested isolated engine" if
                                step["context"]["phase"] == "preflight" else "Prepare tested isolated engine")
        return steps

    def before_step(self, job, index):
        meta = job.get("meta") or {}
        if not meta.get("prepare_required_software") or index != 2:
            return None
        detail = self.package_details(meta["package_id"], meta["package_version"])
        detail_status = {"compatibility": detail.get("compatibility"),
                         "host_prerequisites": _json_copy(detail.get("host_prerequisites", [])),
                         "engine_selection": _json_copy(detail.get("engine_selection", {})),
                         "supported_software": _json_copy(detail.get("supported_software", {}))}
        if detail["digest"] != meta["package_digest"] or not detail["install_enabled"]:
            with self.jobs.lock:
                meta.update(detail_status)
                self.jobs._save(job)
            guidance = detail.get("compatibility")
            if detail["digest"] == meta["package_digest"] and guidance:
                return ("needs-action", guidance["title"] + ": " + guidance["message"]
                        + " No game files were installed.")
            return ("needs-action", "Required game software is not a validated build for this package. "
                    "No game files were installed; Momentum needs updated compatibility evidence.")
        source = None
        if "ironwail" in detail["dependencies"]:
            ctx = job["steps"][2]["context"]
            try:
                source = ironwail.source_for(ctx["inputs"], ctx["package_root"], ctx["package_digest"])
            except dependencies.DependencyError as e:
                return ("needs-action", f"Mod source verification failed: {e}")
            if source is None:
                return ("needs-action", "Approved QBJ3 source preparation did not produce a complete source.")
        elif "vkquake" in detail["dependencies"] and enyo.enabled(
                job["steps"][2]["context"]["package_root"], meta["package_digest"]):
            ctx = job["steps"][2]["context"]
            try:
                source = enyo.source_for(ctx["inputs"], ctx["package_root"], ctx["package_digest"])
            except dependencies.DependencyError as e:
                return ("needs-action", f"Enyo source verification failed: {e}")
            if source is None:
                return ("needs-action", "Approved Enyo download did not produce verified source files.")
        with self.jobs.lock:
            meta.update(detail_status)
            for step in job["steps"][2:]:
                step["context"]["dependencies"] = _json_copy(detail["dependencies"])
                if source is not None:
                    step["context"]["inputs"]["mod_dir"] = str(source)
            meta["install_enabled"] = True
            self.jobs._save(job)
        return None

    def _check_active_operations(self):
        with self.jobs.lock:
            for job in self.jobs.jobs.values():
                if (job.get("meta") or {}).get("kind") not in ("install", "dependency"):
                    continue
                if job["status"] in ("queued", "running", "cancel-requested", "awaiting-approval"):
                    raise InstallError("Another package or dependency operation is active; finish or cancel it first")
                if job.get("manual") or (self.jobs.paths(job["id"])["job_dir"] / "catalog-pending.json").exists() or (
                        job["status"] != "succeeded" and self.jobs._intents_recorded(job["id"])) or (
                        self.jobs.dependency_uncertain(job["id"])):
                    raise InstallError("An earlier operation changed files; reconcile its journal before starting another")

    def prepare_flycast(self):
        """A separately approved shared dependency job; no package code or game writes."""
        with self.submit_lock:
            self._check_active_operations()
            steps = self._dependency_steps()
            return self.jobs.submit("Prepare Flycast", steps, meta={"kind": "dependency"})

    def submit_install(self, package_id, version, source_dir=None, games_root=None, catalog_entry_id=None,
                       trusted_digest=None, inputs=None):
        with self.submit_lock:
            return self._submit_install(package_id, version, source_dir, games_root, catalog_entry_id,
                                        trusted_digest, inputs)

    def _submit_install(self, package_id, version, source_dir, games_root, catalog_entry_id, trusted_digest, inputs):
        detail = self.package_details(package_id, version)
        if trusted_digest != detail["digest"]:
            raise InstallError("Trust approval must match this package's current digest")
        if detail["platform_issues"]:
            raise InstallError("Unsupported platform: " + "; ".join(detail["platform_issues"]))
        snap = packages.snapshot_path(self.here, package_id, version)
        man = detail["manifest"]
        if inputs is None:
            inputs = {"source_dir": source_dir, "games_root": games_root or str(Path.home() / "Games")}
        if not isinstance(inputs, dict):
            raise InstallError("Package inputs must be an object")
        inputs = dict(inputs)
        declared = {f["id"] for f in man["inputs"]}
        if set(inputs) - declared:
            raise InstallError("Undeclared package input")
        for field in man["inputs"]:
            key, typ = field["id"], field["type"]
            if key not in inputs and "default" in field:
                inputs[key] = detail["home_games"] if field["default"] == "home_games" else field["default"]
            if key not in inputs:
                if field.get("required"):
                    raise InstallError(f"Required input: {key}")
                continue
            value = inputs[key]
            if typ == "boolean":
                valid = isinstance(value, bool)
            elif typ == "directory":
                valid = _safe_abs(value)
            elif typ == "choice":
                valid = value in field["choices"]
            else:
                valid = isinstance(value, str) and (bool(value.strip()) or not field.get("required"))
            if not valid:
                raise InstallError(f"Invalid {typ} input: {key}")
        if not all(_safe_abs(inputs.get(k)) for k in ("source_dir", "games_root")):
            raise InstallError("This install profile requires source_dir and games_root directories")
        if not Path(inputs["source_dir"]).is_dir():
            raise InstallError("Source directory does not exist")
        if catalog_entry_id is not None:
            with self.catalog_lock:
                if not any(g["id"] == catalog_entry_id for g in self.read_raw_games()):
                    raise InstallError("The selected library entry no longer exists")
        self._check_active_operations()
        deps = detail["dependencies"]
        prev = self._load_receipt(package_id)
        paths = prev["paths"] if prev else self._defaults_path(package_id)
        if prev:
            # Upgrades and repairs stay in the recorded folder even if the package's default folder name changed.
            game_dir = prev["game_directory"]
            inputs["games_root"] = str(Path(game_dir).parent)
        else:
            game_dir = str(Path(inputs["games_root"]) / man["destination_name"])
        if prev:
            associated = prev.get("catalog", {}).get("entry_id")
            if catalog_entry_id is not None and catalog_entry_id != associated:
                raise InstallError("Installation is already associated; reassociation needs explicit migration")
            catalog_entry_id = associated
        base = {
            "contract_version": man["contract_version"],
            "package_id": package_id,
            "package_version": man["version"],
            "package_digest": packages.read_intake(snap.parent)["digest"],
            "package_root": str(snap),
            "operation": "install",
            "inputs": inputs,
            "game_directory": game_dir,
            "paths": paths,
            "dependencies": deps,
            "previous_receipt": prev,
            "catalog_entry_id": catalog_entry_id,
        }
        steps = [
            {"name": "Package preflight", "protocol": True, "approve_after": True,
             "declared_steps": [str(s) for s in man["operations"]["install"]["steps"]],
             "argv": ["bash", "install.sh", "--context", "{context_file}", "--phase", "preflight"],
             "cwd": str(snap), "context": dict(base, phase="preflight")},
            {"name": "Package apply", "protocol": True,
             "declared_steps": [str(s) for s in man["operations"]["install"]["steps"]],
             "argv": ["bash", "install.sh", "--context", "{context_file}", "--phase", "apply"],
             "cwd": str(snap), "context": dict(base, phase="apply")},
        ]
        meta = {"kind": "install", "package_id": package_id, "package_version": man["version"],
                "package_digest": base["package_digest"], "operation": "install",
                "game_directory": game_dir, "paths": paths, "manifest": {"name": man["name"]},
                "install_enabled": detail["install_enabled"],
                "compatibility": detail.get("compatibility"),
                "host_prerequisites": detail.get("host_prerequisites", []),
                "supported_software": detail.get("supported_software", {}),
                "engine_selection": detail.get("engine_selection", {}),
                "catalog_defaults": {**man["catalog"], "name": man["name"], "icon": paths["icon"]}}
        runtime = next(iter(deps), None)
        prepare_source = False
        if runtime == "ironwail":
            try:
                mod = ironwail.source_for(inputs, str(snap), base["package_digest"])
            except dependencies.DependencyError as e:
                raise InstallError(str(e)) from e
            prepare_source = mod is None
            if mod is not None:
                inputs["mod_dir"] = str(mod)
        elif runtime == "vkquake" and enyo.enabled(str(snap), base["package_digest"]):
            try:
                mod = enyo.source_for(inputs, str(snap), base["package_digest"])
            except dependencies.DependencyError as e:
                raise InstallError(str(e)) from e
            prepare_source = mod is None
            if mod is not None:
                inputs["mod_dir"] = str(mod)
        fallback = detail.get("managed_fallback")
        if detail["package_supported"] and runtime and (not deps[runtime].get("installed") or prepare_source or fallback):
            steps = self._dependency_steps(runtime, detail.get("dependency_targets", {}).get(runtime),
                                           fallback, package_id) + steps
            if runtime == "ironwail" or (runtime == "vkquake" and enyo.enabled(str(snap), base["package_digest"])):
                for step in steps[:2]:
                    step["context"].update(package_root=str(snap), package_digest=base["package_digest"],
                                           inputs=_json_copy(inputs), game_directory=game_dir)
                    step["name"] = ("Check required software and mod download" if
                                    step["context"]["phase"] == "preflight" else "Prepare required software and mod source")
            meta["prepare_required_software"] = True
            if fallback:
                meta["managed_fallback"] = fallback
        return self.jobs.submit(f"Install {man['name']}", steps, game=package_id, meta=meta)

    def approve(self, jid, digest):
        with self.jobs.lock:
            job = self.jobs.jobs.get(jid)
            if not job or job["status"] != "awaiting-approval" or digest != job.get("plan_digest"):
                return "The plan changed or is no longer awaiting approval"
            if (job.get("meta") or {}).get("kind") == "install":
                meta = _json_copy(job["meta"])
                previous = _json_copy(job["steps"][-1]["context"].get("previous_receipt"))
                preparing = bool(meta.get("prepare_required_software")
                                 and job["steps"][1]["status"] == "pending")
            else:
                meta = None
        if meta is not None:
            try:
                detail = self.package_details(meta["package_id"], meta["package_version"])
                if detail["digest"] != meta["package_digest"]:
                    return "Package changed since preflight; cancel and review a new job"
                if preparing and not detail["package_supported"]:
                    return "This game package lacks matching target evidence"
                if preparing and meta.get("managed_fallback") != detail.get("managed_fallback"):
                    return "Isolated engine selection changed; start a new setup review."
                if not preparing and (not meta.get("install_enabled") or not detail["install_enabled"]):
                    if detail.get("compatibility"):
                        return detail["compatibility"]["title"] + ": " + detail["compatibility"]["message"]
                    return "This exact game package/software build lacks matching installer capability evidence"
                if not preparing:
                    planned = job["steps"][-1]["context"].get("dependencies", {})
                    for runtime in ("flycast", "uzdoom"):
                        if runtime in planned and engines.identity(planned[runtime]) != engines.identity(
                                detail["dependencies"].get(runtime, {})):
                            return "Selected engine installation changed; start a new review before approval."
                if self._load_receipt(meta["package_id"]) != previous:
                    return "Installation receipt changed since preflight; cancel and review a new job"
                if "flycast" in detail["dependencies"] and dependencies.APP in dependencies.probe("ps", "--columns=application").splitlines():
                    return "Close Flycast before approving this installation"
                if "supermodel" in detail["dependencies"] and not preparing and supermodel.running(detail["dependencies"]["supermodel"]):
                    return "Close Supermodel before approving this installation"
                if "vkquake" in detail["dependencies"] and not preparing and vkquake.running(detail["dependencies"]["vkquake"]):
                    return "Close vkQuake before approving this installation"
                if "uzdoom" in detail["dependencies"] and uzdoom.running(detail["dependencies"]["uzdoom"]):
                    return "Close UZDoom before approving this installation"
                if "eduke32" in detail["dependencies"] and not preparing and eduke32.running(detail["dependencies"]["eduke32"]):
                    return "Close EDuke32 before approving this installation"
                if "ironwail" in detail["dependencies"] and ironwail.running(detail["dependencies"]["ironwail"]):
                    return "Close Ironwail before approving this installation"
            except (InstallError, ownership.OwnershipError, dependencies.DependencyError, OSError, ValueError) as e:
                return f"Installation approval checks failed: {e}"
        return self.jobs.approve(jid, digest)

    def _missing_user_state(self, j):
        paths = self.jobs.paths(j["id"])
        raw = paths["approved_plan_file"].read_bytes()
        if ownership.digest(raw) != j.get("approved_plan_digest"):
            raise InstallError("Approved plan changed; recovery evidence is retained")
        envelope = json.loads(raw)
        if envelope.get("phase") != "preflight" or envelope.get("outcome") != "succeeded":
            raise InstallError("Only a successful approved plan can be reconciled")
        plan = envelope.get("plan") or {}
        owners = plan.get("media_ownership") or {}
        game = ownership.safe_path(j["meta"]["game_directory"])
        missing = set()
        for row in plan.get("media_inventory") or []:
            if not isinstance(row, dict) or owners.get(row.get("relative_path")) != "user-state":
                continue
            relative = Path(row.get("relative_path", ""))
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise InstallError("Approved media inventory contains an unsafe path")
            path = ownership.safe_path(str(game / relative))
            if not path.exists():
                missing.add(str(path))
        return missing

    def _validate_result(self, j, res, missing_user_state=()):
        res = copy.deepcopy(res)
        missing_user_state = set(missing_user_state)
        ownership.reconcile(j, res, self.jobs.paths(j["id"]), missing_user_state=missing_user_state)
        if missing_user_state:
            res["resources"] = [r for r in res["resources"] if r["path"] not in missing_user_state]
            res["recovery_notes"].append(
                "User-approved reconciliation omitted missing optional user-state media; no managed package file was omitted.")
        m = j.get("meta") or {}
        defaults = res["catalog_proposal"].get("defaults")
        expected = _json_copy(m["catalog_defaults"])
        if isinstance(defaults, dict) and defaults.get("icon") != expected.get("icon"):
            # Recovery may contain the runner's resolved, retained media URL.
            resource = next((r for r in res["resources"] if r["path"] == m["paths"]["icon"]), None)
            if resource:
                assoc = self._load_receipt(m["package_id"])
                gid = (assoc or {}).get("catalog", {}).get("entry_id")
                retained = f"media/{gid}/package-icon-{resource['sha256']}.png"
                if defaults.get("icon") == retained:
                    expected["icon"] = retained
        if defaults != expected:
            raise InstallError("Catalog defaults differ from the validated package manifest")
        for key in ("pending_actions", "checks", "completed_steps", "recovery_notes"):
            if not isinstance(res.get(key), list):
                raise InstallError(f"Result {key} must be a list")
        for k in ("package_id", "package_version", "package_digest"):
            if res.get(k) != m.get(k):
                raise InstallError(f"result {k} mismatch")
        if res.get("outcome") != "succeeded":
            raise InstallError("result outcome must be succeeded")
        if res.get("receipt_committed") is not False:
            raise InstallError("package cannot claim receipt_committed")
        resources = res.get("resources")
        if not isinstance(resources, list):
            raise InstallError("result resources must be a list")
        allowed_roots = [Path(m["game_directory"])] + [Path(p) for p in m["paths"].values()]
        seen = set()
        for r in resources:
            if not isinstance(r, dict):
                raise InstallError("resource must be an object")
            p = r.get("path")
            if p in missing_user_state:
                continue
            if not _safe_abs(p):
                raise InstallError("resource path must be absolute")
            if p in seen:
                raise InstallError(f"duplicate resource {p}")
            seen.add(p)
            rp = Path(p)
            if not any(rp == root or rp.is_relative_to(root) for root in allowed_roots):
                raise InstallError(f"resource outside install scope: {p}")
            if r.get("ownership") not in OWNERSHIP:
                raise InstallError(f"invalid ownership for {p}")
            k = r.get("kind")
            if k == "file":
                if not rp.is_file():
                    raise InstallError(f"missing managed file: {p}")
                sh = r.get("sha256")
                if not isinstance(sh, str) or not HEX64.match(sh) or _hash_file(rp) != sh:
                    raise InstallError(f"hash mismatch for {p}")
            elif k == "directory":
                if not rp.is_dir():
                    raise InstallError(f"missing managed directory: {p}")
            else:
                raise InstallError(f"invalid resource kind for {p}")
        return res

    def busy_for_game(self, entry_id):
        with self.jobs.lock:
            return any((j.get("meta") or {}).get("kind") == "install"
                       and j["status"] in ("queued", "running", "cancel-requested")
                       and entry_id in (j.get("game"), j["steps"][-1].get("context", {}).get("catalog_entry_id"))
                       for j in self.jobs.jobs.values())

    def _receipt_from(self, j, res):
        now = int(time.time())
        m = j["meta"]
        old = self._load_receipt(m["package_id"]) or {}
        history = list(old.get("history") or [])
        history.append({"t": now, "operation": m["operation"], "package_version": m["package_version"]})
        return {
            "receipt_version": 1,
            "installation_id": old.get("installation_id") or ("i-" + secrets.token_hex(8)),
            "package_id": m["package_id"],
            "package_version": m["package_version"],
            "package_digest": m["package_digest"],
            "platform": packages.host_platform(),
            "created_at": old.get("created_at") or now,
            "updated_at": now,
            "history": history[-50:],
            "installation": res.get("installation"),
            "readiness": res.get("readiness"),
            "pending_actions": res.get("pending_actions") or [],
            "checks": res.get("checks") or [],
            "catalog": {
                "entry_id": old.get("catalog", {}).get("entry_id") or res.get("catalog_entry_id"),
                "previous_defaults": old.get("catalog", {}).get("previous_defaults") or {},
                "associated_once": bool(old.get("catalog", {}).get("associated_once")),
            },
            "locations": {
                "source_reference": res.get("source_reference"),
                "game_directory": res.get("game_directory"),
                "launch_argv": (res.get("catalog_proposal") or {}).get("launch_argv") or [],
                "working_directory": (res.get("catalog_proposal") or {}).get("working_directory"),
            },
            "dependencies": res.get("dependencies"),
            "resources": res.get("resources"),
            "game_directory": res.get("game_directory"),
            "paths": _json_copy(m["paths"]),
            "last_job_id": j["id"],
            "state": res.get("state") or {},
            "evidence": old.get("evidence") or {"static": "not-tested", "mock": "not-tested", "real": "not-tested",
                                                  "gameplay": "not-tested"},
        }

    def _commit_catalog(self, rec, res, journal=None, recovery_policy=None):
        proposal = res.get("catalog_proposal") or {}
        defaults = _json_copy(proposal.get("defaults") or {})
        if not isinstance(defaults, dict):
            raise InstallError("catalog defaults must be an object")
        with self.catalog_lock:
            games = self.read_raw_games()
            if not isinstance(games, list):
                raise InstallError("games.json is invalid")
            by_id = {g.get("id"): g for g in games if isinstance(g, dict)}
            entry_id = rec["catalog"]["entry_id"]
            existing = by_id.get(entry_id) if entry_id else None
            first = not bool(rec["catalog"]["associated_once"])
            if existing is None:
                if entry_id:
                    gid = entry_id
                else:
                    base = rec["package_id"]
                    gid = base
                    n = 2
                    while gid in by_id:
                        gid = f"{base}-{n}"
                        n += 1
                existing = {"id": gid}
                games.append(existing)
                rec["catalog"]["entry_id"] = gid
            # Allocate an association durably before publication. Crash recovery must not pick a new slug.
            if journal is not None:
                marker = {"commit_version": 1, "job_id": rec["last_job_id"], "receipt": rec, "result": res}
                if recovery_policy:
                    marker["recovery_policy"] = recovery_policy
                _write_atomic(journal, (json.dumps(marker, indent=2) + "\n").encode())
                _write_atomic(self._receipt_path(rec["package_id"]), (json.dumps(rec, indent=2) + "\n").encode())
            if existing.get("installation_id") == rec["installation_id"] and existing.get("install_job_id") == rec["last_job_id"]:
                # Catalog replacement succeeded before a crash. Never replay defaults over subsequent UI edits.
                rec["catalog"]["associated_once"] = True
                rec["catalog"]["previous_defaults"] = defaults
                return
            if existing.get("installation_id") not in (None, rec["installation_id"]):
                raise InstallError("Library entry belongs to a different installation")
            # Immutable, retained artwork copies are served through media/, never absolute home URLs.
            if first and _is_missing(existing.get("icon")) and defaults.get("icon"):
                icon = ownership.safe_path(rec["paths"]["icon"])
                resource = next((r for r in rec["resources"] if r["path"] == str(icon)), None)
                if not resource or resource["kind"] != "file" or resource["sha256"] != _hash_file(icon):
                    raise InstallError("Catalog icon has no validated retained resource")
                rel = Path("media") / rec["catalog"]["entry_id"] / f"package-icon-{resource['sha256']}.png"
                _write_atomic(self.here / rel, icon.read_bytes())
                defaults["icon"] = rel.as_posix()
                # Persist the resolved media URL before catalog publication as part of the same commit.
                res["catalog_proposal"]["defaults"] = _json_copy(defaults)
                if journal:
                    marker = {"commit_version": 1, "job_id": rec["last_job_id"], "receipt": rec, "result": res}
                    if recovery_policy:
                        marker["recovery_policy"] = recovery_policy
                    _write_atomic(journal, (json.dumps(marker, indent=2) + "\n").encode())
            merged = _merge_catalog(existing, defaults, rec["catalog"]["previous_defaults"], first_association=first)
            if rec.get("installation") == "installed":
                argv = proposal.get("launch_argv") or []
                merged["exec"] = shlex.join(argv)
                merged["cwd"] = proposal.get("working_directory")
            else:
                merged.pop("exec", None)
                merged.pop("cwd", None)
            merged["package_id"] = rec["package_id"]
            merged["package_version"] = rec["package_version"]
            merged["install_status"] = rec.get("installation")
            merged["readiness"] = rec.get("readiness")
            merged["installation_id"] = rec["installation_id"]
            merged["install_job_id"] = rec["last_job_id"]
            existing.clear()
            existing.update(merged)
            self.write_games(games)
        rec["catalog"]["associated_once"] = True
        rec["catalog"]["previous_defaults"] = defaults

    def on_success(self, j):
        m = j.get("meta") or {}
        if m.get("kind") != "install":
            return None
        p = self.jobs.paths(j["id"])
        try:
            idx = len(j["steps"]) - 1
            res = json.loads((p["results_dir"] / f"step-{idx}.json").read_text())
        except (OSError, ValueError) as e:
            return f"install result missing: {e}"
        try:
            with self._receipt_guard(m["package_id"]):
                self._validate_result(j, res)
                old = self._load_receipt(m["package_id"])
                if old != j["steps"][-1]["context"].get("previous_receipt"):
                    raise InstallError("Installation receipt changed since preflight; reconcile before commit")
                rec = self._receipt_from(j, res)
                self._complete_commit(j, rec, res)
            return None
        except (InstallError, ownership.OwnershipError, OSError, ValueError, KeyError, TypeError) as e:
            j["manual"] = True
            return str(e)

    def _complete_commit(self, job, rec, result, recovery_policy=None):
        journal = self.jobs.paths(job["id"])["job_dir"] / "catalog-pending.json"
        self._commit_catalog(rec, result, journal=journal, recovery_policy=recovery_policy)
        _write_atomic(self._receipt_path(rec["package_id"]), (json.dumps(rec, indent=2) + "\n").encode())
        job.update(installation=rec["installation"], readiness=rec["readiness"],
                   actions=_json_copy(rec["pending_actions"]), manual=False, commit_completed=True)
        # Persist success before removing the last recovery marker.
        with self.jobs.lock:
            self.jobs._finish(job, "succeeded")
        journal.unlink()
        fd = os.open(journal.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _reconciliation_proposal(self, jid):
        job = self.jobs.jobs.get(jid)
        if not job or (job.get("meta") or {}).get("kind") != "install":
            raise InstallError("only a package installation can be reconciled")
        if job.get("status") not in ("failed", "interrupted") or not job.get("manual"):
            raise InstallError("this installation is not awaiting manual reconciliation")
        if job.get("surviving"):
            raise InstallError("installation processes are still running")
        if self.jobs.dependency_uncertain(jid):
            raise InstallError("dependency transaction must be reconciled first")
        paths = self.jobs.paths(jid)
        if (paths["job_dir"] / "catalog-pending.json").exists():
            raise InstallError("catalog receipt recovery is already pending; restart Momentum to resume it")
        if not self.jobs._intents_recorded(jid):
            raise InstallError("this job has no package mutation journal to reconcile")
        result_path = paths["results_dir"] / f"step-{len(job['steps']) - 1}.json"
        raw = result_path.read_bytes()
        if ownership.digest(raw) != job["steps"][-1].get("result_digest"):
            raise InstallError("Saved apply result changed; journal retained")
        result = json.loads(raw)
        if result.get("phase") != "apply" or result.get("outcome") != "succeeded":
            raise InstallError("The package apply did not produce a successful proposal; journal retained")
        missing = self._missing_user_state(job)
        result = self._validate_result(job, result, missing_user_state=missing)
        previous = job["steps"][-1]["context"].get("previous_receipt")
        if self._load_receipt(job["meta"]["package_id"]) != previous:
            raise InstallError("Installation receipt changed; journal retained")
        return job, result, missing

    def recovery_details(self, jid):
        """Read-only recovery review; committing always repeats these checks."""
        with self.submit_lock:
            try:
                job, _, missing = self._reconciliation_proposal(jid)
                return {"eligible": True, "title": "Finish installation registration",
                        "message": "The package finished changing files, but registration did not complete. "
                                   "Momentum can verify the saved plan and journal, then finish the receipt and library entry. "
                                   "It will not reinstall the game or reset settings.",
                        "missing_user_state": sorted(missing),
                        "journal": str(self.jobs.paths(job["id"])["job_dir"])}
            except (InstallError, ownership.OwnershipError, OSError, ValueError, KeyError, TypeError) as error:
                return {"eligible": False, "title": "Automatic recovery cannot safely finish",
                        "message": str(error),
                        "instruction": "Keep this job and its journal. Do not delete files to unblock it. "
                                       "Open the log for the failure details; pending catalog recovery requires "
                                       "closing and restarting Momentum, while other failures need the recorded "
                                       "file/process issue resolved before reviewing recovery again."}

    def reconcile_install(self, jid, expected_missing=None):
        """Finish a failed package receipt commit after explicit user reconciliation."""
        with self.submit_lock:
            try:
                job, result, missing = self._reconciliation_proposal(jid)
                if expected_missing is not None and set(expected_missing) != missing:
                    raise InstallError("Optional media changed after review; review recovery again")
                previous = job["steps"][-1]["context"].get("previous_receipt")
                with self._receipt_guard(job["meta"]["package_id"]):
                    if self._load_receipt(job["meta"]["package_id"]) != previous:
                        raise InstallError("Installation receipt changed; journal retained")
                    receipt = self._receipt_from(job, result)
                    policy = {"kind": "omit-missing-user-state", "paths": sorted(missing)} if missing else None
                    self._complete_commit(job, receipt, result, recovery_policy=policy)
                return True
            except (InstallError, ownership.OwnershipError, OSError, ValueError, KeyError, TypeError) as e:
                return f"Recovery stopped safely: {e}. The journal is retained."

    def recover_pending_catalog(self):
        for d in (self.here / "jobs").glob("j*/catalog-pending.json"):
            jid = d.parent.name
            job = self.jobs.jobs.get(jid)
            if job is None:
                raise InstallError(f"Orphaned catalog recovery journal: {d}")
            try:
                if job.get("surviving"):
                    raise InstallError("Installation processes are still running; catalog recovery deferred")
                marker = json.loads(d.read_text())
                if marker.get("commit_version") != 1 or marker.get("job_id") != jid:
                    raise InstallError("Unsupported or damaged catalog recovery journal")
                rec, result = marker["receipt"], marker["result"]
                with self._receipt_guard(job["meta"]["package_id"]):
                    policy = marker.get("recovery_policy")
                    missing = set()
                    if policy is not None:
                        if (not isinstance(policy, dict) or policy.get("kind") != "omit-missing-user-state"
                                or not isinstance(policy.get("paths"), list)
                                or not all(isinstance(p, str) for p in policy["paths"])):
                            raise InstallError("Unsupported recovery policy; evidence retained")
                        missing = set(policy["paths"])
                        if self._missing_user_state(job) != missing:
                            raise InstallError("Optional media changed after recovery approval; evidence retained")
                    self._validate_result(job, result, missing_user_state=missing)
                    if rec.get("last_job_id") != jid or rec.get("package_id") != result["package_id"]:
                        raise InstallError("Receipt recovery identity mismatch")
                    for key in ("package_version", "package_digest", "paths", "game_directory", "resources",
                                "installation", "readiness"):
                        if rec.get(key) != result.get(key):
                            raise InstallError(f"Receipt recovery {key} differs from validated result")
                    current = self._load_receipt(rec["package_id"])
                    previous = job["steps"][-1]["context"].get("previous_receipt")
                    if current != previous and (not current or current.get("last_job_id") != jid
                            or current.get("installation_id") != rec.get("installation_id")):
                        raise InstallError("A newer receipt exists; recovery will not overwrite it")
                    self._complete_commit(job, rec, result, recovery_policy=policy)
            except (InstallError, ownership.OwnershipError, OSError, ValueError, KeyError, TypeError) as e:
                with self.jobs.lock:
                    job["manual"] = True
                    self.jobs._finish(job, "failed", f"Catalog recovery needs attention: {e}. Evidence retained.")


def shlex_quote(s):
    return shlex.quote(s)
