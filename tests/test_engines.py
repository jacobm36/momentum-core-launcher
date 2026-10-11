"""Read-only shared selection; no emulator or package installation."""
import copy
import json
from pathlib import Path
import unittest
from unittest import mock

import dependencies
import engines
import installs
import uzdoom
from tests import test_installs


def facts(scope="user", commit="a" * 64):
    return {"installed": True, "provider": "flatpak", "scope": scope,
            "app_id": "test.Engine", "version": "1.0", "commit": commit,
            "launch_argv": ["flatpak", "run", "--" + scope, "test.Engine"]}


class SelectionTests(unittest.TestCase):
    def test_preferred_supported_avoids_extra_probes(self):
        preferred = facts()
        discover = mock.Mock()
        build = {"provider": "flatpak", "scope": "user", "version": "1.0", "commit": "a" * 64}
        selected = engines.select(preferred, [build], discover)
        self.assertIs(selected.facts, preferred)
        discover.assert_not_called()

    def test_supported_system_copy_beats_untested_user_and_is_not_mutated(self):
        user, system = facts(commit="b" * 64), facts("system")
        before = copy.deepcopy([user, system])
        build = {"provider": "flatpak", "scope": "user", "version": "1.0", "commit": "a" * 64}
        selected = engines.select(user, [build], lambda: [user, system])
        self.assertIs(selected.facts, system)
        self.assertEqual(selected.status, "supported")
        self.assertEqual([user, system], before)
        self.assertEqual(len(selected.details()["candidates"]), 2)

    def test_no_supported_copy_is_untested_not_broken(self):
        selected = engines.select(facts(), [{"version": "2.0"}], lambda: [facts("system")])
        self.assertEqual(selected.status, "untested")
        self.assertEqual(selected.facts["scope"], "user")
        self.assertEqual(engines.select({"installed": False}, [{"version": "1.0"}]).status, "missing")

    def test_provider_and_version_must_match_no_native_scope_exemption(self):
        for build in ({"version": "2.0"}, {"provider": "native"},
                      {"provider": "native", "scope": "user"}):
            self.assertFalse(engines.matches(facts("system"), build))
        with self.assertRaises(ValueError):
            engines.select(facts(), [])

    def test_discovery_failures_are_explicit(self):
        with self.assertRaisesRegex(dependencies.DependencyError, "permission denied"):
            engines.select(facts(), [{"version": "2.0"}],
                           mock.Mock(side_effect=dependencies.DependencyError("permission denied")))

    def test_both_adapters_discover_default_scopes_without_writes(self):
        for adapter in (dependencies, uzdoom):
            with self.subTest(adapter=adapter.__name__), mock.patch.object(
                    adapter, "_detect", side_effect=[facts(), facts("system")]) as detect:
                self.assertEqual(len(adapter.discover()), 2)
                self.assertEqual(detect.call_args_list,
                                 [mock.call(("user",)), mock.call(("system",))])


class InstallerSelectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_installs.InstallsTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root, self.inst = self.fixture.root, self.fixture.inst

    def test_flycast_supported_system_selected_and_all_builds_reported(self):
        snapshot = self.root / "snapshot"
        snapshot.mkdir()
        (snapshot / "package.json").write_text(json.dumps({"requires": [{
            "id": "flycast", "provider": "flatpak", "scope": "user", "app_id": dependencies.APP}]}))
        evidence = json.loads((Path(installs.__file__).parent / "docs/hod2-target-evidence.json").read_text())
        revision = evidence["derived_packages"][0]
        user = {"installed": True, "scope": "user", "version": "v2.7", "commit": "a" * 64}
        system = dict(user, scope="system", commit=evidence["emulator_commit"])
        with mock.patch("packages.snapshot_path", return_value=snapshot), \
                mock.patch("packages.check", return_value={"digest": revision["digest"], "platform_issues": []}), \
                mock.patch.object(self.inst, "_flycast_facts", return_value=user), \
                mock.patch("dependencies.discover", return_value=[user, system]):
            detail = self.inst.package_details("the-house-of-the-dead-2", revision["version"])
        self.assertTrue(detail["install_enabled"])
        self.assertEqual(detail["dependencies"]["flycast"]["scope"], "system")
        self.assertEqual(len(detail["engine_selection"]["flycast"]["supported_builds"]), 2)

    def test_uzdoom_supported_system_selected_with_selected_host_checks(self):
        snapshot = self.root / "snapshot"
        snapshot.mkdir()
        (snapshot / "package.json").write_text(json.dumps({"requires": [{
            "id": "uzdoom", "provider": "flatpak", "scope": "user", "source": "flathub",
            "app_id": uzdoom.APP, "tested_version": "5.0.1"}]}))
        record = next(r for r in installs.compatibility.records(Path(installs.__file__).parent)
                      if r["id"] == "brutal-doom" and r["version"] == "0.2.0")
        user = dict(record["software"], installed=True, scope="user", commit="a" * 64)
        system = dict(record["software"], installed=True, scope="system")
        with mock.patch("packages.snapshot_path", return_value=snapshot), \
                mock.patch("packages.check", return_value={"digest": record["digest"], "platform_issues": []}), \
                mock.patch("uzdoom.detect", return_value=user), \
                mock.patch("uzdoom.discover", return_value=[user, system]), \
                mock.patch("uzdoom.check_host", return_value={"metadata_checked": True}) as host:
            detail = self.inst.package_details("brutal-doom", "0.2.0")
        self.assertTrue(detail["install_enabled"])
        self.assertEqual(detail["dependencies"]["uzdoom"]["scope"], "system")
        self.assertEqual(host.call_args.args[0]["scope"], "system")

    def test_approval_refuses_a_new_selection_after_plan_review(self):
        for runtime in ("flycast", "uzdoom"):
            with self.subTest(runtime=runtime):
                job, _ = self.fixture.fixture()
                job.update(status="awaiting-approval", plan_digest="test-digest")
                job["meta"]["install_enabled"] = True
                original = facts("system")
                job["steps"][-1]["context"]["dependencies"] = {runtime: original}
                detail = {"install_enabled": True, "digest": job["meta"]["package_digest"],
                          "dependencies": {runtime: facts("user")}}
                with mock.patch.object(self.inst, "package_details", return_value=detail), \
                        mock.patch.object(self.fixture.jobs, "approve", create=True) as approve:
                    self.assertIn("Selected engine installation changed",
                                  self.inst.approve(job["id"], "test-digest"))
                    approve.assert_not_called()
