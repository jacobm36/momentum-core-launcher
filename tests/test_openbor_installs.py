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
GAME = "marvel-infinity-war"
VERSION = "0.2.0"


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
        library = []
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            imported = packages.import_package(REPO / f"dist/{GAME}-{VERSION}.zip", app)
            if os.environ.get("MCL_CANDIDATE_EVIDENCE") == "1":
                original = compatibility.find_record
                record = provisional_record(imported["digest"])
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
            inputs = {"games_root": str(home / "Games"), "download_game": not bool(offline)}
            if offline:
                inputs["source_dir"] = offline
            jid = inst.submit_install(GAME, VERSION, inputs=inputs, trusted_digest=imported["digest"])
            job = self.wait(runner, jid)
            self.assertEqual(job["status"], "awaiting-approval", job)
            self.assertEqual(job["plan"]["operation"], "prepare-dependency")
            self.assertFalse(openbor.target_root().exists())
            self.assertFalse((home / "Games").exists())
            self.assertIs(inst.approve(jid, job["plan_digest"]), True)
            job = self.wait(runner, jid)
            self.assertEqual(job["status"], "awaiting-approval", job)
            self.assertEqual(job["plan"]["operation"], "install")
            self.assertEqual(bool(job["plan"]["network"]), not bool(offline))
            self.assertTrue(openbor.verify(openbor.target_root()))
            self.assertFalse((home / "Games").exists())
            self.assertIs(inst.approve(jid, job["plan_digest"]), True)
            job = self.wait(runner, jid)
            self.assertEqual(job["status"], "succeeded", job)
            receipt = inst._load_receipt(GAME)
            game = Path(receipt["game_directory"])
            self.assertEqual(game, home / "Games" / GAME)
            pak = game / "Paks/Marvel_Infinity_War.pak"
            pin = detail["manifest"]["extensions"]["game_download"]
            self.assertEqual(pak.stat().st_size, pin["pak_size"])
            self.assertEqual(installs._hash_file(pak), pin["pak_sha256"])
            source_pak = source / pak.name
            shutil.copyfile(pak, source_pak)
            self.assertEqual(installs._hash_file(source_pak), pin["pak_sha256"])
            cfg = game / "Saves/Marvel_Infinity_War.cfg"
            self.assertEqual(hashlib.sha256(cfg.read_bytes()).hexdigest(),
                             "11d2e516a0b924cb88d2fab1fe940431885d4a838cded8fb02f955989761f43a")
            cfg.write_bytes(b"player changed settings")
            save = game / "Saves/player.sav"
            save.write_bytes(b"player progress")
            engine_before = openbor.detect()
            self.assertEqual(len(library), 1)
            for field in ("icon", "cover", "video"):
                self.assertTrue(library[0][field].startswith("media/"), library)
                self.assertTrue((app / library[0][field]).is_file())
            template = copy.deepcopy(runner.jobs[jid]["steps"][-1]["context"])
            operation_meta = copy.deepcopy(runner.jobs[jid]["meta"])

            def operation(name):
                current = inst.package_details(GAME, VERSION)
                context = dict(template, operation=name, previous_receipt=inst._load_receipt(GAME),
                               dependencies=current["dependencies"],
                               inputs={"games_root": str(game.parent), "download_game": False,
                                       "source_dir": str(source)})
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
            self.assertEqual(installs._hash_file(pak), pin["pak_sha256"])
            operation("uninstall")
            self.assertFalse(pak.exists())
            self.assertEqual(cfg.read_bytes(), b"player changed settings")
            self.assertEqual(save.read_bytes(), b"player progress")
            self.assertEqual(openbor.detect(), engine_before)
            jid = inst.submit_install(GAME, VERSION, inputs={
                "games_root": str(home / "different requested root"),
                "download_game": False, "source_dir": str(source)}, trusted_digest=imported["digest"])
            job = self.wait(runner, jid)
            self.assertEqual(job["status"], "awaiting-approval", job)
            self.assertEqual(job["plan"]["game_directory"], str(game))
            self.assertIs(inst.approve(jid, job["plan_digest"]), True)
            self.assertEqual(self.wait(runner, jid)["status"], "succeeded", runner.get(jid))
            self.assertEqual(cfg.read_bytes(), b"player changed settings")
            self.assertEqual(save.read_bytes(), b"player progress")
            self.assertEqual(inst._load_receipt(GAME)["installation_id"], receipt["installation_id"])
            self.assertEqual(openbor.detect(), engine_before)
            self.assertEqual(len(library), 1)
            (root / "validation.json").write_text(json.dumps({
                "scope": "exact native acquisition and lifecycle; no gameplay launched",
                "package": imported, "online_acquisition": not bool(offline),
                "pak_sha256": installs._hash_file(pak), "engine": engine_before,
                "checks": ["separate approvals", "fresh", "repeat-no-download", "verify",
                           "repair-missing-PAK", "remove-preserves-state-engine",
                           "reinstall-preserves-path-state-identity", "served-artwork"]
            }, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
