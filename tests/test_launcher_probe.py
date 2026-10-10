"""Actual loopback probing and startup with no curl executable available."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

import launcher_probe

HERE = Path(__file__).parents[1]


class Handler(BaseHTTPRequestHandler):
    mode = "momentum"

    def log_message(self, *args):
        pass

    def do_GET(self):
        status = 200
        body = b'{"app":"momentum-core-launcher"}' if self.path == "/api/id" else b"<title>Momentum Core Launcher</title>"
        if self.mode == "legacy" and self.path == "/api/id":
            status, body = 404, b"not found"
        elif self.mode == "foreign":
            status, body = 403, b"foreign service"
        elif self.mode == "redirect":
            status, body = 302, b""
        self.send_response(status)
        if status == 302:
            self.send_header("Location", "https://example.invalid/")
        self.end_headers()
        self.wfile.write(body)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()

    def test_identity_legacy_foreign_redirect_and_closed_port(self):
        for mode, ours in (("momentum", True), ("legacy", True), ("foreign", False), ("redirect", False)):
            with self.subTest(mode=mode), mock.patch.object(Handler, "mode", mode):
                self.assertEqual(launcher_probe.probe(self.http.server_port, "ours"), ours)
                self.assertTrue(launcher_probe.probe(self.http.server_port, "responding"))
        import socket
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        self.assertFalse(launcher_probe.probe(port, "responding"))

    def test_launch_and_guard_work_without_curl(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root / "tools"
            tools.mkdir()
            for name in ("bash", "python3", "dirname", "readlink", "mkdir", "flock"):
                (tools / name).symlink_to(shutil.which(name))
            browser = tools / "google-chrome"
            browser.write_text("#!/bin/bash\nprintf '%s\\n' \"$@\" > \"$HOME/browser-args\"\n")
            browser.chmod(0o755)
            env = dict(os.environ, HOME=str(root), PATH=str(tools), MCL_PORT=str(self.http.server_port),
                       MCL_WINDOWED="1")
            result = subprocess.run(["/bin/bash", str(HERE / "launch.sh")], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--app=http://127.0.0.1:", (root / "browser-args").read_text())
            result = subprocess.run(["/bin/bash", str(HERE / "start-candidate.sh")], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn("already serving", result.stderr)
            with mock.patch.object(Handler, "mode", "foreign"):
                result = subprocess.run(["/bin/bash", str(HERE / "launch.sh")], env=env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 1)
                self.assertIn("another program", result.stderr)
