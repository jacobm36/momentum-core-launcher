"""Exact local candidate ZIPs through the real runner; synthetic media, no gameplay.

MCL_PRIORITY_TESTS=1 enables these isolated tests. MCL_CANDIDATE_EVIDENCE=1
provisions proposed evidence in memory for initial validation only. A second
run without that flag must pass against the persisted evidence before delivery.
"""
import copy
import json
import os
import runpy
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock
import zipfile

import installs
import jobs
import packages
import supermodel
import vkquake
from tests.test_doom_installs import fake_flatpak, write_iwad
from tests.test_quake_installs import write_pak


REPO = Path(os.environ.get(
    "MCL_PACKAGE_REPO", str(Path(__file__).resolve().parents[2] / "momentum-packages")))
CANDIDATES = {
    "star-wars-trilogy-arcade": ("0.2.1", "supermodel", "arcade"),
    "l-a-machineguns": ("0.2.2", "supermodel", "arcade"),
    "quake-slave-zero-x": ("0.2.2", "vkquake", "quake"),
    "brutal-doom": ("0.2.0", "uzdoom", "doom"),
    "the-house-of-the-dead-2": ("0.2.0", "flycast", "hod2-target"),
}
FLYCAST_COMMIT = "86ec4d845a66ff07cdba8e003d8549e93cd7a814b519766e1f744e530c5d3e5b"


@unittest.skipUnless(os.environ.get("MCL_PRIORITY_TESTS") == "1", "opt-in exact priority candidate integration")
class PriorityCandidates(unittest.TestCase):
    def wait(self, runner, jid):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            job = runner.get(jid)
            if job["status"] not in jobs.RUNNING:
                return job
            time.sleep(.02)
        self.fail(f"Timed out waiting for {runner.get(jid)}")

    def exercise(self, game_id, reconcile_missing_state=False, prepare_missing=False,
                 uzdoom_version="5.0.1",
                 uzdoom_commit="d7b8ce76e5480a28d1e07400093a20d47f56c201fd974b0a5dbfa3b26bbd587e",
                 flycast_commit=FLYCAST_COMMIT, publisher_download=False, competing_user=False):
        version, runtime, evidence_name = CANDIDATES[game_id]
        if publisher_download:
            version = "0.3.0"
        native = {"supermodel": supermodel, "vkquake": vkquake}.get(runtime)
        native_facts = native.detect() if native else None
        original_read = Path.read_text
        evidence_path = Path(installs.__file__).parent / f"docs/{evidence_name}-installer-evidence.json"
        if runtime == "flycast":
            evidence_path = Path(installs.__file__).parent / "docs/hod2-target-evidence.json"
        with tempfile.TemporaryDirectory(prefix="momentum-priority-") as temporary:
            root = Path(temporary)
            home, app, source, tools = (root / p for p in ("home with spaces", "app", "source", "tools"))
            for directory in (home, app, source, tools):
                directory.mkdir()
            if native:
                self.assertTrue(native_facts["installed"], native_facts)
                if runtime == "supermodel":
                    for name in supermodel.RUNTIME_FILES:
                        destination = home / "Games/Supermodel" / name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(Path(native_facts["root"]) / name, destination)
                        destination.chmod(supermodel.ASSET_INVENTORY[name][1])
                else:
                    destination = home / "Applications/vkquake.AppImage"
                    destination.parent.mkdir()
                    shutil.copyfile(native_facts["executable"], destination)
                    destination.chmod(0o755)
            elif runtime == "uzdoom":
                ready = root / "flatpak-ready"
                if not prepare_missing:
                    ready.touch()
                fake_flatpak(tools / "flatpak", ready, scope="user" if prepare_missing else "system",
                             version=uzdoom_version, commit=uzdoom_commit,
                             competing_user_commit="a" * 64 if competing_user else None)
            else:
                ready = root / "flatpak-ready"
                if not prepare_missing:
                    ready.touch()
                fake_flatpak(tools / "flatpak", ready, commit=flycast_commit,
                             app="org.flycast.Flycast", version="v2.7",
                             scope="system" if competing_user else "user",
                             competing_user_commit="a" * 64 if competing_user else None)
            if runtime == "supermodel":
                name = "swtrilgy.zip" if game_id.startswith("star-") else "lamachin.zip"
                with zipfile.ZipFile(source / name, "w") as archive:
                    archive.writestr("synthetic.rom", b"not playable")
                (source / "personal-note.txt").write_text("preserve")
            elif runtime == "vkquake":
                write_pak(source / "id1/pak0.pak", {"gfx/palette.lmp": b"synthetic"})
                write_pak(source / "id1/pak1.pak", {"maps/e1m1.bsp": b"synthetic"})
            elif runtime == "uzdoom":
                write_iwad(source / "DOOM2.WAD")
            else:
                (source / "House of the Dead 2, The (USA).cue").write_text(
                    'FILE "track.bin" BINARY\n TRACK 01 MODE1/2352\n INDEX 01 00:00:00\n')
                (source / "track.bin").write_bytes(b"synthetic media")
            originals = {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()}
            catalog = app / "games.json"
            catalog.write_text("[]")
            with mock.patch.dict(os.environ, {"HOME": str(home), "PATH": str(tools) + ":" + os.environ["PATH"]}):
                info = packages.import_package(REPO / f"dist/{game_id}-{version}.zip", app)
                proposed = json.loads(original_read(evidence_path))
                if runtime == "flycast":
                    proposed["derived_packages"].append({
                        "version": version, "digest": info["digest"],
                        "basis": "Candidate installer validation with synthetic media; no new gameplay."})
                else:
                    record = copy.deepcopy(next(r for r in proposed["packages"] if r["id"] == game_id))
                    record.update(version=version, digest=info["digest"])
                    proposed["packages"].append(record)

                def evidence_read(path, *args, **kwargs):
                    if path == evidence_path and os.environ.get("MCL_CANDIDATE_EVIDENCE") == "1":
                        return json.dumps(proposed)
                    return original_read(path, *args, **kwargs)

                with mock.patch.object(Path, "read_text", evidence_read):
                    runner = jobs.Jobs(app / "jobs")
                    inst = installs.Installs(app, threading.Lock(), lambda: json.loads(catalog.read_text()),
                                            lambda data: installs._write_atomic(catalog, json.dumps(data).encode()), runner)
                    runner.on_success, runner.before_step = inst.on_success, inst.before_step
                    if reconcile_missing_state:
                        def remove_optional_before_commit(job):
                            (Path(job["meta"]["game_directory"]) / "personal-note.txt").unlink()
                            return inst.on_success(job)
                        runner.on_success = remove_optional_before_commit
                    try:
                        detail = inst.package_details(game_id, version)
                        self.assertTrue(detail["package_supported"], detail)
                        self.assertEqual(detail["install_enabled"], not prepare_missing, detail)
                        if competing_user:
                            self.assertEqual(detail["dependencies"][runtime]["scope"], "system")
                            self.assertEqual(len(detail["engine_selection"][runtime]["candidates"]), 2)
                        def submit():
                            return inst.submit_install(game_id, version, str(source), trusted_digest=info["digest"])
                        def approve(jid):
                            job = self.wait(runner, jid)
                            self.assertEqual(job["status"], "awaiting-approval", job)
                            self.assertIs(inst.approve(jid, job["plan_digest"]), True)
                            self.assertEqual(self.wait(runner, jid)["status"], "succeeded", runner.get(jid))
                        jid = submit()
                        if prepare_missing or publisher_download:
                            job = self.wait(runner, jid)
                            self.assertEqual(job["status"], "awaiting-approval", job)
                            self.assertEqual(job["plan"]["operation"], "prepare-dependency")
                            self.assertFalse((home / "Games").exists())
                            self.assertIs(inst.approve(jid, job["plan_digest"]), True)
                            job = self.wait(runner, jid)
                            self.assertEqual(job["status"], "awaiting-approval", job)
                            self.assertNotEqual(job["plan"]["operation"], "prepare-dependency")
                            self.assertFalse((home / "Games").exists())
                            if prepare_missing:
                                self.assertEqual(ready.read_text(), "pinned")
                            if publisher_download:
                                self.assertTrue((home / ".cache/momentum-core/enyo" /
                                                 "93b1fcc32084ca85bc2878e38e7a091eee6965134a36d968c50ce9d08bd4ec9c" /
                                                 "pak0.pak").is_file())
                        if reconcile_missing_state:
                            job = self.wait(runner, jid)
                            self.assertIs(inst.approve(jid, job["plan_digest"]), True)
                            self.assertEqual(self.wait(runner, jid)["status"], "failed", runner.get(jid))
                            self.assertIsNone(inst._load_receipt(game_id))
                            self.assertIs(inst.reconcile_install(jid), True)
                            self.assertEqual(runner.get(jid)["status"], "succeeded")
                            runner.on_success = inst.on_success
                        else:
                            approve(jid)
                        receipt = inst._load_receipt(game_id)
                        self.assertEqual(receipt["readiness"], "setup-required")
                        self.assertEqual(Path(receipt["game_directory"]).name, game_id)
                        self.assertEqual(len(json.loads(catalog.read_text())), 1)
                        if game_id == "l-a-machineguns":
                            support = Path(receipt["paths"]["support"])
                            launch = runpy.run_path(str(support / "launch.py"))
                            state = Path(receipt["paths"]["state"])
                            runtime_root = inst.package_details(game_id, version)["dependencies"]["supermodel"]["root"]
                            launch["build_command"](receipt["game_directory"], str(state), runtime_root)
                            nvram = state / "NVRAM/lamachin.nv"
                            self.assertEqual(nvram.read_bytes(), (support / "presets/lamachin.nv").read_bytes())
                            nvram.write_bytes(b"preserve player calibration")
                            launch["build_command"](receipt["game_directory"], str(state), runtime_root)
                            self.assertEqual(nvram.read_bytes(), b"preserve player calibration")
                        if reconcile_missing_state:
                            inst._check_active_operations()
                            self.assertNotIn(
                                str(Path(receipt["game_directory"]) / "personal-note.txt"),
                                {resource["path"] for resource in receipt["resources"]})
                        else:
                            approve(submit())
                            self.assertEqual(inst._load_receipt(game_id)["installation_id"], receipt["installation_id"])
                        self.assertEqual(len(json.loads(catalog.read_text())), 1)
                        for name, content in originals.items():
                            self.assertEqual((source / name).read_bytes(), content)
                        print(f"Validated {game_id} {version}: {info['digest']}; real runner, synthetic media")
                    finally:
                        runner.close()

    def test_star_wars(self):
        self.exercise("star-wars-trilogy-arcade")

    def test_la_machineguns(self):
        self.exercise("l-a-machineguns")

    def test_la_machineguns_real_publication_recovery(self):
        self.exercise("l-a-machineguns", reconcile_missing_state=True)

    def test_episode_enyo(self):
        self.exercise("quake-slave-zero-x")

    @unittest.skipUnless(os.environ.get("MCL_ENYO_DOWNLOAD_TESTS") == "1",
                         "opt-in real publisher download and new Enyo integration")
    def test_episode_enyo_publisher_download(self):
        self.exercise("quake-slave-zero-x", publisher_download=True)

    def test_brutal_doom(self):
        self.exercise("brutal-doom")

    def test_hod2(self):
        self.exercise("the-house-of-the-dead-2")

    def test_hod2_reuses_supported_system_when_user_copy_is_untested(self):
        self.exercise("the-house-of-the-dead-2", competing_user=True)

    def test_brutal_doom_reuses_supported_system_when_user_copy_is_untested(self):
        self.exercise("brutal-doom", competing_user=True)

    def test_brutal_doom_missing_software_separate_pinned_approval(self):
        self.exercise("brutal-doom", prepare_missing=True)

    def test_hod2_missing_software_separate_pinned_approval(self):
        self.exercise("the-house-of-the-dead-2", prepare_missing=True)

    def test_brutal_doom_exact_additional_503_build_reused(self):
        self.exercise("brutal-doom", uzdoom_version="5.0.3",
                      uzdoom_commit="6c574decab62fc97a68c5c23daacafcab37fa1f1cb9362e85c2f6b285cfd3a19")

    def test_hod2_exact_additional_runtime26_build_reused(self):
        self.exercise("the-house-of-the-dead-2",
                      flycast_commit="0f8d2124d1c17696baec607c417d817f0331878c0e88f207c118b82c4dc7a9a1")
