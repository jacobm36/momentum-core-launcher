"""Managed fallback approval, identity and non-destructive boundary tests."""
import copy
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest import mock

import engines
import managed_flatpak as managed


class ManagedFlatpakTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "home"
        self.home.mkdir()
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temporary.cleanup()

    def test_missing_slot_is_readonly_and_confined(self):
        self.assertIsNone(managed.ready("flycast"))
        self.assertFalse((self.home / ".local").exists())
        self.assertTrue(managed.slot("flycast").is_relative_to(self.home))

    def test_partial_slot_fails_visibly_and_is_retained(self):
        directory = managed.slot("flycast")
        directory.mkdir(parents=True)
        (directory / "journal.json").write_text("retain")
        with self.assertRaisesRegex(managed.ManagedError, "Incomplete isolated"):
            managed.ready("flycast")
        self.assertEqual((directory / "journal.json").read_text(), "retain")

    def test_descriptor_and_dependency_graph_drift_are_not_adopted(self):
        directory = managed.slot("uzdoom")
        directory.mkdir(parents=True)
        (directory / "slot.json").write_text(json.dumps({"old": True}))
        with mock.patch.object(managed, "inspect", return_value={"new": True}):
            with self.assertRaisesRegex(managed.ManagedError, "dependency graph changed"):
                managed.ready("uzdoom")

    def test_changed_profile_or_helper_invalidates_binding(self):
        expected = {"runtime": "flycast", "package_id": "game", "profile": "/profile-a"}
        changed = {**expected, "profile": "/profile-b"}
        with mock.patch.object(managed, "binding", return_value=expected):
            with self.assertRaisesRegex(managed.ManagedError, "binding changed"):
                managed.validate_binding(changed)
        self.assertNotEqual(engines.identity({"managed": expected}),
                            engines.identity({"managed": changed}))

    def test_review_environment_contains_no_parent_secrets_and_is_deterministic(self):
        with mock.patch("shutil.which", return_value="/usr/bin/flatpak"), \
                mock.patch("shutil.disk_usage", return_value=mock.Mock(free=20 << 30)):
            with mock.patch.dict(os.environ, {"MCL_EXEC_TOKEN": "first", "SECRET": "private"}):
                first = managed.plan("flycast", "game", {"commit": "old"})
            with mock.patch.dict(os.environ, {"MCL_EXEC_TOKEN": "second", "SECRET": "different"}):
                second = managed.plan("flycast", "game", {"commit": "old"})
        self.assertEqual(first, second)
        self.assertNotIn("SECRET", first["environment"])
        self.assertNotIn("MCL_EXEC_TOKEN", first["environment"])
        self.assertEqual(first["operation"], "prepare-dependency")
        self.assertEqual(first["space_required_bytes"], 6 << 30)
        self.assertFalse(managed.slot("flycast").exists())

    def test_low_disk_space_blocks_before_any_mutation(self):
        with mock.patch("shutil.which", return_value="/usr/bin/flatpak"), \
                mock.patch("shutil.disk_usage", return_value=mock.Mock(free=1)):
            with self.assertRaisesRegex(managed.ManagedError, "GiB free"):
                managed.plan("uzdoom", "game", {})
        self.assertFalse((self.home / ".local").exists())

    def test_foreign_symlink_and_permission_separators_rejected(self):
        (self.home / "link").symlink_to(self.home, target_is_directory=True)
        for path in (str(self.home / "link/slot"), str(self.home / "a:b"), "/tmp/../root"):
            with self.subTest(path=path), self.assertRaises(managed.ManagedError):
                managed.safe(path)

    def test_launch_sets_state_inside_sandbox_without_changing_parent(self):
        bound = {"runtime": "flycast", "package_id": "game",
                 "profile": str(managed.root() / "state/game/engine-profile-v1")}
        media = self.home / "media"
        media.mkdir()
        with mock.patch.object(managed, "validate_binding", return_value=bound), \
                mock.patch("subprocess.call", return_value=0) as launch:
            self.assertEqual(managed.launch(bound, str(media), ["-config", "window:fullscreen=yes"]), 0)
        argv = launch.call_args.args[0]
        self.assertIn("--nofilesystem=host:reset", argv)
        self.assertIn("--die-with-parent", argv)
        self.assertIn("--filesystem=" + str(media) + ":ro", argv)
        self.assertIn("HOME=" + bound["profile"] + "/home", argv)
        self.assertEqual(os.environ["HOME"], str(self.home))
        self.assertTrue((Path(bound["profile"]) / "data/flycast").is_dir())

    def test_cancel_before_provisioning_keeps_slot_absent(self):
        job = Path(self.temporary.name) / "job"
        job.mkdir()
        cancel = job / "cancel"
        cancel.touch()
        context = {"runtime": "flycast", "job_id": "j12345678", "cancel_file": str(cancel),
                   "result_file": str(job / "result.json")}
        with self.assertRaises(InterruptedError):
            managed.provision(context, {}, [])
        self.assertFalse(managed.slot("flycast").exists())

    def test_transaction_failure_retains_journal_without_descriptor(self):
        job = Path(self.temporary.name) / "job"
        job.mkdir()
        context = {"runtime": "uzdoom", "job_id": "j12345678", "cancel_file": str(job / "cancel"),
                   "result_file": str(job / "result.json")}
        approved = {"dependency_commands": [["flatpak", "remote-add", "--user"]]}
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)), \
                mock.patch.object(managed, "emit"):
            with self.assertRaisesRegex(managed.ManagedError, "Partial work retained"):
                managed.provision(context, approved, [])
        journal = json.loads((job / "dependency-transactions.json").read_text())
        self.assertEqual(journal["completed"][0]["exit_code"], 1)
        self.assertIsNone(journal["active_command"])
        self.assertFalse((managed.slot("uzdoom") / "slot.json").exists())
        self.assertTrue((managed.slot("uzdoom") / "journal.json").exists())

    def test_failed_post_transaction_inspection_keeps_uncertainty(self):
        job = Path(self.temporary.name) / "job"
        job.mkdir()
        context = {"runtime": "uzdoom", "job_id": "j12345678", "cancel_file": str(job / "cancel"),
                   "result_file": str(job / "result.json")}
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)), \
                mock.patch.object(managed, "probe", side_effect=managed.ManagedError("inspection failed")), \
                mock.patch.object(managed, "emit"):
            with self.assertRaisesRegex(managed.ManagedError, "inspection failed"):
                managed.provision(context, {"dependency_commands": [["flatpak", "remote-add", "--user"]]}, [])
        journal = json.loads((job / "dependency-transactions.json").read_text())
        self.assertTrue(journal["detection_pending"])
        self.assertFalse((managed.slot("uzdoom") / "slot.json").exists())

    def test_competing_preparation_lock_is_rejected(self):
        with managed.locked("flycast"):
            with self.assertRaisesRegex(managed.ManagedError, "Another process"):
                with managed.locked("flycast"):
                    self.fail("Second preparation lock must not be acquired.")

    def test_acceptance_startup_uses_separate_home_without_copying_user_state(self):
        directory = Path(self.temporary.name) / "candidate"
        directory.mkdir()
        (directory / "start-isolated-test.sh").write_bytes(
            (Path(__file__).parents[1] / "start-isolated-test.sh").read_bytes())
        (directory / "start-candidate.sh").write_text(
            'python3 -c \'import os,json; print(json.dumps({k:os.environ[k] for k in '
            '("HOME","XDG_DATA_HOME","MCL_TEST_ISOLATED_ENGINES")}))\'\n')
        (self.home / "personal-settings").write_text("do not copy")
        result = subprocess.run(["bash", str(directory / "start-isolated-test.sh")],
                                env=os.environ.copy(), capture_output=True, text=True, check=True)
        observed = json.loads(result.stdout.splitlines()[-1])
        expected = self.home / ".local/share/momentum-core/isolated-acceptance-home-v1"
        self.assertEqual(observed["HOME"], str(expected))
        self.assertEqual(observed["XDG_DATA_HOME"], str(expected / ".local/share"))
        self.assertEqual(observed["MCL_TEST_ISOLATED_ENGINES"], "1")
        self.assertFalse((expected / "personal-settings").exists())
        self.assertEqual((self.home / "personal-settings").read_text(), "do not copy")
