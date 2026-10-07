"""Native picker tests never open desktop dialogs."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import picker


class PickerTests(unittest.TestCase):
    def test_selection_preserves_spaces_and_uses_existing_parent(self):
        with tempfile.TemporaryDirectory(prefix="game folder ") as tmp, \
                mock.patch("picker.shutil.which", return_value="/usr/bin/zenity"), \
                mock.patch("picker.subprocess.run", return_value=subprocess.CompletedProcess([], 0, tmp + "\n", "")) as run:
            self.assertEqual(picker.choose_directory(str(Path(tmp) / "new")), tmp)
            self.assertIn("--filename=" + tmp + "/", run.call_args.args[0])
            self.assertNotIn("shell", run.call_args.kwargs)

    def test_cancel_and_kdialog(self):
        with mock.patch("picker.shutil.which", side_effect=[None, "/usr/bin/kdialog"]), \
                mock.patch("picker.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "")) as run:
            self.assertIsNone(picker.choose_directory())
            self.assertEqual(run.call_args.args[0][1], "--getexistingdirectory")

    def test_missing_tool_failure_timeout_and_invalid_selection_are_explicit(self):
        with mock.patch("picker.shutil.which", return_value=None):
            with self.assertRaisesRegex(picker.PickerError, "Zenity"):
                picker.choose_directory()
        for result in (subprocess.CompletedProcess([], 1, "", "cannot open display"),
                       subprocess.CompletedProcess([], 2, "", "no display"),
                       subprocess.CompletedProcess([], 0, "relative\n", "")):
            with mock.patch("picker.shutil.which", return_value="/usr/bin/zenity"), \
                    mock.patch("picker.subprocess.run", return_value=result):
                with self.assertRaises(picker.PickerError):
                    picker.choose_directory()
        with mock.patch("picker.shutil.which", return_value="/usr/bin/zenity"), \
                mock.patch("picker.subprocess.run", side_effect=subprocess.TimeoutExpired("zenity", 300)):
            with self.assertRaisesRegex(picker.PickerError, "timed out"):
                picker.choose_directory()
        self.assertFalse(picker._lock.locked())

    def test_invalid_inputs_and_concurrent_picker(self):
        for value in ("relative", "/bad\0path", None):
            with self.assertRaises(picker.PickerError):
                picker.choose_directory(value)
        with picker._lock:
            with self.assertRaisesRegex(picker.PickerError, "already open"):
                picker.choose_directory()
