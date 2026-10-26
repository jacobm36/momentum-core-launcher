"""Opt-in headless UI regression: MCL_BROWSER_TESTS=1 python3 -m unittest tests.test_package_ui_browser."""
import functools
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get("MCL_BROWSER_TESTS") == "1", "opt-in headless Chrome test")
class PackageBrowser(unittest.TestCase):
    def test_import_trust_inputs_and_plan_review(self):
        self.check_fixture("package-ui.html")

    def test_video_background_and_featured_artwork(self):
        self.check_fixture("library-media.html")

    def test_controller_handoff(self):
        self.check_fixture("gamepad.html")

    def test_bounded_decorative_motion(self):
        self.check_fixture("motion-performance.html")

    def test_library_count(self):
        self.check_fixture("library-count.html")

    def test_session_notifications(self):
        self.check_fixture("notifications.html")

    def test_steamgriddb_editor(self):
        self.check_fixture("steamgriddb.html", window="1280,720")

    def test_browsing_state_info_and_720p_layout(self):
        self.check_fixture("launcher-polish.html", window="1280,720")

    def test_tiled_library(self):
        self.check_fixture("library-tiles.html", window="1280,720")

    def test_tiled_library_desktop(self):
        self.check_fixture("library-tiles.html", window="1920,1080")

    def test_grid_and_game_details(self):
        self.check_fixture("library-details.html", window="1280,720")

    def test_grid_and_game_details_desktop(self):
        self.check_fixture("library-details.html", window="1920,1080")

    def test_grid_and_game_details_compact(self):
        self.check_fixture("library-details.html", window="640,720")

    def test_library_sidebar(self):
        self.check_fixture("library-sidebar.html", window="1280,720")

    def test_library_sidebar_desktop(self):
        self.check_fixture("library-sidebar.html", window="1920,1080")

    def test_selected_tile_preview(self):
        self.check_fixture("tile-preview.html", window="1280,720", virtual_time=15000)

    def test_video_frame_capture(self):
        self.check_fixture("frame-capture.html", window="1280,720", virtual_time=None)

    def check_fixture(self, fixture, window="1280,900", virtual_time=5000):
        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        self.assertIsNotNone(chrome, "Chrome/Chromium is needed for the requested browser test")
        with tempfile.TemporaryDirectory(prefix="mcl-ui-") as tmp:
            root = Path(tmp)
            shutil.copytree(HERE / "web", root / "web")
            shutil.copy(HERE / "tests" / "fixtures" / fixture, root / "test.html")
            finished = threading.Event()
            reported = []

            class ResultHandler(QuietHandler):
                def do_POST(self):
                    if self.path != "/test-result":
                        self.send_error(404)
                        return
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 20000:
                        self.send_error(400)
                        return
                    reported.append(self.rfile.read(size).decode())
                    self.send_response(204)
                    self.end_headers()
                    finished.set()

            handler = functools.partial(ResultHandler, directory=tmp)
            http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            try:
                if virtual_time is None:
                    with (root / "chrome.log").open("w+") as log:
                        process = subprocess.Popen([
                            chrome, "--headless=new", "--disable-gpu", "--disable-background-networking",
                            f"--window-size={window}", "--force-device-scale-factor=1",
                            "--disable-extensions", "--no-first-run", f"--user-data-dir={root / 'profile'}",
                            f"http://127.0.0.1:{http.server_port}/test.html?report=1",
                        ], stdout=log, stderr=subprocess.STDOUT)
                        try:
                            completed = finished.wait(30)
                            log.seek(0)
                            self.assertTrue(completed, "Real-time browser fixture timed out: " + log.read()[-1500:])
                            self.assertIn("PASS:", reported[0], reported[0])
                        finally:
                            if process.poll() is None:
                                process.terminate()
                            try:
                                process.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait(timeout=5)
                    return
                result = subprocess.run([
                    chrome, "--headless=new", "--disable-gpu", "--disable-background-networking",
                    f"--window-size={window}", "--force-device-scale-factor=1",
                    "--disable-extensions", "--no-first-run", f"--user-data-dir={root / 'profile'}",
                    f"--virtual-time-budget={virtual_time}", "--dump-dom",
                    f"http://127.0.0.1:{http.server_port}/test.html"
                ], capture_output=True, text=True, timeout=45)
                self.assertEqual(result.returncode, 0, result.stderr[-1500:])
                start = result.stdout.find('<pre id="result">')
                evidence = result.stdout[start:result.stdout.find("</pre>", start)]
                self.assertIn("PASS:", evidence, evidence)
            finally:
                http.shutdown()
                http.server_close()
                thread.join()
