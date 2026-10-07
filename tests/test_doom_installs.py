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

PACKAGE_REPO = Path(__file__).resolve().parents[2] / "momentum-packages"
GAME_ID = "brutal-doom-64"
VERSION = "5.0.1"
COMMIT = "d7b8ce76e5480a28d1e07400093a20d47f56c201fd974b0a5dbfa3b26bbd587e"


def write_iwad(path):
    names = ("MAP01", "MAP30", "THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SECTORS")
    path.write_bytes(struct.pack("<4sii", b"IWAD", len(names), 12) +
                     b"".join(struct.pack("<ii8s", 12, 0, name.encode()) for name in names))


def fake_flatpak(path, marker, scope="user", commit=COMMIT):
    path.write_text(f"""#!/usr/bin/env python3
from pathlib import Path
import sys
args=sys.argv[1:]
ready=Path({str(marker)!r})
scope={scope!r}
app='org.zdoom.UZDoom'
if args[0]=='ps': pass
elif args[0]=='remotes': print('flathub\\thttps://dl.flathub.org/repo/')
elif args[0]=='list':
    if '--runtime' in args: print('org.freedesktop.Platform/x86_64/25.08')
    elif ready.exists() and '--'+scope in args: print(app+'\\tx86_64\\tstable\\tflathub')
elif args[0]=='info':
    if not ready.exists(): sys.exit(1)
    if '--show-commit' in args: print({commit!r})
    elif '--show-ref' in args: print('runtime/org.freedesktop.Platform/x86_64/25.08' if args[-1].startswith('org.freedesktop.Platform/') else 'app/'+app+'/x86_64/stable')
    elif '--show-metadata' in args: print('[Application]\\nname='+app+'\\nruntime=org.freedesktop.Platform/x86_64/25.08\\ncommand=uzdoom')
    elif '--show-origin' in args: print('flathub')
    elif '--show-runtime' in args: print('org.freedesktop.Platform/x86_64/25.08')
    else: print('Ref: app/'+app+'/x86_64/stable\\nVersion: {VERSION}\\nCommit: {commit}\\nArch: x86_64\\nBranch: stable\\nOrigin: flathub\\nRuntime: org.freedesktop.Platform/x86_64/25.08')
elif args[0]=='install':
    assert '--user' in args and '--noninteractive' in args and 'app/'+app+'/x86_64/stable' in args
    ready.touch()
else: sys.exit('Unexpected Flatpak operation; game launches forbidden: '+str(args))
""")
    path.chmod(0o755)


@unittest.skipUnless(os.environ.get("MCL_DOOM_TESTS") == "1", "opt-in complete Doom mod integration")
class DoomInstalls(unittest.TestCase):
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
                info = packages.import_package(PACKAGE_REPO / "dist/brutal-doom-64-0.1.0.zip", app)
                runner = jobs.Jobs(app / "jobs")
                inst = installs.Installs(app, threading.Lock(), lambda: json.loads(catalog.read_text()),
                                        lambda gs: installs._write_atomic(catalog, json.dumps(gs).encode()), runner)
                runner.on_success, runner.before_step = inst.on_success, inst.before_step

                def submit():
                    return inst.submit_install(GAME_ID, "0.1.0", str(source), trusted_digest=info["digest"])

                def approve(jid):
                    job = self.wait(runner, jid)
                    self.assertEqual(job["status"], "awaiting-approval", job)
                    self.assertNotIn("approval_blocked", job)
                    self.assertIs(inst.approve(jid, job["plan_digest"]), True)
                    return self.wait(runner, jid)

                def operation(name, receipt, template):
                    detail = inst.package_details(GAME_ID, "0.1.0")
                    context = dict(template, operation=name, previous_receipt=receipt,
                                   dependencies=detail["dependencies"])
                    steps = [{"name": f"{name} {phase}", "protocol": True, "approve_after": phase == "preflight",
                              "declared_steps": detail["manifest"]["operations"][name]["steps"],
                              "argv": ["bash", f"{name}.sh", "--context", "{context_file}", "--phase", phase],
                              "cwd": context["package_root"], "context": dict(context, phase=phase)}
                             for phase in ("preflight", "apply")]
                    meta = dict(runner.jobs[template_jid]["meta"], operation=name)
                    return runner.submit(name, steps, game=GAME_ID, meta=meta)

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
                    receipt = inst._load_receipt(GAME_ID)
                    game = Path(receipt["game_directory"])
                    self.assertEqual(receipt["readiness"], "setup-required")
                    wrapper = Path(receipt["paths"]["launcher"]).read_text()
                    self.assertIn(f"flatpak run --{scope}", wrapper)
                    self.assertIn('--filesystem="$game_dir:ro"', wrapper)
                    files = ("bd64gamev2.pk3", "bd64mapsV2.pk3", "STAnnouncerPack.pk3", "ZD64MUSIC.PK3")
                    self.assertEqual(sorted(files, key=wrapper.index), list(files))
                    self.assertTrue(all((game / "mods/BrutalDoom64" / f).is_file() for f in files))
                    if not lifecycle:
                        return
                    template_jid = jid
                    template = runner.jobs[jid]["steps"][-1]["context"].copy()
                    repeat = submit()
                    self.assertEqual(self.wait(runner, repeat)["plan"]["actions"], [])
                    self.assertEqual(approve(repeat)["status"], "succeeded", runner.get(repeat))
                    receipt = inst._load_receipt(GAME_ID)
                    (game / "mods/BrutalDoom64/bd64gamev2.pk3").unlink()
                    repair = operation("repair", receipt, template)
                    self.assertEqual(approve(repair)["status"], "succeeded", runner.get(repair))
                    receipt = inst._load_receipt(GAME_ID)
                    (game / "save.zds").write_text("keep this save")
                    remove = operation("uninstall", receipt, template)
                    self.assertEqual(approve(remove)["status"], "succeeded", runner.get(remove))
                    self.assertFalse((game / "mods/BrutalDoom64/bd64gamev2.pk3").exists())
                    self.assertEqual((game / "DOOM2.WAD").read_bytes(), original)
                    reinstall = submit()
                    self.assertEqual(approve(reinstall)["status"], "succeeded", runner.get(reinstall))
                    self.assertEqual((game / "save.zds").read_text(), "keep this save")
                    self.assertEqual(inst._load_receipt(GAME_ID)["installation_id"], receipt["installation_id"])
                    self.assertEqual(len(json.loads(catalog.read_text())), 1)
                    cancel = submit()
                    self.assertEqual(self.wait(runner, cancel)["status"], "awaiting-approval")
                    self.assertIs(runner.cancel(cancel), True)
                finally:
                    self.assertEqual((source / "DOOM2.WAD").read_bytes(), original)
                    self.assertEqual(state.read_text(), "keep personal settings")
                    runner.close()
                    packages._rmtree(app / "packages")
