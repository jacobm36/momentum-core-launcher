"""Headless native EDuke32 resolver tests; engines and real game data never run."""
import contextlib
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import eduke32
from jobs import Jobs, validate_event


class EDuke32(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".eduke32-test-", dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.jobdir = self.root / "job"
        self.jobdir.mkdir(mode=0o700)
        header = bytearray(64)
        header[:7] = b"\x7fELF\x02\x01\x01"
        header[16:20] = b"\x03\x00\x3e\x00"
        self.engine = bytes(header) + b"synthetic engine, NEVER execute"
        self.archive = self.tar()
        patches = [
            mock.patch("eduke32.Path.home", return_value=self.home),
            mock.patch("eduke32.platform.system", return_value="Linux"),
            mock.patch("eduke32.platform.machine", return_value="x86_64"),
            mock.patch("eduke32.ASSET_SIZE", len(self.archive)),
            mock.patch("eduke32.ASSET_SHA256", hashlib.sha256(self.archive).hexdigest()),
            mock.patch("eduke32.ENGINE_SIZE", len(self.engine)),
            mock.patch("eduke32.ENGINE_SHA256", hashlib.sha256(self.engine).hexdigest()),
            mock.patch("eduke32.subprocess.run", side_effect=AssertionError("No unmocked subprocess")),
            mock.patch("eduke32.running", return_value=False),
        ]
        for patch in patches:
            patch.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(patches)])
        self.context = {"job_id": "j12345678", "phase": "preflight",
                        "result_file": str(self.jobdir / "result.json"),
                        "cancel_file": str(self.jobdir / "cancel"), "approved_plan_digest": None,
                        "intent_file": str(self.jobdir / "intents.jsonl")}
        Path(self.context["intent_file"]).write_bytes(b"")
        self.journal = self.jobdir / "dependency-transactions.json"
        self.guide, self.source, self.managed = eduke32._candidates()

    def tar(self, entries=None):
        if entries is None:
            entries = [(eduke32.ARCHIVE_ROOT, tarfile.DIRTYPE, b""),
                       (eduke32.ARCHIVE_ROOT + "/Makefile", tarfile.REGTYPE, b"mock build only")]
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name, kind, data in entries:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.mode = 0o755 if kind == tarfile.DIRTYPE else 0o644
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    info.linkname = "outside"
                info.size = len(data) if kind == tarfile.REGTYPE else 0
                archive.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
        return stream.getvalue()

    def seed(self, path=None, data=None, mode=0o755):
        path = self.guide if path is None else path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.engine if data is None else data)
        path.chmod(mode)
        return path

    def execute(self):
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
            code = eduke32.run(self.context)
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        for event in events:
            self.assertIsNone(validate_event(event, {"resolve"}))
        result = json.loads(Path(self.context["result_file"]).read_bytes())
        self.assertEqual(events[-1]["outcome"], result["outcome"])
        self.assertEqual({"succeeded": 0, "needs_action": 20, "conflicted": 30,
                          "failed": 40, "cancelled": 130}[result["outcome"]], code)
        self.assertEqual(Path(self.context["intent_file"]).read_bytes(), b"")
        self.assertNotIn("intents", result)
        return code, result

    def approve(self):
        self.assertEqual(self.execute()[0], 0)
        raw = Path(self.context["result_file"]).read_bytes()
        approved = self.jobdir / "approved.json"
        approved.write_bytes(raw)
        self.context.update(phase="apply", approved_plan_file=str(approved),
                            approved_plan_digest="sha256:" + hashlib.sha256(raw).hexdigest())

    def build(self, source):
        record = json.loads(self.journal.read_bytes())
        self.assertEqual(record["active_command"], ["make", "-j2", "eduke32"])
        self.assertEqual(record["build_directory"], str(source))
        self.seed(source / "eduke32")

    def uncertain(self):
        jobs = mock.Mock()
        jobs.paths.return_value = {"job_dir": self.jobdir}
        return Jobs.dependency_uncertain(jobs, self.context["job_id"])

    def prepare(self, build=None, download=None):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch("eduke32.check_build_prerequisites"))
        stack.enter_context(mock.patch("eduke32.download", return_value=self.archive) if download is None
                            else mock.patch("eduke32.download", side_effect=download))
        stack.enter_context(mock.patch("eduke32._build", side_effect=self.build if build is None else build))
        return stack

    def response(self, data=None, url=None, length=None):
        stream = io.BytesIO(self.archive if data is None else data)
        stream.headers = {} if length is None else {"Content-Length": length}
        stream.geturl = lambda: eduke32.ASSET_URL if url is None else url
        opener = mock.Mock()
        opener.open.return_value = stream
        return opener

    def test_missing_preflight_is_read_only_and_exact(self):
        code, result = self.execute()
        self.assertEqual(code, 0)
        facts = result["dependencies"]["eduke32"]
        self.assertFalse(facts["installed"])
        self.assertEqual(facts["executable"], str(self.managed))
        self.assertFalse(self.journal.exists())
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(result["plan"], eduke32.make_plan(facts))
        self.assertEqual(eduke32.commands_for(facts), [["make", "-j2", "eduke32"]])
        self.assertEqual(result["plan"]["dependency_download"], {
            "url": eduke32.ASSET_URL, "sha256": eduke32.ASSET_SHA256,
            "size": len(self.archive), "source_commit": eduke32.SOURCE_COMMIT,
            "target": str(self.managed)})

    def test_selection_order_and_unknown_builds_are_installed_not_capable(self):
        self.seed(self.managed)
        self.assertEqual(eduke32.detect()["executable"], str(self.managed))
        self.seed(self.source, mode=0o775)
        self.assertEqual(eduke32.detect()["executable"], str(self.source))
        self.seed(data=self.engine + b"unknown")
        facts = eduke32.detect()
        self.assertEqual(facts["executable"], str(self.guide))
        self.assertTrue(facts["installed"])
        self.assertFalse(facts["recognized_build"])
        self.assertFalse(facts["capabilities_checked"])
        self.approve()
        with mock.patch("eduke32.download", side_effect=AssertionError("No download")), \
                mock.patch("eduke32._build", side_effect=AssertionError("No rebuild")):
            self.assertEqual(self.execute()[0], 0)
        self.assertEqual(self.guide.read_bytes(), self.engine + b"unknown")
        self.assertEqual(stat.S_IMODE(self.source.stat().st_mode), 0o775)
        self.assertFalse(self.journal.exists())
        self.assertEqual(eduke32.commands_for(facts), [])

    def test_candidate_safety_no_fallback_or_mode_changes(self):
        self.seed(self.managed)
        path = self.seed()
        for mode in (0o644, 0o777, 0o757, 0o4755, 0o2755):
            path.chmod(mode)
            with self.subTest(mode=mode), self.assertRaises(eduke32.DependencyError):
                eduke32.detect()
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)
        path.chmod(0o775)
        self.assertTrue(eduke32.detect()["installed"])
        with mock.patch("eduke32.os.getgid", return_value=path.stat().st_gid + 1):
            with self.assertRaises(eduke32.DependencyError):
                eduke32.detect()
        path.unlink()
        os.mkfifo(path)
        with self.assertRaises(eduke32.DependencyError):
            eduke32.detect()
        path.unlink()
        path.mkdir()
        with self.assertRaises(eduke32.DependencyError):
            eduke32.detect()
        path.rmdir()
        path.symlink_to(self.managed)
        with self.assertRaises(eduke32.DependencyError):
            eduke32.detect()
        path.unlink()
        self.seed(data=b"not ELF")
        with self.assertRaises(eduke32.DependencyError):
            eduke32.detect()

    def test_symlink_ancestor_and_wrong_architecture_rejected(self):
        self.guide.parent.parent.mkdir(parents=True)
        self.guide.parent.symlink_to(self.root)
        with self.assertRaises(eduke32.DependencyError):
            eduke32.detect()
        self.guide.parent.unlink()
        data = bytearray(self.engine)
        data[18:20] = b"\xb7\x00"
        self.seed(data=bytes(data))
        with self.assertRaisesRegex(eduke32.DependencyError, "x86_64"):
            eduke32.detect()

    def test_approved_build_publication_and_durable_redetection(self):
        self.approve()
        publish = eduke32._publish

        def publishing(stage, target):
            record = json.loads(self.journal.read_bytes())
            self.assertEqual(record["active_command"], ["publish-eduke32", str(target)])
            self.assertTrue(record["detection_pending"])
            self.assertTrue(self.uncertain())
            publish(stage, target)

        with self.prepare(), mock.patch("eduke32._publish", side_effect=publishing):
            code, result = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(self.managed.read_bytes(), self.engine)
        self.assertEqual(stat.S_IMODE(self.managed.stat().st_mode), 0o755)
        self.assertTrue(result["dependencies"]["eduke32"]["recognized_build"])
        self.assertFalse(result["dependencies"]["eduke32"]["capabilities_checked"])
        self.assertFalse(self.uncertain())
        record = json.loads(self.journal.read_bytes())
        self.assertIsNone(record["active_command"])
        self.assertFalse(record["detection_pending"])
        self.assertEqual(record["after"], eduke32.detect())
        self.assertEqual(len(record["completed"]), 1)
        self.assertTrue((self.jobdir / "eduke32-build").exists())
        self.assertEqual(list(self.managed.parent.glob(".eduke32.stage-*")), [])

    def test_unknown_build_is_published_but_never_claims_evidence(self):
        self.approve()
        with self.prepare(build=lambda source: self.seed(source / "eduke32", self.engine + b"new build")):
            code, result = self.execute()
        self.assertEqual(code, 0)
        facts = result["dependencies"]["eduke32"]
        self.assertTrue(facts["installed"])
        self.assertFalse(facts["recognized_build"])
        self.assertFalse(facts["capabilities_checked"])

    def test_approval_digest_and_facts_tamper_block_all_work(self):
        self.approve()
        self.context["approved_plan_digest"] = "sha256:" + "0" * 64
        with self.prepare():
            self.assertEqual(self.execute()[0], 40)
        self.assertFalse(self.journal.exists())
        self.context["phase"] = "preflight"
        self.approve()
        self.seed(self.source)
        with self.prepare():
            self.assertEqual(self.execute()[0], 30)
        self.assertFalse(self.journal.exists())

    def test_download_validation_bounds_redirects_and_cancellation(self):
        for data, url, length in ((b"bad", None, None), (self.archive + b"x", None, None),
                                  (None, "https://evil.invalid/archive", None),
                                  (None, None, "999999"), (None, "http://voidpoint.io/file", None)):
            with self.subTest(data=data and len(data), url=url, length=length), \
                    mock.patch("eduke32.urllib.request.build_opener",
                               return_value=self.response(data, url, length)):
                with self.assertRaises(eduke32.DependencyError):
                    eduke32.download(self.context)
        with mock.patch("eduke32.urllib.request.build_opener", return_value=self.response()):
            self.assertEqual(eduke32.download(self.context), self.archive)
        Path(self.context["cancel_file"]).touch()
        with self.assertRaises(eduke32.Cancelled):
            eduke32.download(self.context)

    def test_download_tamper_blocks_build_and_retry(self):
        self.approve()
        with self.prepare(download=lambda context: b"tampered"):
            self.assertEqual(self.execute()[0], 40)
        self.assertFalse(self.managed.exists())
        self.assertTrue(self.uncertain())
        with self.prepare():
            self.assertEqual(self.execute()[0], 40)
        self.assertTrue(json.loads(self.journal.read_bytes())["failed"])

    def test_archive_traversal_links_specials_duplicates_and_bounds(self):
        root = eduke32.ARCHIVE_ROOT
        cases = [
            [(root + "/../escape", tarfile.REGTYPE, b"bad")],
            [("/absolute", tarfile.REGTYPE, b"bad")],
            [(root + "/link", tarfile.SYMTYPE, b"")],
            [(root + "/hard", tarfile.LNKTYPE, b"")],
            [(root + "/fifo", tarfile.FIFOTYPE, b"")],
            [(root + "/dev", tarfile.CHRTYPE, b"")],
            [(root + "/same", tarfile.REGTYPE, b"a"), (root + "/same", tarfile.REGTYPE, b"b")],
            [(root + "/file", tarfile.REGTYPE, b"a"), (root + "/file/child", tarfile.REGTYPE, b"b")],
            [("wrong-root/file", tarfile.REGTYPE, b"bad")],
        ]
        for entries in cases:
            data = self.tar(entries)
            build = self.jobdir / "unsafe-build"
            with self.subTest(entries=entries), mock.patch("eduke32.ASSET_SIZE", len(data)), \
                    mock.patch("eduke32.ASSET_SHA256", hashlib.sha256(data).hexdigest()):
                with self.assertRaises(eduke32.DependencyError):
                    eduke32.extract_source(data, build, self.context)
            self.assertFalse(build.exists())
        with mock.patch("eduke32.MAX_SOURCE_SIZE", 1):
            with self.assertRaises(eduke32.DependencyError):
                eduke32.extract_source(self.archive, self.jobdir / "unsafe-build", self.context)

    def test_build_failure_interruption_and_existing_build_block_retry(self):
        self.approve()
        with self.prepare(build=lambda source: (_ for _ in ()).throw(eduke32.DependencyError("make failed"))):
            self.assertEqual(self.execute()[0], 40)
        self.assertTrue(self.uncertain())
        self.assertEqual(json.loads(self.journal.read_bytes())["active_command"], eduke32.BUILD_ARGV)
        with self.prepare():
            self.assertEqual(self.execute()[0], 40)
        self.assertFalse(self.managed.exists())

    def test_cancellation_waits_for_active_make_then_blocks_publication_retry(self):
        self.approve()
        finished = []

        def build(source):
            self.build(source)
            Path(self.context["cancel_file"]).touch()
            finished.append(True)

        with self.prepare(build=build):
            self.assertEqual(self.execute()[0], 130)
        self.assertEqual(finished, [True])
        self.assertFalse(self.managed.exists())
        self.assertTrue(self.uncertain())
        Path(self.context["cancel_file"]).unlink()
        with self.prepare():
            self.assertEqual(self.execute()[0], 40)

    def test_cancellation_before_work_and_after_publication(self):
        Path(self.context["cancel_file"]).touch()
        self.assertEqual(self.execute()[0], 130)
        self.assertFalse(self.journal.exists())
        Path(self.context["cancel_file"]).unlink()
        self.approve()
        publish = eduke32._publish

        def publication(stage, target):
            publish(stage, target)
            Path(self.context["cancel_file"]).touch()

        with self.prepare(), mock.patch("eduke32._publish", side_effect=publication):
            code, result = self.execute()
        self.assertEqual(code, 130)
        self.assertTrue(result["dependencies"]["eduke32"]["installed"])
        self.assertEqual(self.managed.read_bytes(), self.engine)
        self.assertFalse(self.uncertain())

    def test_publication_no_replace_and_stage_tamper(self):
        self.approve()
        original_inspect = eduke32._inspect

        def inspection(path):
            if path.name.startswith(".eduke32.stage-"):
                path.write_bytes(self.engine + b"tamper")
            return original_inspect(path)

        with self.prepare(), mock.patch("eduke32._inspect", side_effect=inspection):
            self.assertEqual(self.execute()[0], 40)
        self.assertFalse(self.managed.exists())
        self.assertEqual(list(eduke32.target_root().glob(".eduke32.stage-*")), [])
        self.assertTrue(self.uncertain())
        stage = self.seed(eduke32.target_root() / ".stage")
        self.seed(self.managed, self.engine + b"existing")
        with self.assertRaisesRegex(eduke32.DependencyError, "nothing was replaced"):
            eduke32._publish(stage, self.managed)
        self.assertEqual(self.managed.read_bytes(), self.engine + b"existing")

    def test_post_publication_tamper_keeps_detection_pending(self):
        self.approve()
        publish = eduke32._publish

        def tamper(stage, target):
            publish(stage, target)
            target.write_bytes(self.engine + b"changed")

        with self.prepare(), mock.patch("eduke32._publish", side_effect=tamper):
            self.assertEqual(self.execute()[0], 40)
        self.assertTrue(self.uncertain())
        self.assertTrue(json.loads(self.journal.read_bytes())["detection_pending"])

    def test_malformed_active_failed_and_foreign_journals_block_retry(self):
        records = [[], {"job_id": "other"}, {"job_id": self.context["job_id"], "completed": [],
                   "active_command": ["make"]}, {"job_id": self.context["job_id"], "completed": [],
                   "active_command": None, "detection_pending": True},
                   {"job_id": self.context["job_id"], "completed": [],
                    "active_command": None, "failed": True}]
        for record in records:
            self.journal.write_text(json.dumps(record))
            with self.subTest(record=record):
                self.assertEqual(self.execute()[0], 40)
        self.journal.write_text("{broken")
        self.assertEqual(self.execute()[0], 40)

    def test_completed_transaction_reuse_requires_fresh_approval_no_rebuild(self):
        self.approve()
        with self.prepare():
            self.assertEqual(self.execute()[0], 0)
        self.context["phase"] = "preflight"
        self.approve()
        with mock.patch("eduke32.download", side_effect=AssertionError("No download")):
            self.assertEqual(self.execute()[0], 0)
        self.assertFalse(self.uncertain())

    def test_missing_prerequisites_have_explicit_needs_action_no_transaction(self):
        self.approve()
        with mock.patch("eduke32.shutil.which", return_value=None):
            code, result = self.execute()
        self.assertEqual(code, 20)
        self.assertIn("No elevation", result["message"])
        self.assertFalse(self.journal.exists())
        with mock.patch("eduke32.shutil.which", return_value="/usr/bin/tool"), \
                mock.patch("eduke32._probe", side_effect=eduke32.DependencyError("missing pkg")):
            with self.assertRaisesRegex(eduke32.NeedsAction, "development library"):
                eduke32.check_build_prerequisites()

    def test_build_exact_argv_waits_and_failed_exit_is_error(self):
        source = self.jobdir / "source"
        source.mkdir()
        with mock.patch("eduke32.subprocess.run", return_value=mock.Mock(returncode=0)) as command:
            eduke32._build(source)
        self.assertEqual(command.call_args.args[0], ["make", "-j2", "eduke32"])
        self.assertEqual(command.call_args.kwargs["cwd"], source)
        self.assertNotIn("timeout", command.call_args.kwargs)
        with mock.patch("eduke32.subprocess.run", return_value=mock.Mock(returncode=2)):
            with self.assertRaisesRegex(eduke32.DependencyError, "build failed"):
                eduke32._build(source)

    def test_host_read_only_metadata_and_no_engine_execution(self):
        self.seed()
        facts = eduke32.detect()
        library = self.seed(self.root / "libtest.so", mode=0o644)
        interpreter = self.seed(self.root / "loader", mode=0o755)

        def probe(argv):
            self.assertNotEqual(argv[0], str(self.guide))
            if "-l" in argv:
                return f"[Requesting program interpreter: {interpreter}]"
            if "-d" in argv:
                return "(NEEDED) Shared library: [libtest.so]\n(RUNPATH) Library runpath: [$ORIGIN]"
            self.assertEqual(argv, ["/host/ldconfig", "-p"])
            return f"libtest.so (libc6,x86-64) => {library}\n"

        with mock.patch.dict(os.environ, {"LD_PRELOAD": "", "LD_LIBRARY_PATH": "", "LD_AUDIT": ""}), \
                mock.patch("eduke32.shutil.which", side_effect=lambda x: "/host/" + x), \
                mock.patch("eduke32._probe", side_effect=probe):
            host = eduke32.check_host(facts)
        self.assertTrue(host["host_prerequisites_checked"])
        self.assertEqual(host["linked_libraries"], {"libtest.so": str(library)})
        for key in ("capabilities_checked", "cli_checked", "graphics_device_checked",
                    "gameplay_checked", "library_abi_checked"):
            self.assertFalse(host[key])
        self.assertEqual(self.guide.read_bytes(), self.engine)

    def test_host_missing_libraries_unsafe_paths_and_engine_tamper(self):
        self.seed()
        facts = eduke32.detect()
        interpreter = self.seed(self.root / "loader")
        headers = f"[Requesting program interpreter: {interpreter}]"
        for dynamic in ("(NEEDED) Shared library: [missing.so]",
                        "(NEEDED) Shared library: [../bad]",
                        "(NEEDED) Shared library: [missing.so]\n(RUNPATH) Library runpath: [.]"):
            with self.subTest(dynamic=dynamic), \
                    mock.patch.dict(os.environ, {"LD_PRELOAD": "", "LD_LIBRARY_PATH": "", "LD_AUDIT": ""}), \
                    mock.patch("eduke32.shutil.which", side_effect=lambda x: "/host/" + x), \
                    mock.patch("eduke32._probe", side_effect=[headers, dynamic, ""]):
                with self.assertRaises(eduke32.DependencyError):
                    eduke32.check_host(facts)
        with mock.patch.dict(os.environ, {"LD_PRELOAD": "unsafe.so"}):
            with self.assertRaisesRegex(eduke32.DependencyError, "environment"):
                eduke32.check_host(facts)
        with mock.patch.dict(os.environ, {"LD_PRELOAD": "", "LD_LIBRARY_PATH": "", "LD_AUDIT": ""}), \
                mock.patch("eduke32.shutil.which", return_value=None):
            with self.assertRaisesRegex(eduke32.DependencyError, "readelf"):
                eduke32.check_host(facts)
        self.guide.write_bytes(self.engine + b"changed")
        with self.assertRaisesRegex(eduke32.DependencyError, "changed"):
            eduke32.check_host(facts)

    def test_running_exact_other_runtime_and_unrelated_arguments(self):
        self.seed()
        facts = eduke32.detect()
        proc = self.root / "proc"
        proc.mkdir()
        entry = proc / "1234"
        entry.mkdir()
        (entry / "comm").write_bytes(b"python\n")
        (entry / "cmdline").write_bytes(b"/usr/bin/python\0eduke32\0")
        unrelated = self.seed(self.root / "python")
        (entry / "exe").symlink_to(unrelated)
        with mock.patch("eduke32.PROC_ROOT", proc), \
                mock.patch("eduke32.running", wraps=EDUKE_RUNNING):
            self.assertFalse(eduke32.running(facts))
            (entry / "exe").unlink()
            (entry / "exe").symlink_to(self.guide)
            self.assertTrue(eduke32.running(facts))
            (entry / "exe").unlink()
            other = self.seed(self.root / "other/eduke32")
            (entry / "exe").symlink_to(other)
            self.assertTrue(eduke32.running(facts))
            self.guide.write_bytes(self.engine + b"changed")
            with self.assertRaisesRegex(eduke32.DependencyError, "changed"):
                eduke32.running(facts)

    def test_running_inaccessible_suspect_fails_closed_unrelated_is_ignored(self):
        self.seed()
        proc = self.root / "proc"
        proc.mkdir()
        entry = proc / "1234"
        entry.mkdir()
        (entry / "comm").write_bytes(b"eduke32\n")
        (entry / "cmdline").write_bytes(os.fsencode(self.guide) + b"\0")
        with mock.patch("eduke32.PROC_ROOT", proc), \
                mock.patch("eduke32.running", wraps=EDUKE_RUNNING), \
                mock.patch("eduke32.os.readlink", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(eduke32.DependencyError, "suspect"):
                eduke32.running(eduke32.detect())
            (entry / "comm").write_bytes(b"python\n")
            (entry / "cmdline").write_bytes(b"/usr/bin/python\0")
            self.assertFalse(eduke32.running(eduke32.detect()))

    def test_running_guard_prevents_apply_and_uninstalled_facts_rejected(self):
        with mock.patch("eduke32.running", wraps=EDUKE_RUNNING):
            with self.assertRaises(eduke32.DependencyError):
                eduke32.running(eduke32.detect())
        self.seed()
        with mock.patch("eduke32.running", return_value=True):
            self.assertEqual(self.execute()[0], 20)
        self.assertFalse(self.journal.exists())

    def test_unsafe_protocol_paths_cannot_overwrite_existing_files(self):
        victim = self.seed(self.root / "victim")
        result = Path(self.context["result_file"])
        result.symlink_to(victim)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(eduke32.run(self.context), 40)
        self.assertEqual(victim.read_bytes(), self.engine)

    def test_invalid_protocol_contexts_have_explicit_errors_without_writes(self):
        for context in ([], {}, {**self.context, "cancel_file": None},
                        {**self.context, "result_file": self.context["cancel_file"]},
                        {**self.context, "result_file": str(self.journal)}):
            with self.subTest(context=context), contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(eduke32.run(context), 40)
        self.assertFalse(self.journal.exists())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_context_cli_preflight_protocol(self):
        context = self.jobdir / "context.json"
        context.write_text(json.dumps(self.context))
        result = SUBPROCESS_RUN([sys.executable, str(Path(eduke32.__file__)), "--context", str(context)],
                                env={**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        envelope = json.loads(Path(self.context["result_file"]).read_bytes())
        self.assertEqual(envelope["job_id"], self.context["job_id"])
        self.assertFalse(envelope["dependencies"]["eduke32"]["installed"])
        self.assertFalse(self.journal.exists())
        self.assertEqual(Path(self.context["intent_file"]).read_bytes(), b"")

    def test_real_jobs_produced_context_allows_owned_group_writable_jobdir(self):
        jobs_root = self.root / "runner-jobs"
        runner = Jobs(jobs_root, poll=0.02)
        self.addCleanup(runner.close)
        step = {"name": "Check required game software", "protocol": True,
                "approve_after": True, "declared_steps": ["resolve"],
                "argv": [sys.executable, str(Path(eduke32.__file__)), "--context", "{context_file}"],
                "env": {"HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"},
                "context": {"operation": "prepare-dependency", "phase": "preflight"}}
        previous_umask = os.umask(0o002)
        try:
            jid = runner.submit("EDuke32 real runner missing preflight", [step])
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                job = runner.get(jid)
                if job["status"] not in ("queued", "running", "starting"):
                    break
                time.sleep(0.02)
        finally:
            os.umask(previous_umask)
        self.assertEqual(job["status"], "awaiting-approval", job)
        paths = runner.paths(jid)
        self.assertEqual(stat.S_IMODE(paths["job_dir"].stat().st_mode), 0o775)
        context = runner._context(runner.jobs[jid], runner.jobs[jid]["steps"][0])
        self.assertEqual(eduke32._context_paths(context), paths["job_dir"])
        self.assertEqual(job["plan"]["operation"], "prepare-dependency")
        self.assertFalse(job["plan"]["dependencies"]["eduke32"]["installed"])
        self.assertEqual(paths["intent_file"].read_bytes(), b"")
        self.assertFalse((paths["job_dir"] / "dependency-transactions.json").exists())
        self.assertFalse((self.home / "Games").exists())
        with mock.patch("eduke32.os.getgid", return_value=paths["job_dir"].stat().st_gid + 1):
            with self.assertRaisesRegex(eduke32.DependencyError, "Protocol files"):
                eduke32._context_paths(context)
        self.assertIs(runner.cancel(jid), True)

    def test_download_and_extraction_cancellation_keep_uncertain_transaction(self):
        self.approve()

        def download(context):
            Path(context["cancel_file"]).touch()
            raise eduke32.Cancelled("Cancelled in download")

        with self.prepare(download=download):
            self.assertEqual(self.execute()[0], 130)
        self.assertTrue(self.uncertain())
        self.assertFalse(self.managed.exists())
        Path(self.context["cancel_file"]).unlink()
        self.assertEqual(self.execute()[0], 40)

    def test_runtime_appearing_during_build_is_never_replaced(self):
        self.approve()

        def build(source):
            self.build(source)
            self.seed(self.managed, self.engine + b"appeared")

        with self.prepare(build=build):
            code, result = self.execute()
        self.assertEqual(code, 40)
        self.assertIn("facts changed", result["message"])
        self.assertEqual(self.managed.read_bytes(), self.engine + b"appeared")
        self.assertTrue(self.uncertain())

    def test_failed_redetection_and_publication_crash_are_not_retryable(self):
        self.approve()
        with self.prepare(), mock.patch("eduke32._publish", side_effect=OSError("publication interrupted")):
            self.assertEqual(self.execute()[0], 40)
        self.assertTrue(self.uncertain())
        self.assertEqual(json.loads(self.journal.read_bytes())["active_command"],
                         ["publish-eduke32", str(self.managed)])
        self.assertEqual(list(eduke32.target_root().glob(".eduke32.stage-*")), [])
        with self.prepare():
            self.assertEqual(self.execute()[0], 40)

    def test_byte_hash_race_and_wrong_owner_fail_inspection(self):
        path = self.seed()
        with mock.patch("eduke32.os.getuid", return_value=path.stat().st_uid + 1):
            with self.assertRaisesRegex(eduke32.DependencyError, "Unsafe"):
                eduke32.detect()
        original_fstat = os.fstat
        calls = []

        def racing(fd):
            if calls:
                path.write_bytes(self.engine + b"race")
            calls.append(True)
            return original_fstat(fd)

        with mock.patch("eduke32.os.fstat", side_effect=racing):
            with self.assertRaisesRegex(eduke32.DependencyError, "changed during inspection"):
                eduke32._inspect(path)

    def test_host_unsafe_library_mode_and_missing_interpreter(self):
        self.seed()
        library = self.seed(self.root / "library", mode=0o777)
        with self.assertRaisesRegex(eduke32.DependencyError, "Unsafe linked"):
            eduke32._host_elf(library)
        with mock.patch.dict(os.environ, {"LD_PRELOAD": "", "LD_LIBRARY_PATH": "", "LD_AUDIT": ""}), \
                mock.patch("eduke32.shutil.which", return_value="/host/readelf"), \
                mock.patch("eduke32._probe", return_value=""):
            with self.assertRaisesRegex(eduke32.DependencyError, "interpreter"):
                eduke32.check_host(eduke32.detect())

    def test_running_missing_live_executable_fails_closed_zombies_ignored(self):
        self.seed()
        proc = self.root / "proc"
        proc.mkdir()
        entry = proc / "1234"
        entry.mkdir()
        (entry / "status").write_text("State:\tS (sleeping)\n")
        with mock.patch("eduke32.PROC_ROOT", proc), mock.patch("eduke32.running", wraps=EDUKE_RUNNING):
            with self.assertRaisesRegex(eduke32.DependencyError, "live process"):
                eduke32.running(eduke32.detect())
            (entry / "status").write_text("State:\tZ (zombie)\n")
            self.assertFalse(eduke32.running(eduke32.detect()))


EDUKE_RUNNING = eduke32.running
SUBPROCESS_RUN = subprocess.run


if __name__ == "__main__":
    unittest.main()
