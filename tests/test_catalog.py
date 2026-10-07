"""Catalog/download tests never contact the network or execute package scripts."""
import copy
import contextlib
import hashlib
import io
import json
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import catalog
import jobs
import packages
from tests.test_packages import Base, package_files, write_zip


class Response(io.BytesIO):
    def __init__(self, data, url, length=None):
        super().__init__(data)
        self.url = url
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def geturl(self):
        return self.url


class CatalogTests(Base):
    def setUp(self):
        super().setUp()
        self.archive = write_zip(self.t / "fixture.zip", package_files())
        self.data = self.archive.read_bytes()
        info = packages.check(self.archive)
        self.entry = {
            "id": "test-game", "version": "1.0.0", "name": "Test Game", "description": "Your own files.",
            "url": f"https://github.com/{catalog.REPOSITORY}/releases/download/test-game-1.0.0/test-game-1.0.0.zip",
            "icon_url": f"https://raw.githubusercontent.com/{catalog.REPOSITORY}/main/artwork/test-game.png",
            "sha256": hashlib.sha256(self.data).hexdigest(), "digest": info["digest"],
            "size": len(self.data),
            "platform": {"os": "ubuntu", "releases": ["24.04"], "architectures": ["x86_64"]},
        }
        self.platform = mock.patch("packages._platform_issues", return_value=[])
        self.platform.start()
        self.addCleanup(self.platform.stop)
        catalog.validate({"catalog_version": 1, "games": [self.entry]})

    def response(self, entry=None):
        return Response(self.data, (entry or self.entry)["url"], len(self.data))

    def test_fixed_release_urls_and_metadata_validation(self):
        catalog.validate({"catalog_version": 1, "games": [copy.deepcopy(self.entry)]})
        for key, value in (("url", "https://example.com/install.zip"), ("url", self.entry["url"] + "?token=secret"),
                           ("icon_url", "javascript:alert(1)"), ("sha256", "wrong"), ("digest", "wrong"),
                           ("size", True), ("size", catalog.MAX_DOWNLOAD + 1), ("platform", {"os": "ubuntu"}),
                           ("version", "../main"), ("id", "../escape")):
            with self.subTest(key=key, value=value):
                entry = dict(self.entry, **{key: value})
                with self.assertRaises(catalog.CatalogError):
                    catalog.validate({"catalog_version": 1, "games": [entry]})
        with self.assertRaises(catalog.CatalogError):
            catalog.validate({"catalog_version": 1, "games": [self.entry, self.entry]})

    def test_redirects_are_bounded_to_https_github_delivery(self):
        handler = catalog.GitHubRedirect()
        request = urllib.request.Request(self.entry["url"])
        for url in ("http://github.com/file", "https://example.com/file", "https://localhost/file",
                    "https://github.com.evil.test/file", "https://user:password@github.com/file"):
            with self.subTest(url=url), self.assertRaises(catalog.CatalogError):
                handler.redirect_request(request, None, 302, "", {}, url)
        accepted = handler.redirect_request(request, None, 302, "", {},
                                            "https://release-assets.githubusercontent.com/file?sig=abc")
        self.assertIsNotNone(accepted)

    def test_bundled_mod_download_size_limit_is_explicit_and_bounded(self):
        self.assertEqual(catalog.MAX_DOWNLOAD, 512 << 20)
        for size in (140257501, catalog.MAX_DOWNLOAD):
            entry = dict(self.entry, size=size)
            catalog.validate({"catalog_version": 1, "games": [entry]})
        with self.assertRaisesRegex(catalog.CatalogError, "download size"):
            catalog.validate({"catalog_version": 1, "games": [dict(
                self.entry, size=catalog.MAX_DOWNLOAD + 1)]})

    def test_catalog_offline_invalid_and_oversize_errors_are_explicit(self):
        with mock.patch("catalog._open", side_effect=urllib.error.URLError("offline")):
            with self.assertRaisesRegex(catalog.CatalogError, "Check your connection"):
                catalog.load()
        for data in (b"not json", b"x" * (catalog.MAX_CATALOG + 1)):
            with mock.patch("catalog._open", return_value=Response(data, catalog.CATALOG_URL)):
                with self.assertRaises(catalog.CatalogError):
                    catalog.load()

    def test_verified_download_imports_immutable_snapshot_without_execution(self):
        progress = []
        with mock.patch("catalog._open", return_value=self.response()):
            info = catalog.download(self.entry, self.app, progress=lambda current, total: progress.append((current, total)))
        self.assertEqual(info["digest"], self.entry["digest"])
        self.assertEqual(progress[-1], (len(self.data), len(self.data)))
        self.assertTrue(packages.snapshot_path(self.app, "test-game", "1.0.0").is_dir())
        with mock.patch("catalog._open", return_value=self.response()):
            self.assertEqual(catalog.download(self.entry, self.app)["digest"], info["digest"])

    def test_bad_checksum_size_identity_or_digest_never_imports(self):
        for key, value in (("sha256", "0" * 64), ("size", len(self.data) - 1),
                           ("size", len(self.data) + 1), ("digest", "sha256:" + "0" * 64),
                           ("version", "1.0.1")):
            entry = dict(self.entry, **{key: value})
            if key == "version":
                entry["url"] = entry["url"].replace("1.0.0", "1.0.1")
            with self.subTest(key=key), mock.patch("catalog._open", return_value=self.response(entry)):
                with self.assertRaises(catalog.CatalogError):
                    catalog.download(entry, self.app)
                self.assertFalse(packages.list_packages(self.app))

    def test_truncated_download_cleans_temporary_files_then_retry_succeeds(self):
        temporary = self.t / "download-temp"
        temporary.mkdir()
        original = catalog.tempfile.TemporaryDirectory
        def directory(**kw):
            return original(dir=temporary, **kw)
        with mock.patch("catalog.tempfile.TemporaryDirectory", side_effect=directory), \
                mock.patch("catalog._open", return_value=Response(self.data[:50], self.entry["url"])):
            with self.assertRaisesRegex(catalog.CatalogError, "incomplete"):
                catalog.download(self.entry, self.app)
        self.assertEqual(list(temporary.iterdir()), [])
        with mock.patch("catalog._open", return_value=self.response()):
            self.assertIsNotNone(catalog.download(self.entry, self.app))

    def test_cancel_during_download_never_imports_and_cleans_up(self):
        checks = 0
        def cancelled():
            nonlocal checks
            checks += 1
            return checks >= 3
        with mock.patch("catalog._open", return_value=self.response()), \
                mock.patch("packages.import_package") as importing:
            self.assertIsNone(catalog.download(self.entry, self.app, cancelled))
            importing.assert_not_called()

    def test_unsupported_platform_cannot_download(self):
        with mock.patch("packages._platform_issues", return_value=["Wrong architecture"]), \
                mock.patch("catalog._open") as opening:
            with self.assertRaisesRegex(catalog.CatalogError, "Unsupported platform"):
                catalog.download(self.entry, self.app)
            opening.assert_not_called()

    def test_submission_pins_metadata_deduplicates_and_survives_reopen(self):
        runner = jobs.Jobs(self.app / "jobs")
        with mock.patch("catalog.load", return_value={"games": [self.entry]}), \
                mock.patch.object(runner, "_start"):
            first = catalog.submit(self.app, runner, "test-game")
            self.assertEqual(catalog.submit(self.app, runner, "test-game"), first)
            self.assertEqual(runner.jobs[first]["steps"][0]["context"]["entry"]["sha256"], self.entry["sha256"])
            with self.assertRaises(catalog.CatalogError):
                catalog.submit(self.app, runner, "missing")
        runner.close()
        reopened = jobs.Jobs(self.app / "jobs")
        try:
            detail = reopened.get(first)
            self.assertEqual(detail["package_id"], "test-game")
            self.assertEqual(detail["package_version"], "1.0.0")
        finally:
            reopened.close()

    def test_protocol_download_has_measurable_progress_and_no_install_intents(self):
        runner = jobs.Jobs(self.app / "jobs")
        try:
            # Run the worker in-process with transport mocked, then feed its real records to the runner.
            with mock.patch("catalog.load", return_value={"games": [self.entry]}), \
                    mock.patch.object(runner, "_start"):
                jid = catalog.submit(self.app, runner, "test-game")
            job = runner.jobs[jid]
            context = runner._context(job, job["steps"][0])
            output = io.StringIO()
            with contextlib.redirect_stdout(output), mock.patch("catalog._open", return_value=self.response()):
                self.assertEqual(catalog.run(context), 0)
            events = [json.loads(line) for line in output.getvalue().splitlines()]
            for event in events:
                self.assertIsNone(jobs.validate_event(event, ["download"]))
            self.assertEqual(next(e for e in reversed(events) if e["type"] == "progress")["current"], len(self.data))
            self.assertEqual(runner.paths(jid)["intent_file"].read_bytes(), b"")
            self.assertEqual(json.loads(runner.paths(jid)["result_file"].read_text())["outcome"], "succeeded")
        finally:
            runner.close()
