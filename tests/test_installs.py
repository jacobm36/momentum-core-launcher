import json
import os
import sys
import tempfile
import threading
import copy
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import installs
import ownership
from unittest import mock


class DummyLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DummyJobs:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.jobs = {}

    def paths(self, jid):
        d = self.root / jid
        return {"job_dir": d, "intent_file": d / "intents.jsonl", "results_dir": d / "results",
                "approved_plan_file": d / "approved-plan.json"}

    def _finish(self, job, status, error=None):
        job.update(status=status, error=error)


class InstallsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.games_file = self.root / "games.json"
        self.games = [{"id": "hod", "name": "HOD", "exec": "/old", "tags": ["A"], "cover": None, "video": None, "icon": None}]
        self.games_file.write_text(json.dumps(self.games))
        self.jobs = DummyJobs(self.root / "jobs")
        self.jobs.paths("j00000001")["results_dir"].mkdir(parents=True)
        self.jobs.paths("j00000001")["intent_file"].write_text("")
        self.inst = installs.Installs(
            self.root,
            DummyLock(),
            read_raw_games=lambda: json.loads(self.games_file.read_text()),
            write_games=lambda g: self.games_file.write_text(json.dumps(g)),
            jobs=self.jobs,
        )
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.root / "home")
        Path(os.environ["HOME"]).mkdir()

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.tmp.cleanup()

    def test_merge_previous_defaults_rule(self):
        entry = {"name": "Old Name", "description": "", "tags": ["Rail"], "icon": None}
        defaults = {"name": "New Name", "description": "Desc", "tags": ["Rail", "Mouse"], "icon": "/i"}
        prev = {"name": "Old Name", "tags": ["Rail"]}
        out = installs._merge_catalog(entry, defaults, prev, first_association=False)
        self.assertEqual(out["name"], "New Name")  # unchanged-from-default updated
        self.assertEqual(out["description"], "")  # explicit clear is not a missing key
        self.assertEqual(out["tags"], ["Rail", "Mouse"])
        self.assertIsNone(out["icon"])  # artwork never auto-refilled after first association

    def test_first_association_preserves_existing_and_fills_missing(self):
        entry = {"name": "Personal", "description": "", "tags": [], "icon": None}
        defaults = {"name": "Pkg Name", "description": "Pkg Desc", "tags": ["A"], "icon": "/i"}
        out = installs._merge_catalog(entry, defaults, {}, first_association=True)
        self.assertEqual(out["name"], "Personal")
        self.assertEqual(out["description"], "")
        self.assertEqual(out["tags"], [])
        self.assertEqual(out["icon"], "/i")

    def test_missing_defaults_seed_and_removed_unchanged_defaults_disappear(self):
        out = installs._merge_catalog({"name": "Old", "category": "Mine"}, {"description": "New"},
                                      {"name": "Old", "category": "Old"}, first_association=False)
        self.assertNotIn("name", out)
        self.assertEqual(out["category"], "Mine")
        self.assertEqual(out["description"], "New")

    def test_corrupt_receipt_is_not_treated_as_a_fresh_install(self):
        path = self.inst._receipt_path("test-game")
        path.parent.mkdir(parents=True)
        path.write_text("{broken")
        with self.assertRaises(installs.InstallError):
            self.inst._load_receipt("test-game")

    def fixture(self, association="hod"):
        job = {"id": "j00000001", "steps": [{}, {}], "meta": {
            "kind": "install", "package_id": "the-house-of-the-dead-2", "package_version": "0.1.1",
            "package_digest": "sha256:" + "a" * 64, "operation": "install",
            "game_directory": str(self.root / "Games" / "HOD"),
            "paths": {
                "launcher": str(self.root / ".local/bin/hod"),
                "desktop_entry": str(self.root / ".local/share/applications/hod.desktop"),
                "icon": str(self.root / ".local/share/icons/hod.png"),
                "support": str(self.root / ".local/share/momentum-core/packages/hod"),
                "state": str(self.root / ".local/share/momentum-core/state/hod"),
                "backup": str(self.root / ".local/share/momentum-core/backups/hod"),
            },
        }}
        for p in [job["meta"]["game_directory"], job["meta"]["paths"]["support"]]:
            Path(p).mkdir(parents=True, exist_ok=True)
        f = Path(job["meta"]["paths"]["launcher"])
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("#!/bin/sh\n")
        os.chmod(f, 0o755)
        self.jobs.paths(job["id"])["intent_file"].write_text(
            json.dumps({
                "intent_version": 1, "job_id": "j00000001", "seq": 1, "step": "configure",
                "op": "create", "path": str(f), "ownership": "managed",
                "before": {"kind": "absent", "sha256": None},
                "after": {"kind": "file", "sha256": installs._hash_file(f)}, "backup": None
            }) + "\n"
        )
        result = {
            "job_id": job["id"], "operation": "install", "phase": "apply",
            "outcome": "succeeded",
            "package_id": job["meta"]["package_id"],
            "package_version": job["meta"]["package_version"],
            "package_digest": job["meta"]["package_digest"],
            "installation": "installed",
            "readiness": "setup-required",
            "resources": [
                {"path": str(f), "kind": "file", "ownership": "managed", "sha256": installs._hash_file(f)},
                {"path": str(Path(job["meta"]["game_directory"])), "kind": "directory", "ownership": "managed", "sha256": None},
            ],
            "published_changes": [],
            "checks": [],
            "completed_steps": [],
            "recovery_notes": [],
            "pending_actions": [],
            "dependencies": {"flycast": {"provider": "flatpak"}},
            "catalog_entry_id": association,
            "paths": job["meta"]["paths"],
            "game_directory": job["meta"]["game_directory"],
            "source_reference": "/src",
            "receipt_committed": False,
            "catalog_proposal": {
                "defaults": {"name": "The House of the Dead 2", "description": "Desc", "tags": ["Rail Shooter"]},
                "launch_argv": [str(f)],
                "working_directory": job["meta"]["game_directory"],
            },
            "state": {},
        }
        context = dict(job["meta"], inputs={"source_dir": "/src"}, previous_receipt=None,
                       catalog_entry_id=association)
        job["meta"]["catalog_defaults"] = copy.deepcopy(result["catalog_proposal"]["defaults"])
        job["steps"][-1] = {"context": context, "declared_steps": ["configure"]}
        actions, changes, records = [], [], []
        for seq, resource in enumerate(result["resources"], 1):
            action = {"path": resource["path"], "op": "create" if resource["kind"] == "file" else "mkdir",
                      "ownership": "managed", "before": {"kind": "absent", "sha256": None},
                      "after": {k: resource[k] for k in ("kind", "sha256")}, "backup": None}
            records.append(dict(action, intent_version=1, job_id=job["id"], seq=seq, step="configure"))
            changes.append(dict(resource, intent_seq=seq))
            actions.append(action)
        result["published_changes"] = changes
        plan = {k: context[k] for k in ("package_id", "package_version", "package_digest", "operation",
                                        "inputs", "game_directory", "paths", "catalog_entry_id")}
        plan.update(job_id=job["id"], actions=actions,
                    previous_receipt_digest=ownership.digest(ownership.packed(None)).removeprefix("sha256:"))
        envelope = ownership.packed({"phase": "preflight", "outcome": "succeeded", "plan": plan})
        self.jobs.paths(job["id"])["approved_plan_file"].write_bytes(envelope)
        job["approved_plan_digest"] = ownership.digest(envelope)
        self.jobs.paths(job["id"])["intent_file"].write_bytes(
            b"".join(ownership.packed(record) for record in records))
        (self.jobs.paths(job["id"])["results_dir"] / "step-1.json").write_text(json.dumps(result))
        self.jobs.jobs[job["id"]] = job
        return job, result

    def test_on_success_writes_receipt_and_catalog(self):
        job, result = self.fixture()
        self.assertIsNone(self.inst.on_success(job))
        rec = json.loads(self.inst._receipt_path(job["meta"]["package_id"]).read_text())
        self.assertEqual(rec["package_id"], job["meta"]["package_id"])
        games = json.loads(self.games_file.read_text())
        hod = next(x for x in games if x["id"] == "hod")
        self.assertEqual(hod["name"], "HOD")  # first association preserves existing descriptive values
        self.assertEqual(hod["description"], "Desc")
        self.assertEqual(hod["install_status"], "installed")
        self.assertEqual(rec["paths"], job["meta"]["paths"])
        self.assertEqual(rec["game_directory"], result["game_directory"])
        self.assertTrue(job["commit_completed"])

    def test_fresh_catalog_entry_seeds_name_tags_not_placeholder_values(self):
        job, _ = self.fixture(association=None)
        self.assertIsNone(self.inst.on_success(job))
        games = json.loads(self.games_file.read_text())
        game = next(g for g in games if g["id"] == job["meta"]["package_id"])
        self.assertEqual(game["name"], "The House of the Dead 2")
        self.assertEqual(game["tags"], ["Rail Shooter"])
        self.assertEqual(games[0]["id"], "hod")

    def test_unproven_ownership_and_changed_files_never_commit(self):
        job, result = self.fixture()
        unowned = Path(job["meta"]["paths"]["support"]) / "unowned.txt"
        unowned.write_text("already here")
        result["resources"].append({"path": str(unowned), "kind": "file", "ownership": "managed",
                                    "sha256": installs._hash_file(unowned)})
        with self.assertRaisesRegex(ownership.OwnershipError, "lacks approved"):
            self.inst._validate_result(job, result)
        result["resources"].pop()
        Path(result["resources"][0]["path"]).write_text("user modification")
        with self.assertRaisesRegex(ownership.OwnershipError, "Filesystem"):
            self.inst._validate_result(job, result)
        self.assertFalse(self.inst._receipt_path(job["meta"]["package_id"]).exists())

    def test_intent_drift_truncated_and_wrong_job_are_rejected(self):
        job, result = self.fixture()
        path = self.jobs.paths(job["id"])["intent_file"]
        original = path.read_bytes()
        for data in (original[:-1], original.replace(b'"seq":1', b'"seq":3'),
                     original.replace(b'"job_id":"j00000001"', b'"job_id":"j00000002"'),
                     original.replace(b'"ownership":"managed"', b'"ownership":"borrowed"')):
            path.write_bytes(data)
            with self.assertRaises(ownership.OwnershipError):
                self.inst._validate_result(job, result)
        path.write_bytes(original)
        self.inst._validate_result(job, result)

    def test_symlink_launch_resource_is_rejected(self):
        job, result = self.fixture()
        launch = Path(result["resources"][0]["path"])
        target = launch.with_suffix(".real")
        launch.rename(target)
        launch.symlink_to(target)
        with self.assertRaisesRegex(ownership.OwnershipError, "Symlink"):
            self.inst._validate_result(job, result)

    def test_noop_repeat_install_retains_identity_and_needs_no_new_intents(self):
        job, result = self.fixture()
        self.assertIsNone(self.inst.on_success(job))
        previous = self.inst._load_receipt(job["meta"]["package_id"])
        job["steps"][-1]["context"]["previous_receipt"] = previous
        job["steps"][-1]["context"]["catalog_entry_id"] = previous["catalog"]["entry_id"]
        result["catalog_entry_id"] = previous["catalog"]["entry_id"]
        result["published_changes"] = []
        raw = json.loads(self.jobs.paths(job["id"])["approved_plan_file"].read_bytes())
        raw["plan"].update(actions=[], catalog_entry_id=previous["catalog"]["entry_id"],
                           previous_receipt_digest=ownership.digest(ownership.packed(previous)).removeprefix("sha256:"))
        data = ownership.packed(raw)
        self.jobs.paths(job["id"])["approved_plan_file"].write_bytes(data)
        job["approved_plan_digest"] = ownership.digest(data)
        self.jobs.paths(job["id"])["intent_file"].write_bytes(b"")
        (self.jobs.paths(job["id"])["results_dir"] / "step-1.json").write_text(json.dumps(result))
        self.assertIsNone(self.inst.on_success(job))
        current = self.inst._load_receipt(job["meta"]["package_id"])
        self.assertEqual(previous["installation_id"], current["installation_id"])
        self.assertEqual(len(json.loads(self.games_file.read_text())), 1)

    def test_catalog_write_failure_retains_receipt_and_recovers_once(self):
        job, result = self.fixture(association=None)
        writer = self.inst.write_games
        with mock.patch.object(self.inst, "write_games", side_effect=OSError("disk full")):
            self.assertIn("disk full", self.inst.on_success(job))
        marker = self.jobs.paths(job["id"])["job_dir"] / "catalog-pending.json"
        self.assertTrue(marker.exists())
        receipt = self.inst._load_receipt(job["meta"]["package_id"])
        self.assertEqual(receipt["installation"], "installed")
        self.assertEqual(len(json.loads(self.games_file.read_text())), 1)
        self.inst.recover_pending_catalog()
        self.assertFalse(marker.exists())
        self.assertFalse(job["manual"])
        self.assertEqual(job["status"], "succeeded")
        recovered = self.inst._load_receipt(job["meta"]["package_id"])
        self.assertEqual(recovered["installation_id"], receipt["installation_id"])
        self.inst.recover_pending_catalog()
        self.assertEqual(len(json.loads(self.games_file.read_text())), 2)
        self.assertEqual(len(recovered["history"]), 1)

    def test_crash_after_catalog_save_preserves_later_edits_and_no_duplicate(self):
        job, _ = self.fixture(association=None)
        real_write = self.inst.write_games
        def save_then_crash(games):
            real_write(games)
            raise OSError("crash after catalog replacement")
        with mock.patch.object(self.inst, "write_games", side_effect=save_then_crash):
            self.assertIn("crash", self.inst.on_success(job))
        games = json.loads(self.games_file.read_text())
        game = games[-1]
        game.update(description="Personal after crash", icon=None, tags=[], favorite=True)
        real_write(games)
        self.inst.recover_pending_catalog()
        games = json.loads(self.games_file.read_text())
        self.assertEqual(len(games), 2)
        self.assertEqual(games[-1]["description"], "Personal after crash")
        self.assertEqual(games[-1]["tags"], [])
        self.assertIsNone(games[-1]["icon"])
        self.assertTrue(games[-1]["favorite"])

    def test_changed_files_during_recovery_preserve_marker_and_fail_closed(self):
        job, result = self.fixture()
        with mock.patch.object(self.inst, "write_games", side_effect=OSError("disk full")):
            self.inst.on_success(job)
        Path(result["resources"][0]["path"]).write_text("modified after commit interruption")
        self.inst.recover_pending_catalog()
        self.assertTrue(job["manual"])
        self.assertEqual(job["status"], "failed")
        self.assertTrue((self.jobs.paths(job["id"])["job_dir"] / "catalog-pending.json").exists())

    def test_catalog_launch_and_identity_proposals_cannot_drift(self):
        job, result = self.fixture()
        for key, value in (("job_id", "j00000002"), ("readiness", "user-confirmed"),
                           ("game_directory", "/another/game")):
            changed = copy.deepcopy(result)
            changed[key] = value
            with self.assertRaises((ownership.OwnershipError, installs.InstallError)):
                self.inst._validate_result(job, changed)
        for key, value in (("launch_argv", ["/unowned/program"]), ("working_directory", "/another/game"),
                           ("defaults", {"name": "Unapproved default"})):
            changed = copy.deepcopy(result)
            changed["catalog_proposal"][key] = value
            with self.assertRaises((ownership.OwnershipError, installs.InstallError)):
                self.inst._validate_result(job, changed)

    def test_recovery_refuses_a_newer_receipt(self):
        job, _ = self.fixture()
        with mock.patch.object(self.inst, "write_games", side_effect=OSError("disk full")):
            self.inst.on_success(job)
        path = self.inst._receipt_path(job["meta"]["package_id"])
        receipt = json.loads(path.read_text())
        receipt["last_job_id"] = "j00000002"
        path.write_text(json.dumps(receipt))
        self.inst.recover_pending_catalog()
        self.assertEqual(json.loads(path.read_text())["last_job_id"], "j00000002")
        self.assertIn("newer receipt", job["error"])
        self.assertTrue((self.jobs.paths(job["id"])["job_dir"] / "catalog-pending.json").exists())

    def test_catalog_referenced_icon_is_copied_to_retained_served_media(self):
        job, result = self.fixture(association=None)
        path = Path(job["meta"]["paths"]["icon"])
        path.parent.mkdir(parents=True)
        path.write_bytes(b"test png bytes")
        resource = {"path": str(path), "kind": "file", "ownership": "managed",
                    "sha256": installs._hash_file(path)}
        result["resources"].append(resource)
        result["catalog_proposal"]["defaults"]["icon"] = str(path)
        job["meta"]["catalog_defaults"]["icon"] = str(path)
        envelope = json.loads(self.jobs.paths(job["id"])["approved_plan_file"].read_text())
        action = dict(path=str(path), op="create", ownership="managed",
                      before={"kind": "absent", "sha256": None},
                      after={"kind": "file", "sha256": resource["sha256"]}, backup=None)
        envelope["plan"]["actions"].append(action)
        record = dict(action, job_id=job["id"], intent_version=1, seq=3, step="configure")
        with self.jobs.paths(job["id"])["intent_file"].open("ab") as f:
            f.write(ownership.packed(record))
        result["published_changes"].append(dict(resource, intent_seq=3))
        data = ownership.packed(envelope)
        self.jobs.paths(job["id"])["approved_plan_file"].write_bytes(data)
        job["approved_plan_digest"] = ownership.digest(data)
        (self.jobs.paths(job["id"])["results_dir"] / "step-1.json").write_text(json.dumps(result))
        with mock.patch.object(self.inst, "write_games", side_effect=OSError("catalog failure")):
            self.assertIn("catalog failure", self.inst.on_success(job))
        self.inst.recover_pending_catalog()
        self.assertEqual(job["status"], "succeeded", job)
        game = json.loads(self.games_file.read_text())[-1]
        self.assertTrue(game["icon"].startswith("media/"))
        self.assertEqual((self.root / game["icon"]).read_bytes(), path.read_bytes())

    def test_approval_revalidates_evidence_receipt_and_running_emulator(self):
        job, _ = self.fixture()
        job.update(status="awaiting-approval", plan_digest="test-digest")
        job["meta"]["install_enabled"] = True
        detail = {"install_enabled": True, "digest": job["meta"]["package_digest"],
                  "dependencies": {"flycast": {"installed": True}}}
        with mock.patch.object(self.inst, "package_details", return_value=detail), \
                mock.patch.object(self.jobs, "approve", return_value=True, create=True) as approve, \
                mock.patch("dependencies.probe", return_value=""):
            self.assertTrue(self.inst.approve(job["id"], "test-digest"))
            approve.assert_called_once()
        with mock.patch.object(self.inst, "package_details", return_value=dict(detail, install_enabled=False)):
            self.assertIn("lacks matching", self.inst.approve(job["id"], "test-digest"))
        with mock.patch.object(self.inst, "package_details", return_value=detail), \
                mock.patch("dependencies.probe", return_value="org.flycast.Flycast\n"):
            self.assertIn("Close Flycast", self.inst.approve(job["id"], "test-digest"))
        with mock.patch.object(self.inst, "package_details", return_value=detail), \
                mock.patch.object(self.inst, "_load_receipt", return_value={"changed": True}):
            self.assertIn("receipt changed", self.inst.approve(job["id"], "test-digest"))


if __name__ == "__main__":
    unittest.main()
