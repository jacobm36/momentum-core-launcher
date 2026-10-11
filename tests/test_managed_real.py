"""Opt-in real isolated provisioning and exact package runner checks; retained evidence."""
import copy
import json
import os
from pathlib import Path
import runpy
import threading
import time
import unittest
from unittest import mock

import installs
import jobs
import managed_flatpak
import packages


@unittest.skipUnless(os.environ.get("MCL_REAL_MANAGED_TESTS") == "1",
                     "opt-in downloads and exact real-Flatpak managed runner")
class RealManagedInstalls(unittest.TestCase):
    def test_exact_real_software_and_game_approvals(self):
        supplied = os.environ.get("MCL_REAL_MANAGED_ROOT")
        self.assertIsNotNone(supplied, "Supply a new absolute retained validation root.")
        root = managed_flatpak.safe(supplied)
        self.assertFalse(root.exists(), "Never overwrite a validation root.")
        root.mkdir(mode=0o700)
        home, app = root / "home", root / "launcher"
        home.mkdir()
        app.mkdir()
        checker = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                                    "tools/check-managed-flatpak-prototype.py"))
        baseline = checker["normal_snapshot"]()
        (root / "normal-before.json").write_text(json.dumps(baseline, indent=2))
        source = {
            "flycast": Path(os.environ["MCL_REAL_HOD2_SOURCE"]),
            "uzdoom": Path(os.environ["MCL_REAL_DOOM_SOURCE"]),
        }
        before_media = {runtime: checker["fingerprint"](path) for runtime, path in source.items()}
        results = []
        repo = Path(__file__).resolve().parents[2] / "momentum-packages"

        def wait(runner, jid):
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                result = runner.get(jid)
                if result["status"] not in jobs.RUNNING:
                    return result
                time.sleep(.1)
            self.fail(f"Timed out; retain job: {runner.get(jid)}")

        with mock.patch.dict(os.environ, {
            "HOME": str(home), "MCL_TEST_ISOLATED_ENGINES": "1",
            "XDG_DATA_HOME": str(home / ".local/share"),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_STATE_HOME": str(home / ".local/state"),
        }):
            runner = jobs.Jobs(app / "jobs")
            catalog = []
            inst = installs.Installs(app, threading.Lock(), lambda: catalog,
                                     lambda data: catalog.__setitem__(slice(None), data), runner)
            runner.before_step, runner.on_success = inst.before_step, inst.on_success
            try:
                for runtime, game in (("flycast", "the-house-of-the-dead-2"), ("uzdoom", "brutal-doom")):
                    info = packages.import_package(repo / f"dist/{game}-0.3.0.zip", app)
                    path = Path(installs.__file__).parent / (
                        "docs/hod2-target-evidence.json" if runtime == "flycast"
                        else "docs/doom-installer-evidence.json")
                    original_read = Path.read_text
                    evidence = json.loads(original_read(path))
                    if runtime == "flycast" and not any(
                            p["version"] == "0.3.0" for p in evidence["derived_packages"]):
                        evidence["derived_packages"].append({
                            "version": "0.3.0", "digest": info["digest"], "basis": "Provisional real runner."})
                    elif runtime == "uzdoom" and not any(
                            p["id"] == game and p["version"] == "0.3.0" for p in evidence["packages"]):
                        record = copy.deepcopy(next(p for p in evidence["packages"]
                                                    if p["id"] == game and p["version"] == "0.2.0"))
                        record.update(version="0.3.0", digest=info["digest"])
                        evidence["packages"].append(record)

                    def read(file, *args, **kwargs):
                        if file == path and os.environ.get("MCL_CANDIDATE_EVIDENCE") == "1":
                            return json.dumps(evidence)
                        return original_read(file, *args, **kwargs)

                    with mock.patch.object(Path, "read_text", read):
                        detail = inst.package_details(game, "0.3.0")
                        self.assertIsNotNone(detail["managed_fallback"], detail)
                        jid = inst.submit_install(game, "0.3.0", str(source[runtime]),
                                                  trusted_digest=info["digest"])
                        job = wait(runner, jid)
                        self.assertEqual(job["status"], "awaiting-approval", job)
                        self.assertEqual(job["plan"]["managed_engine"], managed_flatpak.CONTRACT)
                        self.assertFalse((home / "Games" / game).exists())
                        self.assertIs(inst.approve(jid, job["plan_digest"]), True)
                        job = wait(runner, jid)
                        self.assertEqual(job["status"], "awaiting-approval", job)
                        self.assertNotEqual(job["plan"]["operation"], "prepare-dependency")
                        self.assertFalse((home / "Games" / game).exists())
                        self.assertIs(inst.approve(jid, job["plan_digest"]), True)
                        self.assertEqual(wait(runner, jid)["status"], "succeeded", runner.get(jid))
                        receipt = inst._load_receipt(game)
                        bound = receipt["dependencies"][runtime]["managed"]
                        managed_flatpak.validate_binding(bound)
                        repeat = inst.submit_install(game, "0.3.0", str(source[runtime]),
                                                     trusted_digest=info["digest"])
                        job = wait(runner, repeat)
                        self.assertEqual(job["status"], "awaiting-approval", job)
                        self.assertEqual(job["plan"]["actions"], [])
                        self.assertIs(inst.approve(repeat, job["plan_digest"]), True)
                        self.assertEqual(wait(runner, repeat)["status"], "succeeded", runner.get(repeat))
                        results.append({"package_id": game, "version": "0.3.0", "digest": info["digest"],
                                        "initial_job": jid, "repeat_job": repeat, "binding": bound,
                                        "slot": managed_flatpak.inspect(runtime),
                                        "separate_approvals": True, "repeat_no_file_changes": True})
                        print("REAL MANAGED RUNNER PASS:", game, info["digest"], flush=True)
            finally:
                runner.close()
        for runtime, media in source.items():
            self.assertEqual(checker["fingerprint"](media), before_media[runtime])
        self.assertEqual(checker["normal_snapshot"](), baseline)
        (root / "real-runner-evidence.json").write_text(json.dumps({
            "status": "passed", "packages": results,
            "normal_engines_profiles_unchanged": True, "original_media_unchanged": True,
            "limits": "Actual acquisition and exact install/repeat only; graphical launch tested separately."},
            indent=2))
