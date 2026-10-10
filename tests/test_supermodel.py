"""Headless native preparation tests: isolated project-local homes, no execution."""
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import supermodel
from jobs import Jobs, validate_event


def archive_bytes(entries):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for name, content, mode, kind in entries:
            member = tarfile.TarInfo(name)
            member.mode, member.type = mode, kind
            member.size = len(content) if kind == tarfile.REGTYPE else 0
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                member.linkname = "../../outside"
            archive.addfile(member, io.BytesIO(content) if member.isfile() else None)
    return out.getvalue()


class Native(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".supermodel-test-", dir=Path.cwd())
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.content = {"supermodel": b"fake runtime, never executed",
                        "Config/Games.xml": b"<games/>", "Config/Music.xml": b"<music/>",
                        "Assets/p1crosshair.bmp": b"asset"}
        self.inventory = {"": (0, 0o755, None), "Config": (0, 0o755, None),
                          "Assets": (0, 0o755, None)}
        self.inventory.update({name: (len(data), 0o755 if name == "supermodel" else 0o644,
                                     hashlib.sha256(data).hexdigest())
                               for name, data in self.content.items()})
        self.entries = [(supermodel.ARCHIVE_ROOT + ("/" + name if name else ""),
                         self.content.get(name, b""), mode,
                         tarfile.REGTYPE if digest else tarfile.DIRTYPE)
                        for name, (_, mode, digest) in self.inventory.items()]
        self.archive = archive_bytes(self.entries)
        self.patches = [
            mock.patch("supermodel.Path.home", return_value=self.home),
            mock.patch("supermodel.platform.system", return_value="Linux"),
            mock.patch("supermodel.platform.machine", return_value="x86_64"),
            mock.patch("supermodel.ASSET_INVENTORY", self.inventory),
            mock.patch("supermodel.RUNTIME_FILES", tuple(self.content)),
            mock.patch("supermodel.ASSET_SIZE", len(self.archive)),
            mock.patch("supermodel.ASSET_SHA256", hashlib.sha256(self.archive).hexdigest()),
            mock.patch("subprocess.run", side_effect=AssertionError("No emulator or game execution")),
        ]
        for patch in self.patches:
            patch.start()
        self.addCleanup(lambda: [patch.stop() for patch in reversed(self.patches)])
        self.addCleanup(self.tmp.cleanup)
        self.context = {"job_id": "j12345678", "phase": "preflight",
                        "result_file": str(self.root / "result.json"),
                        "cancel_file": str(self.root / "cancel"), "approved_plan_digest": None}
        self.journal = self.root / "dependency-transactions.json"

    def execute(self):
        with contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()):
            code = supermodel.run(self.context)
        result = json.loads(Path(self.context["result_file"]).read_text())
        events = [json.loads(line) for line in stdout.getvalue().splitlines()]
        for event in events:
            self.assertIsNone(validate_event(event, {"resolve"}))
        self.assertEqual(events[-1]["outcome"], result["outcome"])
        self.assertNotIn("intents", result)
        return code, result

    def approve(self):
        self.assertEqual(self.execute()[0], 0)
        raw = Path(self.context["result_file"]).read_bytes()
        approved = self.root / "approved.json"
        approved.write_bytes(raw)
        self.context.update(phase="apply", approved_plan_file=str(approved),
                            approved_plan_digest="sha256:" + hashlib.sha256(raw).hexdigest())

    def seed(self, root):
        for name, data in self.content.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(self.inventory[name][1])

    def uncertain(self):
        fake_jobs = mock.Mock()
        fake_jobs.paths.return_value = {"job_dir": self.root}
        return Jobs.dependency_uncertain(fake_jobs, self.context["job_id"])

    def response(self, data=None):
        response = io.BytesIO(self.archive if data is None else data)
        response.headers = {}
        response.geturl = lambda: supermodel.ASSET_URL
        opener = mock.Mock()
        opener.open.return_value = response
        return opener

    def test_exact_preflight_no_mutations(self):
        code, result = self.execute()
        self.assertEqual(code, 0)
        plan = result["plan"]
        self.assertEqual(plan, supermodel.make_plan(supermodel.detect()))
        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["dependency_commands"], [])
        self.assertEqual(plan["dependency_download"], {
            "url": supermodel.ASSET_URL, "size": len(self.archive),
            "sha256": hashlib.sha256(self.archive).hexdigest(), "version": supermodel.VERSION,
            "target": str(supermodel.target_root())})
        self.assertFalse(self.journal.exists())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_reuse_immutable_runtime_does_not_read_user_data(self):
        existing = self.home / "Games/Supermodel"
        self.seed(existing)
        (existing / "Config/Supermodel.ini").symlink_to(self.root / "missing-personal-config")
        (existing / "NVRAM").symlink_to(self.root / "missing-personal-nvram")
        facts = supermodel.detect()
        self.assertTrue(facts["installed"])
        self.assertEqual(facts["root"], str(existing))
        self.assertEqual(facts["launch_argv"], [str(existing / "supermodel")])
        self.assertFalse(facts["capabilities_checked"])
        self.assertEqual(supermodel.make_plan(facts)["dependency_download"], None)
        self.approve()
        with mock.patch("supermodel.download", side_effect=AssertionError("No upgrade")):
            self.assertEqual(self.execute()[0], 0)
        self.assertFalse(self.journal.exists())
        self.assertEqual(supermodel.detect()["skipped"], [])
        self.assertEqual(supermodel.detect()["location"], str(existing))
        (existing / "Assets/p1crosshair.bmp").write_bytes(b"modified")
        facts = supermodel.detect()
        self.assertFalse(facts["installed"])
        self.assertEqual(facts["root"], str(supermodel.target_root()))
        self.assertEqual([x["path"] for x in facts["skipped"]], [str(existing)])
        self.assertIn("left untouched", facts["skipped"][0]["reason"])
        self.assertEqual((existing / "Assets/p1crosshair.bmp").read_bytes(), b"modified")
        self.assertTrue((existing / "Config/Supermodel.ini").is_symlink())

    def test_wrong_permissions_symlinks_or_unsupported_platform_not_reused(self):
        existing = self.home / "Games/Supermodel"
        self.seed(existing)
        (existing / "supermodel").chmod(0o777)
        self.assertFalse(supermodel.detect()["installed"])
        (existing / "supermodel").chmod(0o755)
        with mock.patch("supermodel.platform.machine", return_value="aarch64"):
            self.assertFalse(supermodel.detect()["installed"])
            self.assertEqual(self.execute()[0], 20)
        real = existing / "Config/Games.xml"
        other = self.root / "xml"
        real.rename(other)
        real.symlink_to(other)
        self.assertFalse(supermodel.detect()["installed"])

    def test_real_approved_flow_mocked_download_and_durable_publication(self):
        self.approve()
        publish = supermodel._publish

        def observed_publish(stage, target):
            self.assertTrue(self.uncertain())
            self.assertEqual(json.loads(self.journal.read_text())["active_command"],
                             ["publish-supermodel", str(target)])
            self.assertTrue(supermodel._verified(stage))
            publish(stage, target)

        with mock.patch("supermodel.urllib.request.build_opener", return_value=self.response()), \
                mock.patch("supermodel._publish", side_effect=observed_publish):
            code, result = self.execute()
        self.assertEqual(code, 0)
        self.assertTrue(result["dependencies"]["supermodel"]["installed"])
        self.assertFalse(self.uncertain())
        self.assertFalse((supermodel.target_root() / "Config/Supermodel.ini").exists())
        self.assertEqual(len(result["completed_transactions"]), 1)
        self.assertEqual(supermodel.validate_archive(self.archive), self.content)
        self.assertFalse(any(supermodel.target_root().parent.glob("*.stage-*")))

    def test_digest_and_all_envelope_fields_are_bound(self):
        self.approve()
        approved = Path(self.context["approved_plan_file"])
        original = approved.read_bytes()
        approved.write_bytes(b"{}")
        self.assertEqual(self.execute()[0], 40)
        for field, value in (("job_id", "another"), ("phase", "apply"), ("outcome", "failed"),
                             ("plan", {})):
            with self.subTest(field=field):
                envelope = json.loads(original)
                envelope[field] = value
                raw = json.dumps(envelope).encode()
                approved.write_bytes(raw)
                self.context["approved_plan_digest"] = "sha256:" + hashlib.sha256(raw).hexdigest()
                self.assertEqual(self.execute()[0], 30)
        self.assertFalse(supermodel.target_root().exists())
        self.assertFalse(self.journal.exists())

    def test_refresh_before_changes_and_no_replacement(self):
        self.approve()

        def concurrent_download(context):
            self.seed(self.home / "Games/Supermodel")
            return self.archive

        with mock.patch("supermodel.download", side_effect=concurrent_download):
            self.assertEqual(self.execute()[0], 40)
        self.assertFalse(self.journal.exists())
        self.assertFalse(supermodel.target_root().exists())
        target = supermodel.target_root()
        target.mkdir(parents=True)
        marker = target / "personal"
        marker.write_text("leave alone")
        stage = target.parent / "stage"
        stage.mkdir()
        with self.assertRaisesRegex(supermodel.DependencyError, "already exists"):
            supermodel._publish(stage, target)
        self.assertEqual(marker.read_text(), "leave alone")
        self.context["phase"] = "preflight"
        # The verified personal runtime still permits reuse, without touching target.
        self.assertEqual(self.execute()[0], 0)
        shutil_root = self.home / "Games/Supermodel/supermodel"
        shutil_root.write_text("unsupported")
        self.assertEqual(self.execute()[0], 20)

    def test_cancellation_before_work_during_download_and_before_publication(self):
        Path(self.context["cancel_file"]).touch()
        self.assertEqual(self.execute()[0], 130)
        self.assertEqual(list(self.home.iterdir()), [])
        Path(self.context["cancel_file"]).unlink()
        self.approve()

        def cancelled_download(context):
            Path(context["cancel_file"]).touch()
            return self.archive

        with mock.patch("supermodel.download", side_effect=cancelled_download):
            self.assertEqual(self.execute()[0], 130)
        self.assertFalse(self.journal.exists())
        Path(self.context["cancel_file"]).unlink()
        verified = supermodel._verified

        def cancelled_stage(root):
            result = verified(root)
            if ".stage-" in root.name:
                Path(self.context["cancel_file"]).touch()
            return result

        with mock.patch("supermodel.download", return_value=self.archive), \
                mock.patch("supermodel._verified", side_effect=cancelled_stage):
            self.assertEqual(self.execute()[0], 130)
        self.assertFalse(supermodel.target_root().exists())
        self.assertFalse(self.uncertain())

    def test_interrupted_publication_blocks_retry_even_if_installed(self):
        self.approve()
        publish = supermodel._publish

        def interrupted(stage, target):
            publish(stage, target)
            raise OSError("simulated interruption after directory publication")

        with mock.patch("supermodel.download", return_value=self.archive), \
                mock.patch("supermodel._publish", side_effect=interrupted):
            self.assertEqual(self.execute()[0], 40)
        self.assertTrue(supermodel.detect()["installed"])
        self.assertTrue(self.uncertain())
        with mock.patch("supermodel.download", side_effect=AssertionError("No retry")):
            self.assertEqual(self.execute()[0], 40)
        self.context["phase"] = "preflight"
        self.assertEqual(self.execute()[0], 40)

    def test_corrupt_foreign_and_detection_pending_journal_fail_closed(self):
        for record in ("invalid", "[]", json.dumps({"job_id": "other"}),
                       json.dumps({"job_id": self.context["job_id"], "completed": [],
                                   "active_command": None, "detection_pending": True})):
            self.journal.write_text(record)
            self.assertTrue(self.uncertain())
            self.assertEqual(self.execute()[0], 40)

    def test_bad_hash_and_bounded_cancelled_download(self):
        self.approve()
        with mock.patch("supermodel.urllib.request.build_opener", return_value=self.response(b"x")):
            self.assertEqual(self.execute()[0], 40)
        self.assertFalse(self.journal.exists())
        with mock.patch("supermodel.urllib.request.build_opener",
                        return_value=self.response(self.archive + b"x")):
            with self.assertRaisesRegex(supermodel.DependencyError, "exceeds"):
                supermodel.download(self.context)
        response = self.response()
        real_read = response.open.return_value.read

        def read(size):
            chunk = real_read(size)
            Path(self.context["cancel_file"]).touch()
            return chunk

        response.open.return_value.read = read
        with mock.patch("supermodel.urllib.request.build_opener", return_value=response):
            with self.assertRaises(supermodel.Cancelled):
                supermodel.download(self.context)
        Path(self.context["cancel_file"]).unlink()
        with mock.patch("supermodel.time.monotonic", side_effect=[0, 61]), \
                mock.patch("supermodel.urllib.request.build_opener", return_value=self.response()):
            with self.assertRaisesRegex(supermodel.DependencyError, "timed out"):
                supermodel.download(self.context)

    def test_unsafe_tar_rejected_without_extraction(self):
        bad_entries = [
            (supermodel.ARCHIVE_ROOT + "/../outside", b"x", 0o644, tarfile.REGTYPE),
            ("/absolute", b"x", 0o644, tarfile.REGTYPE),
            (supermodel.ARCHIVE_ROOT + "/supermodel", b"", 0o755, tarfile.SYMTYPE),
            (supermodel.ARCHIVE_ROOT + "/supermodel", b"", 0o755, tarfile.LNKTYPE),
            (supermodel.ARCHIVE_ROOT + "/supermodel", b"", 0o755, tarfile.FIFOTYPE),
            (supermodel.ARCHIVE_ROOT + "/supermodel", b"x" * 500, 0o755, tarfile.REGTYPE),
            (supermodel.ARCHIVE_ROOT + "/supermodel", self.content["supermodel"], 0o4755, tarfile.REGTYPE),
        ]
        variations = [self.entries + [entry] for entry in bad_entries]
        variations += [self.entries + [self.entries[-1]], self.entries[:-1]]
        # Replace, rather than duplicate, to exercise type/permission/size checks.
        variations += [[entry if item[0] == entry[0] else item for item in self.entries]
                       for entry in bad_entries[2:]]
        for entries in variations:
            data = archive_bytes(entries)
            with self.subTest(entry=entries[-1][0]), \
                    mock.patch("supermodel.ASSET_SIZE", len(data)), \
                    mock.patch("supermodel.ASSET_SHA256", hashlib.sha256(data).hexdigest()):
                with self.assertRaises(supermodel.DependencyError):
                    supermodel.validate_archive(data)
        self.assertFalse((self.root / "outside").exists())

    def test_https_redirect_allowlist(self):
        for url in (supermodel.ASSET_URL, "https://release-assets.githubusercontent.com/a?token=public"):
            supermodel._check_url(url)
        for url in ("http://github.com/a", "https://evil.example/a", "file:///etc/passwd",
                    "https://user@github.com/a", "https://github.com:444/a"):
            with self.assertRaises(supermodel.DependencyError):
                supermodel._check_url(url)
            with self.assertRaises(supermodel.DependencyError):
                supermodel._Redirects().redirect_request(None, None, 302, "", {}, url)

    def test_running_compares_inode_not_names_and_fails_closed(self):
        self.seed(self.home / "Games/Supermodel")
        facts = supermodel.detect()
        proc = self.root / "proc"
        proc.mkdir()
        entry = proc / "123"
        entry.mkdir()
        unrelated = self.root / "unrelated-supermodel"
        unrelated.write_text("unrelated")
        (entry / "exe").symlink_to(unrelated)
        with mock.patch("supermodel.PROC_ROOT", proc):
            self.assertFalse(supermodel.running(facts))
            (entry / "exe").unlink()
            (entry / "exe").symlink_to(facts["executable"])
            self.assertTrue(supermodel.running(facts))
            (entry / "exe").unlink()
            (entry / "status").write_text("State:\tS (sleeping)\nKthread:\t0\n")
            with self.assertRaisesRegex(supermodel.DependencyError, "Cannot inspect"):
                supermodel.running(facts)
            (entry / "status").write_text("State:\tZ (zombie)\n")
            self.assertFalse(supermodel.running(facts))
            (entry / "status").unlink()
            with mock.patch("supermodel.os.readlink", side_effect=PermissionError("denied")), \
                    contextlib.redirect_stdout(io.StringIO()) as out, \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                for comm, cmdline in ((b"systemd\n", b"/usr/lib/systemd/systemd\0--user\0"),
                                      (b"(sd-pam)\n", b"(sd-pam)\0")):
                    (entry / "comm").write_bytes(comm)
                    (entry / "cmdline").write_bytes(cmdline)
                    self.assertFalse(supermodel.running(facts))
                suspicious = [
                    (b"supermodel\n", b"/usr/lib/systemd/systemd\0--user\0"),
                    (b"systemd\n", b"/opt/SuperModel/supermodel\0--token=SECRET\0"),
                    (b"launcher\n", os.fsencode(facts["executable"]) + b"\0game.zip\0"),
                    (b"sh\n", b"sh\0-c\0exec ./supermodel --password=SECRET\0"),
                    (b"systemd\n", b""),
                    (b"", b"/usr/lib/systemd/systemd\0"),
                ]
                for comm, cmdline in suspicious:
                    with self.subTest(comm=comm):
                        (entry / "comm").write_bytes(comm)
                        (entry / "cmdline").write_bytes(cmdline)
                        with self.assertRaisesRegex(supermodel.DependencyError, "Cannot inspect process 123") as caught:
                            supermodel.running(facts)
                        self.assertNotIn("SECRET", str(caught.exception))
                (entry / "comm").unlink()
                (entry / "cmdline").write_bytes(b"/usr/lib/systemd/systemd\0--user\0")
                with self.assertRaises(supermodel.DependencyError):
                    supermodel.running(facts)
                (entry / "cmdline").unlink()
                with self.assertRaises(supermodel.DependencyError):
                    supermodel.running(facts)
            self.assertEqual(out.getvalue() + err.getvalue(), "")
            (entry / "status").write_text("State:\tS (sleeping)\nKthread:\t0\n")
            other = proc / "456"
            other.mkdir()
            (other / "exe").symlink_to(self.root / "inaccessible-root-process")
            (entry / "status").write_text("State:\tS (sleeping)\nKthread:\t0\n")
            real_stat = Path.stat

            def owner(path, *args, **kwargs):
                metadata = real_stat(path, *args, **kwargs)
                if path == other:
                    return os.stat_result((*metadata[:4], os.getuid() + 1, *metadata[5:]))
                return metadata

            with mock.patch("supermodel.Path.stat", owner):
                # Same-user inaccessible process 123 still fails closed.
                with self.assertRaisesRegex(supermodel.DependencyError, "Cannot inspect process 123"):
                    supermodel.running(facts)
                shutil.rmtree(entry)
                with mock.patch("supermodel.os.readlink", side_effect=PermissionError("root exe")):
                    self.assertFalse(supermodel.running(facts))
        with mock.patch("supermodel.PROC_ROOT", self.root / "missing"):
            with self.assertRaises(supermodel.DependencyError):
                supermodel.running(facts)


    def help_output(self, version=supermodel.HELP_VERSION, flags=supermodel.REQUIRED_FLAGS):
        return "\n".join([version, "Usage: Supermodel <romset> [options]", *flags]) + "\n"

    def test_host_check_uses_exact_executable_isolated_config_cwd_and_validates_output(self):
        self.seed(self.home / "Games/Supermodel")
        facts = supermodel.detect()

        def probe(argv, **kwargs):
            self.assertEqual(argv, [facts["executable"], "-help"])
            self.assertEqual(kwargs["timeout"], 15)
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertTrue((Path(kwargs["cwd"]) / "Config").is_dir())
            self.assertFalse(Path(kwargs["cwd"]).is_relative_to(self.home))
            self.assertEqual(kwargs["env"]["HOME"], str(Path(kwargs["cwd"]) / "home"))
            return mock.Mock(returncode=0, stdout=self.help_output(), stderr="")

        with mock.patch("supermodel.subprocess.run", side_effect=probe):
            self.assertEqual(supermodel.check_host(facts)["gameplay_checked"], False)
        failures = [
            (mock.Mock(returncode=127, stdout="", stderr="error while loading shared libraries: libSDL2"),
             "host libraries"),
            (mock.Mock(returncode=0, stdout=self.help_output("Supermodel (Version 0.3)"), stderr=""), "version"),
            (mock.Mock(returncode=0, stdout=self.help_output(flags=supermodel.REQUIRED_FLAGS[:-1]), stderr=""),
             "-print-inputs"),
            (mock.Mock(returncode=1, stdout=self.help_output(), stderr=""), "exit 1"),
            (subprocess.TimeoutExpired("supermodel", 15), "could not run"),
        ]
        for outcome, message in failures:
            with self.subTest(message=message), \
                    mock.patch("supermodel.subprocess.run", side_effect=[outcome]):
                with self.assertRaisesRegex(supermodel.DependencyError, message):
                    supermodel.check_host(facts)
        for changed in ({"installed": False}, {"executable": "/usr/bin/supermodel"},
                        {"launch_argv": ["supermodel"]}):
            with self.subTest(changed=changed), mock.patch("supermodel.subprocess.run") as run:
                with self.assertRaises(supermodel.DependencyError):
                    supermodel.check_host({**facts, **changed})
                run.assert_not_called()
        with mock.patch("supermodel._verified", return_value=False), \
                mock.patch("supermodel.subprocess.run") as run:
            with self.assertRaisesRegex(supermodel.DependencyError, "changed"):
                supermodel.check_host(facts)
            run.assert_not_called()

    def test_host_check_fake_executable_real_process_isolated(self):
        root = self.home / "Games/Supermodel"
        root.mkdir(parents=True)
        executable = root / "supermodel"
        evidence = self.root / "probe-cwd"
        help_text = self.root / "help.txt"
        help_text.write_text(self.help_output())
        executable.write_text("#!/bin/sh\n"
                              f"pwd > '{evidence}'\n"
                              "test -d Config || exit 9\n"
                              f"cat '{help_text}'\n")
        executable.chmod(0o755)
        facts = {"installed": True, "version": supermodel.VERSION, "root": str(root),
                 "executable": str(executable), "launch_argv": [str(executable)]}
        self.patches[-1].stop()
        try:
            with mock.patch("supermodel._verified", return_value=True):
                self.assertTrue(supermodel.check_host(facts)["cli_checked"])
        finally:
            self.patches[-1].start()
        probe_cwd = Path(evidence.read_text().strip())
        self.assertFalse(probe_cwd.exists())
        self.assertFalse((root / "Config").exists())


@unittest.skipUnless(os.environ.get("MCL_SUPERMODEL_DOWNLOAD_TEST") == "1",
                     "Opt-in public pinned download; isolated project-local home only")
class OfficialArchive(unittest.TestCase):
    def test_public_asset_actual_approved_flow_no_real_software_or_execution(self):
        with tempfile.TemporaryDirectory(prefix=".supermodel-live-test-", dir=Path.cwd()) as folder:
            root = Path(folder)
            home = root / "home"
            home.mkdir()
            context = {"job_id": "j12345678", "phase": "preflight",
                       "result_file": str(root / "result.json"), "cancel_file": str(root / "cancel"),
                       "approved_plan_digest": None}
            with mock.patch("supermodel.Path.home", return_value=home), \
                    mock.patch("subprocess.run", side_effect=AssertionError("No execution")), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(supermodel.run(context), 0)
                raw = Path(context["result_file"]).read_bytes()
                approved = root / "approved.json"
                approved.write_bytes(raw)
                context.update(phase="apply", approved_plan_file=str(approved),
                               approved_plan_digest="sha256:" + hashlib.sha256(raw).hexdigest())
                self.assertEqual(supermodel.run(context), 0)
                facts = supermodel.detect()
                self.assertTrue(facts["installed"])
                self.assertEqual(facts["sha256"],
                                 "4497b72c682d22f29b45d33607e07651240c2222a1e95e4b3f77846c9a7c1311")
                self.assertFalse(facts["capabilities_checked"])
                self.assertTrue(Path(facts["root"]).is_relative_to(home))
            with mock.patch("supermodel.Path.home", return_value=home):
                self.assertTrue(supermodel.check_host(facts)["cli_checked"])


if __name__ == "__main__":
    unittest.main()
