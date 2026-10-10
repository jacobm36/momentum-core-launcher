"""Opt-in real Episode Enyo package/runner tests; synthetic base data, no engine launch."""
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import threading
import time
import unittest
from unittest import mock

import installs
import jobs
import packages
import vkquake

PACKAGE_REPO = Path(__file__).resolve().parents[2] / "momentum-packages"
GAME_ID = "quake-slave-zero-x"


def write_pak(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = bytearray(b"PACK" + b"\0" * 8)
    directory = []
    for name, data in entries.items():
        directory.append(struct.pack("<56sii", name.encode(), len(content), len(data)))
        content.extend(data)
    offset = len(content)
    content.extend(b"".join(directory))
    content[4:12] = struct.pack("<ii", offset, len(directory) * 64)
    path.write_bytes(content)


@unittest.skipUnless(os.environ.get("MCL_QUAKE_TESTS") == "1", "opt-in real bundled mod integration")
class QuakeInstalls(unittest.TestCase):
    def wait(self, runner, jid):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and runner.get(jid)["status"] in jobs.RUNNING:
            time.sleep(.02)
        return runner.get(jid)

    def test_reused_engine_lifecycle_retained_save_reinstall_and_recovery(self):
        self.exercise()

    def test_missing_engine_requires_separate_download_and_game_approvals(self):
        self.exercise(missing=True)

    def exercise(self, missing=False):
        original_runtime = vkquake.detect()
        self.assertTrue(original_runtime["installed"], original_runtime)
        with tempfile.TemporaryDirectory(prefix="momentum-quake-runner-") as temporary:
            root = Path(temporary)
            home, app, source = (root / p for p in ("home with spaces", "launcher", "Quake source"))
            for p in (home, app, source):
                p.mkdir()
            if not missing:
                engine = home / "Applications/vkquake.AppImage"
                engine.parent.mkdir()
                shutil.copyfile(original_runtime["executable"], engine)
                engine.chmod(0o755)
            write_pak(source / "id1/pak0.pak", {"gfx/palette.lmp": b"synthetic palette"})
            write_pak(source / "id1/pak1.pak", {"maps/e1m1.bsp": b"synthetic map"})
            (source / "enyo").mkdir()
            (source / "enyo/config.cfg").write_text("personal settings")
            (source / "unrelated-mod").mkdir()
            (source / "unrelated-mod/keep").write_text("not copied")
            original = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
            catalog = app / "games.json"
            catalog.write_text("[]")
            with mock.patch.dict(os.environ, {"HOME": str(home)}):
                info = packages.import_package(PACKAGE_REPO / "dist/quake-slave-zero-x-0.2.1.zip", app)
                runner = jobs.Jobs(app / "jobs")
                inst = installs.Installs(app, threading.Lock(), lambda: json.loads(catalog.read_text()),
                                        lambda gs: installs._write_atomic(catalog, json.dumps(gs).encode()), runner)
                runner.on_success, runner.before_step = inst.on_success, inst.before_step

                def approve(jid):
                    job = self.wait(runner, jid)
                    self.assertEqual(job["status"], "awaiting-approval", job)
                    self.assertNotIn("approval_blocked", job)
                    self.assertIs(inst.approve(jid, job["plan_digest"]), True)
                    return self.wait(runner, jid)

                def submit():
                    return inst.submit_install(GAME_ID, "0.2.1", str(source), trusted_digest=info["digest"])

                def operation(name, receipt, template):
                    detail = inst.package_details(GAME_ID, "0.2.1")
                    context = dict(template, operation=name, previous_receipt=receipt,
                                   dependencies=detail["dependencies"])
                    steps = [{"name": f"{name} {phase}", "protocol": True, "approve_after": phase == "preflight",
                              "declared_steps": detail["manifest"]["operations"][name]["steps"],
                              "argv": ["bash", f"{name}.sh", "--context", "{context_file}", "--phase", phase],
                              "cwd": context["package_root"], "context": dict(context, phase=phase)}
                             for phase in ("preflight", "apply")]
                    meta = {"kind": "install", "package_id": GAME_ID, "package_version": "0.2.1",
                            "package_digest": info["digest"], "operation": name,
                            "game_directory": receipt["game_directory"], "paths": receipt["paths"],
                            "install_enabled": True, "catalog_defaults": {
                                **detail["manifest"]["catalog"], "name": detail["manifest"]["name"],
                                "icon": receipt["paths"]["icon"]}}
                    return runner.submit(name, steps, game=GAME_ID, meta=meta)

                try:
                    jid = submit()
                    job = self.wait(runner, jid)
                    if missing:
                        self.assertEqual(job["plan"]["operation"], "prepare-dependency")
                        self.assertFalse((home / "Games").exists())
                        job = approve(jid)
                        self.assertEqual(job["status"], "awaiting-approval", job)
                        self.assertNotEqual(job["plan"]["operation"], "prepare-dependency")
                        self.assertTrue(vkquake.detect()["installed"])
                    runner.close()
                    runner = jobs.Jobs(app / "jobs", on_success=inst.on_success, before_step=inst.before_step)
                    inst.jobs = runner
                    self.assertEqual(runner.get(jid)["plan_digest"], job["plan_digest"])
                    self.assertEqual(approve(jid)["status"], "succeeded", runner.get(jid))
                    receipt = inst._load_receipt(GAME_ID)
                    self.assertEqual(receipt["readiness"], "setup-required")
                    self.assertEqual(len(json.loads(catalog.read_text())), 1)
                    game = Path(receipt["game_directory"])
                    self.assertTrue((game / "enyo/pak0.pak").is_file())
                    self.assertEqual((game / "enyo/config.cfg").read_text(), "personal settings")
                    self.assertFalse((game / "unrelated-mod").exists())
                    launcher = Path(receipt["paths"]["launcher"]).read_text()
                    self.assertIn("-game enyo", launcher)
                    self.assertNotIn("-fullscreen", launcher)
                    if missing:
                        return
                    template = runner.jobs[jid]["steps"][-1]["context"].copy()
                    repeat = submit()
                    self.assertEqual(self.wait(runner, repeat)["plan"]["actions"], [])
                    self.assertEqual(approve(repeat)["status"], "succeeded", runner.get(repeat))
                    receipt = inst._load_receipt(GAME_ID)
                    (game / "enyo/pak0.pak").unlink()
                    repair = operation("repair", receipt, template)
                    self.assertEqual(approve(repair)["status"], "succeeded", runner.get(repair))
                    receipt = inst._load_receipt(GAME_ID)
                    (game / "enyo/save.sav").write_text("retain this save")
                    remove = operation("uninstall", receipt, template)
                    self.assertEqual(approve(remove)["status"], "succeeded", runner.get(remove))
                    self.assertFalse((game / "enyo/pak0.pak").exists())
                    self.assertTrue((game / "id1/pak0.pak").is_file())
                    self.assertEqual((game / "enyo/save.sav").read_text(), "retain this save")
                    reinstall = submit()
                    self.assertEqual(approve(reinstall)["status"], "succeeded", runner.get(reinstall))
                    self.assertEqual(inst._load_receipt(GAME_ID)["installation_id"], receipt["installation_id"])
                    self.assertEqual(len(json.loads(catalog.read_text())), 1)
                    self.assertEqual((game / "enyo/save.sav").read_text(), "retain this save")
                    cancelled = submit()
                    self.assertEqual(self.wait(runner, cancelled)["status"], "awaiting-approval")
                    self.assertIs(runner.cancel(cancelled), True)
                    self.assertEqual(inst._load_receipt(GAME_ID)["last_job_id"], reinstall)
                finally:
                    self.assertEqual({p.relative_to(source): p.read_bytes()
                                      for p in source.rglob("*") if p.is_file()}, original)
                    runner.close()
                    packages._rmtree(app / "packages")
