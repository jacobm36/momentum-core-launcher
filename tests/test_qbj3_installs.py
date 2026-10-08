"""Opt-in real runner/full QBJ3 source; synthetic Quake base, no engine execution."""
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
import ironwail
import jobs
import packages
from tests.test_quake_installs import write_pak

REPO = Path(__file__).resolve().parents[2] / "momentum-packages"
ID = "quake-brutalist-jam-3"
REFERENCE_SOURCE = Path("/home/jake/Games/Quake/qbj3")
REFERENCE_ENGINE = Path("/home/jake/Games/Ironwail/0.8.2")


def prepare_test_engine(home, root):
    engine = home / "Games/Ironwail/0.8.2"
    engine.mkdir(parents=True)
    if (REFERENCE_ENGINE / "ironwail").is_file():
        for name in ("ironwail", "ironwail.pak"):
            shutil.copyfile(REFERENCE_ENGINE / name, engine / name)
            (engine / name).chmod(0o755 if name == "ironwail" else 0o644)
    else:
        archive = root / "official-ironwail.tar.gz"
        ironwail.download({"cancel_file": str(root / "cancel")}, ironwail.URL,
                          archive, ironwail.ARCHIVE_SIZE, ironwail.ARCHIVE_SHA)
        ironwail.extract_engine(archive, engine)
    return engine


@unittest.skipUnless(os.environ.get("MCL_QBJ3_TESTS") == "1", "opt-in complete QBJ3 source/runner validation")
class QBJ3Installs(unittest.TestCase):
    def wait(self, runner, jid):
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline and runner.get(jid)["status"] in jobs.RUNNING:
            time.sleep(.1)
        return runner.get(jid)

    def test_complete_reuse_lifecycle_preservation(self):
        self.exercise(lifecycle=True)

    def test_missing_official_engine_preparation_and_separate_game_approval(self):
        self.exercise(missing_engine=True)

    def test_missing_mod_full_pinned_archive_preparation_and_game_approval(self):
        self.exercise(missing_mod=True)

    def exercise(self, lifecycle=False, missing_engine=False, missing_mod=False):
        with tempfile.TemporaryDirectory(prefix="momentum-qbj3-runner-") as temp:
            root = Path(temp)
            home, app, source = (root / p for p in ("home with spaces", "launcher", "Quake source"))
            for p in (home, app, source):
                p.mkdir()
            if not missing_engine:
                prepare_test_engine(home, root)
            write_pak(source / "id1/pak0.pak", {"gfx/palette.lmp": b"synthetic palette"})
            write_pak(source / "id1/pak1.pak", {"maps/e1m1.bsp": b"synthetic map"})
            (source / "id1/config.cfg").write_text("keep source settings")
            before = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
            catalog = app / "games.json"
            catalog.write_text("[]")
            with mock.patch.dict(os.environ, {"HOME": str(home)}):
                info = packages.import_package(REPO / "dist/quake-brutalist-jam-3-0.1.0.zip", app)
                runner = jobs.Jobs(app / "jobs")
                inst = installs.Installs(app, threading.Lock(), lambda: json.loads(catalog.read_text()),
                                        lambda gs: installs._write_atomic(catalog, json.dumps(gs).encode()), runner)
                runner.on_success, runner.before_step = inst.on_success, inst.before_step
                inputs = {"source_dir": str(source), "games_root": str(home / "Games")}
                if not missing_mod:
                    inputs["mod_dir"] = str(REFERENCE_SOURCE)

                def submit():
                    return inst.submit_install(ID, "0.1.0", trusted_digest=info["digest"], inputs=inputs)

                def approve(jid):
                    j = self.wait(runner, jid)
                    self.assertEqual(j["status"], "awaiting-approval", j)
                    self.assertNotIn("approval_blocked", j)
                    self.assertIs(inst.approve(jid, j["plan_digest"]), True)
                    return self.wait(runner, jid)

                def operation(name, receipt, template):
                    detail = inst.package_details(ID, "0.1.0")
                    context = dict(template, operation=name, previous_receipt=receipt,
                                   dependencies=detail["dependencies"])
                    phases = ("preflight",) if name == "verify" else ("preflight", "apply")
                    steps = [{"name": name + " " + phase, "protocol": True,
                              "approve_after": phase == "preflight" and name != "verify",
                              "declared_steps": detail["manifest"]["operations"][name]["steps"],
                              "argv": ["bash", name + ".sh", "--context", "{context_file}", "--phase", phase],
                              "cwd": context["package_root"], "context": dict(context, phase=phase)}
                             for phase in phases]
                    meta = dict(runner.jobs[template_jid]["meta"], operation=name,
                                prepare_required_software=False)
                    if name == "verify":
                        meta["kind"] = "verification"
                    return runner.submit(name, steps, game=ID, meta=meta)

                try:
                    jid = submit()
                    job = self.wait(runner, jid)
                    if missing_engine or missing_mod:
                        self.assertEqual(job["plan"]["operation"], "prepare-dependency", job)
                        self.assertFalse((home / "Games/Quake - Brutalist Jam III").exists())
                        cancelled = jid
                        self.assertIs(runner.cancel(cancelled), True)
                        jid = submit()
                        job = self.wait(runner, jid)
                        if missing_mod:
                            self.assertEqual(job["plan"]["downloads"][0]["bytes"], ironwail.MOD_SIZE)
                        job = approve(jid)
                        self.assertEqual(job["status"], "awaiting-approval", job)
                        self.assertNotEqual(job["plan"]["operation"], "prepare-dependency")
                    runner.close()
                    runner = jobs.Jobs(app / "jobs", on_success=inst.on_success, before_step=inst.before_step)
                    inst.jobs = runner
                    self.assertEqual(runner.get(jid)["plan_digest"], job["plan_digest"])
                    self.assertEqual(approve(jid)["status"], "succeeded", runner.get(jid))
                    receipt = inst._load_receipt(ID)
                    game = Path(receipt["game_directory"])
                    self.assertEqual(receipt["readiness"], "setup-required")
                    self.assertEqual((game / "id1/config.cfg").read_text(), "keep source settings")
                    self.assertTrue((game / "qbj3/progs.dat").is_file())
                    wrapper = Path(receipt["paths"]["launcher"]).read_text()
                    self.assertIn("-game qbj3 -fullscreen +mlook", wrapper)
                    self.assertEqual(len(json.loads(catalog.read_text())), 1)
                    if not lifecycle:
                        return
                    template_jid = jid
                    template = runner.jobs[jid]["steps"][-1]["context"].copy()
                    verify = operation("verify", receipt, template)
                    self.assertEqual(self.wait(runner, verify)["status"], "succeeded", runner.get(verify))
                    self.assertEqual(inst._load_receipt(ID), receipt)
                    repeat = submit()
                    self.assertEqual(self.wait(runner, repeat)["plan"]["actions"], [])
                    self.assertEqual(approve(repeat)["status"], "succeeded", runner.get(repeat))
                    receipt = inst._load_receipt(ID)
                    (game / "qbj3/progs.dat").unlink()
                    repair = operation("repair", receipt, template)
                    self.assertEqual(approve(repair)["status"], "succeeded", runner.get(repair))
                    receipt = inst._load_receipt(ID)
                    verify = operation("verify", receipt, template)
                    self.assertEqual(self.wait(runner, verify)["status"], "succeeded", runner.get(verify))
                    self.assertEqual(inst._load_receipt(ID), receipt)
                    (game / "qbj3/momentum-test.sav").write_text("keep this save")
                    remove = operation("uninstall", receipt, template)
                    self.assertEqual(approve(remove)["status"], "succeeded", runner.get(remove))
                    self.assertFalse((game / "qbj3/progs.dat").exists())
                    self.assertTrue((game / "id1/pak0.pak").is_file())
                    reinstall = submit()
                    self.assertEqual(approve(reinstall)["status"], "succeeded", runner.get(reinstall))
                    result_size = runner.paths(reinstall)["result_file"].stat().st_size
                    self.assertGreater(result_size, 1 << 20)
                    self.assertLessEqual(result_size, jobs.MAX_RESULT)
                    print(f"Full QBJ3 reinstall result: {result_size} bytes (limit {jobs.MAX_RESULT}).")
                    self.assertEqual((game / "qbj3/momentum-test.sav").read_text(), "keep this save")
                    self.assertEqual(inst._load_receipt(ID)["installation_id"], receipt["installation_id"])
                    self.assertEqual(len(json.loads(catalog.read_text())), 1)
                finally:
                    runner.close()
                    self.assertEqual({p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}, before)
                    packages._rmtree(app / "packages")
