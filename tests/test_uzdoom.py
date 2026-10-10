"""All Flatpak commands are mocked; tests never install or launch an engine."""
import contextlib
import copy
import hashlib
import io
import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jobs
import uzdoom

COMMIT = "d7b8ce76e5480a28d1e07400093a20d47f56c201fd974b0a5dbfa3b26bbd587e"
RUNTIME = "org.freedesktop.Platform/x86_64/25.08"
INFO = (f"Ref: {uzdoom.REF}\nArch: x86_64\nBranch: stable\nOrigin: flathub\n"
        f"Version: 5.0.1\nCommit: {COMMIT}\n")
METADATA = f"[Application]\nname={uzdoom.APP}\nruntime={RUNTIME}\ncommand=uzdoom\n"


def facts(installed=False, remote=False, scope="user", available=True, **extra):
    return {"provider": "flatpak", "scope": scope, "app_id": uzdoom.APP,
            "arch": "x86_64", "branch": "stable", "origin": "flathub",
            "flatpak_available": available, "installed": installed, "remote_present": remote,
            "version": "5.0.1" if installed else None, "commit": COMMIT if installed else None,
            "capabilities_checked": False, "launch_argv": ["flatpak", "run", "--" + scope, uzdoom.APP],
            "running": False, "capability_note": uzdoom.NOTE, **extra}


class Detection(unittest.TestCase):
    def responses(self, scope="user", info=INFO, remote=True, running=False):
        rows = f"{uzdoom.APP}\tx86_64\tstable\tflathub\n"
        return ([] if scope == "user" else [""]) + [
            rows, "flathub\t" + uzdoom.REMOTE_URL + "\n" if remote else "",
            info, COMMIT + "\n", uzdoom.APP + "\n" if running else ""]

    def test_no_flatpak_never_probes(self):
        with mock.patch("uzdoom.shutil.which", return_value=None), mock.patch("uzdoom.probe") as probe:
            self.assertEqual(uzdoom.detect(), facts(available=False))
            self.assertFalse(uzdoom.running())
        probe.assert_not_called()

    def test_user_preferred_without_system_queries(self):
        with mock.patch("uzdoom.shutil.which", return_value="flatpak"), \
                mock.patch("uzdoom.probe", side_effect=self.responses()) as probe:
            observed = uzdoom.detect()
        self.assertEqual(observed, facts(True, True, location="Flatpak (your user account)"))
        self.assertFalse(any("--system" in call.args for call in probe.call_args_list))
        self.assertEqual(probe.call_args.args, ("ps", "--columns=application"))

    def test_default_system_reused_read_only(self):
        with mock.patch("uzdoom.shutil.which", return_value="flatpak"), \
                mock.patch("uzdoom.probe", side_effect=self.responses("system")) as probe:
            observed = uzdoom.detect()
        self.assertEqual(observed, facts(True, True, "system", location="Flatpak (system-wide)"))
        self.assertEqual(uzdoom.commands_for(observed), [])
        self.assertTrue(all(call.args[0] in ("list", "remotes", "info", "ps")
                            for call in probe.call_args_list))
        self.assertFalse(any("--installation" in str(call) for call in probe.call_args_list))

    def test_missing_is_always_user_with_remote_optional(self):
        for remote in (False, True):
            with self.subTest(remote=remote), mock.patch("uzdoom.shutil.which", return_value="flatpak"), \
                    mock.patch("uzdoom.probe", side_effect=[
                        "", "", "flathub\t" + uzdoom.REMOTE_URL if remote else "", ""]):
                self.assertEqual(uzdoom.detect(), facts(remote=remote))

    def test_invalid_or_ambiguous_ref_or_origin_never_falls_back(self):
        for row in (f"{uzdoom.APP}\taarch64\tstable\tflathub",
                    f"{uzdoom.APP}\tx86_64\tbeta\tflathub",
                    f"{uzdoom.APP}\tx86_64\tstable\tother",
                    f"{uzdoom.APP}",
                    (f"{uzdoom.APP}\tx86_64\tstable\tflathub\n" * 2)):
            with self.subTest(row=row), mock.patch("uzdoom.shutil.which", return_value="flatpak"), \
                    mock.patch("uzdoom.probe", return_value=row) as probe:
                with self.assertRaisesRegex(uzdoom.DependencyError, "ref/origin"):
                    uzdoom.detect()
                self.assertEqual(probe.call_count, 1)

    def test_remote_url_exact_and_not_replaced(self):
        for url in ("https://untrusted.example/repo/", "https://dl.flathub.org/repo/extra",
                    "http://dl.flathub.org/repo/", "https://flathub.org/repo/",
                    "https://dl.flathub.org/repo////"):
            with self.subTest(url=url), mock.patch("uzdoom.shutil.which", return_value="flatpak"), \
                    mock.patch("uzdoom.probe", side_effect=["", "", "flathub\t" + url]):
                with self.assertRaisesRegex(uzdoom.DependencyError, "unexpected URL"):
                    uzdoom.detect()
        with mock.patch("uzdoom.shutil.which", return_value="flatpak"), \
                mock.patch("uzdoom.probe", side_effect=["", "", "flathub\t" + uzdoom.REMOTE_URL.rstrip("/"), ""]):
            self.assertTrue(uzdoom.detect()["remote_present"])

    def test_missing_remote_for_installed_app_rejected(self):
        with mock.patch("uzdoom.shutil.which", return_value="flatpak"), \
                mock.patch("uzdoom.probe", side_effect=self.responses(remote=False)):
            with self.assertRaisesRegex(uzdoom.DependencyError, "trusted Flathub"):
                uzdoom.detect()

    def test_info_must_match_ref_origin_and_commit_and_have_version(self):
        for info in (INFO.replace(uzdoom.REF, "app/" + uzdoom.APP + "/aarch64/stable"),
                     INFO.replace("Branch: stable", "Branch: beta"),
                     INFO.replace("Origin: flathub", "Origin: other"),
                     INFO.replace("Version: 5.0.1", "Version:"),
                     INFO.replace(COMMIT, "a" * 64),
                     INFO + "Version: 6.0\n"):
            with self.subTest(info=info), mock.patch("uzdoom.shutil.which", return_value="flatpak"), \
                    mock.patch("uzdoom.probe", side_effect=self.responses(info=info)):
                with self.assertRaises(uzdoom.DependencyError):
                    uzdoom.detect()

    def test_running_matches_exact_application_in_any_scope(self):
        with mock.patch("uzdoom.shutil.which", return_value="flatpak"), \
                mock.patch("uzdoom.probe", side_effect=self.responses("system", running=True)):
            self.assertTrue(uzdoom.detect()["running"])
        with mock.patch("uzdoom.probe", return_value="other.app\n" + uzdoom.APP + ".Fake\n") as probe:
            self.assertFalse(uzdoom.running(facts()))
        probe.assert_called_once_with("ps", "--columns=application")

    def test_no_scope_choices(self):
        with self.assertRaises(TypeError):
            uzdoom.detect("system")


class HostPrerequisites(unittest.TestCase):
    def check(self, current, responses):
        with mock.patch("uzdoom.detect", return_value=current), \
                mock.patch("uzdoom.probe", side_effect=responses) as probe:
            result = uzdoom.check_host(current)
        self.assertTrue(all(call.args[0] in ("info", "list") for call in probe.call_args_list))
        return result

    def test_system_metadata_only_no_capability_claim(self):
        current = facts(True, True, "system")
        result = self.check(current, [uzdoom.REF, METADATA, RUNTIME, RUNTIME, "runtime/" + RUNTIME])
        self.assertTrue(result["host_prerequisites_checked"])
        self.assertEqual(result["version"], "5.0.1")
        self.assertEqual(result["commit"], COMMIT)
        for key in ("capabilities_checked", "gameplay_checked", "cli_checked",
                    "graphics_checked", "content_access_checked"):
            self.assertFalse(result[key])
        self.assertFalse(current["capabilities_checked"])

    def test_user_can_use_default_system_runtime(self):
        result = self.check(facts(True, True), [
            uzdoom.REF, METADATA, RUNTIME, "", RUNTIME, "runtime/" + RUNTIME])
        self.assertEqual(result["runtime_scope"], "system")

    def test_changed_version_commit_or_scope_rejected(self):
        current = facts(True, True)
        for changed in (facts(True, True, version="5.0.0"),
                        facts(True, True, commit="a" * 64), facts(True, True, "system")):
            with self.subTest(changed=changed), mock.patch("uzdoom.detect", return_value=changed), \
                    mock.patch("uzdoom.probe") as probe:
                with self.assertRaisesRegex(uzdoom.DependencyError, "changed"):
                    uzdoom.check_host(current)
                probe.assert_not_called()

    def test_missing_or_malformed_host_metadata_and_runtime_rejected(self):
        bad_responses = [
            ["app/" + uzdoom.APP + "/x86_64/beta"],
            [uzdoom.REF, "[Application]\nname=other\n"],
            [uzdoom.REF, METADATA.replace(uzdoom.APP, "other")],
            [uzdoom.REF, METADATA.replace("x86_64", "aarch64")],
            [uzdoom.REF, METADATA, "other/x86_64/25.08"],
            [uzdoom.REF, METADATA, RUNTIME, "", ""],
            [uzdoom.REF, METADATA, RUNTIME, RUNTIME, "runtime/other/x86_64/25.08"]]
        for responses in bad_responses:
            with self.subTest(responses=responses), mock.patch("uzdoom.detect", return_value=facts(True, True)), \
                    mock.patch("uzdoom.probe", side_effect=responses):
                with self.assertRaises(uzdoom.DependencyError):
                    uzdoom.check_host(facts(True, True))
        with self.assertRaisesRegex(uzdoom.DependencyError, "not installed"):
            uzdoom.check_host(facts())


class Preparation(unittest.TestCase):
    def setUp(self):
        # Keep all test file operations inside the project, not the system temporary directory.
        self.directory = tempfile.TemporaryDirectory(prefix=".uzdoom-test-", dir=Path.cwd())
        self.root = Path(self.directory.name)
        self.context = {"job_id": "j12345678", "phase": "preflight",
                        "result_file": str(self.root / "result.json"),
                        "cancel_file": str(self.root / "cancel"), "approved_plan_digest": None}
        self.journal = self.root / "dependency-transactions.json"

    def tearDown(self):
        self.directory.cleanup()

    def execute(self):
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
            code = uzdoom.run(self.context)
        result = json.loads(Path(self.context["result_file"]).read_text())
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        for event in events:
            self.assertIsNone(jobs.validate_event(event, ["resolve"]))
        self.assertEqual(events[-1]["outcome"], result["outcome"])
        self.assertEqual(jobs.RESULT_OUTCOME[result["outcome"]], jobs.EXIT_OUTCOME[code])
        return code, result

    def approve(self, current):
        with mock.patch("uzdoom.detect", return_value=current):
            self.assertEqual(self.execute()[0], 0)
        raw = Path(self.context["result_file"]).read_bytes()
        approved = self.root / "approved-plan.json"
        approved.write_bytes(raw)
        self.context.update(phase="apply", approved_plan_file=str(approved),
                            approved_plan_digest="sha256:" + hashlib.sha256(raw).hexdigest())

    def transaction(self, argv, **kwargs):
        journal = json.loads(self.journal.read_text())
        self.assertEqual(journal["active_command"], argv)
        self.assertEqual(journal["dependency"], uzdoom.APP)
        self.assertNotIn("timeout", kwargs)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        return mock.Mock(returncode=0)

    def test_preflight_no_writes_and_missing_flatpak_needs_action(self):
        with mock.patch("uzdoom.detect", return_value=facts()), mock.patch("uzdoom.subprocess.run") as command:
            code, result = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(len(result["plan"]["dependency_commands"]), 2)
        self.assertFalse(self.journal.exists())
        command.assert_not_called()
        with mock.patch("uzdoom.detect", return_value=facts(available=False)):
            code, result = self.execute()
        self.assertEqual(code, 20)
        self.assertIn("cannot elevate", result["message"])
        self.assertIn("sudo apt install flatpak", result["message"])

    def test_commands_are_exact_missing_only_user_and_no_upgrades(self):
        self.assertEqual(uzdoom.commands_for(facts(True, True, "system")), [])
        self.assertEqual(uzdoom.commands_for(facts(True, True)), [])
        self.assertEqual(uzdoom.commands_for(facts(available=False)), [])
        commands = uzdoom.commands_for(facts())
        self.assertEqual(commands[0], ["flatpak", "remote-add", "--user", "--if-not-exists",
                                       "flathub", uzdoom.REMOTE_DESCRIPTOR])
        self.assertEqual(commands[1], ["flatpak", "install", "--user", "--noninteractive", "-y",
                                       "flathub", uzdoom.REF])
        with self.assertRaises(uzdoom.DependencyError):
            uzdoom.commands_for(facts(scope="system"))

    def test_package_evidence_pins_fresh_user_install_only(self):
        target = "a" * 64
        expected = [
            ["flatpak", "install", "--user", "--noninteractive", "-y",
             "flathub", uzdoom.REF],
            ["flatpak", "update", "--user", "--noninteractive", "-y",
             "--commit=" + target, uzdoom.APP],
        ]
        self.assertEqual(uzdoom.commands_for(facts(remote=True), target, pin_fresh_install=True), expected)
        self.assertEqual(uzdoom.commands_for(facts(True, True), target), [])
        self.assertEqual(uzdoom.commands_for(
            facts(True, True), target, pin_fresh_install=True), [
                ["flatpak", "update", "--user", "--noninteractive", "-y",
                 "--commit=" + target, uzdoom.APP]])
        self.assertEqual(uzdoom.commands_for(
            facts(True, True, "system"), target, pin_fresh_install=True), [])
        with mock.patch("uzdoom.probe", return_value=f"Commit: {target}\n") as probe:
            plan = uzdoom.make_plan(facts(remote=True), target)
            existing_plan = uzdoom.make_plan(facts(True, True), target)
        self.assertEqual(plan["target_commit"], target)
        self.assertEqual(plan["dependency_commands"], expected)
        self.assertEqual(existing_plan["dependency_commands"], [])
        probe.assert_any_call("remote-info", "--user", "--commit=" + target,
                              "flathub", uzdoom.REF)
        self.assertEqual(probe.call_count, 2)
        with mock.patch("uzdoom.probe", return_value="Commit: " + "b" * 64 + "\n"):
            with self.assertRaisesRegex(uzdoom.DependencyError, "did not confirm"):
                uzdoom.make_plan(facts(remote=True), target)
        with self.assertRaisesRegex(uzdoom.DependencyError, "Invalid"):
            uzdoom.make_plan(facts(remote=True), "not-a-commit")

    def test_separate_remote_and_install_transactions_redetect_before_and_after_each(self):
        initial, with_remote, installed = facts(), facts(remote=True), facts(True, True)
        self.approve(initial)
        with mock.patch("uzdoom.detect", side_effect=[
                initial, initial, with_remote, with_remote, installed, installed]) as detect, \
                mock.patch("uzdoom.subprocess.run", side_effect=self.transaction) as command:
            code, result = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(detect.call_count, 6)
        self.assertEqual(command.call_count, 2)
        self.assertEqual([t["argv"][1] for t in result["completed_transactions"]], ["remote-add", "install"])
        self.assertEqual(result["dependencies"]["uzdoom"], installed)
        journal = json.loads(self.journal.read_text())
        self.assertIsNone(journal["active_command"])
        self.assertFalse(journal["detection_pending"])
        self.assertEqual(journal["after"], installed)

    def test_evidence_pinned_install_applies_commit_before_success(self):
        target = "a" * 64
        self.context["target_commit"] = target
        initial = facts(remote=True)
        unpinned = facts(True, True)
        pinned = facts(True, True)
        pinned["commit"] = target
        with mock.patch("uzdoom.probe", return_value=f"Commit: {target}\n"):
            self.approve(initial)
        with mock.patch("uzdoom.detect", side_effect=[initial, initial, unpinned, unpinned, pinned, pinned]), \
                mock.patch("uzdoom.probe", return_value=f"Commit: {target}\n"), \
                mock.patch("uzdoom.subprocess.run", side_effect=self.transaction) as command:
            code, result = self.execute()
        self.assertEqual(code, 0, result)
        self.assertEqual(command.call_count, 2)
        self.assertEqual(command.call_args_list[1].args[0],
                         ["flatpak", "update", "--user", "--noninteractive", "-y",
                          "--commit=" + target, uzdoom.APP])
        self.assertEqual(result["dependencies"]["uzdoom"]["commit"], target)

    def test_missing_remote_checks_commit_before_install(self):
        target = "b" * 64
        self.context["target_commit"] = target
        initial, with_remote, unpinned = facts(), facts(remote=True), facts(True, True)
        pinned = facts(True, True)
        pinned["commit"] = target
        self.approve(initial)
        with mock.patch("uzdoom.detect", side_effect=[
                initial, initial, with_remote, with_remote, unpinned, unpinned, pinned, pinned]), \
                mock.patch("uzdoom.probe", return_value=f"Commit: {target}\n") as probe, \
                mock.patch("uzdoom.subprocess.run", side_effect=self.transaction) as command:
            code, result = self.execute()
        self.assertEqual(code, 0, result)
        self.assertEqual([call.args[0][1] for call in command.call_args_list],
                         ["remote-add", "install", "update"])
        probe.assert_called_with("remote-info", "--user", "--commit=" + target,
                                 "flathub", uzdoom.REF)

    def test_existing_system_or_user_reused_without_any_commands(self):
        for scope in ("system", "user"):
            current = facts(True, True, scope)
            self.context["phase"] = "preflight"
            self.approve(current)
            with mock.patch("uzdoom.detect", return_value=current), mock.patch("uzdoom.subprocess.run") as command:
                code, result = self.execute()
            self.assertEqual(code, 0)
            self.assertEqual(result["dependencies"]["uzdoom"], current)
            command.assert_not_called()

    def test_changed_facts_never_upgrade_or_switch_scope(self):
        initial = facts(remote=True)
        for changed in (facts(True, True), facts(True, True, "system"), facts()):
            self.context["phase"] = "preflight"
            self.approve(initial)
            with mock.patch("uzdoom.detect", return_value=changed), mock.patch("uzdoom.subprocess.run") as command:
                self.assertEqual(self.execute()[0], 30)
            command.assert_not_called()

    def test_concurrent_install_between_transactions_does_not_upgrade(self):
        initial, installed = facts(), facts(True, True, "system")
        self.approve(initial)
        with mock.patch("uzdoom.detect", side_effect=[initial, initial, installed, installed]), \
                mock.patch("uzdoom.subprocess.run", side_effect=self.transaction) as command:
            code, result = self.execute()
        self.assertEqual(code, 30)
        self.assertEqual(command.call_count, 1)
        self.assertEqual(result["dependencies"]["uzdoom"], installed)

    def test_redetect_before_first_transaction_blocks_concurrent_change(self):
        initial = facts(remote=True)
        self.approve(initial)
        with mock.patch("uzdoom.detect", side_effect=[initial, facts(True, True)]), \
                mock.patch("uzdoom.subprocess.run") as command:
            self.assertEqual(self.execute()[0], 30)
        command.assert_not_called()
        self.assertFalse(self.journal.exists())

    def test_existing_version_drift_requires_new_approval(self):
        current = facts(True, True, "system")
        self.approve(current)
        with mock.patch("uzdoom.detect", return_value=facts(True, True, "system", version="5.0.0")), \
                mock.patch("uzdoom.subprocess.run") as command:
            self.assertEqual(self.execute()[0], 30)
        command.assert_not_called()

    def test_system_appearing_after_user_install_is_not_a_successful_user_install(self):
        initial = facts(remote=True)
        self.approve(initial)
        with mock.patch("uzdoom.detect", side_effect=[initial, initial, facts(True, True, "system")]), \
                mock.patch("uzdoom.subprocess.run", side_effect=self.transaction):
            self.assertEqual(self.execute()[0], 30)

    def test_tampered_digest_and_exact_envelope_binding(self):
        current = facts(remote=True)
        self.approve(current)
        approved = Path(self.context["approved_plan_file"])
        original = approved.read_bytes()
        approved.write_bytes(original + b" ")
        with mock.patch("uzdoom.detect", return_value=current), mock.patch("uzdoom.subprocess.run") as command:
            self.assertEqual(self.execute()[0], 40)
        command.assert_not_called()
        envelope = json.loads(original)
        variants = []
        for key, value in (("job_id", "jffffffff"), ("operation", "install"),
                           ("phase", "apply"), ("outcome", "failed"), ("result_version", 2)):
            changed = copy.deepcopy(envelope)
            changed[key] = value
            variants.append(changed)
        changed = copy.deepcopy(envelope)
        changed["plan"]["dependency_commands"][0].append("--system")
        variants.append(changed)
        changed = copy.deepcopy(envelope)
        changed["dependencies"]["uzdoom"]["commit"] = "a" * 64
        variants.append(changed)
        for changed in variants:
            raw = json.dumps(changed).encode()
            approved.write_bytes(raw)
            self.context["approved_plan_digest"] = "sha256:" + hashlib.sha256(raw).hexdigest()
            with mock.patch("uzdoom.detect", return_value=current), mock.patch("uzdoom.subprocess.run") as command:
                self.assertEqual(self.execute()[0], 30)
            command.assert_not_called()

    def test_cancel_before_work_never_detects_or_transacts(self):
        Path(self.context["cancel_file"]).touch()
        with mock.patch("uzdoom.detect") as detect, mock.patch("uzdoom.subprocess.run") as command:
            self.assertEqual(self.execute()[0], 130)
        detect.assert_not_called()
        command.assert_not_called()

    def test_cancel_active_command_waits_and_records_redetection(self):
        initial = facts()
        self.approve(initial)

        def transaction(argv, **kwargs):
            self.transaction(argv, **kwargs)
            Path(self.context["cancel_file"]).touch()
            self.assertEqual(json.loads(self.journal.read_text())["active_command"], argv)
            return mock.Mock(returncode=0)

        with mock.patch("uzdoom.detect", side_effect=[initial, initial, facts(remote=True)]), \
                mock.patch("uzdoom.subprocess.run", side_effect=transaction) as command:
            code, result = self.execute()
        self.assertEqual(code, 130)
        self.assertEqual(command.call_count, 1)
        self.assertTrue(result["dependencies"]["uzdoom"]["remote_present"])
        self.assertFalse(json.loads(self.journal.read_text())["detection_pending"])

    def test_cancel_during_read_only_redetection_prevents_command(self):
        initial = facts(remote=True)
        self.approve(initial)
        calls = 0

        def detect():
            nonlocal calls
            calls += 1
            if calls == 2:
                Path(self.context["cancel_file"]).touch()
            return initial

        with mock.patch("uzdoom.detect", side_effect=detect), mock.patch("uzdoom.subprocess.run") as command:
            self.assertEqual(self.execute()[0], 130)
        command.assert_not_called()
        self.assertFalse(self.journal.exists())

    def test_failed_transaction_still_redetects_and_retains_facts(self):
        initial = facts(remote=True)
        self.approve(initial)
        with mock.patch("uzdoom.detect", side_effect=[initial, initial, facts(True, True)]), \
                mock.patch("uzdoom.subprocess.run", return_value=mock.Mock(returncode=1)):
            code, result = self.execute()
        self.assertEqual(code, 40)
        self.assertTrue(result["dependencies"]["uzdoom"]["installed"])
        self.assertEqual(result["completed_transactions"][0]["exit_code"], 1)
        self.assertFalse(json.loads(self.journal.read_text())["detection_pending"])

    def test_detection_failure_leaves_pending_journal_and_blocks_new_preflight(self):
        initial = facts(remote=True)
        self.approve(initial)
        with mock.patch("uzdoom.detect", side_effect=[
                initial, initial, uzdoom.DependencyError("probe failure")]), \
                mock.patch("uzdoom.subprocess.run", side_effect=self.transaction):
            self.assertEqual(self.execute()[0], 40)
        self.assertTrue(json.loads(self.journal.read_text())["detection_pending"])
        self.context["phase"] = "preflight"
        with mock.patch("uzdoom.detect") as detect, mock.patch("uzdoom.subprocess.run") as command:
            code, result = self.execute()
        self.assertEqual(code, 40)
        self.assertIn("uncertain", result["message"])
        detect.assert_not_called()
        command.assert_not_called()

    def test_spawn_failure_preserves_active_command_and_blocks_retry(self):
        initial = facts(remote=True)
        self.approve(initial)
        with mock.patch("uzdoom.detect", return_value=initial), \
                mock.patch("uzdoom.subprocess.run", side_effect=OSError("spawn failed")):
            self.assertEqual(self.execute()[0], 40)
        self.assertEqual(json.loads(self.journal.read_text())["active_command"],
                         uzdoom.commands_for(initial)[0])
        with mock.patch("uzdoom.detect") as detect, mock.patch("uzdoom.subprocess.run") as command:
            self.assertEqual(self.execute()[0], 40)
        detect.assert_not_called()
        command.assert_not_called()

    def test_wrong_job_journal_and_running_engine_block_preparation(self):
        self.journal.write_text(json.dumps({"job_id": "jffffffff", "dependency": uzdoom.APP}))
        with mock.patch("uzdoom.detect") as detect:
            self.assertEqual(self.execute()[0], 40)
        detect.assert_not_called()
        self.journal.unlink()
        with mock.patch("uzdoom.detect", return_value=facts(True, True, running=True)), \
                mock.patch("uzdoom.subprocess.run") as command:
            self.assertEqual(self.execute()[0], 20)
        command.assert_not_called()

    def test_malformed_or_incomplete_journal_never_becomes_a_clean_retry(self):
        for fields in ({}, {"active_command": None}, {"active_command": "", "detection_pending": False},
                       {"active_command": None, "detection_pending": 0},
                       {"active_command": None, "detection_pending": False, "attempts": "broken"}):
            previous = {"job_id": self.context["job_id"], "dependency": uzdoom.APP,
                        "attempts": [], "completed": [], **fields}
            self.journal.write_text(json.dumps(previous))
            with mock.patch("uzdoom.detect") as detect, mock.patch("uzdoom.subprocess.run") as command:
                self.assertEqual(self.execute()[0], 40)
            self.assertEqual(json.loads(self.journal.read_text()), previous)
            detect.assert_not_called()
            command.assert_not_called()

    def test_clean_retry_retains_prior_completed_transactions(self):
        initial = facts(remote=True)
        self.approve(initial)
        prior = [{"argv": uzdoom.commands_for(initial)[0], "exit_code": 1}]
        self.journal.write_text(json.dumps({
            "job_id": self.context["job_id"], "dependency": uzdoom.APP,
            "active_command": None, "detection_pending": False, "attempts": [], "completed": prior}))
        with mock.patch("uzdoom.detect", side_effect=[initial, initial, facts(True, True), facts(True, True)]), \
                mock.patch("uzdoom.subprocess.run", side_effect=self.transaction):
            self.assertEqual(self.execute()[0], 0)
        self.assertEqual(json.loads(self.journal.read_text())["attempts"], [{"completed": prior}])

    def test_false_success_install_never_claims_prepared(self):
        current = facts(remote=True)
        self.approve(current)
        with mock.patch("uzdoom.detect", return_value=current), \
                mock.patch("uzdoom.subprocess.run", side_effect=self.transaction):
            code, result = self.execute()
        self.assertEqual(code, 40)
        self.assertIn("not detected", result["message"])

    def test_scope_override_and_missing_approval_rejected(self):
        self.context["scope"] = "system"
        with mock.patch("uzdoom.detect") as detect:
            self.assertEqual(self.execute()[0], 40)
        detect.assert_not_called()
        self.context.pop("scope")
        self.context["phase"] = "apply"
        with mock.patch("uzdoom.detect", return_value=facts()), mock.patch("uzdoom.subprocess.run") as command:
            self.assertEqual(self.execute()[0], 40)
        command.assert_not_called()

    def test_cli_context_preflight_emits_jobs_protocol_without_transaction(self):
        context_file = self.root / "context.json"
        context_file.write_text(json.dumps(self.context))
        with mock.patch.object(sys, "argv", ["uzdoom.py", "--context", str(context_file)]), \
                mock.patch("dependencies.shutil.which", return_value=None), \
                mock.patch("dependencies.probe") as probe, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as exit_info:
                runpy.run_path(str(Path(uzdoom.__file__)), run_name="__main__")
        self.assertEqual(exit_info.exception.code, 20)
        result = json.loads(Path(self.context["result_file"]).read_text())
        self.assertEqual(result["outcome"], "needs_action")
        for line in output.getvalue().splitlines():
            self.assertIsNone(jobs.validate_event(json.loads(line)))
        probe.assert_not_called()

    def test_job_local_approval_cannot_alias_result_cancel_or_journal(self):
        current = facts(remote=True)
        self.approve(current)
        for path in (Path(self.context["result_file"]), Path(self.context["cancel_file"]),
                     self.journal, self.root.parent / "approved-plan.json"):
            self.context["approved_plan_file"] = str(path)
            with mock.patch("uzdoom.detect", return_value=current), mock.patch("uzdoom.subprocess.run") as command:
                self.assertEqual(self.execute()[0], 40)
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
