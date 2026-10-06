#!/usr/bin/env python3
"""User-scope Flycast detection and approval-bound preparation; never launches an emulator."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from jobs import _write_durable

APP = "org.flycast.Flycast"
REMOTE_URL = "https://dl.flathub.org/repo/"
REMOTE_DESCRIPTOR = "https://flathub.org/repo/flathub.flatpakrepo"
ALLOWED_REMOTE_URLS = {REMOTE_URL, "https://dl.flathub.org/repo", "https://flathub.org/repo/",
                       "https://flathub.org/repo"}


class DependencyError(ValueError):
    pass


def probe(*args):
    try:
        result = subprocess.run(["flatpak", *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, timeout=15,
                                env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as e:
        raise DependencyError(f"Cannot inspect Flatpak: {e}") from e
    if result.returncode:
        raise DependencyError(f"Flatpak {' '.join(args)} failed: {result.stderr.strip() or result.returncode}")
    return result.stdout


def detect():
    facts = {"provider": "flatpak", "scope": "user", "app_id": APP,
             "flatpak_available": bool(shutil.which("flatpak")), "installed": False,
             "remote_present": False, "version": None, "commit": None,
             "capabilities_checked": False, "launch_argv": ["flatpak", "run", "--user", APP],
             "capability_note": "Installation metadata alone does not verify CLI flags, CUE launch or lightgun behavior."}
    if not facts["flatpak_available"]:
        return facts
    for line in probe("remotes", "--user", "--columns=name,url").splitlines():
        parts = line.split("\t")
        if parts[0] == "flathub":
            if len(parts) != 2 or parts[1] not in ALLOWED_REMOTE_URLS:
                raise DependencyError("The user Flathub remote has an unexpected URL; resolve it manually.")
            facts["remote_present"] = True
    apps = probe("list", "--user", "--app", "--columns=application").splitlines()
    facts["installed"] = APP in apps
    if facts["installed"]:
        info = probe("info", "--user", APP)
        for line in info.splitlines():
            key, sep, value = line.strip().partition(":")
            if sep and key in ("Version", "Commit"):
                facts[key.lower()] = value.strip() or None
    return facts


def commands_for(facts):
    if not facts["flatpak_available"] or facts["installed"]:
        return []
    commands = []
    if not facts["remote_present"]:
        commands.append(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", REMOTE_DESCRIPTOR])
    commands.append(["flatpak", "install", "--user", "--noninteractive", "-y", "flathub", APP])
    return commands


def make_plan(facts):
    return {"plan_version": 1, "operation": "prepare-dependency", "dependency": APP,
            "scope": "user", "dependencies": {"flycast": facts}, "actions": [],
            "dependency_commands": commands_for(facts),
            "manual_actions": [{"action_id": "flycast-capability-check",
                                "message": "Flycast capability evidence is still required before game installation."}],
            "notes": ["No system remotes, elevation or emulator upgrades.",
                      "Shared Flycast and its runtime remain installed if game installation later fails.",
                      "Cancellation waits for an active Flatpak transaction to finish."]}


def emit(kind, message, **fields):
    print(json.dumps(dict(event_version=1, type=kind, message=message, **fields)), flush=True)


def run(context):
    """Execute only an approved dependency plan; persist facts even on a transaction failure."""
    phase = context["phase"]
    facts, completed = None, []
    code, outcome, message = 0, "succeeded", "User-scope Flycast preparation complete; capability checks remain."
    plan = None
    try:
        if phase not in ("preflight", "apply"):
            raise DependencyError("Unsupported dependency phase")
        if Path(context["cancel_file"]).exists():
            code, outcome, message = 130, "cancelled", "Cancelled before dependency work."
        else:
            facts = detect()
            if not facts["flatpak_available"]:
                code, outcome, message = 20, "needs_action", (
                    "Flatpak is missing. Install it using your Ubuntu system tools, then retry. Momentum cannot elevate.")
            elif phase == "preflight":
                plan = make_plan(facts)
                message = "Review the exact user-scope dependency commands before proceeding."
            else:
                raw = Path(context["approved_plan_file"]).read_bytes()
                if "sha256:" + hashlib.sha256(raw).hexdigest() != context["approved_plan_digest"]:
                    raise DependencyError("The saved dependency plan changed; obtain a new approval.")
                envelope = json.loads(raw)
                plan = envelope.get("plan")
                if (envelope.get("job_id") != context["job_id"] or envelope.get("outcome") != "succeeded"
                        or envelope.get("phase") != "preflight" or plan != make_plan(facts)):
                    code, outcome, message = 30, "conflicted", "Dependency facts changed; rerun preflight and review a new plan."
                else:
                    journal = Path(context["result_file"]).parent / "dependency-transactions.json"
                    attempts = []
                    if journal.exists():
                        previous = json.loads(journal.read_text())
                        if previous.get("job_id") != context["job_id"]:
                            raise DependencyError("Dependency journal belongs to a different job.")
                        if previous.get("active_command") or previous.get("detection_pending"):
                            raise DependencyError("An earlier dependency transaction is uncertain; reconcile before retry.")
                        attempts = previous.get("attempts", []) + [{"completed": previous["completed"]}]
                    for index, argv in enumerate(plan["dependency_commands"]):
                        if Path(context["cancel_file"]).exists():
                            code, outcome, message = 130, "cancelled", "Cancellation acknowledged between dependency transactions."
                            break
                        if commands_for(facts) != plan["dependency_commands"][index:]:
                            code, outcome, message = 30, "conflicted", (
                                "Dependency facts changed during preparation; review a fresh plan. No upgrade was attempted.")
                            break
                        emit("step_started", " ".join(argv), step="resolve")
                        _write_durable(journal, (json.dumps({"job_id": context["job_id"],
                            "attempts": attempts, "completed": completed, "active_command": argv, "before": facts},
                            sort_keys=True) + "\n").encode())
                        # Child output is diagnostic, not the NDJSON event channel. No timeout kills a transaction.
                        result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=sys.stderr, stderr=sys.stderr,
                                                env={**os.environ, "LC_ALL": "C"})
                        transaction = {"argv": argv, "exit_code": result.returncode}
                        completed.append(transaction)
                        _write_durable(journal, (json.dumps({"job_id": context["job_id"],
                            "attempts": attempts, "completed": completed, "active_command": None, "detection_pending": True},
                            sort_keys=True) + "\n").encode())
                        facts = detect()
                        transaction["observed"] = facts
                        _write_durable(journal, (json.dumps({"job_id": context["job_id"],
                            "attempts": attempts, "completed": completed, "active_command": None, "after": facts},
                            sort_keys=True) + "\n").encode())
                        if result.returncode:
                            code, outcome, message = 40, "failed", (
                                f"Flatpak transaction failed (exit {result.returncode}); completed dependency work is retained.")
                            break
                        emit("step_completed", "Dependency transaction finished; detected state recorded.", step="resolve")
                    if code == 0:
                        facts = detect()
                        if not facts["installed"]:
                            raise DependencyError("Flatpak returned success but user-scope Flycast was not detected.")
                        if Path(context["cancel_file"]).exists():
                            code, outcome, message = 130, "cancelled", (
                                "Cancellation acknowledged after the transaction. Installed dependency is retained.")
    except (DependencyError, OSError, ValueError, KeyError) as e:
        code, outcome, message = 40, "failed", str(e)
        print(message, file=sys.stderr)
    result = {"result_version": 1, "job_id": context["job_id"], "phase": phase,
              "operation": "prepare-dependency", "outcome": outcome, "message": message,
              "dependencies": {"flycast": facts}, "completed_transactions": completed}
    if plan is not None:
        result["plan"] = plan
    _write_durable(Path(context["result_file"]), (json.dumps(result, sort_keys=True) + "\n").encode())
    if outcome == "needs_action":
        emit("needs_action", message, action_id="install-flatpak", blocks_play=True)
    elif phase == "apply" and outcome == "succeeded":
        emit("needs_action", "Flycast is prepared, but game capability validation remains. No gameplay readiness is claimed.",
             action_id="flycast-capability-check", blocks_play=True)
    emit("result", message, outcome=outcome)
    return code


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--context":
        sys.exit("Usage: dependencies.py --context /absolute/context.json")
    sys.exit(run(json.loads(Path(sys.argv[2]).read_text())))
