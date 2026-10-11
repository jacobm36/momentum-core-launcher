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
import catalog
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

    def test_folder_picker_route_requires_token_and_returns_cancel_or_error(self):
        with mock.patch("picker.choose_directory", return_value=str(self.t)) as choose:
            self.assertEqual(self.request("/api/picker/directory", {"initial": str(self.t)}),
                             (200, {"path": str(self.t)}))
            choose.assert_called_once_with(str(self.t))
            req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/picker/directory", b"{}")
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(req)
            self.assertEqual(error.exception.code, 403)
            self.assertEqual(choose.call_count, 1)
        with mock.patch("picker.choose_directory", return_value=None):
            self.assertEqual(self.request("/api/picker/directory", {}), (200, {"path": None}))
        with mock.patch("picker.choose_directory", side_effect=server.picker.PickerError("No desktop picker")):
            self.assertEqual(self.request("/api/picker/directory", {}), (400, {"error": "No desktop picker"}))

    def test_installed_game_import_reviews_selection_and_preserves_concurrent_edits(self):
        apps = self.t / "shortcuts"
        apps.mkdir()
        shortcut = apps / "my-game.desktop"
        shortcut.write_text("[Desktop Entry]\nName=My Game\nExec=steam steam://rungameid/123\nCategories=Game;\n")
        second = apps / "other.desktop"
        second.write_text("[Desktop Entry]\nName=Other Game\nExec=/other/game\nCategories=Game;\n")
        with mock.patch("game_import.applications", return_value=apps):
            status, scan = self.request("/api/library/discover", {})
            self.assertEqual(status, 200, scan)
            self.assertFalse((self.app / "games.json").exists())
            candidate = next(c for c in scan["candidates"] if c["source"] == shortcut.name)
            selection = [{"source": candidate["source"], "sha256": candidate["sha256"]}]
            status, result = self.request("/api/library/import", {"selection": selection})
            self.assertEqual(status, 200, result)
            self.assertEqual(len(result["added"]), 1)
            games = json.loads((self.app / "games.json").read_text())
            self.assertEqual([g["id"] for g in games], ["my-game"])
            games[0].update(exec="my edited command", favorite=True)
            (self.app / "games.json").write_text(json.dumps(games))
            status, result = self.request("/api/library/import", {"selection": selection})
            self.assertEqual(status, 200, result)
            self.assertFalse(result["added"])
            self.assertEqual(len(result["skipped"]), 1)
            self.assertEqual(json.loads((self.app / "games.json").read_text()), games)
            shortcut.write_text(shortcut.read_text().replace("rungameid/123", "rungameid/456"))
            self.assertEqual(self.request("/api/library/import", {"selection": selection})[0], 400)
            self.assertEqual(json.loads((self.app / "games.json").read_text()), games)
            self.assertFalse(self.runner.list())

    def test_installed_game_import_requires_token_and_rejects_unreviewed_input(self):
        for path in ("/api/library/discover", "/api/library/import"):
            request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", b"{}")
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 403)
        with mock.patch("game_import.discover", return_value={"candidates": []}):
            for data in ({}, {"selection": [{"source": "/arbitrary/file", "sha256": "0" * 64}]}, []):
                self.assertEqual(self.request("/api/library/import", data)[0], 400)
        with mock.patch("game_import.discover", side_effect=OSError("cannot read shortcuts")):
            self.assertEqual(self.request("/api/library/discover", {}),
                             (400, {"error": "cannot read shortcuts"}))
        self.assertFalse((self.app / "games.json").exists())

    def test_zip_import_details_no_execution_and_corrupt_upload(self):
        data = self.upload()
        self.assertEqual(data["id"], "test-game")
        status, detail = self.request("/api/packages/test-game/1.0.0")
        self.assertEqual(status, 200)
        self.assertEqual(detail["digest"], data["digest"])
        self.assertEqual(detail["manifest"]["inputs"], manifest()["inputs"])
        self.assertFalse(self.runner.list())
        self.assertEqual(self.request("/api/packages/import-upload", b"not a zip", raw=True)[0], 400)

    def test_catalog_and_download_routes_are_game_focused_and_token_protected(self):
        with mock.patch("catalog.load", return_value={"catalog_version": 1, "games": []}):
            self.assertEqual(self.request("/api/catalog"), (200, {"catalog_version": 1, "games": []}))
        with mock.patch("catalog.load", side_effect=catalog.CatalogError("offline")):
            self.assertEqual(self.request("/api/catalog"), (502, {"error": "offline"}))
        with mock.patch("catalog.submit", return_value="j00000001") as submit:
            status, data = self.request("/api/packages/download", {"id": "the-house-of-the-dead-2"})
            self.assertEqual((status, data), (200, {"id": "j00000001"}))
            submit.assert_called_once_with(self.app, self.runner, "the-house-of-the-dead-2")
            req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/packages/download",
                                         json.dumps({"id": "the-house-of-the-dead-2"}).encode())
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(req)
            self.assertEqual(error.exception.code, 403)
            self.assertEqual(submit.call_count, 1)

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
        self.assertIn("launcher update", detail["approval_blocked"])
        self.assertEqual(detail["compatibility"]["reason"], "missing-evidence")
        status, failure = self.request(f"/api/jobs/{jid}/approve", {"plan_digest": detail["plan_digest"]})
        self.assertEqual(status, 409)
        self.assertIn("launcher update", failure["error"])
        self.assertFalse((self.app / "jobs" / jid / "approved-plan.json").exists())
        self.assertFalse(self.catalog)
        self.assertEqual(self.request(f"/api/jobs/{jid}/cancel", {})[0], 200)

    def test_blocked_prerequisite_commands_survive_job_restart(self):
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
        prerequisites = [{"title": "FUSE2 missing", "commands": [
            ["sudo", "apt", "update"], ["sudo", "apt", "install", "-y", "libfuse2t64"]]}]
        with self.runner.lock:
            job = self.runner.jobs[jid]
            job["meta"].update(engine_selection={"flycast": {"status": "untested",
                                "candidates": [{"scope": "user"}, {"scope": "system"}]}},
                               host_prerequisites=prerequisites, compatibility={
                "reason": "host-prerequisites", "title": "Action required",
                "message": "Install the system prerequisites."})
            self.runner._save(job)
        self.runner.close()
        self.runner = jobs.Jobs(self.app / "jobs")
        self.inst.jobs = self.runner
        server.JOBS = self.runner
        status, detail = self.request(f"/api/jobs/{jid}")
        self.assertEqual(status, 200)
        self.assertEqual(detail["host_prerequisites"], prerequisites)
        self.assertEqual(detail["compatibility"]["reason"], "host-prerequisites")
        self.assertEqual(len(detail["engine_selection"]["flycast"]["candidates"]), 2)
        self.assertTrue(detail["approval_blocked"])
        self.assertFalse((self.app / "jobs" / jid / "approved-plan.json").exists())

    def test_existing_installation_keeps_recorded_folder(self):
        data = self.upload()
        old = self.t / "Games" / "Old Name, The (USA)"
        prev = {"game_directory": str(old), "paths": self.inst._defaults_path("test-game"), "catalog": {}}
        with mock.patch.object(self.inst, "_load_receipt", return_value=prev):
            status, reply = self.request("/api/packages/install", {
                "id": data["id"], "version": data["version"], "trusted_digest": data["digest"],
                "inputs": {"source_dir": str(self.t), "games_root": str(self.t / "Elsewhere")}})
        self.assertEqual(status, 200, reply)
        jid = reply["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self.runner.get(jid)["status"] in jobs.RUNNING:
            time.sleep(.02)
        status, detail = self.request(f"/api/jobs/{jid}")
        self.assertEqual(detail["plan"]["game_directory"], str(old))
        context = self.runner.jobs[jid]["steps"][0]["context"]
        self.assertEqual(context["inputs"]["games_root"], str(old.parent))
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
        discovery = mock.patch("dependencies.discover", return_value=[])
        discovery.start()
        self.addCleanup(discovery.stop)
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
                                        (evidence["package_id"], "99.0.0")):
                with self.subTest(package_id=package_id, version=version):
                    self.assertFalse(self.inst.package_details(package_id, version)["install_enabled"])
            for revision in evidence["derived_packages"]:
                summary["digest"] = revision["digest"]
                self.assertTrue(self.inst.package_details(evidence["package_id"], revision["version"])["install_enabled"])
                self.assertFalse(self.inst.package_details(evidence["package_id"], evidence["package_version"])["install_enabled"])
            summary["digest"] = evidence["package_digest"]
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

    def test_reconcile_install_endpoint_is_explicit(self):
        with mock.patch.object(self.inst, "reconcile_install", return_value=True) as reconcile:
            self.assertEqual(self.request("/api/jobs/j12345678/reconcile", {})[0], 400)
            status, response = self.request("/api/jobs/j12345678/reconcile", {"missing_user_state": []})
        self.assertEqual((status, response), (200, {"status": "reconcile"}))
        reconcile.assert_called_once_with("j12345678", expected_missing=[])

    def test_recovery_preview_is_read_only_and_unknown_job_is_reported(self):
        self.assertEqual(self.request("/api/jobs/j12345678/recovery")[0], 404)
        data = self.upload()
        jid = self.inst.submit_install(data["id"], data["version"], str(self.t), trusted_digest=data["digest"])
        with mock.patch.object(self.inst, "recovery_details", return_value={"eligible": False}) as preview:
            self.assertEqual(self.request(f"/api/jobs/{jid}/recovery"), (200, {"eligible": False}))
            preview.assert_called_once_with(jid)

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
                mock.patch("dependencies.subprocess.run", side_effect=[apps, remotes, probe]) as run:
            facts = installs.Installs._flycast_facts({"provider": "flatpak", "scope": "user",
                                                    "app_id": "org.flycast.Flycast"})
        self.assertTrue(facts["installed"])
        self.assertFalse(facts["capabilities_checked"])
        self.assertEqual(facts["version"], "v2.7")
        self.assertEqual(run.call_args_list[1].args[0], ["flatpak", "remotes", "--user", "--columns=name,url"])
