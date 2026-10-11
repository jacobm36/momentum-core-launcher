"""Opt-in complete Brutal Doom 64 package and real runner; mocked Flatpak, no games."""
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest import mock

import installs
import jobs
import packages
import uzdoom

PACKAGE_REPO = Path(os.environ.get("MCL_PACKAGE_REPO",
                                  str(Path(__file__).resolve().parents[2] / "momentum-packages")))
GAME_ID = "brutal-doom-64"
VERSION = "5.0.1"
COMMIT = "d7b8ce76e5480a28d1e07400093a20d47f56c201fd974b0a5dbfa3b26bbd587e"


def write_iwad(path):
    names = ("MAP01", "MAP30", "THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SECTORS")
    path.write_bytes(struct.pack("<4sii", b"IWAD", len(names), 12) +
                     b"".join(struct.pack("<ii8s", 12, 0, name.encode()) for name in names))


def fake_flatpak(path, marker, scope="user", commit=COMMIT, app="org.zdoom.UZDoom", version=VERSION,
                 competing_user_commit=None):
    path.write_text(f"""#!/usr/bin/env python3
from pathlib import Path
import sys
args=sys.argv[1:]
ready=Path({str(marker)!r})
scope={scope!r}
app={app!r}
commit={commit!r}
competing_user_commit={competing_user_commit!r}
if competing_user_commit and '--user' in args:
    scope='user'
    commit=competing_user_commit
if ready.exists() and ready.read_text()=='unpinned': commit='b'*64
if args[0]=='ps': pass
elif args[0]=='remotes': print('flathub\\thttps://dl.flathub.org/repo/')
elif args[0]=='list':
    if '--runtime' in args: print('org.freedesktop.Platform/x86_64/25.08')
    elif ready.exists() and '--'+scope in args:
        print(app if '--columns=application' in args else app+'\\tx86_64\\tstable\\tflathub')
elif args[0]=='info':
    if not ready.exists(): sys.exit(1)
    if '--show-commit' in args: print(commit)
    elif '--show-ref' in args: print('runtime/org.freedesktop.Platform/x86_64/25.08' if args[-1].startswith('org.freedesktop.Platform/') else 'app/'+app+'/x86_64/stable')
    elif '--show-metadata' in args: print('[Application]\\nname='+app+'\\nruntime=org.freedesktop.Platform/x86_64/25.08\\ncommand=uzdoom')
    elif '--show-origin' in args: print('flathub')
    elif '--show-runtime' in args: print('org.freedesktop.Platform/x86_64/25.08')
    else: print('Ref: app/'+app+'/x86_64/stable\\nVersion: {version}\\nCommit: '+commit+'\\nArch: x86_64\\nBranch: stable\\nOrigin: flathub\\nRuntime: org.freedesktop.Platform/x86_64/25.08')
elif args[0]=='remote-info':
    assert '--commit='+{commit!r} in args
    print('Commit: '+{commit!r})
elif args[0]=='install':
    assert '--user' in args and '--noninteractive' in args and (app in args or 'app/'+app+'/x86_64/stable' in args)
    ready.write_text('unpinned')
elif args[0]=='update':
    assert '--user' in args and '--noninteractive' in args and '--commit='+{commit!r} in args
    assert ready.exists()
    ready.write_text('pinned')
else: sys.exit('Unexpected Flatpak operation; game launches forbidden: '+str(args))
""")
    path.chmod(0o755)


@unittest.skipUnless(os.environ.get("MCL_DOOM_TESTS") == "1", "opt-in complete Doom mod integration")
class DoomInstalls(unittest.TestCase):
    game_id = GAME_ID
    package_version = "0.1.0"
    mod_directory = "mods/BrutalDoom64"
    files = ("bd64gamev2.pk3", "bd64mapsV2.pk3", "STAnnouncerPack.pk3", "ZD64MUSIC.PK3")
    load_order = files

    def wait(self, runner, jid):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and runner.get(jid)["status"] in jobs.RUNNING:
            time.sleep(.02)
        return runner.get(jid)

    def test_system_reuse_lifecycle_preservation_and_reinstall(self):
        self.exercise(scope="system", lifecycle=True)

    def test_user_reuse(self):
        self.exercise()

    def test_missing_user_preparation_then_separate_game_approval(self):
        self.exercise(missing=True)

    def test_unapproved_build_stays_gated(self):
        self.exercise(commit="a" * 64)

    def exercise(self, scope="user", missing=False, lifecycle=False, commit=COMMIT):
        with tempfile.TemporaryDirectory(prefix="momentum-doom-runner-") as temporary:
            root = Path(temporary)
            home, app, source, tools = (root / p for p in ("home with spaces", "launcher", "IWAD source", "tools"))
            for p in (home, app, source, tools):
                p.mkdir()
            marker = root / "software-ready"
            if not missing:
                marker.touch()
            fake_flatpak(tools / "flatpak", marker, scope, commit)
            write_iwad(source / "DOOM2.WAD")
            original = (source / "DOOM2.WAD").read_bytes()
            state = home / ".var/app/org.zdoom.UZDoom/config/personal.ini"
            state.parent.mkdir(parents=True)
            state.write_text("keep personal settings")
            catalog = app / "games.json"
            catalog.write_text("[]")
            with mock.patch.dict(os.environ, {"HOME": str(home), "PATH": str(tools) + ":" + os.environ["PATH"]}):
                info = packages.import_package(
                    PACKAGE_REPO / f"dist/{self.game_id}-{self.package_version}.zip", app)
                runner = jobs.Jobs(app / "jobs")
                inst = installs.Installs(app, threading.Lock(), lambda: json.loads(catalog.read_text()),
                                        lambda gs: installs._write_atomic(catalog, json.dumps(gs).encode()), runner)
                runner.on_success, runner.before_step = inst.on_success, inst.before_step

                def submit():
                    return inst.submit_install(self.game_id, self.package_version, str(source), trusted_digest=info["digest"])

                def approve(jid):
                    job = self.wait(runner, jid)
                    self.assertEqual(job["status"], "awaiting-approval", job)
                    self.assertNotIn("approval_blocked", job)
                    self.assertIs(inst.approve(jid, job["plan_digest"]), True)
                    return self.wait(runner, jid)

                def operation(name, receipt, template):
                    detail = inst.package_details(self.game_id, self.package_version)
                    context = dict(template, operation=name, previous_receipt=receipt,
                                   dependencies=detail["dependencies"])
                    steps = [{"name": f"{name} {phase}", "protocol": True, "approve_after": phase == "preflight",
                              "declared_steps": detail["manifest"]["operations"][name]["steps"],
                              "argv": ["bash", f"{name}.sh", "--context", "{context_file}", "--phase", phase],
                              "cwd": context["package_root"], "context": dict(context, phase=phase)}
                             for phase in ("preflight", "apply")]
                    meta = dict(runner.jobs[template_jid]["meta"], operation=name)
                    return runner.submit(name, steps, game=self.game_id, meta=meta)

                try:
                    jid = submit()
                    job = self.wait(runner, jid)
                    self.assertEqual(job["status"], "awaiting-approval", job)
                    if commit != COMMIT:
                        self.assertIn("approval_blocked", job)
                        self.assertIsNot(inst.approve(jid, job["plan_digest"]), True)
                        self.assertFalse((home / "Games").exists())
                        self.assertEqual(json.loads(catalog.read_text()), [])
                        return
                    if missing:
                        self.assertEqual(job["plan"]["operation"], "prepare-dependency")
                        self.assertFalse((home / "Games").exists())
                        job = approve(jid)
                        self.assertEqual(job["status"], "awaiting-approval", job)
                        self.assertNotEqual(job["plan"]["operation"], "prepare-dependency")
                    runner.close()
                    runner = jobs.Jobs(app / "jobs", on_success=inst.on_success, before_step=inst.before_step)
                    inst.jobs = runner
                    self.assertEqual(runner.get(jid)["plan_digest"], job["plan_digest"])
                    self.assertEqual(approve(jid)["status"], "succeeded", runner.get(jid))
                    receipt = inst._load_receipt(self.game_id)
                    game = Path(receipt["game_directory"])
                    self.assertEqual(receipt["readiness"], "setup-required")
                    wrapper = Path(receipt["paths"]["launcher"]).read_text()
                    self.assertIn(f"flatpak run --{scope}", wrapper)
                    self.assertIn('--filesystem="$game_dir:ro"', wrapper)
                    self.assertEqual(sorted(self.load_order, key=wrapper.index), list(self.load_order))
                    self.assertTrue(all((game / self.mod_directory / f).is_file() for f in self.files))
                    if self.game_id == "brutal-doom":
                        self.assertIn('if [[ "${1:-}" == "--metal" ]]', wrapper)
                        self.assertNotIn("brutalVoxelDoom", wrapper)
                    if self.game_id == "ashes-2063":
                        self.assertNotIn("FDPatch", wrapper)
                        self.assertNotIn("game_support", wrapper)
                    if not lifecycle:
                        return
                    template_jid = jid
                    template = runner.jobs[jid]["steps"][-1]["context"].copy()
                    repeat = submit()
                    self.assertEqual(self.wait(runner, repeat)["plan"]["actions"], [])
                    self.assertEqual(approve(repeat)["status"], "succeeded", runner.get(repeat))
                    receipt = inst._load_receipt(self.game_id)
                    (game / self.mod_directory / self.files[0]).unlink()
                    repair = operation("repair", receipt, template)
                    self.assertEqual(approve(repair)["status"], "succeeded", runner.get(repair))
                    receipt = inst._load_receipt(self.game_id)
                    (game / "save.zds").write_text("keep this save")
                    remove = operation("uninstall", receipt, template)
                    self.assertEqual(approve(remove)["status"], "succeeded", runner.get(remove))
                    self.assertFalse((game / self.mod_directory / self.files[0]).exists())
                    self.assertEqual((game / "DOOM2.WAD").read_bytes(), original)
                    reinstall = submit()
                    self.assertEqual(approve(reinstall)["status"], "succeeded", runner.get(reinstall))
                    self.assertEqual((game / "save.zds").read_text(), "keep this save")
                    self.assertEqual(inst._load_receipt(self.game_id)["installation_id"], receipt["installation_id"])
                    self.assertEqual(len(json.loads(catalog.read_text())), 1)
                    cancel = submit()
                    self.assertEqual(self.wait(runner, cancel)["status"], "awaiting-approval")
                    self.assertIs(runner.cancel(cancel), True)
                finally:
                    self.assertEqual((source / "DOOM2.WAD").read_bytes(), original)
                    self.assertEqual(state.read_text(), "keep personal settings")
                    runner.close()
                    packages._rmtree(app / "packages")


class BrutalDoomInstalls(DoomInstalls):
    game_id = "brutal-doom"
    mod_directory = "mods/Brutal_Doom"
    files = ("brutalv21.pk3", "DoomMetalVol5.wad")
    load_order = ("brutalv21.pk3",)


class AliensInstalls(DoomInstalls):
    game_id = "aliens-eradication"
    mod_directory = "mods/Aliens_Eradication"
    files = ("ALIENS_ERADICATION_TC_2_0.pk3", "ERADICATION_MAPSET_2_0.wad")
    load_order = files


class AshesInstalls(DoomInstalls):
    game_id = "ashes-2063"
    mod_directory = "mods/Ashes_2063"
    files = ("Ashes2063Enriched2_23.pk3",)
    load_order = files
