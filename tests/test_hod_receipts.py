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
        source_package = Path(os.environ["MCL_HOD_PACKAGE"]).resolve()
        evidence = json.loads((Path(installs.__file__).parent / "docs/hod2-target-evidence.json").read_text())
        metadata = f"    Version: {evidence['emulator_version']}\n    Commit: {evidence['emulator_commit']}"
        with tempfile.TemporaryDirectory(prefix="mcl-hod-receipts-") as tmp:
            root = Path(tmp)
            home = root / "home with spaces"
            home.mkdir()
            app = root / "launcher"
            app.mkdir()
            mockbin = root / "mockbin"
            mockbin.mkdir()
            flatpak = mockbin / "flatpak"
            flatpak.write_text(f"""#!{sys.executable}
import sys
command = sys.argv[1]
if command == 'ps': pass
elif command == 'remotes': print('flathub\\thttps://dl.flathub.org/repo/')
elif command == 'list': print('org.flycast.Flycast')
elif command == 'info': print({metadata!r})
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
                def install():
                    jid = inst.submit_install(info["id"], info["version"], str(source),
                                              trusted_digest=info["digest"])
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline and runner.get(jid)["status"] in jobs.RUNNING:
                        time.sleep(.02)
                    detail = runner.get(jid)
                    self.assertEqual(detail["status"], "awaiting-approval", detail)
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
