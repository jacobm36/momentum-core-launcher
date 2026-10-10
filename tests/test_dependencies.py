"""No real Flatpak writes: resolver probes and transactions are mocked."""
import contextlib
import copy
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import dependencies


def facts(installed=False, remote=False, available=True):
    return {"provider": "flatpak", "scope": "user", "app_id": dependencies.APP,
            "flatpak_available": available, "installed": installed, "remote_present": remote,
            "version": "v2.7" if installed else None, "commit": "test-commit" if installed else None,
            "capabilities_checked": False, "launch_argv": ["flatpak", "run", "--user", dependencies.APP]}


class Detection(unittest.TestCase):
    def test_missing_flatpak_never_runs_commands(self):
        with mock.patch("dependencies.shutil.which", return_value=None), \
                mock.patch("dependencies.subprocess.run") as run:
            result = dependencies.detect()
        self.assertFalse(result["flatpak_available"])
        run.assert_not_called()

    def test_installed_version_commit_and_remote_are_read_only(self):
        responses = [dependencies.APP + "\n", "flathub\thttps://dl.flathub.org/repo/\n",
                     "   Version: v2.7\n Commit: abc123\n"]
        with mock.patch("dependencies.shutil.which", return_value="/usr/bin/flatpak"), \
                mock.patch("dependencies.probe", side_effect=responses) as probe:
            result = dependencies.detect()
        self.assertTrue(result["installed"])
        self.assertTrue(result["remote_present"])
        self.assertEqual(result["version"], "v2.7")
        self.assertEqual(result["commit"], "abc123")
        self.assertFalse(result["capabilities_checked"])
        self.assertEqual([call.args[:2] for call in probe.call_args_list],
                         [("list", "--user"), ("remotes", "--user"), ("info", "--user")])
        self.assertEqual(result["location"], "Flatpak (your user account)")

    def test_existing_system_wide_install_is_reused_in_place(self):
        responses = ["", dependencies.APP + "\n", "flathub\thttps://dl.flathub.org/repo/\n",
                     "   Version: v2.7\n Commit: abc123\n"]
        with mock.patch("dependencies.shutil.which", return_value="/usr/bin/flatpak"), \
                mock.patch("dependencies.probe", side_effect=responses) as probe:
            result = dependencies.detect()
        self.assertEqual(result["scope"], "system")
        self.assertTrue(result["installed"])
        self.assertEqual(result["launch_argv"], ["flatpak", "run", "--system", dependencies.APP])
        self.assertEqual(result["location"], "Flatpak (system-wide)")
        self.assertEqual([call.args[:2] for call in probe.call_args_list],
                         [("list", "--user"), ("list", "--system"), ("remotes", "--system"), ("info", "--system")])
        self.assertEqual(dependencies.make_plan(result)["dependency_commands"], [])

    def test_missing_everywhere_prepares_user_scope_only(self):
        with mock.patch("dependencies.shutil.which", return_value="/usr/bin/flatpak"), \
                mock.patch("dependencies.probe", side_effect=["", "", ""]):
            result = dependencies.detect()
        self.assertEqual(result["scope"], "user")
        self.assertFalse(result["installed"])
        for command in dependencies.commands_for(result):
            self.assertIn("--user", command)

    def test_unexpected_remote_is_not_silently_reused_or_replaced(self):
        with mock.patch("dependencies.shutil.which", return_value="flatpak"), \
                mock.patch("dependencies.probe", return_value="flathub\thttps://untrusted.example/repo/\n"):
            with self.assertRaisesRegex(dependencies.DependencyError, "unexpected URL"):
                dependencies.detect()

    def test_failed_probe_and_timeout_are_explicit(self):
        with mock.patch("dependencies.subprocess.run", return_value=mock.Mock(
                returncode=1, stdout="", stderr="permission denied")):
            with self.assertRaisesRegex(dependencies.DependencyError, "permission denied"):
                dependencies.probe("list", "--user")
        with mock.patch("dependencies.subprocess.run", side_effect=subprocess.TimeoutExpired("flatpak", 15)):
            with self.assertRaisesRegex(dependencies.DependencyError, "Cannot inspect"):
                dependencies.probe("list", "--user")

    def test_planning_no_upgrade_and_user_only_commands(self):
        self.assertEqual(dependencies.commands_for(facts(installed=True)), [])
        self.assertEqual(dependencies.commands_for(facts(available=False)), [])
        commands = dependencies.commands_for(facts())
        self.assertEqual(len(commands), 2)
        self.assertTrue(all("--user" in command for command in commands))
        self.assertIn("--noninteractive", commands[1])
        self.assertEqual(len(dependencies.commands_for(facts(remote=True))), 1)

    def test_package_evidence_pins_fresh_user_install_but_never_changes_existing_copy(self):
        target = "a" * 64
        commands = dependencies.commands_for(facts(remote=True), target, pin_fresh_install=True)
        self.assertEqual(commands, [
            ["flatpak", "install", "--user", "--noninteractive", "-y", "flathub", dependencies.APP],
            ["flatpak", "update", "--user", "--noninteractive", "-y", "--commit=" + target, dependencies.APP],
        ])
        self.assertEqual(dependencies.commands_for(facts(True, True), target), [])
        self.assertEqual(dependencies.commands_for(
            facts(True, True), target, pin_fresh_install=True), [
                ["flatpak", "update", "--user", "--noninteractive", "-y",
                 "--commit=" + target, dependencies.APP]])
        self.assertEqual(dependencies.commands_for(
            dict(facts(True, True), scope="system"), target, pin_fresh_install=True), [])
        with mock.patch("dependencies.probe", return_value=f"Commit: {target}\n") as probe:
            plan = dependencies.make_plan(facts(remote=True), target)
            existing_plan = dependencies.make_plan(facts(True, True), target)
        self.assertEqual(plan["target_commit"], target)
        self.assertEqual(len(plan["dependency_commands"]), 2)
        self.assertEqual(existing_plan["dependency_commands"], [])
        probe.assert_any_call("remote-info", "--user", "--commit=" + target,
                              "flathub", dependencies.APP)
        self.assertEqual(probe.call_count, 2)
        with mock.patch("dependencies.probe", return_value="Commit: " + "b" * 64 + "\n"):
            with self.assertRaisesRegex(dependencies.DependencyError, "did not confirm"):
                dependencies.make_plan(facts(remote=True), target)
        with self.assertRaisesRegex(dependencies.DependencyError, "Invalid"):
            dependencies.make_plan(facts(remote=True), "not-a-commit")


class Preparation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.context = {"job_id": "j12345678", "phase": "preflight",
                        "result_file": str(self.root / "result.json"),
                        "cancel_file": str(self.root / "cancel"), "approved_plan_digest": None}

    def tearDown(self):
        self.tmp.cleanup()

    def execute(self):
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
            code = dependencies.run(self.context)
        result = json.loads(Path(self.context["result_file"]).read_text())
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(events[-1]["outcome"], result["outcome"])
        return code, result

    def approve(self, observed):
        with mock.patch("dependencies.detect", return_value=observed):
            self.assertEqual(self.execute()[0], 0)
        raw = Path(self.context["result_file"]).read_bytes()
        path = self.root / "approved-plan.json"
        path.write_bytes(raw)
        self.context.update(phase="apply", approved_plan_file=str(path),
                            approved_plan_digest="sha256:" + hashlib.sha256(raw).hexdigest())

    def test_preflight_changes_nothing_and_requires_flatpak(self):
        with mock.patch("dependencies.detect", return_value=facts()), \
                mock.patch("dependencies.subprocess.run") as run:
            code, result = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(len(result["plan"]["dependency_commands"]), 2)
        run.assert_not_called()
        self.assertFalse((self.root / "dependency-transactions.json").exists())
        with mock.patch("dependencies.detect", return_value=facts(available=False)):
            code, result = self.execute()
        self.assertEqual(code, 20)
        self.assertIn("Ubuntu", result["message"])
        self.assertIn("sudo apt install flatpak", result["message"])

    def test_approved_missing_dependency_install_and_durable_command_intent(self):
        initial = facts(remote=True)
        self.approve(initial)

        def transaction(argv, **kwargs):
            journal = json.loads((self.root / "dependency-transactions.json").read_text())
            self.assertEqual(journal["active_command"], argv)
            self.assertNotIn("timeout", kwargs)
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            return mock.Mock(returncode=0)

        with mock.patch("dependencies.detect", side_effect=[initial, facts(True, True), facts(True, True)]), \
                mock.patch("dependencies.subprocess.run", side_effect=transaction) as run:
            code, result = self.execute()
        self.assertEqual(code, 0)
        self.assertTrue(result["dependencies"]["flycast"]["installed"])
        self.assertFalse(result["dependencies"]["flycast"]["capabilities_checked"])
        self.assertEqual(len(result["completed_transactions"]), 1)
        self.assertEqual(run.call_args.args[0][1], "install")
        self.assertIsNone(json.loads((self.root / "dependency-transactions.json").read_text())["active_command"])

    def test_evidence_pinned_install_uses_user_scope_and_checks_final_commit(self):
        target = "a" * 64
        self.context["target_commit"] = target
        initial, unpinned, pinned = facts(remote=True), facts(True, True), dict(facts(True, True), commit=target)
        with mock.patch("dependencies.detect", return_value=initial), \
                mock.patch("dependencies.probe", return_value=f"Commit: {target}\n"):
            self.assertEqual(self.execute()[0], 0)
        raw = Path(self.context["result_file"]).read_bytes()
        approval = self.root / "pinned-plan.json"
        approval.write_bytes(raw)
        self.context.update(phase="apply", approved_plan_file=str(approval),
                            approved_plan_digest="sha256:" + hashlib.sha256(raw).hexdigest())
        with mock.patch("dependencies.detect", side_effect=[initial, unpinned, pinned, pinned]), \
                mock.patch("dependencies.probe", return_value=f"Commit: {target}\n"), \
                mock.patch("dependencies.subprocess.run", return_value=mock.Mock(returncode=0)) as run:
            code, result = self.execute()
        self.assertEqual(code, 0, result)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][1], "install")
        self.assertEqual(run.call_args_list[1].args[0],
                         ["flatpak", "update", "--user", "--noninteractive", "-y",
                          "--commit=" + target, dependencies.APP])
        self.assertEqual(result["dependencies"]["flycast"]["commit"], target)

    def test_missing_user_remote_is_verified_before_app_install(self):
        target = "a" * 64
        self.context["target_commit"] = target
        initial, with_remote, unpinned = facts(), facts(remote=True), facts(True, True)
        pinned = dict(unpinned, commit=target)
        self.approve(initial)
        with mock.patch("dependencies.detect", side_effect=[
                initial, with_remote, unpinned, pinned, pinned]), \
                mock.patch("dependencies.probe", return_value=f"Commit: {target}\n") as probe, \
                mock.patch("dependencies.subprocess.run", return_value=mock.Mock(returncode=0)) as run:
            code, result = self.execute()
        self.assertEqual(code, 0, result)
        self.assertEqual([call.args[0][1] for call in run.call_args_list],
                         ["remote-add", "install", "update"])
        probe.assert_called_with("remote-info", "--user", "--commit=" + target,
                                 "flathub", dependencies.APP)

    def test_unavailable_tested_commit_stops_before_install(self):
        target = "a" * 64
        with mock.patch("dependencies.probe", side_effect=dependencies.DependencyError("commit unavailable")):
            with self.assertRaisesRegex(dependencies.DependencyError, "commit unavailable"):
                dependencies.make_plan(facts(remote=True), target)

    def test_remote_setup_and_install_are_separate_recorded_transactions(self):
        initial = facts()
        self.approve(initial)
        with mock.patch("dependencies.detect", side_effect=[
                initial, facts(remote=True), facts(True, True), facts(True, True)]), \
                mock.patch("dependencies.subprocess.run", return_value=mock.Mock(returncode=0)):
            code, result = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual([c["argv"][1] for c in result["completed_transactions"]], ["remote-add", "install"])

    def test_concurrent_install_after_remote_setup_does_not_trigger_an_upgrade(self):
        initial = facts()
        self.approve(initial)
        with mock.patch("dependencies.detect", side_effect=[initial, facts(True, True)]), \
                mock.patch("dependencies.subprocess.run", return_value=mock.Mock(returncode=0)) as run:
            code, result = self.execute()
        self.assertEqual(code, 30)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][1], "remote-add")
        self.assertTrue(result["dependencies"]["flycast"]["installed"])

    def test_existing_dependency_is_reused_without_install_or_upgrade(self):
        current = facts(True, True)
        self.approve(current)
        with mock.patch("dependencies.detect", return_value=current), \
                mock.patch("dependencies.subprocess.run") as run:
            code, result = self.execute()
        self.assertEqual(code, 0)
        self.assertTrue(result["dependencies"]["flycast"]["installed"])
        run.assert_not_called()

    def test_failed_transaction_preserves_completed_work(self):
        initial = facts(remote=True)
        self.approve(initial)
        with mock.patch("dependencies.detect", side_effect=[initial, facts(True, True)]), \
                mock.patch("dependencies.subprocess.run", return_value=mock.Mock(returncode=1)):
            code, result = self.execute()
        self.assertEqual(code, 40)
        self.assertEqual(result["completed_transactions"][0]["exit_code"], 1)
        self.assertTrue(result["dependencies"]["flycast"]["installed"])

    def test_probe_failure_after_transaction_retains_exit_evidence(self):
        initial = facts(remote=True)
        self.approve(initial)
        with mock.patch("dependencies.detect", side_effect=[initial, dependencies.DependencyError("probe failed")]), \
                mock.patch("dependencies.subprocess.run", return_value=mock.Mock(returncode=0)):
            code, result = self.execute()
        self.assertEqual(code, 40)
        self.assertEqual(result["completed_transactions"][0]["exit_code"], 0)
        journal = json.loads((self.root / "dependency-transactions.json").read_text())
        self.assertTrue(journal["detection_pending"])

    def test_cancellation_waits_for_transaction_and_keeps_dependency(self):
        initial = facts(remote=True)
        self.approve(initial)

        def transaction(*args, **kwargs):
            Path(self.context["cancel_file"]).write_text("cancel")
            return mock.Mock(returncode=0)

        with mock.patch("dependencies.detect", side_effect=[initial, facts(True, True), facts(True, True)]), \
                mock.patch("dependencies.subprocess.run", side_effect=transaction):
            code, result = self.execute()
        self.assertEqual(code, 130)
        self.assertTrue(result["dependencies"]["flycast"]["installed"])
        self.assertEqual(len(result["completed_transactions"]), 1)

    def test_cancel_before_first_command(self):
        self.approve(facts())
        Path(self.context["cancel_file"]).write_text("cancel")
        with mock.patch("dependencies.detect") as detect, mock.patch("dependencies.subprocess.run") as run:
            code, _ = self.execute()
        self.assertEqual(code, 130)
        detect.assert_not_called()
        run.assert_not_called()

    def test_approval_drift_and_wrong_job_cannot_mutate(self):
        self.approve(facts())
        with mock.patch("dependencies.detect", return_value=facts(remote=True)), \
                mock.patch("dependencies.subprocess.run") as run:
            code, _ = self.execute()
        self.assertEqual(code, 30)
        run.assert_not_called()
        self.context["job_id"] = "j87654321"
        with mock.patch("dependencies.detect", return_value=facts()), mock.patch("dependencies.subprocess.run") as run:
            code, _ = self.execute()
        self.assertEqual(code, 30)
        run.assert_not_called()

    def test_plan_tampering_cannot_mutate(self):
        self.approve(facts())
        Path(self.context["approved_plan_file"]).write_text("{}")
        with mock.patch("dependencies.detect", return_value=facts()), mock.patch("dependencies.subprocess.run") as run:
            code, _ = self.execute()
        self.assertEqual(code, 40)
        run.assert_not_called()

    def test_uncertain_previous_transaction_cannot_be_overwritten(self):
        initial = facts(remote=True)
        self.approve(initial)
        journal = self.root / "dependency-transactions.json"
        previous = {"job_id": self.context["job_id"], "active_command": ["flatpak", "install"],
                    "completed": []}
        journal.write_text(json.dumps(previous))
        with mock.patch("dependencies.detect", return_value=initial), mock.patch("dependencies.subprocess.run") as run:
            code, result = self.execute()
        self.assertEqual(code, 40)
        self.assertIn("reconcile", result["message"])
        self.assertEqual(json.loads(journal.read_text()), previous)
        run.assert_not_called()

    def test_retry_preserves_prior_completed_transactions(self):
        initial = facts(remote=True)
        self.approve(initial)
        journal = self.root / "dependency-transactions.json"
        previous = [{"argv": ["flatpak", "install"], "exit_code": 1}]
        journal.write_text(json.dumps({"job_id": self.context["job_id"], "active_command": None,
                                      "completed": previous}))
        with mock.patch("dependencies.detect", side_effect=[initial, facts(True, True), facts(True, True)]), \
                mock.patch("dependencies.subprocess.run", return_value=mock.Mock(returncode=0)):
            code, _ = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(journal.read_text())["attempts"][0]["completed"], previous)
