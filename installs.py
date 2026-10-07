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
from contextlib import contextmanager
from pathlib import Path

import packages
import dependencies
import ownership

DESC_FIELDS = ("name", "description", "tagline", "category", "tags")
ART_FIELDS = ("icon", "cover", "video", "screenshots")
OWNERSHIP = {"managed", "borrowed", "user-state", "shared-dependency"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class InstallError(ValueError):
    pass


def _safe_abs(p):
    return isinstance(p, str) and os.path.isabs(p) and not any(c in p for c in "\0\n\r")


def _json_copy(v):
    return json.loads(json.dumps(v))


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
        for req in man["requires"]:
            if req["id"] != "flycast":
                raise InstallError(f"Unsupported dependency resolver: {req['id']}")
            facts["flycast"] = self._flycast_facts(req)
        evidence = json.loads((Path(__file__).parent / "docs/hod2-target-evidence.json").read_text())
        flycast = facts.get("flycast", {})
        approved_packages = [(evidence["package_version"], evidence["package_digest"])]
        approved_packages.extend((p["version"], p["digest"]) for p in evidence.get("derived_packages", []))
        supported = (
            package_id == evidence["package_id"] and (version, summary["digest"]) in approved_packages
            and not summary["platform_issues"])
        enabled = (
            supported
            and flycast.get("installed") is True
            and flycast.get("version") == evidence["emulator_version"]
            and flycast.get("commit") == evidence["emulator_commit"])
        if enabled:
            flycast["capabilities_checked"] = True
            flycast["capability_note"] = (
                "HOD2 gameplay was validated on this Flycast build. Approved artwork-only package revisions "
                "inherit unchanged executable-code evidence; confirm gameplay for each installation.")
            flycast["capability_evidence"] = "docs/hod2-target-evidence.json"
        return dict(summary, manifest=man, home_games=str(Path.home() / "Games"), dependencies=facts,
                    install_enabled=enabled, package_supported=supported)

    @staticmethod
    def _dependency_steps():
        helper = str(Path(__file__).with_name("dependencies.py"))
        return [{"name": name, "protocol": True, "approve_after": phase == "preflight",
                 "declared_steps": ["resolve"],
                 "argv": [sys.executable, helper, "--context", "{context_file}"],
                 "context": {"operation": "prepare-dependency", "phase": phase}}
                for name, phase in [("Check required game software", "preflight"),
                                    ("Prepare required game software", "apply")]]

    def before_step(self, job, index):
        meta = job.get("meta") or {}
        if not meta.get("prepare_required_software") or index != 2:
            return None
        detail = self.package_details(meta["package_id"], meta["package_version"])
        if detail["digest"] != meta["package_digest"] or not detail["install_enabled"]:
            return ("needs-action", "Required game software is not a validated build for this package. "
                    "No game files were installed; Momentum needs updated compatibility evidence.")
        with self.jobs.lock:
            for step in job["steps"][2:]:
                step["context"]["dependencies"] = _json_copy(detail["dependencies"])
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
            return self.jobs.submit("Prepare user-scope Flycast", steps, meta={"kind": "dependency"})

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
        game_dir = str(Path(inputs["games_root"]) / man["destination_name"])
        deps = detail["dependencies"]
        prev = self._load_receipt(package_id)
        paths = prev["paths"] if prev else self._defaults_path(package_id)
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
                "catalog_defaults": {**man["catalog"], "name": man["name"], "icon": paths["icon"]}}
        if detail["package_supported"] and not deps.get("flycast", {}).get("installed"):
            steps = self._dependency_steps() + steps
            meta["prepare_required_software"] = True
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
                if not preparing and (not meta.get("install_enabled") or not detail["install_enabled"]):
                    return ("Game installation is enabled only for approved HOD2 packages with the verified user-scope "
                            "Flycast v2.7 build. Current package/build lacks matching capability evidence.")
                if self._load_receipt(meta["package_id"]) != previous:
                    return "Installation receipt changed since preflight; cancel and review a new job"
                if dependencies.APP in dependencies.probe("ps", "--columns=application").splitlines():
                    return "Close Flycast before approving this installation"
            except (InstallError, ownership.OwnershipError, dependencies.DependencyError, OSError, ValueError) as e:
                return f"Installation approval checks failed: {e}"
        return self.jobs.approve(jid, digest)

    def _validate_result(self, j, res):
        ownership.reconcile(j, res, self.jobs.paths(j["id"]))
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

    def _commit_catalog(self, rec, res, journal=None):
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
                _write_atomic(journal, (json.dumps({"commit_version": 1, "job_id": rec["last_job_id"],
                    "receipt": rec, "result": res}, indent=2) + "\n").encode())
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
                    _write_atomic(journal, (json.dumps({"commit_version": 1, "job_id": rec["last_job_id"],
                        "receipt": rec, "result": res}, indent=2) + "\n").encode())
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

    def _complete_commit(self, job, rec, result):
        journal = self.jobs.paths(job["id"])["job_dir"] / "catalog-pending.json"
        self._commit_catalog(rec, result, journal=journal)
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
                    self._validate_result(job, result)
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
                    self._complete_commit(job, rec, result)
            except (InstallError, ownership.OwnershipError, OSError, ValueError, KeyError, TypeError) as e:
                with self.jobs.lock:
                    job["manual"] = True
                    self.jobs._finish(job, "failed", f"Catalog recovery needs attention: {e}. Evidence retained.")


def shlex_quote(s):
    return shlex.quote(s)
