"""Headless vkQuake resolver tests; never execute an AppImage or game."""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import vkquake
from jobs import Jobs, validate_event


class VkQuake(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".vkquake-test-", dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        header = bytearray(64)
        header[:7] = b"\x7fELF\x02\x01\x01"
        header[8:11] = b"AI\x02"
        header[18:20] = b"\x3e\x00"
        self.image = bytes(header) + b"fake AppImage: never executed"
        patches = [
            mock.patch("vkquake.Path.home", return_value=self.home),
            mock.patch("vkquake.platform.system", return_value="Linux"),
            mock.patch("vkquake.platform.machine", return_value="x86_64"),
            mock.patch("vkquake.ASSET_SIZE", len(self.image)),
            mock.patch("vkquake.ASSET_SHA256", hashlib.sha256(self.image).hexdigest()),
            mock.patch("subprocess.run", side_effect=AssertionError("No subprocess allowed")),
        ]
        for patch in patches:
            patch.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(patches)])
        self.context = {"job_id": "j12345678", "phase": "preflight",
                        "result_file": str(self.root / "result.json"),
                        "cancel_file": str(self.root / "cancel"), "approved_plan_digest": None}
        self.journal = self.root / "dependency-transactions.json"
        self.personal = self.home / "Applications/vkquake.AppImage"

    def execute(self):
        with contextlib.redirect_stdout(io.StringIO()) as output, \
                contextlib.redirect_stderr(io.StringIO()):
            code = vkquake.run(self.context)
        result = json.loads(Path(self.context["result_file"]).read_bytes())
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        for event in events:
            self.assertIsNone(validate_event(event, {"resolve"}))
        self.assertEqual(events[-1]["outcome"], result["outcome"])
        self.assertEqual({"succeeded": 0, "needs_action": 20, "conflicted": 30,
                          "failed": 40, "cancelled": 130}[result["outcome"]], code)
        self.assertNotIn("intents", result)
        return code, result

    def approve(self):
        self.assertEqual(self.execute()[0], 0)
        raw = Path(self.context["result_file"]).read_bytes()
        approved = self.root / "approved.json"
        approved.write_bytes(raw)
        self.context.update(phase="apply", approved_plan_file=str(approved),
                            approved_plan_digest="sha256:" + hashlib.sha256(raw).hexdigest())

    def seed(self, path=None, data=None):
        path = self.personal if path is None else path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.image if data is None else data)
        path.chmod(0o755)
        return path

    def uncertain(self):
        jobs = mock.Mock()
        jobs.paths.return_value = {"job_dir": self.root}
        return Jobs.dependency_uncertain(jobs, self.context["job_id"])

    def response(self, data=None, url=None, length=None):
        stream = io.BytesIO(self.image if data is None else data)
        stream.headers = {} if length is None else {"Content-Length": length}
        stream.geturl = lambda: vkquake.ASSET_URL if url is None else url
        opener = mock.Mock()
        opener.open.return_value = stream
        return opener

    def test_preflight_missing_is_read_only_and_exact(self):
        code, result = self.execute()
        self.assertEqual(code, 0)
        self.assertFalse(result["dependencies"]["vkquake"]["installed"])
        self.assertEqual(result["plan"], vkquake.make_plan(vkquake.detect()))
        self.assertEqual(result["plan"]["dependency_download"], {
            "url": vkquake.ASSET_URL, "size": len(self.image), "version": vkquake.VERSION,
            "sha256": hashlib.sha256(self.image).hexdigest(), "target": str(vkquake.target_path())})
        self.assertEqual(result["plan"]["actions"], [])
        self.assertEqual(result["plan"]["dependency_commands"], [])
        self.assertFalse(self.journal.exists())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_reuse_personal_or_managed_exact_executable(self):
        for path in (self.personal, vkquake.target_path()):
            with self.subTest(path=path):
                self.context["phase"] = "preflight"
                self.seed(path)
                facts = vkquake.detect()
                self.assertEqual(facts, {"provider": "appimage", "scope": "user",
                    "installed": True, "version": "1.36.0", "executable": str(path),
                    "sha256": hashlib.sha256(self.image).hexdigest(), "launch_argv": [str(path)],
                    "capabilities_checked": False, "location": str(path), "skipped": []})
                self.approve()
                with mock.patch("vkquake.download", side_effect=AssertionError("No upgrade")):
                    self.assertEqual(self.execute()[0], 0)
                self.assertIsNone(json.loads(Path(self.context["result_file"]).read_bytes())
                                  ["plan"]["dependency_download"])
                self.assertFalse(self.journal.exists())
                path.unlink()

    def assert_skipped_personal(self, facts, reason):
        self.assertEqual(facts["executable"], str(vkquake.target_path()))
        self.assertEqual([x["path"] for x in facts["skipped"]], [str(self.personal)])
        self.assertIn(reason, facts["skipped"][0]["reason"])

    def test_different_personal_build_left_untouched_and_managed_used(self):
        self.seed(vkquake.target_path())
        self.seed(data=b"wrong")
        facts = vkquake.detect()
        self.assertTrue(facts["installed"])
        self.assert_skipped_personal(facts, "left untouched")
        self.approve()
        with mock.patch("vkquake.download", side_effect=AssertionError("No replacement")):
            self.assertEqual(self.execute()[0], 0)
        self.assertEqual(self.personal.read_bytes(), b"wrong")
        self.assertTrue(vkquake._verified(vkquake.target_path()))
        self.assertFalse(self.journal.exists())

    def test_different_personal_build_plans_managed_download_only(self):
        self.seed(data=b"wrong")
        facts = vkquake.detect()
        self.assertFalse(facts["installed"])
        self.assert_skipped_personal(facts, "left untouched")
        self.assertEqual(vkquake.make_plan(facts)["dependency_download"]["target"], str(vkquake.target_path()))
        self.assertEqual(self.personal.read_bytes(), b"wrong")

    def test_invalid_managed_copy_still_blocks(self):
        vkquake.target_path().parent.mkdir(parents=True)
        vkquake.target_path().write_bytes(b"wrong managed")
        vkquake.target_path().chmod(0o755)
        with self.assertRaisesRegex(vkquake.DependencyError, "Unverified"):
            vkquake.detect()
        self.assertEqual(self.execute()[0], 40)
        self.seed(data=b"wrong")
        with self.assertRaisesRegex(vkquake.DependencyError, "Unverified"):
            vkquake.detect()
        self.seed()
        self.assertEqual(vkquake.detect()["executable"], str(self.personal))

    def test_exact_owned_group_writable_guide_mode_reused_only_for_own_group(self):
        path = self.seed()
        path.chmod(0o775)
        facts = vkquake.detect()
        self.assertTrue(facts["installed"])
        self.assertEqual(path.stat().st_mode & 0o7777, 0o775)
        self.approve()
        with mock.patch("vkquake.download", side_effect=AssertionError("No replacement")):
            self.assertEqual(self.execute()[0], 0)
        self.assertEqual(path.stat().st_mode & 0o7777, 0o775)
        with mock.patch("vkquake.os.getgid", return_value=path.stat().st_gid + 1):
            self.assert_skipped_personal(vkquake.detect(), "left untouched")
        path.write_bytes(b"wrong")
        path.chmod(0o775)
        self.assert_skipped_personal(vkquake.detect(), "left untouched")
        self.assertEqual(path.read_bytes(), b"wrong")

    def test_candidate_modes_types_and_symlinks_skipped_untouched(self):
        path = self.seed()
        for mode in (0o644, 0o777, 0o757, 0o4755, 0o2755):
            path.chmod(mode)
            with self.subTest(mode=mode):
                self.assert_skipped_personal(vkquake.detect(), "left untouched")
                self.assertEqual(path.stat().st_mode & 0o7777, mode)
        path.unlink()
        os.mkfifo(path)
        self.assert_skipped_personal(vkquake.detect(), "left untouched")
        path.unlink()
        path.mkdir()
        self.assert_skipped_personal(vkquake.detect(), "left untouched")
        path.rmdir()
        path.symlink_to(self.root / "missing")
        self.assert_skipped_personal(vkquake.detect(), "left untouched")
        self.assertTrue(path.is_symlink())
        path.unlink()
        path.parent.rmdir()
        (self.root / "real-applications").mkdir()
        path.parent.symlink_to(self.root / "real-applications", target_is_directory=True)
        self.assert_skipped_personal(vkquake.detect(), "left untouched")
        self.assertEqual(list((self.root / "real-applications").iterdir()), [])

    def test_missing_host_prerequisites_are_reported_without_running_appimage(self):
        self.seed(self.personal)
        facts = vkquake.detect()
        with mock.patch("vkquake.ctypes.util.find_library",
                        side_effect=lambda name: None if name == "fuse" else "libvulkan.so.1"), \
                mock.patch("vkquake.ctypes.CDLL", side_effect=lambda name: object()):
            self.assertEqual(vkquake.missing_host_prerequisites(facts), ["fuse"])
        with mock.patch("vkquake.ctypes.util.find_library", return_value=None):
            self.assertEqual(vkquake.missing_host_prerequisites(facts), ["fuse", "vulkan"])

    def test_approved_download_durable_publication_and_detection(self):
        self.approve()
        publish = vkquake._publish

        def observed(stage, target):
            self.assertTrue(self.uncertain())
            self.assertTrue(vkquake._verified(stage))
            self.assertEqual(json.loads(self.journal.read_text())["active_command"],
                             ["publish-vkquake", str(target)])
            publish(stage, target)

        with mock.patch("vkquake.urllib.request.build_opener", return_value=self.response()), \
                mock.patch("vkquake._publish", side_effect=observed):
            code, result = self.execute()
        self.assertEqual(code, 0)
        self.assertTrue(result["dependencies"]["vkquake"]["installed"])
        self.assertEqual(vkquake.target_path().read_bytes(), self.image)
        self.assertEqual(vkquake.target_path().stat().st_mode & 0o777, 0o755)
        self.assertFalse(self.uncertain())
        self.assertEqual(len(result["completed_transactions"]), 1)
        self.assertEqual(list(vkquake.target_root().glob(".vkquake.stage-*")), [])

    def test_approval_digest_envelope_and_facts_bound(self):
        self.approve()
        path = Path(self.context["approved_plan_file"])
        original = path.read_bytes()
        path.write_bytes(b"{}")
        self.assertEqual(self.execute()[0], 40)
        for field, value in (("job_id", "foreign"), ("phase", "apply"), ("outcome", "failed"),
                             ("plan", {})):
            envelope = json.loads(original)
            envelope[field] = value
            raw = json.dumps(envelope).encode()
            path.write_bytes(raw)
            self.context["approved_plan_digest"] = "sha256:" + hashlib.sha256(raw).hexdigest()
            self.assertEqual(self.execute()[0], 30)
        path.write_bytes(original)
        self.context["approved_plan_digest"] = "sha256:" + hashlib.sha256(original).hexdigest()
        self.seed()
        self.assertEqual(self.execute()[0], 30)
        self.assertFalse(vkquake.target_path().exists())
        self.assertFalse(self.journal.exists())

    def test_cancel_before_during_and_after_publication(self):
        cancel = Path(self.context["cancel_file"])
        cancel.touch()
        self.assertEqual(self.execute()[0], 130)
        cancel.unlink()
        self.approve()

        def cancelled_download(context):
            cancel.touch()
            return self.image

        with mock.patch("vkquake.download", side_effect=cancelled_download):
            self.assertEqual(self.execute()[0], 130)
        self.assertFalse(self.journal.exists())
        cancel.unlink()
        verified = vkquake._verified

        def cancelled_stage(path):
            result = verified(path)
            if ".stage-" in path.name:
                cancel.touch()
            return result

        with mock.patch("vkquake.download", return_value=self.image), \
                mock.patch("vkquake._verified", side_effect=cancelled_stage):
            self.assertEqual(self.execute()[0], 130)
        self.assertFalse(vkquake.target_path().exists())
        self.assertFalse(self.uncertain())
        cancel.unlink()
        publish = vkquake._publish

        def cancelled_published(stage, target):
            publish(stage, target)
            cancel.touch()

        with mock.patch("vkquake.download", return_value=self.image), \
                mock.patch("vkquake._publish", side_effect=cancelled_published):
            self.assertEqual(self.execute()[0], 130)
        self.assertTrue(vkquake.detect()["installed"])
        self.assertFalse(self.uncertain())
        self.assertEqual(list(vkquake.target_root().glob(".vkquake.stage-*")), [])

    def test_resolver_errors_and_refresh_before_publication(self):
        self.approve()
        for error in (OSError("network failed"), vkquake.DependencyError("resolver failed"),
                      ValueError("invalid response")):
            with mock.patch("vkquake.download", side_effect=error):
                self.assertEqual(self.execute()[0], 40)
        self.assertFalse(self.journal.exists())

        def changed(context):
            self.seed()
            return self.image

        with mock.patch("vkquake.download", side_effect=changed):
            self.assertEqual(self.execute()[0], 40)
        self.assertFalse(self.journal.exists())
        self.assertFalse(vkquake.target_path().exists())

    def test_atomic_no_replace(self):
        stage = self.seed(self.root / "stage")
        target = self.seed(self.root / "target", b"retain")
        with self.assertRaisesRegex(vkquake.DependencyError, "already exists"):
            vkquake._publish(stage, target)
        self.assertEqual(target.read_bytes(), b"retain")
        target.unlink()
        target.symlink_to(self.root / "absent")
        with self.assertRaises(vkquake.DependencyError):
            vkquake._publish(stage, target)
        self.assertFalse((self.root / "absent").exists())

    def test_interrupted_publication_or_detection_blocks_retry(self):
        self.approve()
        publish = vkquake._publish

        def interrupted(stage, target):
            publish(stage, target)
            raise OSError("interrupted after publication")

        with mock.patch("vkquake.download", return_value=self.image), \
                mock.patch("vkquake._publish", side_effect=interrupted):
            self.assertEqual(self.execute()[0], 40)
        self.assertTrue(vkquake.detect()["installed"])
        self.assertTrue(self.uncertain())
        self.assertEqual(self.execute()[0], 40)
        self.context["phase"] = "preflight"
        self.assertEqual(self.execute()[0], 40)

    def test_malformed_foreign_active_or_pending_journal(self):
        for record in ("invalid", "[]", "{}", json.dumps({"job_id": "foreign"}),
                       json.dumps({"job_id": self.context["job_id"], "completed": [],
                                   "active_command": ["publish-vkquake"]}),
                       json.dumps({"job_id": self.context["job_id"], "completed": [],
                                   "active_command": None, "detection_pending": True})):
            self.journal.write_text(record)
            self.assertTrue(self.uncertain())
            self.assertEqual(self.execute()[0], 40)

    def test_download_hash_size_redirect_timeout_and_cancel(self):
        for data in (b"short", self.image[:-1] + b"x", self.image + b"x"):
            with mock.patch("vkquake.urllib.request.build_opener", return_value=self.response(data)):
                with self.assertRaises(vkquake.DependencyError):
                    vkquake.download(self.context)
        for url in ("http://github.com/x", "https://evil.test/x", "https://github.com:444/x",
                    "https://name:password@github.com/x"):
            with self.assertRaises(vkquake.DependencyError):
                vkquake._check_url(url)
        with mock.patch("vkquake.urllib.request.build_opener",
                        return_value=self.response(url="https://evil.test/image")):
            with self.assertRaises(vkquake.DependencyError):
                vkquake.download(self.context)
        with mock.patch("vkquake.urllib.request.build_opener",
                        return_value=self.response(length="1")):
            with self.assertRaises(vkquake.DependencyError):
                vkquake.download(self.context)
        with mock.patch("vkquake.time.monotonic", side_effect=[0, 61]), \
                mock.patch("vkquake.urllib.request.build_opener", return_value=self.response()):
            with self.assertRaisesRegex(vkquake.DependencyError, "timed out"):
                vkquake.download(self.context)
        opener = self.response()
        read = opener.open.return_value.read

        def cancel_read(size):
            data = read(size)
            Path(self.context["cancel_file"]).touch()
            return data

        opener.open.return_value.read = cancel_read
        with mock.patch("vkquake.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(vkquake.Cancelled):
                vkquake.download(self.context)

    def test_mock_download_cannot_bypass_hash_check(self):
        self.approve()
        with mock.patch("vkquake.download", return_value=b"untrusted"):
            self.assertEqual(self.execute()[0], 40)
        self.assertFalse(self.journal.exists())

    def test_non_graphical_host_checks_honest_flags(self):
        self.seed()
        with mock.patch("vkquake.ctypes.util.find_library",
                        side_effect=lambda name: {"fuse": "libfuse.so.2", "vulkan": "libvulkan.so.1"}[name]), \
                mock.patch("vkquake.ctypes.CDLL") as loader:
            result = vkquake.check_host(vkquake.detect())
        self.assertEqual(loader.call_count, 2)
        for flag in ("gameplay_checked", "cli_checked", "capabilities_checked",
                     "fuse_mount_checked", "graphics_device_checked"):
            self.assertFalse(result[flag])
        self.assertTrue(result["bytes_verified"])
        self.assertTrue(result["host_prerequisites_checked"])

    def test_host_missing_loaders_changed_hash_header_and_architecture(self):
        path = self.seed()
        facts = vkquake.detect()
        with mock.patch("vkquake.ctypes.util.find_library", return_value=None):
            with self.assertRaisesRegex(vkquake.DependencyError, "Missing host"):
                vkquake.check_host(facts)
        with mock.patch("vkquake.ctypes.util.find_library", return_value="libfuse3.so.3"), \
                mock.patch("vkquake.ctypes.CDLL"):
            with self.assertRaisesRegex(vkquake.DependencyError, "FUSE2"):
                vkquake.check_host(facts)
        with mock.patch("vkquake.ctypes.util.find_library", return_value="libfuse.so.2"), \
                mock.patch("vkquake.ctypes.CDLL", side_effect=OSError("unavailable")):
            with self.assertRaises(vkquake.DependencyError):
                vkquake.check_host(facts)
        with mock.patch("vkquake.platform.machine", return_value="aarch64"):
            with self.assertRaises(vkquake.DependencyError):
                vkquake.check_host(facts)
            self.assertEqual(self.execute()[0], 20)
        path.write_bytes(b"wrong")
        with self.assertRaises(vkquake.DependencyError):
            vkquake.check_host(facts)
        bad = bytes(64)
        path.write_bytes(bad)
        with mock.patch("vkquake.ASSET_SIZE", len(bad)), \
                mock.patch("vkquake.ASSET_SHA256", hashlib.sha256(bad).hexdigest()):
            with self.assertRaisesRegex(vkquake.DependencyError, "ELF"):
                vkquake.check_host(vkquake.detect())

    def proc(self, pid, executable, comm=b"vkquake", argv=b"vkquake\0"):
        entry = self.root / "proc" / str(pid)
        entry.mkdir(parents=True)
        (entry / "exe").symlink_to(executable)
        (entry / "comm").write_bytes(comm)
        (entry / "cmdline").write_bytes(argv)
        return entry

    def test_running_direct_mounted_cmdline_and_idle(self):
        self.seed()
        proc = self.root / "proc"
        proc.mkdir()
        facts = vkquake.detect()
        with mock.patch("vkquake.PROC_ROOT", proc):
            self.assertFalse(vkquake.running(facts))
            entry = self.proc(100, self.personal)
            self.assertTrue(vkquake.running(facts))
            (entry / "exe").unlink()
            engine = self.seed(self.root / ".mount_vkQu123/usr/bin/vkquake")
            (entry / "exe").symlink_to(engine)
            self.assertTrue(vkquake.running(facts))
            (entry / "exe").unlink()
            unrelated = self.seed(self.root / "other")
            (entry / "exe").symlink_to(unrelated)
            (entry / "comm").write_bytes(b"generic-loader")
            (entry / "cmdline").write_bytes(b"loader\0/home/user/vkquake.AppImage\0")
            self.assertFalse(vkquake.running(facts))
            (entry / "cmdline").write_bytes(b"/tmp/.mount_vkQuabc/usr/bin/vkquake\0")
            self.assertTrue(vkquake.running(facts))
            (entry / "cmdline").write_bytes(b"system-service\0")
            self.assertFalse(vkquake.running(facts))
            (entry / "comm").write_bytes(b"vkquake.AppImag")
            self.assertTrue(vkquake.running(facts))
            (entry / "comm").write_bytes(b"bash")
            (entry / "cmdline").write_bytes(str(self.personal).encode() + b"\0-game\0x\0")
            self.assertTrue(vkquake.running(facts))

    def test_running_ignores_development_commands_mentioning_vkquake(self):
        self.seed()
        tool = self.seed(self.root / "usr/bin/python3")
        entry = self.proc(100, tool, comm=b"python3",
                          argv=b"python3\0-m\0unittest\0tests/test_vkquake.py\0vkquake.py\0")
        self.proc(101, tool, comm=b"copilot",
                  argv=b"copilot\0--prompt\0inspect ~/Applications/vkquake.AppImage\0")
        self.proc(102, tool, comm=b"bash", argv=b"bash\0-c\0grep vkquake vkquake.py\0")
        with mock.patch("vkquake.PROC_ROOT", entry.parent):
            self.assertFalse(vkquake.running(vkquake.detect()))
            with mock.patch("vkquake.os.readlink", side_effect=PermissionError("protected")):
                self.assertFalse(vkquake.running(vkquake.detect()))

    def test_protected_unrelated_and_suspect_unreadable_fail_closed(self):
        self.seed()
        unrelated = self.seed(self.root / "system-service")
        entry = self.proc(100, unrelated, comm=b"system-service", argv=b"system-service\0")
        with mock.patch("vkquake.PROC_ROOT", entry.parent), \
                mock.patch("vkquake.os.readlink", side_effect=PermissionError("protected")):
            self.assertFalse(vkquake.running(vkquake.detect()))
            (entry / "comm").write_bytes(b"vkquake")
            with self.assertRaisesRegex(vkquake.DependencyError, "suspect"):
                vkquake.running(vkquake.detect())
            (entry / "comm").write_bytes(b"system-service")
            (entry / "cmdline").write_bytes(b"/tmp/.mount_vkQuabc/usr/bin/vkquake\0")
            with self.assertRaisesRegex(vkquake.DependencyError, "suspect"):
                vkquake.running(vkquake.detect())
            (entry / "comm").unlink()
            (entry / "cmdline").unlink()
            with self.assertRaises(vkquake.DependencyError):
                vkquake.running(vkquake.detect())

    def test_unreadable_mounted_runtime_and_zombie(self):
        self.seed()
        engine = self.seed(self.root / ".mount_vkquake/usr/bin/vkquake")
        entry = self.proc(100, engine)
        (entry / "cmdline").unlink()
        with mock.patch("vkquake.PROC_ROOT", entry.parent):
            self.assertTrue(vkquake.running(vkquake.detect()))
            with mock.patch("vkquake.os.readlink", side_effect=PermissionError("protected")):
                with self.assertRaisesRegex(vkquake.DependencyError, "suspect"):
                    vkquake.running(vkquake.detect())
            (entry / "exe").unlink()
            (entry / "status").write_text("State:\tS (sleeping)\n")
            with self.assertRaises(vkquake.DependencyError):
                vkquake.running(vkquake.detect())
            (entry / "status").write_text("State:\tZ (zombie)\n")
            self.assertFalse(vkquake.running(vkquake.detect()))


@unittest.skipUnless(os.environ.get("MCL_TEST_VKQUAKE_DOWNLOAD") == "1",
                     "Official anonymous download requires explicit opt-in")
class OfficialDownload(unittest.TestCase):
    def test_pinned_official_asset_without_execution(self):
        with tempfile.TemporaryDirectory(prefix=".vkquake-official-", dir=Path.cwd()) as folder:
            context = {"cancel_file": str(Path(folder) / "cancel")}
            data = vkquake.download(context)
            self.assertEqual(len(data), 9001464)
            self.assertEqual(hashlib.sha256(data).hexdigest(),
                             "f1824b12744b6b343c6155cf5f775df225b9e6c9ee606c95c9363f63f124992a")
            path = Path(folder) / "vkquake.AppImage"
            path.write_bytes(data)
            path.chmod(0o755)
            self.assertTrue(vkquake._verified(path))


if __name__ == "__main__":
    unittest.main()
