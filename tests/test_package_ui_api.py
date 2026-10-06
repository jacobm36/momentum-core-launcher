"""Local package UI API tests; all media, jobs, uploads and catalogs are temporary."""
import io
import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tests.test_packages import Base, manifest, package_files
import installs
import jobs
import server


PREFLIGHT = b"""#!/bin/bash
exec python3 - "$@" <<'PY'
import json, pathlib, sys
c = json.loads(pathlib.Path(sys.argv[sys.argv.index('--context') + 1]).read_text())
assert c['phase'] == 'preflight'
plan = {'game_directory': c['game_directory'], 'actions': [], 'dependencies': c['dependencies']}
r = {'outcome': 'succeeded', 'phase': 'preflight', 'plan': plan}
pathlib.Path(c['result_file']).write_text(json.dumps(r))
print(json.dumps({'event_version': 1, 'type': 'result', 'message': 'Preview', 'outcome': 'succeeded'}))
PY
"""


class PackageUiApi(Base):
    def setUp(self):
        super().setUp()
        self.catalog = []
        self.runner = jobs.Jobs(self.app / "jobs")
        self.inst = installs.Installs(self.app, threading.Lock(), lambda: self.catalog,
                                     lambda gs: self.catalog.extend(gs), self.runner)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.http.server_port
        self.patches = [
            mock.patch.object(server, "HERE", self.app),
            mock.patch.object(server, "PORT", self.port),
            mock.patch.object(server, "JOBS", self.runner),
            mock.patch.object(server, "INSTALLS", self.inst),
            mock.patch("packages._platform_issues", return_value=[]),
            mock.patch.object(self.inst, "_load_receipt", return_value=None),
            mock.patch.object(self.inst, "_flycast_facts", return_value={"flycast": False}),
        ]
        for p in self.patches:
            p.start()
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.runner.close()
        for p in reversed(self.patches):
            p.stop()
        super().tearDown()

    def request(self, path, data=None, raw=False):
        body = data if raw else json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", body,
                                     headers={"X-Token": server.TOKEN})
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as e:
            response = e
        with response:
            return response.status, json.loads(response.read())

    def upload(self):
        stream = io.BytesIO()
        files = package_files(extra={"install.sh": PREFLIGHT})
        with zipfile.ZipFile(stream, "w") as z:
            for name, data in files.items():
                z.writestr(name, data)
        status, data = self.request("/api/packages/import-upload", stream.getvalue(), raw=True)
        self.assertEqual(status, 200, data)
        return data

    def test_zip_import_details_no_execution_and_corrupt_upload(self):
        data = self.upload()
        self.assertEqual(data["id"], "test-game")
        status, detail = self.request("/api/packages/test-game/1.0.0")
        self.assertEqual(status, 200)
        self.assertEqual(detail["digest"], data["digest"])
        self.assertEqual(detail["manifest"]["inputs"], manifest()["inputs"])
        self.assertFalse(self.runner.list())
        self.assertEqual(self.request("/api/packages/import-upload", b"not a zip", raw=True)[0], 400)

    def test_trust_and_platform_are_enforced_before_scripts(self):
        data = self.upload()
        args = {"id": "test-game", "version": "1.0.0", "inputs": {
            "source_dir": str(self.t), "games_root": str(self.t / "Games")}}
        self.assertEqual(self.request("/api/packages/install", args)[0], 400)
        args["trusted_digest"] = "sha256:" + "0" * 64
        self.assertEqual(self.request("/api/packages/install", args)[0], 400)
        args["trusted_digest"] = data["digest"]
        with mock.patch("packages._platform_issues", return_value=["Wrong architecture"]):
            self.assertEqual(self.request("/api/packages/install", args)[0], 400)
        self.assertFalse(self.runner.list())

    def test_preflight_review_and_apply_gate_survive_reopening(self):
        data = self.upload()
        status, reply = self.request("/api/packages/install", {
            "id": data["id"], "version": data["version"], "trusted_digest": data["digest"],
            "inputs": {"source_dir": str(self.t), "games_root": str(self.t / "Games")}})
        self.assertEqual(status, 200, reply)
        jid = reply["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self.runner.get(jid)["status"] in jobs.RUNNING:
            time.sleep(.02)
        self.assertEqual(self.runner.get(jid)["status"], "awaiting-approval")
        self.runner.close()
        self.runner = jobs.Jobs(self.app / "jobs")
        self.inst.jobs = self.runner
        server.JOBS = self.runner
        status, detail = self.request(f"/api/jobs/{jid}")
        self.assertEqual(detail["plan"]["game_directory"], str(self.t / "Games" / "Test Game (USA)"))
        self.assertIn("matching target evidence", detail["approval_blocked"])
        status, failure = self.request(f"/api/jobs/{jid}/approve", {"plan_digest": detail["plan_digest"]})
        self.assertEqual(status, 409)
        self.assertIn("capability", failure["error"])
        self.assertFalse((self.app / "jobs" / jid / "approved-plan.json").exists())
        self.assertFalse(self.catalog)
        self.assertEqual(self.request(f"/api/jobs/{jid}/cancel", {})[0], 200)

    def test_input_and_association_validation(self):
        data = self.upload()
        args = {"id": data["id"], "version": data["version"], "trusted_digest": data["digest"],
                "inputs": {"source_dir": str(self.t), "games_root": "relative"}}
        self.assertEqual(self.request("/api/packages/install", args)[0], 400)
        args["inputs"]["games_root"] = str(self.t / "Games")
        args["catalog_entry_id"] = "missing"
        self.assertEqual(self.request("/api/packages/install", args)[0], 400)
        self.assertFalse(self.runner.list())

    def test_target_evidence_enables_only_matching_package_digest_and_emulator_commit(self):
        evidence_path = Path(server.__file__).parent / "docs/hod2-target-evidence.json"
        evidence = json.loads(evidence_path.read_text())
        snapshot = self.t / "evidence-snapshot"
        snapshot.mkdir()
        man = manifest(id=evidence["package_id"], version=evidence["package_version"])
        (snapshot / "package.json").write_text(json.dumps(man))
        summary = {"id": evidence["package_id"], "version": evidence["package_version"],
                   "digest": evidence["package_digest"], "platform_issues": []}
        flycast = {"installed": True, "version": evidence["emulator_version"],
                   "commit": evidence["emulator_commit"], "capabilities_checked": False}
        with mock.patch("packages.snapshot_path", return_value=snapshot), \
                mock.patch("packages.check", return_value=summary), \
                mock.patch.object(self.inst, "_flycast_facts", side_effect=lambda req: dict(flycast)):
            detail = self.inst.package_details(evidence["package_id"], evidence["package_version"])
            self.assertTrue(detail["install_enabled"])
            self.assertTrue(detail["dependencies"]["flycast"]["capabilities_checked"])
            for key, value in (("installed", False), ("version", "untested-version"),
                               ("commit", "a-different-build"), ("commit", None)):
                with self.subTest(key=key, value=value):
                    previous = flycast[key]
                    flycast[key] = value
                    detail = self.inst.package_details(evidence["package_id"], evidence["package_version"])
                    self.assertFalse(detail["install_enabled"])
                    self.assertFalse(detail["dependencies"]["flycast"]["capabilities_checked"])
                    flycast[key] = previous
            for package_id, version in (("untested-game", evidence["package_version"]),
                                        (evidence["package_id"], "0.1.2")):
                with self.subTest(package_id=package_id, version=version):
                    self.assertFalse(self.inst.package_details(package_id, version)["install_enabled"])
            summary["platform_issues"] = ["Unsupported platform"]
            self.assertFalse(self.inst.package_details(evidence["package_id"], evidence["package_version"])["install_enabled"])
            summary["platform_issues"] = []
            summary["digest"] = "sha256:" + "0" * 64
            self.assertFalse(self.inst.package_details(evidence["package_id"], evidence["package_version"])["install_enabled"])

    def test_pending_catalog_marker_is_retained_and_blocks_dismissal_and_new_work(self):
        data = self.upload()
        args = {"id": data["id"], "version": data["version"], "trusted_digest": data["digest"],
                "inputs": {"source_dir": str(self.t), "games_root": str(self.t / "Games")}}
        status, response = self.request("/api/packages/install", args)
        self.assertEqual(status, 200)
        jid = response["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self.runner.get(jid)["status"] in jobs.RUNNING:
            time.sleep(.02)
        marker = self.runner.paths(jid)["job_dir"] / "catalog-pending.json"
        marker.write_text('{"retained":"recovery evidence"}')
        self.inst.recover_pending_catalog()
        self.assertEqual(marker.read_text(), '{"retained":"recovery evidence"}')
        self.assertTrue(self.runner.get(jid)["manual"])
        self.assertEqual(self.request(f"/api/jobs/{jid}/dismiss", {})[0], 409)
        self.assertEqual(self.request("/api/packages/install", args)[0], 400)

    def test_duplicate_work_and_changed_plan_are_not_silently_accepted(self):
        data = self.upload()
        args = {"id": data["id"], "version": data["version"], "trusted_digest": data["digest"],
                "inputs": {"source_dir": str(self.t), "games_root": str(self.t / "Games")}}
        status, response = self.request("/api/packages/install", args)
        self.assertEqual(status, 200)
        self.assertEqual(self.request("/api/packages/install", args)[0], 400)
        jid = response["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self.runner.get(jid)["status"] in jobs.RUNNING:
            time.sleep(.02)
        (self.runner.paths(jid)["results_dir"] / "step-0.json").write_text('{"plan":"changed"}')
        status, detail = self.request(f"/api/jobs/{jid}")
        self.assertEqual(status, 200)
        self.assertIn("digest mismatch", detail["plan_error"])

    def test_dependency_job_approval_to_observed_result_uses_temporary_flatpak_only(self):
        bin_dir, state = self.t / "bin", self.t / "flatpak-state.json"
        bin_dir.mkdir()
        tool = bin_dir / "flatpak"
        tool.write_text(f"""#!{sys.executable}
import json, pathlib, sys
state = pathlib.Path({str(state)!r})
current = json.loads(state.read_text()) if state.exists() else {{'remote': False, 'installed': False}}
command = sys.argv[1]
if command == 'remotes':
    if current['remote']: print('flathub\\thttps://dl.flathub.org/repo/')
elif command == 'list':
    if current['installed']: print('org.flycast.Flycast')
elif command == 'info':
    print('    Version: mock-1\\n    Commit: mock-commit')
elif command == 'remote-add':
    current['remote'] = True
    state.write_text(json.dumps(current))
elif command == 'install':
    assert '--user' in sys.argv and '--noninteractive' in sys.argv
    current['installed'] = True
    state.write_text(json.dumps(current))
else:
    sys.exit(1)
""")
        tool.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}):
            status, response = self.request("/api/dependencies/flycast/prepare", {})
            self.assertEqual(status, 200, response)
            jid = response["id"]
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and self.runner.get(jid)["status"] in jobs.RUNNING:
                time.sleep(.02)
            status, detail = self.request(f"/api/jobs/{jid}")
            self.assertEqual(detail["status"], "awaiting-approval", detail)
            self.assertNotIn("approval_blocked", detail)
            self.assertEqual(len(detail["plan"]["dependency_commands"]), 2)
            self.assertFalse(state.exists())  # preview never installs or configures anything
            self.assertEqual(self.request(f"/api/jobs/{jid}/approve",
                                         {"plan_digest": detail["plan_digest"]})[0], 200)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and self.runner.get(jid)["status"] in jobs.RUNNING:
                time.sleep(.02)
            status, result = self.request(f"/api/jobs/{jid}")
        self.assertEqual(result["status"], "succeeded", result)
        observed = result["dependency_result"]
        self.assertEqual(len(observed["completed_transactions"]), 2)
        self.assertTrue(observed["dependencies"]["flycast"]["installed"])
        self.assertFalse(observed["dependencies"]["flycast"]["capabilities_checked"])
        self.assertEqual(observed["dependencies"]["flycast"]["version"], "mock-1")
        self.assertFalse(self.catalog)
        self.assertTrue((self.runner.paths(jid)["job_dir"] / "dependency-transactions.json").exists())

    def test_uncertain_dependency_journal_survives_reopening_and_blocks_new_jobs(self):
        jid = self.runner.submit("Dependency recovery", [{"name": "no-op", "argv": ["true"]}],
                                 meta={"kind": "dependency"})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self.runner.get(jid)["status"] in jobs.RUNNING:
            time.sleep(.02)
        ledger = self.runner.paths(jid)["job_dir"] / "dependency-transactions.json"
        ledger.write_text(json.dumps({"job_id": jid, "completed": [], "active_command": ["flatpak", "install"]}))
        self.runner.close()
        self.runner = jobs.Jobs(self.app / "jobs")
        self.inst.jobs = self.runner
        server.JOBS = self.runner
        self.assertTrue(self.runner.get(jid)["manual"])
        self.assertTrue(ledger.exists())
        self.assertEqual(self.request(f"/api/jobs/{jid}/dismiss", {})[0], 409)
        self.assertEqual(self.request("/api/dependencies/flycast/prepare", {})[0], 400)


class DependencyFacts(unittest.TestCase):
    def test_installed_is_not_capability_evidence_and_version_has_indent(self):
        probe = mock.Mock(returncode=0, stdout="    Version: v2.7\n", stderr="")
        remotes = mock.Mock(returncode=0, stdout="flathub\thttps://dl.flathub.org/repo/\n", stderr="")
        apps = mock.Mock(returncode=0, stdout="org.flycast.Flycast\n", stderr="")
        with mock.patch("dependencies.shutil.which", return_value="/mock/flatpak"), \
                mock.patch("dependencies.subprocess.run", side_effect=[remotes, apps, probe]) as run:
            facts = installs.Installs._flycast_facts({"provider": "flatpak", "scope": "user",
                                                    "app_id": "org.flycast.Flycast"})
        self.assertTrue(facts["installed"])
        self.assertFalse(facts["capabilities_checked"])
        self.assertEqual(facts["version"], "v2.7")
        self.assertEqual(run.call_args_list[0].args[0], ["flatpak", "remotes", "--user", "--columns=name,url"])
