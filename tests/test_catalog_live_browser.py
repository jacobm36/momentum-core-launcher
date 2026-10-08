"""Opt-in real public catalog/ZIP and headless GUI; synthetic media and fake emulator only.

MCL_CATALOG_TESTS=1 python3 -m unittest tests.test_catalog_live_browser
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import catalog
import installs
import jobs
import packages
import server
import supermodel
import vkquake
import eduke32
from tests.test_quake_installs import write_pak
from tests.test_doom_installs import write_iwad, fake_flatpak
from tests.test_duke_installs import write_grp

HERE = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("MCL_CATALOG_TESTS") == "1", "opt-in real public download/headless test")
class CatalogLiveBrowser(unittest.TestCase):
    def test_public_download_to_game_install_via_actual_gui_and_api(self):
        self.exercise("the-house-of-the-dead-2", "The House of the Dead 2", "0.1.3")

    def test_virtua_cop_2_public_gui_install(self):
        self.exercise("virtua-cop-2", "Virtua Cop 2", "0.1.0")

    def test_star_wars_public_gui_install(self):
        self.exercise("star-wars-trilogy-arcade", "Star Wars Trilogy Arcade", "0.1.0")

    def test_la_machineguns_public_gui_install(self):
        self.exercise("l-a-machineguns", "L.A. Machineguns", "0.1.0")

    def test_episode_enyo_public_gui_install(self):
        self.exercise("quake-slave-zero-x", "Quake - Slave Zero X: Episode Enyo", "0.1.0")

    def test_brutal_doom_64_public_gui_install(self):
        self.exercise("brutal-doom-64", "Brutal Doom 64", "0.1.0")

    def test_duke_public_gui_install(self):
        self.exercise("duke-nukem-3d", "Duke Nukem 3D", "0.1.1")

    def exercise(self, game_id, name, version):
        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        self.assertIsNotNone(chrome)
        evidence = json.loads((HERE / "docs/hod2-target-evidence.json").read_text())
        metadata = f"    Version: {evidence['emulator_version']}\n    Commit: {evidence['emulator_commit']}"
        native = supermodel.detect() if game_id in ("star-wars-trilogy-arcade", "l-a-machineguns") else None
        quake = vkquake.detect() if game_id == "quake-slave-zero-x" else None
        doom = game_id == "brutal-doom-64"
        duke = eduke32.detect() if game_id == "duke-nukem-3d" else None
        with tempfile.TemporaryDirectory(prefix="mcl-catalog-live-") as tmp:
            root = Path(tmp)
            home, app, source, tools = (root / name for name in ("home", "launcher", "source", "tools"))
            for directory in (home, app, source, tools):
                directory.mkdir()
            shutil.copytree(HERE / "web", app / "web")
            html = (HERE / "tests/fixtures/catalog-live.html").read_text()
            html = html.replace("SOURCE_DIRECTORY", json.dumps(str(source))).replace(
                "GAMES_ROOT", json.dumps(str(home / "Games")))
            html = html.replace("the-house-of-the-dead-2", game_id).replace("The House of the Dead 2", name)
            html = html.replace("SETUP_WAIT_ATTEMPTS", "6000" if quake or doom or duke else "1000")
            (app / "web/catalog-live.html").write_text(html)
            (app / "games.json").write_text("[]")
            (source / "House of the Dead 2, The (USA).cue").write_text(
                'FILE "track 01.bin" BINARY\n TRACK 01 MODE1/2352\n INDEX 01 00:00:00\n')
            (source / "track 01.bin").write_bytes(b"synthetic media, not a game" * 100)
            if duke:
                self.assertTrue(duke["installed"], "Known-working EDuke32 required for isolated GUI validation")
                engine = home / "Games/Duke-Nukem-3D/eduke32"
                engine.parent.mkdir(parents=True)
                shutil.copyfile(duke["executable"], engine)
                engine.chmod(0o755)
                write_grp(source / "DUKE3D.GRP")
            if quake:
                self.assertTrue(quake["installed"], "Pinned vkQuake is required for isolated live GUI verification")
                engine = home / "Applications/vkquake.AppImage"
                engine.parent.mkdir()
                shutil.copyfile(quake["executable"], engine)
                engine.chmod(0o755)
                write_pak(source / "id1/pak0.pak", {"gfx/palette.lmp": b"synthetic palette"})
                write_pak(source / "id1/pak1.pak", {"maps/e1m1.bsp": b"synthetic map"})
            if game_id == "virtua-cop-2":
                lines = ["39"]
                for n in range(1, 40):
                    track = f"track {n:02d}.bin"
                    (source / track).write_bytes(b"synthetic media, not a game" * 100)
                    lines.append(f'{n} {n * 45000} 4 2352 "{track}" 0')
                (source / "Virtua Cop 2 (Japan).gdi").write_text("\n".join(lines) + "\n")
            if native:
                self.assertTrue(native["installed"], "Opt-in browser verification needs the pinned native software")
                target = home / "Games/Supermodel"
                for asset in supermodel.RUNTIME_FILES:
                    p = target / asset
                    p.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(Path(native["root"]) / asset, p)
                    p.chmod(supermodel.ASSET_INVENTORY[asset][1])
                media = "swtrilgy.zip" if game_id == "star-wars-trilogy-arcade" else "lamachin.zip"
                with zipfile.ZipFile(source / media, "w") as archive:
                    archive.writestr("synthetic.rom", b"synthetic arcade media, not a playable game")
            flatpak = tools / "flatpak"
            flatpak.write_text(f"""#!{sys.executable}
import sys
command = sys.argv[1]
if command == 'ps': pass
elif command == 'remotes': print('flathub\\thttps://dl.flathub.org/repo/')
elif command == 'list': print('org.flycast.Flycast')
elif command == 'info': print({metadata!r})
else: sys.exit('Real emulator execution is prohibited in this test')
""")
            flatpak.chmod(0o755)
            if doom:
                write_iwad(source / "DOOM2.WAD")
                marker = root / "software-ready"
                marker.touch()
                fake_flatpak(flatpak, marker, scope="system")
            runner = jobs.Jobs(app / "jobs")
            completed = threading.Event()
            outcome = {}

            class LiveHandler(server.Handler):
                def do_GET(self):
                    parsed = urlsplit(self.path)
                    if parsed.path != "/catalog-live-result":
                        return super().do_GET()
                    outcome["status"] = parse_qs(parsed.query).get("status", [""])[0]
                    self._json({"received": True})
                    completed.set()

            http = ThreadingHTTPServer(("127.0.0.1", 0), LiveHandler)
            lock = threading.RLock()
            inst = installs.Installs(app, lock, lambda: json.loads((app / "games.json").read_text()),
                                    lambda games: installs._write_atomic(app / "games.json", json.dumps(games).encode()),
                                    runner)
            runner.on_success, runner.before_step = inst.on_success, inst.before_step
            worker = threading.Thread(target=http.serve_forever, daemon=True)
            try:
                with mock.patch.dict(os.environ, {"HOME": str(home), "PATH": str(tools) + ":" + os.environ["PATH"]}), \
                        mock.patch.multiple(server, HERE=app, PORT=http.server_port, JOBS=runner,
                                            INSTALLS=inst, STATS=app / "playstats.json", lock=lock):
                    # Fetch the real public catalog before launching Chrome, not a mocked endpoint.
                    self.assertIn(game_id, [game["id"] for game in catalog.load()["games"]])
                    worker.start()
                    # Real downloads and worker processes need wall time, not Chrome's virtual clock.
                    with tempfile.TemporaryFile() as browser_log:
                        browser = subprocess.Popen([
                            chrome, "--headless=new", "--disable-gpu", "--disable-background-networking",
                            "--disable-extensions", "--no-first-run", f"--user-data-dir={root / 'browser'}",
                            f"http://127.0.0.1:{http.server_port}/web/catalog-live.html",
                        ], stdout=subprocess.DEVNULL, stderr=browser_log)
                        try:
                            finished = completed.wait(600 if quake or doom or duke else 150)
                            browser_log.seek(0)
                            diagnostics = browser_log.read().decode(errors="replace")[-1500:]
                            self.assertTrue(finished, f"GUI did not finish; browser={browser.poll()}, "
                                            f"jobs={runner.list()}, stderr={diagnostics}")
                            self.assertTrue(outcome["status"].startswith("PASS:"), outcome["status"])
                        finally:
                            if browser.poll() is None:
                                browser.terminate()
                            try:
                                browser.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                browser.kill()
                                browser.wait(timeout=10)
                    receipt = inst._load_receipt(game_id)
                    self.assertEqual(receipt["package_version"], version)
                    self.assertEqual(receipt["readiness"], "setup-required")
                    self.assertEqual(len(json.loads((app / "games.json").read_text())), 1)
                    self.assertEqual((source / "track 01.bin").read_bytes(), b"synthetic media, not a game" * 100)
                    self.assertTrue(Path(receipt["game_directory"]).is_relative_to(home))
            finally:
                if worker.is_alive():
                    http.shutdown()
                    worker.join()
                http.server_close()
                runner.close()
                packages._rmtree(app / "packages")
