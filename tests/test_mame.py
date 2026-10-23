"""Pinned MAME detection and isolated preparation guards; no downloads/game launch."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from dependencies import DependencyError
import installs
import mame
import mame_flatpak as managed


class MameTests(unittest.TestCase):
    def probe(self, operation, *args):
        scope = "user" if "--user" in args else "system"
        if operation == "ps":
            return ""
        if operation == "list":
            if "--runtime" in args:
                return mame.RUNTIME + "\n"
            return (mame.APP + "\tx86_64\tstable\tflathub\n") if scope == "system" else ""
        if operation == "remotes":
            return "flathub\thttps://dl.flathub.org/repo/\n"
        if operation == "info":
            if "--show-ref" in args:
                return mame.REF + "\n"
            if "--show-commit" in args:
                return (mame.RUNTIME_COMMIT if args[-1] == mame.RUNTIME else mame.COMMIT) + "\n"
            if "--show-runtime" in args:
                return mame.RUNTIME + "\n"
            if "--show-metadata" in args:
                return f"[Application]\nname={mame.APP}\ncommand=mame\nruntime={mame.RUNTIME}\n"
            return f" Ref: {mame.REF}\n Version: {mame.VERSION}\n Commit: {mame.COMMIT}\n"
        raise AssertionError((operation, args))

    def test_system_fallback_and_exact_runtime_metadata(self):
        with mock.patch.object(mame, "probe", side_effect=self.probe), \
                mock.patch("shutil.which", return_value="/usr/bin/flatpak"):
            facts = mame.detect()
            self.assertEqual(facts["scope"], "system")
            self.assertEqual(facts["commit"], mame.COMMIT)
            checks = mame.check_host(facts)
            self.assertEqual(checks["runtime_commit"], mame.RUNTIME_COMMIT)
            self.assertFalse(checks["gameplay_checked"])

    def test_runtime_drift_is_explicit(self):
        def probe(operation, *args):
            if operation == "info" and "--show-commit" in args and args[-1] == mame.RUNTIME:
                return "b" * 64
            return self.probe(operation, *args)
        with mock.patch.object(mame, "probe", side_effect=probe), \
                mock.patch("shutil.which", return_value="/usr/bin/flatpak"):
            with self.assertRaisesRegex(DependencyError, "runtime commit"):
                mame.check_host(mame.detect())

    def test_wrong_remote_and_changed_commit_are_refused(self):
        for target in ("remotes", "info"):
            def probe(operation, *args):
                if operation == target:
                    if operation == "remotes":
                        return "flathub\thttps://invalid.example/repo"
                    if "--show-commit" in args:
                        return "b" * 64
                return self.probe(operation, *args)
            with self.subTest(target=target), \
                    mock.patch.object(mame, "probe", side_effect=probe), \
                    mock.patch("shutil.which", return_value="/usr/bin/flatpak"):
                with self.assertRaises(DependencyError):
                    mame.detect()

    def test_missing_flatpak_is_readonly(self):
        with mock.patch("shutil.which", return_value=None), mock.patch.object(mame, "probe") as probe:
            facts = mame.detect()
        self.assertFalse(facts["flatpak_available"])
        self.assertFalse(facts["installed"])
        probe.assert_not_called()

    def test_managed_plan_pins_both_app_and_runtime_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"HOME": tmp}), \
                mock.patch("shutil.which", return_value="/usr/bin/flatpak"), \
                mock.patch("shutil.disk_usage", return_value=mock.Mock(free=20 << 30)):
            plan = managed.plan("mame", "time-crisis-ii", mame.missing())
            commands = plan["dependency_commands"]
            self.assertIn("--commit=" + mame.COMMIT, commands[2])
            self.assertIn("--commit=" + mame.RUNTIME_COMMIT, commands[4])
            self.assertEqual(commands[4][-1], mame.RUNTIME)
            self.assertEqual(commands[5][-1], mame.APP)
            self.assertFalse(Path(tmp, ".local").exists())
            self.assertNotIn("MCL_EXEC_TOKEN", plan["environment"])

    def test_other_runtime_metadata_refused_before_install(self):
        with self.assertRaises(managed.ManagedError):
            managed.app_metadata(f"[Application]\nname={mame.APP}\ncommand=mame\n"
                                 "runtime=org.kde.Platform/x86_64/other\n", "mame")

    def test_retained_launch_is_confined_and_supervised(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"HOME": tmp}):
            media = Path(tmp, "game")
            media.mkdir()
            bound = {"runtime": "mame", "package_id": "time-crisis-ii",
                     "profile": str(Path(tmp, "state", "profile"))}
            with mock.patch.object(managed, "validate_binding"), \
                    mock.patch.object(managed.subprocess, "call", return_value=0) as launch:
                self.assertEqual(managed.launch(bound, str(media), ["timecrs2", "-nowindow"]), 0)
            argv = launch.call_args.args[0]
            self.assertIn("--die-with-parent", argv)
            self.assertIn("--nofilesystem=host:reset", argv)
            self.assertIn("--filesystem=" + str(media) + ":ro", argv)
            self.assertIn("HOME=" + bound["profile"] + "/home", argv)
            self.assertEqual(argv[-3:], ["mame", "timecrs2", "-nowindow"])

    def test_missing_engine_uses_mame_preparation_helper(self):
        fallback = {"existing": mame.missing()}
        steps = installs.Installs._dependency_steps("mame", fallback=fallback, package_id="time-crisis-ii")
        self.assertEqual(len(steps), 2)
        self.assertTrue(steps[0]["argv"][1].endswith("mame_flatpak.py"))
        self.assertTrue(steps[0]["approve_after"])
        self.assertFalse(steps[1]["approve_after"])

    def test_managed_rom_audit_does_not_create_game_profile(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"HOME": tmp}):
            media = Path(tmp, "game")
            media.mkdir()
            profile = Path(tmp, "absent-profile")
            bound = {"runtime": "mame", "package_id": "time-crisis-ii", "profile": str(profile)}
            with mock.patch.object(managed, "validate_binding"), \
                    mock.patch.object(managed.subprocess, "call", return_value=0):
                self.assertEqual(managed.launch(bound, str(media), ["timecrs2", "-verifyroms"],
                                                initialize=False), 0)
            self.assertFalse(profile.exists())

    def test_partial_slot_preserved_and_low_space_refused(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"HOME": tmp}):
            with mock.patch("shutil.which", return_value="/usr/bin/flatpak"), \
                    mock.patch("shutil.disk_usage", return_value=mock.Mock(free=1)):
                with self.assertRaisesRegex(managed.ManagedError, "GiB free"):
                    managed.plan("mame", "time-crisis-ii", {})
            directory = managed.slot("mame")
            directory.mkdir(parents=True)
            (directory / "journal.json").write_text("keep")
            with self.assertRaisesRegex(managed.ManagedError, "Incomplete isolated"):
                managed.ready("mame")
            self.assertEqual((directory / "journal.json").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
