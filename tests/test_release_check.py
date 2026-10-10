"""Read-only release preflight and compatibility diagnostics."""
import contextlib
import importlib.util
import io
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import compatibility
from tests.test_packages import package_files, write_tree, write_zip

spec = importlib.util.spec_from_file_location("release_check", Path(__file__).parents[1] / "tools/check-release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class Diagnostics(unittest.TestCase):
    def test_reasons_do_not_mislabel_platform_or_software_as_launcher_updates(self):
        for platform, supported, enabled, prerequisites, facts, reason in (
            (["Wrong architecture"], False, False, [], {}, "unsupported-platform"),
            ([], False, False, [], {}, "missing-evidence"),
            ([], True, False, [{"title": "FUSE"}], {}, "host-prerequisites"),
            ([], True, False, [], {"supermodel": {"installed": True}}, "software-mismatch"),
            ([], True, False, [], {"supermodel": {"installed": False}}, "software-missing"),
        ):
            with self.subTest(reason=reason):
                result = compatibility.guidance(platform, supported, enabled, prerequisites, facts)
                self.assertEqual(result["reason"], reason)
                self.assertEqual("url" in result, reason == "missing-evidence")
        self.assertIsNone(compatibility.guidance([], True, True, [], {}))

    def test_exact_records_include_current_arcade_pair_and_reject_changed_digest(self):
        here = Path(__file__).parents[1]
        for game in ("l-a-machineguns", "star-wars-trilogy-arcade"):
            record = next(r for r in compatibility.records(here) if r["id"] == game)
            self.assertEqual(compatibility.find_record(here, game, record["version"], record["digest"]), record)
            self.assertIsNone(compatibility.find_record(here, game, record["version"], "sha256:" + "0" * 64))

    def test_cli_exit_and_final_result_are_unambiguous_and_all_inputs_checked(self):
        for fail in (False, True):
            with self.subTest(fail=fail), mock.patch.object(release, "check") as check:
                check.side_effect = ["first", ValueError("Catalog digest differs")] if fail else ["first", "second"]
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = release.main(["first.zip", "second.zip"])
                self.assertEqual(check.call_count, 2)
                self.assertEqual(code, 1 if fail else 0)
                self.assertTrue(output.getvalue().rstrip().endswith("RELEASE CHECK: FAIL" if fail else "RELEASE CHECK: PASS"))

    def test_invalid_launcher_archive_is_a_failure_not_a_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            invalid = Path(temporary) / "launcher.zip"
            invalid.write_bytes(b"invalid")
            with mock.patch.object(release, "check") as check, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(release.main(["game.zip", "--launcher-archive", str(invalid)]), 1)
            check.assert_not_called()
            self.assertIn("RELEASE CHECK: FAIL", output.getvalue())


class ReleaseFailures(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.source = self.repo / "test-game/package"
        self.repo.mkdir()
        (self.repo / "tools").mkdir()
        original_builder = Path(os.environ.get("MCL_PACKAGE_REPO",
            str(Path(__file__).parents[2] / "momentum-packages"))) / "tools/build.py"
        # Use the repository's existing immutable-version validator, not a test stub.
        if not original_builder.is_file():
            self.skipTest("Package builder checkout required; set MCL_PACKAGE_REPO")
        shutil.copyfile(original_builder, self.repo / "tools/build.py")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, capture_output=True)
        self.files = package_files(extra={
            "tests/check_package.py": b"print('self-check passed')\n",
            "tests/__init__.py": b"import sys\nfrom pathlib import Path\nsys.dont_write_bytecode=True\n"
                                 b"if globals().get('__cached__'):\n p=Path(__cached__);p.unlink(missing_ok=True)\n"
                                 b" if p.parent.exists(): p.parent.rmdir()\n",
            "tests/test_minimal.py": b"import unittest\nclass Check(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n",
        })
        write_tree(self.source, self.files)
        self.archive = write_zip(self.root / "test-game-1.0.0.zip", self.files)
        self.info = release.packages.check(self.archive)
        self.launcher = self.root / "launcher"
        shutil.copytree(Path(__file__).parents[1] / "docs", self.launcher / "docs")
        self.evidence_path = self.launcher / "docs/arcade-installer-evidence.json"
        evidence = json.loads(self.evidence_path.read_text())
        evidence["packages"].append({
            "id": "test-game", "version": "1.0.0", "digest": self.info["digest"],
            "installer_validated": True, "runtime": "flycast",
            "software": {"provider": "flatpak", "scope": "user", "app_id": "org.flycast.Flycast",
                         "version": "v2.7", "commit": "a" * 64},
        })
        self.evidence_path.write_text(json.dumps(evidence))
        self.distribution = self.root / "distribution"
        self.distribution.mkdir()
        self.entry = {
            "id": "test-game", "version": "1.0.0", "name": "Test", "description": "Test release",
            "url": "https://github.com/jacobm36/momentum-distribution/releases/download/test-game-1.0.0/test-game-1.0.0.zip",
            "icon_url": "https://raw.githubusercontent.com/jacobm36/momentum-distribution/main/artwork/test-game.png",
            "digest": self.info["digest"], "sha256": hashlib.sha256(self.archive.read_bytes()).hexdigest(),
            "size": self.archive.stat().st_size,
            "platform": json.loads(self.files["package.json"])["platform"],
        }
        self.save_catalog()
        (self.distribution / "test-game-1.0.0.zip.sha256").write_text(
            self.entry["sha256"] + "  test-game-1.0.0.zip\n")

    def save_catalog(self):
        (self.distribution / "catalog.json").write_text(
            json.dumps({"catalog_version": 1, "games": [self.entry]}))

    def check(self, public=False):
        return release.check(self.archive, self.repo, self.distribution, self.launcher, public)

    def test_complete_local_check_and_catalog_drift(self):
        self.assertEqual(self.check(), "test-game-1.0.0")
        for key, value in (("digest", "sha256:" + "0" * 64), ("size", 1), ("sha256", "0" * 64)):
            with self.subTest(key=key):
                original = self.entry[key]
                self.entry[key] = value
                self.save_catalog()
                with self.assertRaisesRegex(ValueError, "Catalog " + key):
                    self.check()
                self.entry[key] = original
        self.save_catalog()

    def test_missing_evidence_and_wrong_software_stop(self):
        evidence = json.loads(self.evidence_path.read_text())
        record = evidence["packages"][-1]
        record["software"]["scope"] = "system"
        self.evidence_path.write_text(json.dumps(evidence))
        with self.assertRaisesRegex(ValueError, "software scope"):
            self.check()
        record["digest"] = "sha256:" + "0" * 64
        self.evidence_path.write_text(json.dumps(evidence))
        with self.assertRaisesRegex(ValueError, "lacks approved evidence"):
            self.check()

    def test_modified_source_modes_and_public_wrong_bytes_stop(self):
        source = self.source / "install.sh"
        source.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "bytes/modes"):
            self.check()
        source.chmod(0o644)
        with mock.patch.object(release.catalog, "_open", return_value=io.BytesIO(b"wrong")):
            with self.assertRaisesRegex(ValueError, "Public asset size"):
                self.check(public=True)

    def test_existing_tag_with_different_bytes_blocks_release(self):
        readme = self.source / "README.md"
        readme.write_bytes(b"older released bytes")
        subprocess.run(["git", "add", "test-game"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.name=Release Test", "-c", "user.email=test@example.invalid",
                        "commit", "-qm", "Fixture"],
                       cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "tag", "test-game-1.0.0"], cwd=self.repo, check=True, capture_output=True)
        readme.write_bytes(self.files["README.md"])
        with self.assertRaisesRegex(ValueError, "differs from its tag"):
            self.check()
