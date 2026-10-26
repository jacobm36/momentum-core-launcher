"""Exact private package runner integrations with isolated synthetic Flatpak."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import compatibility
import installs
import jobs
import managed_flatpak
import packages
from tests.test_doom_installs import write_iwad

REPO = Path(os.environ.get("MCL_PACKAGE_REPO",
                          str(Path(__file__).resolve().parents[2] / "momentum-packages")))


@unittest.skipUnless(os.environ.get("MCL_MANAGED_TESTS") == "1", "opt-in exact managed candidate integration")
class ManagedInstalls(unittest.TestCase):
    def wait(self, runner, jid):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            job = runner.get(jid)
            if job["status"] not in jobs.RUNNING:
                return job
            time.sleep(.05)
        self.fail(f"Timed out: {runner.get(jid)}")

    def exercise(self, runtime, game=None, version="0.3.0"):
        game = game or ("the-house-of-the-dead-2" if runtime == "flycast" else "brutal-doom")
        with tempfile.TemporaryDirectory(prefix="managed-runner-") as temporary:
            root = Path(temporary)
            home, app, source, tools = [root / p for p in ("home with spaces", "launcher", "source", "tools")]
            for p in (home, app, source, tools):
                p.mkdir()
            (home / "mock-engine.json").write_text(json.dumps({"runtime": runtime}))
            binary = tools / "flatpak"
            binary.write_bytes((Path(__file__).parent / "fixtures/managed-flatpak.py").read_bytes())
            binary.chmod(0o755)
            if runtime == "flycast":
                (source / "House of the Dead 2, The (USA).cue").write_text(
                    'FILE "track.bin" BINARY\n TRACK 01 MODE1/2352\n INDEX 01 00:00:00\n')
                (source / "track.bin").write_bytes(b"synthetic")
            else:
                write_iwad(source / "DOOM2.WAD")
            original = {p.name: p.read_bytes() for p in source.iterdir()}
            with mock.patch.dict(os.environ, {"HOME": str(home), "PATH": str(tools) + ":" + os.environ["PATH"]}):
                imported = packages.import_package(REPO / f"dist/{game}-{version}.zip", app)
                original_read = Path.read_text
                evidence_path = Path(installs.__file__).parent / (
                    "docs/hod2-target-evidence.json" if runtime == "flycast" else "docs/doom-installer-evidence.json")
                evidence = json.loads(original_read(evidence_path))
                if runtime == "flycast":
                    if not any(r["version"] == version for r in evidence["derived_packages"]):
                        evidence["derived_packages"].append({
                            "version": version, "digest": imported["digest"],
                            "basis": "Provisional exact managed integration."})
                elif not any(r["id"] == game and r["version"] == "0.3.0" for r in evidence["packages"]):
                    basis = ("brutal-doom", "0.3.0") if game == "brutal-doom-64" else (game, "0.2.0")
                    record = copy.deepcopy(next(r for r in evidence["packages"]
                                                if (r["id"], r["version"]) == basis))
                    record.update(id=game, version="0.3.0", digest=imported["digest"])
                    evidence["packages"].append(record)

                def read(path, *args, **kwargs):
                    if path == evidence_path and os.environ.get("MCL_CANDIDATE_EVIDENCE") == "1":
                        return json.dumps(evidence)
                    return original_read(path, *args, **kwargs)

                library = []
                runner = jobs.Jobs(app / "jobs")
                inst = installs.Installs(app, threading.Lock(), lambda: library,
                                         lambda data: library.__setitem__(slice(None), data), runner)
                runner.before_step, runner.on_success = inst.before_step, inst.on_success
                try:
                    with mock.patch.object(Path, "read_text", read):
                        detail = inst.package_details(game, version)
                        self.assertTrue(detail["package_supported"], detail)
                        self.assertFalse(detail["install_enabled"])
                        self.assertIsNotNone(detail["managed_fallback"])
                        jid = inst.submit_install(game, version, str(source), trusted_digest=imported["digest"])
                        job = self.wait(runner, jid)
                        self.assertEqual(job["status"], "awaiting-approval", job)
                        self.assertEqual(job["plan"]["managed_engine"], managed_flatpak.CONTRACT)
                        self.assertFalse((home / "Games").exists())
                        self.assertIs(inst.approve(jid, job["plan_digest"]), True)
                        job = self.wait(runner, jid)
                        self.assertEqual(job["status"], "awaiting-approval", job)
                        self.assertNotEqual(job["plan"]["operation"], "prepare-dependency")
                        self.assertFalse((home / "Games").exists())
                        planned = job["plan"]["dependencies"][runtime]["managed"]
                        self.assertTrue(Path(planned["helper"]).is_file())
                        self.assertIs(inst.approve(jid, job["plan_digest"]), True)
                        self.assertEqual(self.wait(runner, jid)["status"], "succeeded", runner.get(jid))
                        receipt = inst._load_receipt(game)
                        self.assertEqual(receipt["dependencies"][runtime]["managed"], planned)
                        wrapper = Path(receipt["paths"]["launcher"]).read_text()
                        self.assertIn("--media", wrapper)
                        self.assertNotIn("exec flatpak run", wrapper)
                        if version == "0.3.1":
                            for field, asset in installs.PRESENTATION_ASSETS.items():
                                self.assertTrue(library[0][field].startswith("media/"), library)
                                self.assertEqual((app / library[0][field]).read_bytes(),
                                                 (Path(receipt["paths"]["support"]) / asset).read_bytes())
                        jid = inst.submit_install(game, version, str(source), trusted_digest=imported["digest"])
                        job = self.wait(runner, jid)
                        self.assertEqual(job["status"], "awaiting-approval", job)
                        self.assertEqual(job["plan"]["actions"], [])
                        self.assertIs(inst.approve(jid, job["plan_digest"]), True)
                        self.assertEqual(self.wait(runner, jid)["status"], "succeeded", runner.get(jid))
                        self.assertEqual(inst._load_receipt(game)["installation_id"], receipt["installation_id"])
                        self.assertEqual(len(library), 1)
                        self.assertEqual({p.name: p.read_bytes() for p in source.iterdir()}, original)
                        template = copy.deepcopy(runner.jobs[jid]["steps"][-1]["context"])
                        operation_meta = copy.deepcopy(runner.jobs[jid]["meta"])
                        profile = Path(planned["profile"])
                        profile.mkdir(parents=True)
                        (profile / "save-marker").write_text("preserve")
                        slot_before = (Path(planned["slot"]) / "slot.json").read_bytes()

                        def operation(name):
                            if name == "uninstall":
                                operation_id = inst.submit_uninstall(game, imported["digest"])
                                job = self.wait(runner, operation_id)
                                self.assertEqual(job["status"], "awaiting-approval", job)
                                self.assertEqual(job["plan"]["operation"], "uninstall")
                                self.assertIs(inst.approve(operation_id, job["plan_digest"]), True)
                                self.assertEqual(self.wait(runner, operation_id)["status"],
                                                 "succeeded", runner.get(operation_id))
                                self.assertEqual(inst._load_receipt(game)["installation"], "removed")
                                self.assertNotIn("exec", library[0])
                                return
                            detail = inst.package_details(game, version)
                            context = dict(template, operation=name, previous_receipt=inst._load_receipt(game),
                                           dependencies=detail["dependencies"])
                            steps = [{
                                "name": name + " " + phase, "protocol": True, "approve_after": phase == "preflight",
                                "declared_steps": detail["manifest"]["operations"][name]["steps"],
                                "argv": ["bash", name + ".sh", "--context", "{context_file}", "--phase", phase],
                                "cwd": context["package_root"], "context": dict(context, phase=phase)}
                                     for phase in ("preflight", "apply")]
                            operation_id = runner.submit(name, steps, game=game,
                                                         meta=dict(operation_meta, operation=name))
                            job = self.wait(runner, operation_id)
                            self.assertEqual(job["status"], "awaiting-approval", job)
                            self.assertIs(inst.approve(operation_id, job["plan_digest"]), True)
                            self.assertEqual(self.wait(runner, operation_id)["status"],
                                             "succeeded", runner.get(operation_id))

                        Path(receipt["paths"]["launcher"]).unlink()
                        operation("repair")
                        self.assertTrue(Path(receipt["paths"]["launcher"]).is_file())
                        operation("uninstall")
                        self.assertEqual((profile / "save-marker").read_text(), "preserve")
                        self.assertEqual((Path(planned["slot"]) / "slot.json").read_bytes(), slot_before)
                        self.assertTrue(Path(planned["helper"]).is_file())
                        jid = inst.submit_install(game, version, str(source), trusted_digest=imported["digest"])
                        job = self.wait(runner, jid)
                        self.assertEqual(job["status"], "awaiting-approval", job)
                        self.assertIs(inst.approve(jid, job["plan_digest"]), True)
                        self.assertEqual(self.wait(runner, jid)["status"], "succeeded", runner.get(jid))
                        self.assertEqual((profile / "save-marker").read_text(), "preserve")
                        self.assertEqual(inst._load_receipt(game)["dependencies"][runtime]["managed"], planned)
                        # A changed binding after review must not receive approval.
                        jid = inst.submit_install(game, version, str(source), trusted_digest=imported["digest"])
                        job = self.wait(runner, jid)
                        changed = Path(planned["slot"]) / "slot.json"
                        raw = changed.read_bytes()
                        changed.write_text("{}")
                        self.assertIn("failed", inst.approve(jid, job["plan_digest"]).lower())
                        changed.write_bytes(raw)
                        runner.cancel(jid)
                        print(f"Managed exact runner PASS: {game} {version} {imported['digest']}")
                finally:
                    runner.close()

    def test_hod2_separate_engine_game_approvals_repeat_and_binding_drift(self):
        self.exercise("flycast")

    def test_hod2_presentation_revision(self):
        self.exercise("flycast", version="0.3.1")

    def test_brutal_doom_separate_engine_game_approvals_repeat_and_binding_drift(self):
        self.exercise("uzdoom")

    def test_brutal_doom_64_separate_engine_game_approvals_repeat_and_binding_drift(self):
        self.exercise("uzdoom", "brutal-doom-64")
