"""Complete Duke package and runner with synthetic GRP; no engine invocation."""
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

import eduke32
import installs
import jobs
import packages

PACKAGE_REPO = Path(__file__).resolve().parents[2] / "momentum-packages"
GAME_ID = "duke-nukem-3d"


def write_grp(path):
    entries = {"GAME.CON": b"synthetic game", "TILES000.ART": b"synthetic art",
               "E1L1.MAP": b"synthetic map", "E2L1.MAP": b"synthetic map",
               "E3L1.MAP": b"synthetic map"}
    path.write_bytes(b"KenSilverman" + struct.pack("<I", len(entries)) +
                     b"".join(struct.pack("<12sI", name.encode(), len(data)) for name, data in entries.items()) +
                     b"".join(entries.values()))


@unittest.skipUnless(os.environ.get("MCL_DUKE_TESTS") == "1", "opt-in complete Duke runner integration")
class DukeInstalls(unittest.TestCase):
    def wait(self, runner, jid):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline and runner.get(jid)["status"] in jobs.RUNNING:
            time.sleep(.02)
        return runner.get(jid)

    def test_reuse_lifecycle_and_retained_state(self):
        self.exercise()

    def test_changed_engine_stays_gated(self):
        self.exercise(unknown=True)

    def test_missing_engine_requires_separate_approval_before_game_writes(self):
        self.exercise(missing=True)

    def test_prepared_unknown_build_stops_before_game_mutations(self):
        self.exercise(missing=True, prepare=True)

    def test_bundled_runtime_fresh_install_and_retained_state(self):
        self.exercise(missing=True, prepare=True, bundled=True)

    def test_bundled_runtime_existing_engine_and_presentation(self):
        self.exercise(bundled=True)

    def test_bundled_runtime_cancel_before_publication(self):
        self.exercise(missing=True, bundled=True)

    def test_bundled_runtime_unknown_existing_engine_stays_gated(self):
        self.exercise(unknown=True, bundled=True)

    def exercise(self, unknown=False, missing=False, prepare=False, bundled=False):
        version = "0.2.0" if bundled else "0.1.1"
        working = eduke32.detect()
        self.assertTrue(working["installed"], working)
        original_engine = Path(working["executable"]).read_bytes()
        with tempfile.TemporaryDirectory(prefix="momentum-duke-runner-") as temporary:
            root = Path(temporary)
            home, app, source = (root / p for p in ("home with spaces", "launcher", "Duke source"))
            for path in (home, app, source):
                path.mkdir()
            if not missing:
                engine = home / "Games/Duke-Nukem-3D/eduke32"
                engine.parent.mkdir(parents=True)
                engine.write_bytes(original_engine + (b"changed" if unknown else b""))
                engine.chmod(0o755)
            write_grp(source / "DUKE3D.GRP")
            (source / "eduke32.cfg").write_text("[Setup]\nNoAutoLoad=0\npersonal preference\n")
            (source / "settings.cfg").write_text("personal bindings")
            (source / "unrelated-mod").mkdir()
            (source / "unrelated-mod/keep").write_text("not copied")
            original = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
            shared = home / ".config/eduke32/personal.cfg"
            shared.parent.mkdir(parents=True)
            shared.write_text("do not change shared settings")
            library = app / "games.json"
            library.write_text("[]")
            tools = root / "tools"
            tools.mkdir()
            if prepare and not bundled:
                built = root / "mock-built-engine"
                built.write_bytes(original_engine + b"isolated unknown compiled artifact")
                (tools / "make").write_text(
                    "#!/usr/bin/env python3\nfrom pathlib import Path\n"
                    f"Path('eduke32').write_bytes(Path({str(built)!r}).read_bytes())\n"
                    "Path('eduke32').chmod(0o755)\n")
                (tools / "make").chmod(0o755)
            with mock.patch.dict(os.environ, {"HOME": str(home), "PATH": str(tools) + ":" + os.environ["PATH"]}):
                info = packages.import_package(PACKAGE_REPO / "dist" / f"duke-nukem-3d-{version}.zip", app)
                runner = jobs.Jobs(app / "jobs")
                inst = installs.Installs(app, threading.Lock(), lambda: json.loads(library.read_text()),
                                        lambda games: installs._write_atomic(library, json.dumps(games).encode()), runner)
                runner.on_success, runner.before_step = inst.on_success, inst.before_step

                def submit():
                    return inst.submit_install(GAME_ID, version, str(source), trusted_digest=info["digest"])

                def approve(jid):
                    job = self.wait(runner, jid)
                    self.assertEqual(job["status"], "awaiting-approval", job)
                    self.assertNotIn("approval_blocked", job)
                    self.assertIs(inst.approve(jid, job["plan_digest"]), True)
                    return self.wait(runner, jid)

                def operation(name, receipt, template):
                    detail = inst.package_details(GAME_ID, version)
                    context = dict(template, operation=name, previous_receipt=receipt,
                                   dependencies=detail["dependencies"])
                    steps = [{"name": f"{name} {phase}", "protocol": True, "approve_after": phase == "preflight",
                              "declared_steps": detail["manifest"]["operations"][name]["steps"],
                              "argv": ["bash", f"{name}.sh", "--context", "{context_file}", "--phase", phase],
                              "cwd": context["package_root"], "context": dict(context, phase=phase)}
                             for phase in ("preflight", "apply")]
                    meta = dict(runner.jobs[first]["meta"], operation=name)
                    return runner.submit(name, steps, game=GAME_ID, meta=meta)

                try:
                    first = submit()
                    job = self.wait(runner, first)
                    self.assertEqual(job["status"], "awaiting-approval", job)
                    if unknown:
                        self.assertIn("approval_blocked", job)
                        self.assertIsNot(inst.approve(first, job["plan_digest"]), True)
                        self.assertFalse((home / "Games" / ("duke-nukem-3d" if bundled else "Duke Nukem 3D - Momentum")).exists())
                        self.assertEqual(json.loads(library.read_text()), [])
                        return
                    if missing:
                        self.assertEqual(job["plan"]["operation"], "prepare-dependency")
                        self.assertFalse((home / "Games").exists())
                        self.assertEqual(json.loads(library.read_text()), [])
                        if prepare and bundled:
                            self.assertIsNot(inst.approve(first, "sha256:" + "0" * 64), True)
                            self.assertEqual(job["plan"]["runtime_publication"]["sha256"], eduke32.ENGINE_SHA256)
                            self.assertNotIn("dependency_download", job["plan"])
                            self.assertEqual(job["plan"]["dependency_commands"], [])
                            job = approve(first)
                            self.assertEqual(job["status"], "awaiting-approval", job)
                            self.assertEqual(job["plan"]["operation"], "install")
                            self.assertTrue(eduke32.detect()["recognized_build"])
                            self.assertFalse((home / "Games").exists())
                            self.assertEqual(json.loads(library.read_text()), [])
                        elif prepare:
                            prepared = approve(first)
                            self.assertEqual(prepared["status"], "needs-action", prepared)
                            self.assertIn("not been validated", prepared["error"])
                            self.assertTrue(eduke32.detect()["installed"])
                            self.assertFalse(eduke32.detect()["recognized_build"])
                            self.assertFalse((home / "Games").exists())
                            self.assertEqual(json.loads(library.read_text()), [])
                        else:
                            self.assertIs(runner.cancel(first), True)
                            if bundled:
                                self.assertFalse(eduke32.target_path().exists())
                        if not (prepare and bundled):
                            return
                    runner.close()
                    runner = jobs.Jobs(app / "jobs", on_success=inst.on_success, before_step=inst.before_step)
                    inst.jobs = runner
                    self.assertEqual(runner.get(first)["plan_digest"], job["plan_digest"])
                    self.assertEqual(approve(first)["status"], "succeeded", runner.get(first))
                    receipt = inst._load_receipt(GAME_ID)
                    game = Path(receipt["game_directory"])
                    self.assertEqual(receipt["readiness"], "setup-required")
                    self.assertTrue(all((game / "autoload" / filename).is_file()
                                        for filename in ("dukeupscale.zip", "voxel_duke3d.zip", "duke3d_music-sc55.zip")))
                    self.assertEqual((game / "settings.cfg").read_text(), "personal bindings")
                    self.assertFalse((game / "unrelated-mod").exists())
                    wrapper = Path(receipt["paths"]["launcher"]).read_text()
                    self.assertIn("-usecwd -g autoload/dukeupscale.zip -g autoload/voxel_duke3d.zip", wrapper)
                    self.assertIn("-mh dukeupscale.def -mh duke3d_voxels.def", wrapper)
                    if bundled:
                        self.assertIn("-fullscreen", wrapper)
                        entry = json.loads(library.read_text())[0]
                        manifest = json.loads((Path(receipt["paths"]["support"]) / "package.json").read_text())
                        self.assertEqual(entry["description"], manifest["catalog"]["description"])
                        for field in ("cover", "grid", "icon"):
                            self.assertTrue(entry[field].startswith("media/"), entry)
                            self.assertTrue((app / entry[field]).is_file())
                        self.assertEqual(len(entry["screenshots"]), 1)
                        self.assertTrue((app / entry["screenshots"][0]).is_file())
                        self.assertEqual((app / entry["screenshots"][0]).read_bytes(),
                                         (app / entry["cover"]).read_bytes())
                        entry.update(description="My Duke description", grid=None, screenshots=[])
                        library.write_text(json.dumps([entry]))
                    else:
                        self.assertNotIn("-fullscreen", wrapper)
                    template = runner.jobs[first]["steps"][-1]["context"].copy()
                    repeat = submit()
                    self.assertEqual(self.wait(runner, repeat)["plan"]["actions"], [])
                    self.assertEqual(approve(repeat)["status"], "succeeded", runner.get(repeat))
                    receipt = inst._load_receipt(GAME_ID)
                    (game / "autoload/dukeupscale.zip").unlink()
                    repair = operation("repair", receipt, template)
                    self.assertEqual(approve(repair)["status"], "succeeded", runner.get(repair))
                    receipt = inst._load_receipt(GAME_ID)
                    (game / "save.sav").write_text("retain save")
                    remove = (inst.submit_uninstall(GAME_ID, info["digest"]) if bundled else
                              operation("uninstall", receipt, template))
                    self.assertEqual(approve(remove)["status"], "succeeded", runner.get(remove))
                    self.assertFalse((game / "autoload/dukeupscale.zip").exists())
                    self.assertEqual((game / "DUKE3D.GRP").read_bytes(), original[Path("DUKE3D.GRP")])
                    if bundled:
                        self.assertEqual(Path(eduke32.detect()["executable"]).read_bytes(), original_engine)
                        self.assertEqual(
                            installs._hash_file(Path(receipt["paths"]["support"]) / eduke32.BUNDLED_SOURCE),
                            eduke32.ASSET_SHA256)
                        self.assertEqual(json.loads(library.read_text())[0]["install_status"], "removed")
                    self.assertEqual(approve(submit())["status"], "succeeded")
                    self.assertEqual((game / "save.sav").read_text(), "retain save")
                    self.assertEqual(inst._load_receipt(GAME_ID)["installation_id"], receipt["installation_id"])
                    self.assertEqual(len(json.loads(library.read_text())), 1)
                    if bundled:
                        entry = json.loads(library.read_text())[0]
                        self.assertEqual(entry["description"], "My Duke description")
                        self.assertIsNone(entry["grid"])
                        self.assertEqual(entry["screenshots"], [])
                    cancel = submit()
                    self.assertEqual(self.wait(runner, cancel)["status"], "awaiting-approval")
                    self.assertIs(runner.cancel(cancel), True)
                finally:
                    self.assertEqual({p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}, original)
                    self.assertEqual(shared.read_text(), "do not change shared settings")
                    self.assertEqual(Path(working["executable"]).read_bytes(), original_engine)
                    runner.close()
                    packages._rmtree(app / "packages")
