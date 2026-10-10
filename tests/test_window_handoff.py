import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import server
from window_handoff import HandoffError, KioskHandoff


class WindowHandoffTests(unittest.TestCase):
    def setUp(self):
        self.handoff = KioskHandoff(47615)
        self.env = mock.patch.dict(os.environ, {"DISPLAY": ":1", "XDG_SESSION_TYPE": "x11"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def release(self, windows=None, fullscreen=True):
        with mock.patch.object(self.handoff, "_kiosk", side_effect=lambda pid: pid == os.getpid()), \
                mock.patch("window_handoff.shutil.which", return_value="/usr/bin/tool"), \
                mock.patch.object(self.handoff, "_windows", return_value=windows or [("0x123", os.getpid())]), \
                mock.patch.object(self.handoff, "_fullscreen", return_value=fullscreen), \
                mock.patch.object(self.handoff, "_set_fullscreen") as change:
            self.handoff.release()
            return change

    def test_release_only_owned_fullscreen_kiosk_and_restore(self):
        change = self.release([("0x456", 1), ("0x123", os.getpid())])
        change.assert_called_once_with("0x123", False)
        with mock.patch.object(self.handoff, "_kiosk", return_value=True), \
                mock.patch.object(self.handoff, "_windows", return_value=[("0x123", os.getpid())]), \
                mock.patch.object(self.handoff, "_set_fullscreen") as restore:
            self.handoff.restore()
        restore.assert_called_once_with("0x123", True)
        self.assertIsNone(self.handoff.window)

    def test_repeated_release_does_not_lose_restore_identity(self):
        self.release()
        with mock.patch.object(self.handoff, "_windows") as windows:
            self.handoff.release()
        windows.assert_not_called()
        self.assertEqual(self.handoff.window, ("0x123", os.getpid()))

    def test_nonfullscreen_window_unchanged(self):
        self.release(fullscreen=False).assert_not_called()
        self.assertIsNone(self.handoff.window)

    def test_wayland_unchanged(self):
        with mock.patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}), \
                mock.patch.object(self.handoff, "_kiosk") as kiosk:
            self.handoff.release()
        kiosk.assert_not_called()

    def test_windowed_browser_does_not_require_tools(self):
        with mock.patch.object(self.handoff, "_kiosk", return_value=False), \
                mock.patch("window_handoff.shutil.which") as which:
            self.handoff.release()
        which.assert_not_called()

    def test_missing_tools_explicitly_block_kiosk_handoff(self):
        with mock.patch.object(self.handoff, "_kiosk", return_value=True), \
                mock.patch("window_handoff.shutil.which", return_value=None):
            with self.assertRaisesRegex(HandoffError, "requires wmctrl and xprop"):
                self.handoff.release()

    def test_ambiguous_windows_are_not_changed(self):
        with self.assertRaisesRegex(HandoffError, "Multiple"):
            self.release([("0x123", os.getpid()), ("0x456", os.getpid())])
        self.assertIsNone(self.handoff.window)

    def test_changed_window_identity_not_restored(self):
        self.release()
        with mock.patch.object(self.handoff, "_kiosk", return_value=True), \
                mock.patch.object(self.handoff, "_windows", return_value=[("0x123", 1)]), \
                mock.patch.object(self.handoff, "_set_fullscreen") as restore:
            self.handoff.restore()
        restore.assert_not_called()
        self.assertIsNone(self.handoff.window)

    def test_restore_failure_visible_and_retryable(self):
        self.release()
        with mock.patch.object(self.handoff, "_kiosk", return_value=True), \
                mock.patch.object(self.handoff, "_windows", return_value=[self.handoff.window]), \
                mock.patch.object(self.handoff, "_set_fullscreen", side_effect=HandoffError("WM refused")):
            self.handoff.restore()
        self.assertEqual(self.handoff.warning, "WM refused")
        self.assertIsNotNone(self.handoff.window)

    def test_window_manager_acknowledgement_is_checked(self):
        with mock.patch.object(self.handoff, "_run") as run, \
                mock.patch.object(self.handoff, "_fullscreen", side_effect=[True, False]), \
                mock.patch("window_handoff.time.sleep"):
            self.handoff._set_fullscreen("0x123", False)
        run.assert_called_once_with("wmctrl", "-ir", "0x123", "-b", "remove,fullscreen")

    def test_tool_failure_is_not_success(self):
        with mock.patch("window_handoff.subprocess.run",
                        return_value=subprocess.CompletedProcess([], 1, "", "failed")):
            with self.assertRaisesRegex(HandoffError, "failed"):
                self.handoff._run("wmctrl", "-lp")

    def test_process_identity_requires_exact_profile_url_and_kiosk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = root / "123"
            process.mkdir()
            command = process / "cmdline"
            command.write_bytes(b"\0".join(arg.encode() for arg in
                                ("chrome", "--kiosk", self.handoff.profile, self.handoff.url)))
            with mock.patch("window_handoff.Path", side_effect=lambda path: root if path == "/proc" else Path(path)):
                self.assertTrue(self.handoff._kiosk(123))
                command.write_bytes(b"chrome\0--kiosk\0--user-data-dir=/unrelated\0")
                self.assertFalse(self.handoff._kiosk(123))

    def test_track_restores_only_after_last_game_exits(self):
        process = mock.Mock()
        process.wait.return_value = 0
        other = mock.Mock()
        for other_alive in (True, False):
            with self.subTest(other_alive=other_alive), \
                    mock.patch.object(server, "running", {"game": process, "other": other}), \
                    mock.patch.object(server, "started", {}), \
                    mock.patch.object(server, "alive", side_effect=lambda p: p is other and other_alive), \
                    mock.patch.object(server, "update_stats"), \
                    mock.patch.object(server.HANDOFF, "restore") as restore:
                server.track("game", process, 0)
                self.assertEqual(restore.call_count, 0 if other_alive else 1)
