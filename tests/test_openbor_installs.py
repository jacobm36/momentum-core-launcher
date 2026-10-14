"""Opt-in exact OpenBOR package through the real runner; no gameplay launch."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

import installs
import jobs
import openbor
import packages
import compatibility
from tests.test_openbor import provisional_record

REPO = Path(os.environ.get("MCL_PACKAGE_REPO",
                          str(Path(__file__).resolve().parents[2] / "momentum-packages")))
GAME = os.environ.get("MCL_OPENBOR_GAME", "marvel-infinity-war")
SPECS = {
    "marvel-infinity-war": dict(version="0.3.0", previous="0.2.0", pak="Marvel_Infinity_War.pak",
                                cfg="Marvel_Infinity_War.cfg", downloads=True,
                                cfg_sha256="11d2e516a0b924cb88d2fab1fe940431885d4a838cded8fb02f955989761f43a"),
    # User-supplied PAK only; requires MCL_OPENBOR_SOURCE.
    "ultimate-double-dragon-3": dict(version="0.1.0", previous=None, pak="UDD_3.0.pak",
                                     cfg="UDD_3.0.cfg", downloads=False,
                                     cfg_sha256="f106c4ce5b830697a0442f9922c4a73e18bf1411abd52a9120e345f0e120f37b"),
}
SPEC = SPECS[GAME]
VERSION = os.environ.get("MCL_OPENBOR_VERSION", SPEC["version"])
PREVIOUS = SPEC["previous"]


def offline_inputs(games_root, source):
    inputs = {"games_root": str(games_root), "source_dir": str(source)}
    if SPEC["downloads"]:
        inputs["download_game"] = False
    return inputs


def pak_pin(manifest):
    ext = manifest["extensions"]
    if "game_download" in ext:
        return ext["game_download"]["pak_size"], ext["game_download"]["pak_sha256"]
    return ext["source_pak"]["size"], ext["source_pak"]["sha256"]


def layout(detail):
    return openbor.requirement_layout(detail["manifest"]["requires"][0])


@unittest.skipUnless(os.environ.get("MCL_OPENBOR_TESTS") == "1",
                     "opt-in exact OpenBOR acquisition/lifecycle integration")
class OpenBORInstalls(unittest.TestCase):
    def wait(self, runner, jid):
        deadline = time.monotonic() + 1900
        while time.monotonic() < deadline:
            job = runner.get(jid)
            if job["status"] not in jobs.RUNNING:
                return job
            time.sleep(.05)
        self.fail(f"Timed out: {runner.get(jid)}")

    def test_exact_acquisition_lifecycle_and_preserved_state(self):
        work = os.environ.get("MCL_OPENBOR_WORK")
        if work:
            root = Path(work)
            root.mkdir(parents=True, exist_ok=False)
        else:
            temporary = tempfile.TemporaryDirectory(prefix="openbor-runner-")
            self.addCleanup(temporary.cleanup)
            root = Path(temporary.name)
        home, app, source = [root / p for p in ("home with spaces", "launcher", "source")]
        for directory in (home, app, source):
            directory.mkdir()
        offline = os.environ.get("MCL_OPENBOR_SOURCE")
        if not SPEC["downloads"] and not offline:
            self.skipTest("this package requires MCL_OPENBOR_SOURCE")
        library = []
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            imported = packages.import_package(REPO / f"dist/{GAME}-{VERSION}.zip", app)
            if os.environ.get("MCL_CANDIDATE_EVIDENCE") == "1":
                original = compatibility.find_record
                record = dict(provisional_record(imported["digest"]), id=GAME, version=VERSION)
                def find(launcher, game, version, digest):
                    if (game, version, digest) == (GAME, VERSION, imported["digest"]):
                        return record
                    return original(launcher, game, version, digest)
                override = mock.patch.object(compatibility, "find_record", side_effect=find)
                override.start()
                self.addCleanup(override.stop)
            runner = jobs.Jobs(app / "jobs")
            inst = installs.Installs(app, threading.RLock(), lambda: library,
                                     lambda data: library.__setitem__(slice(None), data), runner)
            runner.before_step, runner.on_success = inst.before_step, inst.on_success
            self.addCleanup(runner.close)
            detail = inst.package_details(GAME, VERSION)
            self.assertTrue(detail["package_supported"], detail)
            self.assertFalse(detail["install_enabled"])
            if offline:
                inputs = offline_inputs(home / "Games", offline)
            else:
                inputs = {"games_root": str(home / "Games"), "download_game": True}
            jid = inst.submit_install(GAME, VERSION, inputs=inputs, trusted_digest=imported["digest"])
            job = self.wait(runner, jid)
            self.assertEqual(job["status"], "awaiting-approval", job)
            self.assertEqual(job["plan"]["operation"], "prepare-dependency")
            self.assertFalse(openbor.target_root(layout(detail)).exists())
            self.assertFalse((home / "Games").exists())
            self.assertIs(inst.approve(jid, job["plan_digest"]), True)
            job = self.wait(runner, jid)
            self.assertEqual(job["status"], "awaiting-approval", job)
            self.assertEqual(job["plan"]["operation"], "install")
            self.assertEqual(bool(job["plan"]["network"]), not bool(offline))
            self.assertTrue(openbor.verify(openbor.target_root(layout(detail))))
            self.assertFalse((home / "Games").exists())
            self.assertIs(inst.approve(jid, job["plan_digest"]), True)
            job = self.wait(runner, jid)
            self.assertEqual(job["status"], "succeeded", job)
            receipt = inst._load_receipt(GAME)
            game = Path(receipt["game_directory"])
            self.assertEqual(game, home / "Games" / GAME)
            pak = game / "Paks" / SPEC["pak"]
            pak_size, pak_sha256 = pak_pin(detail["manifest"])
            self.assertEqual(pak.stat().st_size, pak_size)
            self.assertEqual(installs._hash_file(pak), pak_sha256)
            source_pak = source / pak.name
            shutil.copyfile(pak, source_pak)
            self.assertEqual(installs._hash_file(source_pak), pak_sha256)
            cfg = game / "Saves" / SPEC["cfg"]
            self.assertEqual(hashlib.sha256(cfg.read_bytes()).hexdigest(), SPEC["cfg_sha256"])
            cfg.write_bytes(b"player changed settings")
            save = game / "Saves/player.sav"
            save.write_bytes(b"player progress")
            engine_before = openbor.detect(layout(detail))
            self.assertEqual(len(library), 1)
            for field in [f for f in ("icon", "cover", "video") if detail["manifest"]["catalog"].get(f)]:
                self.assertTrue(library[0][field].startswith("media/"), library)
                self.assertTrue((app / library[0][field]).is_file())
            template = copy.deepcopy(runner.jobs[jid]["steps"][-1]["context"])
            operation_meta = copy.deepcopy(runner.jobs[jid]["meta"])

            def operation(name):
                current = inst.package_details(GAME, VERSION)
                context = dict(template, operation=name, previous_receipt=inst._load_receipt(GAME),
                               dependencies=current["dependencies"],
                               inputs=offline_inputs(game.parent, source))
                steps = [{
                    "name": name + " " + phase, "protocol": True,
                    "approve_after": phase == "preflight",
                    "declared_steps": current["manifest"]["operations"][name]["steps"],
                    "argv": ["bash", name + ".sh", "--context", "{context_file}", "--phase", phase],
                    "cwd": context["package_root"], "context": dict(context, phase=phase)}
                         for phase in ("preflight", "apply")]
                if name == "verify":
                    steps = steps[:1]
                    steps[0]["approve_after"] = False
                    opid = runner.submit(name, steps, game=GAME, meta={"kind": "verification"})
                    verified = self.wait(runner, opid)
                    self.assertEqual(verified["status"], "succeeded", verified)
                    return
                opid = runner.submit(name, steps, game=GAME, meta=dict(operation_meta, operation=name))
                reviewed = self.wait(runner, opid)
                self.assertEqual(reviewed["status"], "awaiting-approval", reviewed)
                self.assertEqual(reviewed["plan"]["network"], [])
                self.assertIs(inst.approve(opid, reviewed["plan_digest"]), True)
                self.assertEqual(self.wait(runner, opid)["status"], "succeeded", runner.get(opid))

            jid = inst.submit_install(GAME, VERSION, inputs=inputs, trusted_digest=imported["digest"])
            job = self.wait(runner, jid)
            self.assertEqual(job["status"], "awaiting-approval", job)
            self.assertEqual(job["plan"]["actions"], [])
            self.assertEqual(job["plan"]["network"], [])
            self.assertIs(inst.approve(jid, job["plan_digest"]), True)
            self.assertEqual(self.wait(runner, jid)["status"], "succeeded", runner.get(jid))
            operation("verify")
            pak.unlink()
            operation("repair")
            self.assertEqual(installs._hash_file(pak), pak_sha256)
            operation("uninstall")
            self.assertFalse(pak.exists())
            self.assertEqual(cfg.read_bytes(), b"player changed settings")
            self.assertEqual(save.read_bytes(), b"player progress")
            self.assertEqual(openbor.detect(layout(detail)), engine_before)
            jid = inst.submit_install(GAME, VERSION, inputs=offline_inputs(
                home / "different requested root", source), trusted_digest=imported["digest"])
            job = self.wait(runner, jid)
            self.assertEqual(job["status"], "awaiting-approval", job)
            self.assertEqual(job["plan"]["game_directory"], str(game))
            self.assertIs(inst.approve(jid, job["plan_digest"]), True)
            self.assertEqual(self.wait(runner, jid)["status"], "succeeded", runner.get(jid))
            self.assertEqual(cfg.read_bytes(), b"player changed settings")
            self.assertEqual(save.read_bytes(), b"player progress")
            self.assertEqual(inst._load_receipt(GAME)["installation_id"], receipt["installation_id"])
            self.assertEqual(openbor.detect(layout(detail)), engine_before)
            self.assertEqual(len(library), 1)
            (root / "validation.json").write_text(json.dumps({
                "scope": "exact native acquisition and lifecycle; no gameplay launched",
                "package": imported, "online_acquisition": not bool(offline),
                "pak_sha256": installs._hash_file(pak), "engine": engine_before,
                "checks": ["separate approvals", "fresh", "repeat-no-download", "verify",
                           "repair-missing-PAK", "remove-preserves-state-engine",
                           "reinstall-preserves-path-state-identity", "served-artwork"]
            }, indent=2) + "\n")


    def _install(self, inst, runner, version, inputs, digest, prepare):
        jid = inst.submit_install(GAME, version, inputs=inputs, trusted_digest=digest)
        job = self.wait(runner, jid)
        if prepare:
            self.assertEqual(job["status"], "awaiting-approval", job)
            self.assertEqual(job["plan"]["operation"], "prepare-dependency")
            self.assertIs(inst.approve(jid, job["plan_digest"]), True)
            job = self.wait(runner, jid)
        self.assertEqual(job["status"], "awaiting-approval", job)
        self.assertEqual(job["plan"]["operation"], "install")
        self.assertEqual(job["plan"]["network"], [])
        plan = job["plan"]
        self.assertIs(inst.approve(jid, job["plan_digest"]), True)
        self.assertEqual(self.wait(runner, jid)["status"], "succeeded", runner.get(jid))
        return plan

    @unittest.skipUnless(os.environ.get("MCL_OPENBOR_SOURCE") and PREVIOUS,
                         "offline PAK folder and a previous release required for upgrade check")
    def test_upgrade_from_previous_release_preserves_state_and_legacy_engine(self):
        temporary = tempfile.TemporaryDirectory(prefix="openbor-upgrade-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        home, app = root / "home with spaces", root / "launcher"
        home.mkdir()
        app.mkdir()
        library = []
        inputs = {"games_root": str(home / "Games"), "download_game": False,
                  "source_dir": os.environ["MCL_OPENBOR_SOURCE"]}
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            old = packages.import_package(REPO / f"dist/{GAME}-{PREVIOUS}.zip", app)
            new = packages.import_package(REPO / f"dist/{GAME}-{VERSION}.zip", app)
            if os.environ.get("MCL_CANDIDATE_EVIDENCE") == "1":
                original = compatibility.find_record
                record = provisional_record(new["digest"])
                record["version"] = VERSION
                def find(launcher, game, version, digest):
                    if (game, version, digest) == (GAME, VERSION, new["digest"]):
                        return record
                    return original(launcher, game, version, digest)
                override = mock.patch.object(compatibility, "find_record", side_effect=find)
                override.start()
                self.addCleanup(override.stop)
            runner = jobs.Jobs(app / "jobs")
            inst = installs.Installs(app, threading.RLock(), lambda: library,
                                     lambda data: library.__setitem__(slice(None), data), runner)
            runner.before_step, runner.on_success = inst.before_step, inst.on_success
            self.addCleanup(runner.close)
            self._install(inst, runner, PREVIOUS, inputs, old["digest"], prepare=True)
            legacy = openbor.target_root("legacy")
            legacy_facts = openbor.detect("legacy")
            first = inst._load_receipt(GAME)
            game = Path(first["game_directory"])
            launcher = Path(first["paths"]["launcher"])
            self.assertIn(str(legacy), launcher.read_text())
            cfg, save = game / "Saves/Marvel_Infinity_War.cfg", game / "Saves/player.sav"
            cfg.write_bytes(b"player changed settings")
            save.write_bytes(b"player progress")
            detail = inst.package_details(GAME, VERSION)
            self.assertEqual(layout(detail), "build")
            self.assertTrue(detail["package_supported"], detail)
            self.assertFalse(detail["install_enabled"])
            plan = self._install(inst, runner, VERSION, inputs, new["digest"], prepare=True)
            replaced = [a for a in plan["actions"] if a["path"] == str(launcher)]
            self.assertEqual([a["op"] for a in replaced], ["replace"])
            receipt = inst._load_receipt(GAME)
            self.assertEqual(receipt["package_version"], VERSION)
            self.assertEqual(receipt["installation_id"], first["installation_id"])
            self.assertEqual(receipt["game_directory"], str(game))
            build = openbor.target_root("build")
            self.assertTrue(openbor.verify(build))
            self.assertIn(str(build / "usr/bin/OpenBOR"), launcher.read_text())
            self.assertNotIn(str(legacy) + "/", launcher.read_text())
            self.assertTrue(Path(replaced[0]["backup"]).is_file())
            self.assertEqual(openbor.detect("legacy"), legacy_facts)
            self.assertEqual(cfg.read_bytes(), b"player changed settings")
            self.assertEqual(save.read_bytes(), b"player progress")
            self.assertEqual(len(library), 1)
            self.assertTrue(inst.package_details(GAME, VERSION)["install_enabled"])


if __name__ == "__main__":
    unittest.main()
