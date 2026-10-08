"""Pinned preparation safety/approval tests. No engine invocation."""
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

import ironwail as iw
from dependencies import DependencyError
from tests.test_quake_installs import write_pak


class IronwailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)

    def context(self):
        job = self.root / "job"
        job.mkdir(exist_ok=True)
        return {"phase": "preflight", "operation": "prepare-dependency", "job_id": "jtest",
                "result_file": str(job / "result.json"), "cancel_file": str(job / "cancel"),
                "package_root": str(self.root), "package_digest": "sha256:" + "a" * 64,
                "inputs": {"source_dir": str(self.root), "games_root": str(self.home / "Games")},
                "game_directory": str(self.home / "Games/Game")}

    def test_missing_detection_uses_managed_path_and_no_capability_claim(self):
        facts = iw.detect()
        self.assertFalse(facts["installed"])
        self.assertFalse(facts["capabilities_checked"])
        self.assertEqual(facts["executable"], str(iw.target_root() / "ironwail"))

    def test_unsafe_candidate_never_falls_back(self):
        p = self.home / "Games/Quake/ironwail"
        p.parent.mkdir(parents=True)
        p.symlink_to("/etc/passwd")
        with self.assertRaises(DependencyError):
            iw.detect()

    def test_unknown_candidate_never_falls_back(self):
        p = self.home / "Games/Quake/ironwail"
        p.parent.mkdir(parents=True)
        p.write_text("unknown")
        with self.assertRaises(DependencyError):
            iw.detect()

    def test_engine_companion_checks_cannot_be_skipped(self):
        engine = self.home / "Games/Quake/ironwail"
        engine.parent.mkdir(parents=True)
        engine.write_bytes(b"engine")
        engine.chmod(0o755)
        with mock.patch.object(iw, "_regular", side_effect=[None, DependencyError("invalid companion")]) as check:
            with self.assertRaises(DependencyError):
                iw.detect()
        self.assertEqual(check.call_count, 2)
        self.assertEqual(check.call_args.args[0], engine.parent / "ironwail.pak")
        companion = engine.parent / "ironwail.pak"
        companion.write_bytes(b"companion")
        iw._regular(companion, 9, hashlib.sha256(b"companion").hexdigest())
        with self.assertRaises(DependencyError):
            iw._regular(companion, 9, iw.PAK_SHA)
        companion.unlink()
        companion.symlink_to("/etc/passwd")
        with self.assertRaises(DependencyError):
            iw._regular(companion, 9, iw.PAK_SHA)

    def test_paths_reject_relative_traversal_symlink_control(self):
        link = self.root / "link"
        link.symlink_to(self.home, target_is_directory=True)
        for p in ("relative", str(self.root / "../escape"), str(link / "file"), "/tmp/evil\npath"):
            with self.subTest(p=p), self.assertRaises(DependencyError):
                iw.safe(p)

    def test_archive_names_reject_unsafe_entries(self):
        for name in ("../escape", "/absolute", "qbj3//x", "qbj3\\x", "x:y", "qbj3/\nx"):
            with self.subTest(name=name), self.assertRaises(DependencyError):
                iw._archive_name(name)

    def test_trusted_redirects_only(self):
        for url in ("http://github.com/x", "https://evil.example/x", "https://user@github.com/x"):
            with self.subTest(url=url), self.assertRaises(DependencyError):
                iw._url(url)
        iw._url(iw.MOD_URL)
        iw._url(iw.URL)

    def test_download_binds_user_agent_size_hash_and_final_host(self):
        data = b"verified archive"
        digest = hashlib.sha256(data).hexdigest()
        for case in ("valid", "wrong-hash", "truncated", "oversized", "wrong-length", "untrusted-host"):
            with self.subTest(case=case):
                body = data[:-1] if case == "truncated" else data + b"x" if case == "oversized" else data
                response = io.BytesIO(body)
                response.headers = {"Content-Length": str(len(data) + (case == "wrong-length"))}
                response.geturl = lambda: "https://evil.example/archive" if case == "untrusted-host" else iw.MOD_URL
                opener = mock.Mock()
                opener.open.return_value = response
                destination = self.root / case
                with mock.patch.object(iw.urllib.request, "build_opener", return_value=opener):
                    if case == "valid":
                        iw.download(self.context(), iw.MOD_URL, destination, len(data), digest)
                        self.assertEqual(destination.read_bytes(), data)
                    else:
                        with self.assertRaises(DependencyError):
                            iw.download(self.context(), iw.MOD_URL, destination, len(data),
                                        "a" * 64 if case == "wrong-hash" else digest)
                request = opener.open.call_args.args[0]
                self.assertEqual(request.get_header("User-agent"), "Momentum-Core-QBJ3/0.1.0")

    def test_download_cancels_during_stream(self):
        response = io.BytesIO(b"archive")
        response.headers = {}
        response.geturl = lambda: iw.MOD_URL
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(iw.urllib.request, "build_opener", return_value=opener), \
                mock.patch.object(iw, "cancel", side_effect=[None, iw.Cancelled("cancelled")]):
            with self.assertRaises(iw.Cancelled):
                iw.download(self.context(), iw.MOD_URL, self.root / "partial", 7,
                            hashlib.sha256(b"archive").hexdigest())
        self.assertEqual((self.root / "partial").read_bytes(), b"")

    def test_extract_mod_positive_hashes_and_cancellation(self):
        archive = self.root / "source.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("qbj3/progs.dat", b"data")
        index = {"files": [{"relative_path": "qbj3/progs.dat", "size": 4,
                            "sha256": hashlib.sha256(b"data").hexdigest()}]}
        stage = self.root / "stage"
        stage.mkdir()
        with mock.patch.object(iw, "EXPANDED_SIZE", 4):
            iw.extract_mod(self.context(), archive, stage, index)
            self.assertEqual((stage / "qbj3/progs.dat").read_bytes(), b"data")
            second = self.root / "cancelled-stage"
            second.mkdir()
            with mock.patch.object(iw, "cancel", side_effect=iw.Cancelled("cancelled")):
                with self.assertRaises(iw.Cancelled):
                    iw.extract_mod(self.context(), archive, second, index)
            self.assertEqual(list(second.iterdir()), [])

    def test_failed_approved_download_retains_uncertain_journal_without_publishing(self):
        c = self.context()
        destination = iw.target_root()
        plan = {"downloads": [{"url": iw.URL, "bytes": iw.ARCHIVE_SIZE, "sha256": iw.ARCHIVE_SHA,
                               "destination": str(destination), "purpose": "shared-software"}]}
        with mock.patch.object(iw, "make_plan", return_value=plan), \
                mock.patch.object(iw, "index_for", return_value={"files": []}):
            self.assertEqual(iw.run(c), 0)
            raw = Path(c["result_file"]).read_bytes()
            approved = Path(c["result_file"]).parent / "approved.json"
            approved.write_bytes(raw)
            c.update(phase="apply", approved_plan_file=str(approved),
                     approved_plan_digest="sha256:" + hashlib.sha256(raw).hexdigest())
            with mock.patch.object(iw, "download", side_effect=DependencyError("network failed")):
                self.assertEqual(iw.run(c), 40)
        journal = Path(c["result_file"]).parent / "dependency-transactions.json"
        self.assertEqual(json.loads(journal.read_text())["active_command"][1], "shared-software")
        self.assertFalse(destination.exists())
        self.assertEqual(list(destination.parent.iterdir()), [])
        self.assertEqual(iw.run(c), 40)

    def test_invalid_base_blocks_source_preparation(self):
        with self.assertRaises(DependencyError):
            iw.validate_base(self.root)
        write_pak(self.root / "id1/pak0.pak", {"gfx/test": b"data"})
        write_pak(self.root / "id1/pak1.pak", {"maps/test": b"data"})
        iw.validate_base(self.root)
        (self.root / "id1/pak1.pak").write_bytes(b"bad")
        with self.assertRaises(DependencyError):
            iw.validate_base(self.root)

    def test_existing_mod_allows_state_edits_but_not_asset_edits(self):
        folder = self.root / "qbj3"
        folder.mkdir()
        rows = []
        for name in ("progs.dat", "config.cfg"):
            p = folder / name
            p.write_bytes(b"source")
            rows.append({"relative_path": "qbj3/" + name, "size": 6, "sha256": iw.filehash(p)})
        index = {"files": rows}
        (folder / "config.cfg").write_text("personal setting")
        iw.mod_matches(folder, index)
        with self.assertRaises(DependencyError):
            iw.mod_matches(folder, index, exact_state=True)
        (folder / "progs.dat").write_text("edited")
        with self.assertRaises(DependencyError):
            iw.mod_matches(folder, index)

    def test_mod_unknown_symlink_rejected(self):
        folder = self.root / "qbj3"
        folder.mkdir()
        (folder / "save").symlink_to("/etc/passwd")
        with self.assertRaises(DependencyError):
            iw.mod_matches(folder, {"files": []})

    def test_invalid_explicit_mod_never_downloads(self):
        c = self.context()
        c["inputs"]["mod_dir"] = str(self.root / "missing")
        with mock.patch.object(iw, "validate_base"), mock.patch.object(iw, "index_for", return_value={"files": []}):
            with self.assertRaises(DependencyError):
                iw.source_for(c["inputs"], c["package_root"], c["package_digest"])

    def test_unsafe_tar_rejected_without_extraction(self):
        archive, stage = self.root / "bad.tar", self.root / "stage"
        stage.mkdir()
        with tarfile.open(archive, "w") as t:
            for i in range(7):
                info = tarfile.TarInfo("../escape" + str(i))
                info.size = 1
                t.addfile(info, io.BytesIO(b"x"))
        with self.assertRaises(DependencyError):
            iw.extract_engine(archive, stage)
        self.assertEqual(list(stage.iterdir()), [])

    def test_mod_zip_rejects_path_and_duplicate_and_inventory(self):
        stage = self.root / "stage"
        stage.mkdir()
        for names in (["../escape"], ["qbj3/file", "qbj3/file"], ["qbj3/extra"]):
            archive = self.root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as z:
                for name in names:
                    z.writestr(name, b"x")
            with self.assertRaises(DependencyError):
                iw.extract_mod(self.context(), archive, stage, {"files": []})
            self.assertEqual(list(stage.iterdir()), [])

    def test_publication_never_replaces_existing_destination(self):
        source, destination = self.root / "stage", self.root / "target"
        source.mkdir()
        destination.mkdir()
        (destination / "keep").write_text("unchanged")
        with self.assertRaises(DependencyError):
            iw._publish(source, destination)
        self.assertEqual((destination / "keep").read_text(), "unchanged")

    def test_preflight_and_changed_approval_remain_readonly(self):
        c = self.context()
        with mock.patch.object(iw, "make_plan", return_value={"operation": "prepare-dependency", "downloads": []}), \
                mock.patch.object(iw, "index_for", return_value={"files": []}):
            self.assertEqual(iw.run(c), 0)
            raw = Path(c["result_file"]).read_bytes()
            approved = Path(c["result_file"]).parent / "approved.json"
            approved.write_bytes(raw)
            c.update(phase="apply", approved_plan_file=str(approved),
                     approved_plan_digest="sha256:" + hashlib.sha256(raw).hexdigest())
            self.assertEqual(iw.run(c), 0)
            c["approved_plan_digest"] = "sha256:" + "0" * 64
            self.assertEqual(iw.run(c), 40)
        self.assertFalse((self.home / ".local").exists())

    def test_stale_plan_conflicts(self):
        c = self.context()
        with mock.patch.object(iw, "make_plan", return_value={"downloads": []}):
            self.assertEqual(iw.run(c), 0)
            raw = Path(c["result_file"]).read_bytes()
        approved = Path(c["result_file"]).parent / "approved.json"
        approved.write_bytes(raw)
        c.update(phase="apply", approved_plan_file=str(approved),
                 approved_plan_digest="sha256:" + hashlib.sha256(raw).hexdigest())
        with mock.patch.object(iw, "make_plan", return_value={"downloads": [{"changed": True}]}):
            self.assertEqual(iw.run(c), 30)

    def test_cancellation_before_preflight(self):
        c = self.context()
        Path(c["cancel_file"]).touch()
        self.assertEqual(iw.run(c), 130)
        self.assertFalse((self.home / ".local").exists())

    def test_uncertain_transaction_blocks_retry(self):
        c = self.context()
        journal = Path(c["result_file"]).parent / "dependency-transactions.json"
        journal.write_text(json.dumps({"job_id": "jtest", "completed": [], "active_command": ["publish"]}))
        self.assertEqual(iw.run(c), 40)

    def test_invalid_context_does_not_write_result_outside_job(self):
        c = self.context()
        c["cancel_file"] = str(self.root / "outside")
        self.assertEqual(iw.run(c), 40)
        self.assertFalse(Path(c["result_file"]).exists())

    def test_protocol_paths_cannot_alias_result_journal_cancel_or_context(self):
        for alias in ("result_file", "cancel_file", "journal", "context_file"):
            with self.subTest(alias=alias):
                c = self.context()
                c["context_file"] = str(Path(c["result_file"]).parent / "context.json")
                c["approved_plan_file"] = (str(Path(c["result_file"]).parent / "dependency-transactions.json")
                                           if alias == "journal" else c[alias])
                self.assertEqual(iw.run(c), 40)
                self.assertFalse(Path(c["result_file"]).exists())
