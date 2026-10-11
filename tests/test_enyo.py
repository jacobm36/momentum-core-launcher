"""Publisher acquisition checks; synthetic content and no game execution."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import enyo
import vkquake


class EnyoSource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.content = b"synthetic publisher PAK"
        for name, value in (("PAK_SIZE", len(self.content)),
                            ("PAK_SHA", hashlib.sha256(self.content).hexdigest())):
            patch = mock.patch.object(enyo, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_extract_only_expected_file_and_verified_bytes(self):
        archive = self.root / "publisher.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("enyo/pak0.pak", self.content)
        destination = self.root / "pak0.pak"
        enyo.extract(archive, destination)
        self.assertEqual(destination.read_bytes(), self.content)

    def test_wrong_layout_size_content_and_duplicate_rejected(self):
        for contents in (
            [("../pak0.pak", self.content)],
            [("enyo/pak0.pak", b"wrong")],
            [("enyo/pak0.pak", b"x" * len(self.content))],
            [("enyo/pak0.pak", self.content), ("other.txt", b"extra")],
        ):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory(dir=self.root) as temp:
                archive = Path(temp) / "publisher.zip"
                with zipfile.ZipFile(archive, "w") as bundle:
                    for name, data in contents:
                        bundle.writestr(name, data)
                with self.assertRaises(enyo.DependencyError):
                    enyo.extract(archive, Path(temp) / "pak0.pak")

    def test_symlink_source_and_untrusted_hosts_rejected(self):
        (self.root / "real").write_bytes(self.content)
        (self.root / "link").symlink_to(self.root / "real")
        with self.assertRaises(enyo.DependencyError):
            enyo.verify(self.root / "link")
        for url in ("http://poppyworks.itch.io/file", "https://evil.example/file",
                    "https://poppyworks.itch.io.evil.example/file",
                    "https://user:password@poppyworks.itch.io/file"):
            with self.subTest(url=url), self.assertRaises(enyo.DependencyError):
                enyo.check_url(url)
        enyo.check_url(enyo.PAGE)
        enyo.check_url("https://itchio-mirror." + "a" * 32 + ".r2.cloudflarestorage.com/file")

    def test_reuse_never_overwrites_different_existing_source(self):
        source = self.root / "Quake"
        (source / "enyo").mkdir(parents=True)
        pak = source / "enyo/pak0.pak"
        pak.write_bytes(self.content)
        with mock.patch.object(enyo, "enabled", return_value=True):
            self.assertEqual(enyo.source_for({"source_dir": str(source)}, str(self.root), "digest"),
                             pak.parent)
            pak.write_bytes(b"personal different content")
            with self.assertRaises(enyo.DependencyError):
                enyo.source_for({"source_dir": str(source)}, str(self.root), "digest")
        self.assertEqual(pak.read_bytes(), b"personal different content")

    def test_source_approval_plan_is_separate_and_publisher_bound(self):
        facts = {"installed": True}
        context = {"package_root": str(self.root), "package_digest": "digest"}
        with mock.patch.object(enyo, "enabled", return_value=True), \
                mock.patch.object(enyo, "download_plan", return_value={"page": enyo.PAGE}):
            plan = vkquake.make_plan(facts, context)
        self.assertEqual(plan["operation"], "prepare-dependency")
        self.assertEqual(plan["downloads"], [{"page": enyo.PAGE}])
        self.assertEqual(plan["actions"], [])

    def test_prepare_publishes_only_verified_cache_and_retains_it(self):
        target = self.root / "cache/pak0.pak"
        facts = {"installed": True}
        context = {"job_id": "j12345678", "cancel_file": str(self.root / "cancel")}
        def download(ctx, path):
            with zipfile.ZipFile(path, "w") as bundle:
                bundle.writestr("enyo/pak0.pak", self.content)
        with mock.patch.object(enyo, "cache_path", return_value=target), \
                mock.patch.object(enyo, "download_plan", return_value={"target": str(target)}), \
                mock.patch.object(enyo, "download", side_effect=download), \
                mock.patch.object(vkquake, "detect", return_value=facts), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            completed = []
            journal = self.root / "journal.json"
            enyo.prepare(context, journal, [], completed, facts)
            self.assertEqual(target.read_bytes(), self.content)
            self.assertEqual(completed[0]["sha256"], enyo.PAK_SHA)
            self.assertIsNone(json.loads(journal.read_text())["active_command"])
            self.assertEqual(list(target.parent.glob(".enyo-download-*")), [])
            with self.assertRaises(enyo.DependencyError):
                enyo.prepare(context, journal, [], [], facts)
        self.assertEqual(target.read_bytes(), self.content)
