"""Opt-in real HOD package / fake media integration. Never runs a real emulator.

MCL_HOD_PACKAGE=/absolute/HOD-package.zip python3 -m unittest tests.test_hod_receipts
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import installs
import jobs
import packages


@unittest.skipUnless(os.environ.get("MCL_HOD_PACKAGE"), "opt-in external HOD package integration")
class HodReceipts(unittest.TestCase):
    def test_install_repeat_missing_file_repair_and_catalog_recovery(self):
        self.exercise_install()

    def test_missing_software_prepares_then_continues_same_game_job(self):
        self.exercise_install(initially_missing=True)

    def test_new_untested_build_stops_before_game_files(self):
        self.exercise_install(initially_missing=True, installed_build_matches=False)

    def test_cancel_software_review_changes_nothing(self):
        self.exercise_install(initially_missing=True, cancel_at_approval=True)

    def test_cancel_game_review_retains_prepared_software_without_installing_game(self):
        self.exercise_install(initially_missing=True, cancel_after_preparation=True)

    def exercise_install(self, initially_missing=False, installed_build_matches=True,
                         cancel_at_approval=False, cancel_after_preparation=False):
        source_package = Path(os.environ["MCL_HOD_PACKAGE"]).resolve()
        evidence = json.loads((Path(installs.__file__).parent / "docs/hod2-target-evidence.json").read_text())
        metadata = f"    Version: {evidence['emulator_version']}\n    Commit: {evidence['emulator_commit']}"
        if not installed_build_matches:
            metadata = "    Version: new-untested-build\n    Commit: untested"
        with tempfile.TemporaryDirectory(prefix="mcl-hod-receipts-") as tmp:
            root = Path(tmp)
            home = root / "home with spaces"
            home.mkdir()
            app = root / "launcher"
            app.mkdir()
            mockbin = root / "mockbin"
            mockbin.mkdir()
            flatpak = mockbin / "flatpak"
            installed_marker = root / "software-installed"
            if not initially_missing:
                installed_marker.touch()
            flatpak.write_text(f"""#!{sys.executable}
import sys, pathlib
installed = pathlib.Path({str(installed_marker)!r})
command = sys.argv[1]
if command == 'ps': pass
elif command == 'remotes': print('flathub\\thttps://dl.flathub.org/repo/')
elif command == 'list':
    if installed.exists(): print('org.flycast.Flycast')
elif command == 'info': print({metadata!r})
elif command == 'install':
    assert sys.argv[2:] == ['--user', '--noninteractive', '-y', 'flathub', 'org.flycast.Flycast']
    installed.touch()
else: sys.exit('Unexpected emulator/dependency execution: ' + str(sys.argv))
""")
            flatpak.chmod(0o755)
            source = root / "synthetic source"
            source.mkdir()
            (source / "House of the Dead 2, The (USA).cue").write_text(
                'FILE "track 01.bin" BINARY\n TRACK 01 MODE1/2352\n INDEX 01 00:00:00\n')
            (source / "track 01.bin").write_bytes(b"synthetic disc" * 100)
            (source / "save.dat").write_text("synthetic state")
            catalog_path = app / "games.json"
            catalog_path.write_text("[]")
            with mock.patch.dict(os.environ, {"HOME": str(home), "PATH": str(mockbin) + ":" + os.environ["PATH"]}):
                info = packages.import_package(source_package, app)
                runner = jobs.Jobs(app / "jobs")
                inst = installs.Installs(app, threading.Lock(), lambda: json.loads(catalog_path.read_text()),
                                        lambda gs: installs._write_atomic(catalog_path, json.dumps(gs).encode()), runner)
                runner.on_success = inst.on_success
                runner.before_step = inst.before_step
                def install():
                    nonlocal runner
                    jid = inst.submit_install(info["id"], info["version"], str(source),
                                              trusted_digest=info["digest"])
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline and runner.get(jid)["status"] in jobs.RUNNING:
                        time.sleep(.02)
                    detail = runner.get(jid)
                    self.assertEqual(detail["status"], "awaiting-approval", detail)
                    if detail["plan"].get("operation") == "prepare-dependency":
                        self.assertNotIn("approval_blocked", detail)
                        self.assertFalse(installed_marker.exists())
                        runner.close()
                        runner = jobs.Jobs(app / "jobs", on_success=inst.on_success, before_step=inst.before_step)
                        inst.jobs = runner
                        self.assertEqual(runner.get(jid)["plan_digest"], detail["plan_digest"])
                        if cancel_at_approval:
                            self.assertIs(runner.cancel(jid), True)
                            self.assertFalse(installed_marker.exists())
                            self.assertFalse((home / "Games").exists())
                            return jid
                        self.assertIs(inst.approve(jid, detail["plan_digest"]), True)
                        deadline = time.monotonic() + 20
                        while time.monotonic() < deadline and runner.get(jid)["status"] in jobs.RUNNING:
                            time.sleep(.02)
                        detail = runner.get(jid)
                        self.assertTrue(installed_marker.exists())
                        if not installed_build_matches:
                            self.assertEqual(detail["status"], "needs-action", detail)
                            self.assertFalse((home / "Games").exists())
                            self.assertEqual(json.loads(catalog_path.read_text()), [])
                            self.assertIsNone(inst._load_receipt(info["id"]))
                            return jid
                        self.assertEqual(detail["status"], "awaiting-approval", detail)
                        self.assertNotIn("approval_blocked", detail)
                        self.assertEqual(len(runner.jobs[jid]["steps"]), 4)
                        self.assertFalse((home / "Games").exists())
                        self.assertNotEqual(detail["plan"].get("operation"), "prepare-dependency")
                        runner.close()
                        runner = jobs.Jobs(app / "jobs", on_success=inst.on_success, before_step=inst.before_step)
                        inst.jobs = runner
                        self.assertEqual(runner.get(jid)["plan_digest"], detail["plan_digest"])
                        if cancel_after_preparation:
                            self.assertIs(runner.cancel(jid), True)
                            self.assertTrue(installed_marker.exists())
                            self.assertFalse((home / "Games").exists())
                            self.assertEqual(json.loads(catalog_path.read_text()), [])
                            self.assertIsNone(inst._load_receipt(info["id"]))
                            return jid
                    # Exercise production approval against the synthetic metadata, never a real emulator.
                    self.assertIs(inst.approve(jid, detail["plan_digest"]), True)
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline and runner.get(jid)["status"] in jobs.RUNNING:
                        time.sleep(.02)
                    detail = runner.get(jid)
                    self.assertEqual(detail["status"], "succeeded", detail)
                    return jid

                try:
                    first = install()
                    if cancel_at_approval or cancel_after_preparation or not installed_build_matches:
                        return
                    receipt = inst._load_receipt(info["id"])
                    identity = receipt["installation_id"]
                    games = json.loads(catalog_path.read_text())
                    self.assertEqual(games[0]["name"], info["name"])
                    self.assertTrue(games[0]["tags"])
                    self.assertTrue(games[0]["icon"].startswith("media/"))
                    self.assertTrue((app / games[0]["icon"]).is_file())
                    self.assertEqual(receipt["readiness"], "setup-required")
                    self.assertEqual(receipt["paths"], runner.jobs[first]["meta"]["paths"])
                    games[0].update(description="Personal notes", tags=[], icon=None, favorite=True)
                    installs._write_atomic(catalog_path, json.dumps(games).encode())
                    (Path(receipt["game_directory"]) / "save.dat").write_text("state changed by player")
                    repeat = install()
                    self.assertEqual(runner.paths(repeat)["intent_file"].read_bytes(), b"")
                    self.assertEqual(inst._load_receipt(info["id"])["installation_id"], identity)
                    launcher = Path(receipt["paths"]["launcher"])
                    launcher.unlink()
                    repaired = install()
                    self.assertTrue(launcher.is_file())
                    self.assertTrue(runner.paths(repaired)["intent_file"].stat().st_size > 0)
                    games = json.loads(catalog_path.read_text())
                    self.assertEqual(len(games), 1)
                    self.assertEqual(games[0]["description"], "Personal notes")
                    self.assertEqual(games[0]["tags"], [])
                    self.assertIsNone(games[0]["icon"])
                    self.assertTrue(games[0]["favorite"])
                    self.assertEqual((source / "save.dat").read_text(), "synthetic state")
                    self.assertEqual((Path(receipt["game_directory"]) / "save.dat").read_text(), "state changed by player")
                finally:
                    runner.close()
                    packages._rmtree(app / "packages")
