"""Selected acceptance bundles preserve exact snapshots and reject missing evidence."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest import mock
import zipfile

from tests.test_packages import manifest, package_files, write_zip

spec = importlib.util.spec_from_file_location("candidate_build",
                                             Path(__file__).parents[1] / "tools/build-candidate.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class CandidateBuild(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "package-repo"
        (self.repo / "dist").mkdir(parents=True)
        self.output = self.root / "acceptance.zip"
        for game in ("quake-slave-zero-x", "the-house-of-the-dead-2", "brutal-doom", "marvel-infinity-war"):
            version = builder.PRIVATE_CANDIDATES[game]
            files = package_files(manifest(id=game, version=version, destination_name=game))
            write_zip(self.repo / "dist" / f"{game}-{version}.zip", files)

    def build(self, *selected, options=()):
        args = [str(self.output), "--package-repo", str(self.repo), *options]
        for game in selected:
            args.extend(["--package", game])
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(
                builder.subprocess, "check_output",
                side_effect=(["a" * 40] if "--runtime-only" in options
                             else [b"README.md\0launch.sh\0", "a" * 40])):
            builder.main(args)

    def test_selected_three_snapshots_and_private_inventory(self):
        selected = ("quake-slave-zero-x", "the-house-of-the-dead-2", "brutal-doom")
        with mock.patch.object(builder.compatibility, "find_record", return_value={
            "installer_validated": True, "software": {"commit": "a" * 64}
        }) as evidence:
            self.build(*selected)
        self.assertEqual(evidence.call_count, 3)
        with zipfile.ZipFile(self.output) as bundle:
            delivery = json.loads(bundle.read("acceptance/candidate-build.json"))
            self.assertEqual(delivery["scope"], "private-acceptance-only")
            self.assertEqual([p["id"] for p in delivery["packages"]], list(selected))
            self.assertEqual(delivery["launcher_base_revision"], "a" * 40)
            guide = bundle.read("acceptance/ACCEPTANCE-GUIDE.txt").decode()
            self.assertIn("six approved public games", guide)
            self.assertEqual(delivery["delivery_profile"], "acceptance")
            self.assertIn("bash start-candidate.sh", guide)
            self.assertFalse(any(name.startswith(("acceptance/jobs/", "acceptance/media/"))
                                 or name == "acceptance/games.json" for name in bundle.namelist()))
            for entry in delivery["packages"]:
                intake = json.loads(bundle.read(
                    f"acceptance/packages/{entry['id']}/{entry['version']}/intake.json"))
                self.assertEqual(intake["digest"], entry["digest"])
                self.assertEqual(intake["source"], f"bundled:{entry['id']}-{entry['version']}.zip")

    def test_missing_evidence_creates_no_output(self):
        with mock.patch.object(builder.compatibility, "find_record", return_value=None):
            with self.assertRaisesRegex(ValueError, "No exact installer evidence"):
                self.build("brutal-doom")
        self.assertFalse(self.output.exists())

    def test_runtime_only_launcher_inventory_and_extracted_imports(self):
        with mock.patch.object(builder.compatibility, "find_record") as evidence:
            self.build(options=("--runtime-only", "--launcher-only"))
        evidence.assert_not_called()
        inventory = json.loads((builder.HERE / "tools/runtime-files.json").read_text())["files"]
        with zipfile.ZipFile(self.output) as bundle:
            delivery = json.loads(bundle.read("acceptance/candidate-build.json"))
            self.assertEqual(delivery["delivery_profile"], "runtime")
            self.assertEqual(delivery["packages"], [])
            self.assertEqual(set(delivery["launcher_file_sha256"]), set(inventory))
            self.assertEqual(set(bundle.namelist()),
                             {f"acceptance/{name}" for name in inventory}
                             | {"acceptance/ACCEPTANCE-GUIDE.txt", "acceptance/candidate-build.json"})
            for name, digest in delivery["launcher_file_sha256"].items():
                self.assertEqual(hashlib.sha256(bundle.read(f"acceptance/{name}")).hexdigest(), digest)
            self.assertTrue(all(not name.startswith(("tests/", "tools/", ".github/"))
                                for name in inventory))
            self.assertNotIn("docs/acceptance-history.md", inventory)
            extracted = self.root / "extracted"
            bundle.extractall(extracted)
        modules = [Path(name).stem for name in inventory if "/" not in name and name.endswith(".py")]
        result = subprocess.run([sys.executable, "-c",
                                 "import importlib; " +
                                 "; ".join(f"importlib.import_module({name!r})" for name in modules)],
                                cwd=extracted / "acceptance", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_runtime_inventory_covers_modules_assets_and_exact_evidence(self):
        inventory = set(json.loads((builder.HERE / "tools/runtime-files.json").read_text())["files"])
        required = {p.relative_to(builder.HERE).as_posix() for pattern in
                    ("*.py", "web/*", "docs/*.json") for p in builder.HERE.glob(pattern) if p.is_file()}
        required.discard("cleanup_shortcuts.py")
        self.assertLessEqual(required, inventory)

    def test_runtime_only_still_requires_selected_package_evidence(self):
        with mock.patch.object(builder.compatibility, "find_record", return_value=None):
            with self.assertRaisesRegex(ValueError, "No exact installer evidence"):
                self.build("brutal-doom", options=("--runtime-only",))
        self.assertFalse(self.output.exists())

    def test_launcher_only_rejects_package_selection(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.build("brutal-doom", options=("--launcher-only",))
        self.assertFalse(self.output.exists())

    def test_openbor_only_bundle_has_focused_isolated_instructions(self):
        with mock.patch.object(builder.compatibility, "find_record", return_value={
            "installer_validated": True, "software": {"version": "6391"}
        }):
            self.build("marvel-infinity-war")
        with zipfile.ZipFile(self.output) as bundle:
            inventory = json.loads(bundle.read("acceptance/candidate-build.json"))
            self.assertEqual([p["id"] for p in inventory["packages"]], ["marvel-infinity-war"])
            guide = bundle.read("acceptance/ACCEPTANCE-GUIDE.txt").decode()
            self.assertIn("bash start-isolated-test.sh", guide)
            self.assertIn("offline", guide)
            self.assertIn("No upstream executable", guide)
            self.assertNotIn("Allow at least 6 GiB for Flycast", guide)

    def test_renamed_archive_with_wrong_identity_rejected(self):
        version = builder.PRIVATE_CANDIDATES["brutal-doom"]
        write_zip(self.repo / "dist" / f"brutal-doom-{version}.zip", package_files())
        with self.assertRaisesRegex(ValueError, "Archive identity differs"):
            self.build("brutal-doom")
        self.assertFalse(self.output.exists())

    def test_duplicate_and_existing_output_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.build("brutal-doom", "brutal-doom")
            self.output.write_bytes(b"existing delivery")
            with self.assertRaises(SystemExit):
                self.build("brutal-doom")
        self.assertEqual(self.output.read_bytes(), b"existing delivery")

    def test_failed_archive_write_does_not_leave_partial_delivery(self):
        with mock.patch.object(builder.compatibility, "find_record", return_value={
            "installer_validated": True, "software": {}
        }), mock.patch.object(builder.zipfile.ZipFile, "write", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.build("brutal-doom")
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".momentum-candidate-*")), [])
