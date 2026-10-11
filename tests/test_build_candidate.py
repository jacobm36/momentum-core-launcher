"""Selected acceptance bundles preserve exact snapshots and reject missing evidence."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
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

    def build(self, *selected):
        args = [str(self.output), "--package-repo", str(self.repo)]
        for game in selected:
            args.extend(["--package", game])
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(
                builder.subprocess, "check_output",
                side_effect=[b"README.md\0launch.sh\0", "a" * 40]):
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
            self.assertIn("public publication is blocked", guide)
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
