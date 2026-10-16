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

    def check_fixture(self, fixture):
        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        self.assertIsNotNone(chrome, "Chrome/Chromium is needed for the requested browser test")
        with tempfile.TemporaryDirectory(prefix="mcl-ui-") as tmp:
            root = Path(tmp)
            shutil.copytree(HERE / "web", root / "web")
            shutil.copy(HERE / "tests" / "fixtures" / fixture, root / "test.html")
            handler = functools.partial(QuietHandler, directory=tmp)
            http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            try:
                result = subprocess.run([
                    chrome, "--headless=new", "--disable-gpu", "--disable-background-networking",
                    "--disable-extensions", "--no-first-run", f"--user-data-dir={root / 'profile'}",
                    "--virtual-time-budget=5000", "--dump-dom",
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
