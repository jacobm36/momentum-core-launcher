"""Bounded prototype guards; no real Flatpak or normal profiles are touched."""
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest import mock


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                           "tools/managed-flatpak-prototype.py"))


class ManagedFlatpakPrototype(unittest.TestCase):
    def test_environment_is_explicit_and_does_not_mutate_parent(self):
        with mock.patch.dict("os.environ", {"HOME": "/personal", "FLATPAK_USER_DIR": "/borrowed"}):
            env = MODULE["environment"](Path("/experiment/slot"))
            self.assertEqual(env["FLATPAK_USER_DIR"], "/experiment/slot/flatpak")
            self.assertEqual(env["HOME"], "/experiment/slot/bootstrap/home")
            self.assertEqual(os.environ["HOME"], "/personal")

    def test_rejects_symlink_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "link").symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "Symlink"):
                MODULE["safe_directory"](root / "link/child")

    def test_partial_slot_is_not_adopted_or_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            slot = MODULE["slot_path"](Path(tmp), "flycast")
            slot.mkdir(parents=True)
            (slot / "foreign").write_text("preserve")
            with self.assertRaisesRegex(ValueError, "Incomplete/unknown"):
                MODULE["prepare"](Path(tmp), "flycast")
            self.assertEqual((slot / "foreign").read_text(), "preserve")
            self.assertFalse((slot / "slot.json").exists())

    def test_launch_maps_state_inside_sandbox_and_resets_manifest_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slot = MODULE["slot_path"](root, "flycast")
            slot.mkdir(parents=True)
            (slot / "slot.json").write_text(json.dumps({"verified": True}))
            media = root / "media"
            media.mkdir()
            with mock.patch.dict(MODULE["launch"].__globals__, {
                    "inspect": lambda *_: {"verified": True}}):
                argv, env = MODULE["launch"](root, "flycast", "game-a", media, ["game.cue"])
                other, _ = MODULE["launch"](root, "flycast", "game-b", media, ["game.cue"])
            self.assertIn("--nofilesystem=host:reset", argv)
            self.assertIn("--filesystem=" + str(media) + ":ro", argv)
            self.assertIn("HOME=" + str(root / "profiles/game-a/home"), argv)
            self.assertNotEqual(argv, other)
            self.assertEqual(env["FLATPAK_USER_DIR"], str(slot / "flatpak"))
            self.assertTrue((root / "profiles/game-a/data/flycast").is_dir())

    def test_rejects_wrong_command_in_build_metadata(self):
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            MODULE["metadata"]("[Application]\nname=org.flycast.Flycast\n"
                               "command=other\nruntime=org.freedesktop.Platform/x86_64/25.08\n",
                               MODULE["BUILDS"]["flycast"])

    def test_failed_transaction_retains_journal_without_success_descriptor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slot = MODULE["slot_path"](root, "uzdoom")

            def fail(*_):
                self.assertEqual(json.loads((slot / "journal.json").read_text())["state"],
                                 "preparing")
                raise RuntimeError("download failed")

            with mock.patch.dict(MODULE["prepare"].__globals__, {"command": fail}):
                with self.assertRaisesRegex(RuntimeError, "download failed"):
                    MODULE["prepare"](root, "uzdoom")
            self.assertTrue((slot / "journal.json").exists())
            self.assertFalse((slot / "slot.json").exists())
            with self.assertRaisesRegex(ValueError, "Incomplete/unknown"):
                MODULE["prepare"](root, "uzdoom")

    def test_complete_slot_is_reverified_not_reinstalled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slot = MODULE["slot_path"](root, "uzdoom")
            slot.mkdir(parents=True)
            (slot / "slot.json").write_text(json.dumps({"verified": True}))
            with mock.patch.dict(MODULE["prepare"].__globals__, {
                    "inspect": lambda *_: {"verified": True},
                    "command": mock.Mock(side_effect=AssertionError("Must not install"))}):
                self.assertEqual(MODULE["prepare"](root, "uzdoom"), {"verified": True})

    def test_changed_descriptor_refuses_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slot = MODULE["slot_path"](root, "flycast")
            slot.mkdir(parents=True)
            (slot / "slot.json").write_text(json.dumps({"verified": True}))
            with mock.patch.dict(MODULE["launch"].__globals__, {
                    "inspect": lambda *_: {"verified": False}}):
                with self.assertRaisesRegex(ValueError, "descriptor changed"):
                    MODULE["launch"](root, "flycast", "game-a", root, [])
            self.assertFalse((root / "profiles").exists())

    def test_invalid_profile_is_rejected_before_inspection(self):
        with self.assertRaisesRegex(ValueError, "Profile identity"):
            MODULE["launch"](Path("/not-used"), "flycast", "../personal", Path("/media"), [])

    def test_installed_system_runtime_cannot_satisfy_managed_slot(self):
        build = MODULE["BUILDS"]["uzdoom"]
        responses = {
            "--show-commit": build["commit"],
            "--show-ref": "app/org.zdoom.UZDoom/x86_64/stable",
            "--show-origin": "flathub",
            "--show-metadata": "[Application]\nname=org.zdoom.UZDoom\ncommand=uzdoom\n"
                               "runtime=org.freedesktop.Platform/x86_64/25.08\n",
            "--show-runtime": "org.freedesktop.Platform/x86_64/25.08",
        }

        def probe(_, operation, *args):
            self.assertIn("--user", args)
            if operation == "list":
                return "org.zdoom.UZDoom/x86_64/stable\tabcdef\tflathub"
            return next(responses[arg] for arg in args if arg in responses)

        with mock.patch.dict(MODULE["inspect"].__globals__, {"command": probe}):
            with self.assertRaisesRegex(ValueError, "runtime is absent"):
                MODULE["inspect"](Path("/experiment/slot"), "uzdoom")
