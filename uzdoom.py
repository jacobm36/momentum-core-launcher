#!/usr/bin/env python3
"""Approval-bound UZDoom preparation. Metadata checks never launch the engine."""
import configparser
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from dependencies import DependencyError, emit, probe, REMOTE_DESCRIPTOR, REMOTE_URL
from jobs import _write_durable

APP = "org.zdoom.UZDoom"
ARCH = "x86_64"
BRANCH = "stable"
REF = f"app/{APP}/{ARCH}/{BRANCH}"
NOTE = "Metadata prerequisites only; CLI flags, content access, graphics and gameplay remain untested."


def running(facts=None):
    """Inspect all instances, not just the selected installation."""
    if facts is not None and not facts.get("flatpak_available"):
        return False
    if facts is None and not shutil.which("flatpak"):
        return False
    return APP in probe("ps", "--columns=application").split()


def _metadata(text):
    values = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition(":")
        if sep and key in ("Ref", "Arch", "Branch", "Origin", "Version", "Commit"):
            if key in values:
                raise DependencyError(f"Duplicate UZDoom metadata field: {key}")
            values[key] = value.strip()
    return values


def _validate(facts):
    if (facts.get("provider") != "flatpak" or facts.get("app_id") != APP
            or facts.get("scope") not in ("user", "system")
            or facts.get("arch") != ARCH or facts.get("branch") != BRANCH
            or facts.get("origin") != "flathub"
            or facts.get("launch_argv") != ["flatpak", "run", "--" + facts["scope"], APP]
            or any(type(facts.get(key)) is not bool for key in (
                "flatpak_available", "installed", "remote_present", "capabilities_checked"))
            or facts["capabilities_checked"]):
        raise DependencyError("Invalid UZDoom dependency facts; rerun detection.")
    if facts["installed"]:
        if (not facts["flatpak_available"] or not facts["remote_present"]
                or not isinstance(facts.get("version"), str) or not facts["version"].strip()
                or not re.fullmatch(r"[a-f0-9]{64}", facts.get("commit") or "")):
            raise DependencyError("Installed UZDoom version, commit and trusted Flathub remote are required.")
    elif facts["scope"] != "user" or facts.get("version") is not None or facts.get("commit") is not None:
        raise DependencyError("Missing UZDoom may only be prepared in user scope.")


def detect():
    """Prefer installed user, then default system; never inspect named installations."""
    return _detect(("user", "system"))


def discover():
    """Inspect both default scopes; invalid metadata remains an explicit error."""
    return [facts for scope in ("user", "system")
            if (facts := _detect((scope,)))["installed"]]


def _detect(scopes):
    facts = {"provider": "flatpak", "scope": "user", "app_id": APP,
             "arch": ARCH, "branch": BRANCH, "origin": "flathub",
             "flatpak_available": bool(shutil.which("flatpak")), "installed": False,
             "remote_present": False, "version": None, "commit": None,
             "capabilities_checked": False, "launch_argv": ["flatpak", "run", "--user", APP],
             "running": False, "capability_note": NOTE}
    if not facts["flatpak_available"]:
        return facts
    for scope in scopes:
        rows = [line.split("\t") for line in probe(
            "list", "--" + scope, "--app", "--columns=application,arch,branch,origin").splitlines()]
        candidates = [row for row in rows if row[0] == APP]
        if candidates:
            if candidates != [[APP, ARCH, BRANCH, "flathub"]]:
                raise DependencyError(f"Unexpected UZDoom ref/origin in {scope}; reconcile manually.")
            facts.update(scope=scope, installed=True, launch_argv=["flatpak", "run", "--" + scope, APP],
                         location=f"Flatpak ({'your user account' if scope == 'user' else 'system-wide'})")
            break
    scope = "--" + facts["scope"]
    remotes = [line.split("\t") for line in probe("remotes", scope, "--columns=name,url").splitlines()]
    flathub = [row for row in remotes if row[0] == "flathub"]
    if flathub:
        if (len(flathub) != 1 or len(flathub[0]) != 2
                or flathub[0][1] not in (REMOTE_URL, REMOTE_URL.rstrip("/"))):
            raise DependencyError(f"The {facts['scope']} Flathub remote has an unexpected URL; reconcile manually.")
        facts["remote_present"] = True
    if facts["installed"]:
        info = _metadata(probe("info", scope, APP))
        if any(info.get(key) != value for key, value in (
                ("Ref", REF), ("Arch", ARCH), ("Branch", BRANCH), ("Origin", "flathub"))):
            raise DependencyError("Installed UZDoom ref/origin metadata differs from the expected x86_64 stable app.")
        commit = probe("info", scope, "--show-commit", APP).strip()
        if info.get("Commit") != commit:
            raise DependencyError("UZDoom commit changed during detection; retry.")
        facts.update(version=info.get("Version"), commit=commit)
    facts["running"] = running(facts)
    _validate(facts)
    return facts


def check_host(facts):
    """Read-only ref/metadata/runtime checks, not a CLI or gameplay capability check."""
    _validate(facts)
    if not facts["installed"]:
        raise DependencyError("UZDoom is not installed; prepare the dependency first.")
    observed = detect()
    if facts["scope"] == "system" and observed.get("scope") == "user":
        observed = _detect((facts["scope"],))
    if observed != facts:
        raise DependencyError("UZDoom facts/version/commit changed; rerun detection and preflight.")
    scope = "--" + facts["scope"]
    if probe("info", scope, "--show-ref", APP).strip() != REF:
        raise DependencyError("UZDoom exact app ref changed.")
    metadata = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        metadata.read_string(probe("info", scope, "--show-metadata", APP))
        name = metadata["Application"]["name"]
        runtime = metadata["Application"]["runtime"]
        command = metadata["Application"]["command"]
    except (configparser.Error, KeyError) as exc:
        raise DependencyError(f"Invalid UZDoom application metadata: {exc}") from exc
    if name != APP or not command.strip() or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/x86_64/[A-Za-z0-9_.-]+", runtime):
        raise DependencyError("Unexpected UZDoom application/runtime metadata.")
    if probe("info", scope, "--show-runtime", APP).strip() != runtime:
        raise DependencyError("UZDoom runtime metadata changed.")
    runtime_scope = None
    for candidate in (("user", "system") if facts["scope"] == "user" else ("system",)):
        if runtime in probe("list", "--" + candidate, "--runtime", "--columns=ref").splitlines():
            runtime_scope = candidate
            break
    if runtime_scope is None or probe(
            "info", "--" + runtime_scope, "--show-ref", runtime).strip() != "runtime/" + runtime:
        raise DependencyError("The UZDoom runtime is not installed with its exact ref.")
    return {"host_prerequisites_checked": True, "metadata_checked": True, "ref_checked": True,
            "runtime_installed": True, "runtime": runtime, "runtime_scope": runtime_scope,
            "scope": facts["scope"], "version": facts["version"], "commit": facts["commit"],
            "cli_checked": False, "capabilities_checked": False, "gameplay_checked": False,
            "content_access_checked": False, "graphics_checked": False, "note": NOTE}


def commands_for(facts, target_commit=None, pin_fresh_install=False):
    _validate(facts)
    if not facts["flatpak_available"]:
        return []
    if facts["installed"]:
        if (not pin_fresh_install or facts["scope"] != "user" or not target_commit
                or facts.get("commit") == target_commit):
            return []
        return [["flatpak", "update", "--user", "--noninteractive", "-y",
                 "--commit=" + target_commit, APP]]
    commands = []
    if not facts["remote_present"]:
        commands.append(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", REMOTE_DESCRIPTOR])
    commands.append(["flatpak", "install", "--user", "--noninteractive", "-y",
                     "flathub", REF])
    if target_commit:
        commands.append(["flatpak", "update", "--user", "--noninteractive", "-y",
                         "--commit=" + target_commit, APP])
    return commands


def make_plan(facts, target_commit=None):
    if target_commit is not None and (
            not isinstance(target_commit, str) or not re.fullmatch(r"[a-f0-9]{64}", target_commit)):
        raise DependencyError("Invalid evidence-backed UZDoom commit.")
    _verify_remote_commit(facts, target_commit)
    commands = commands_for(facts, target_commit,
                            pin_fresh_install=bool(target_commit) and not facts["installed"])
    notes = ["No named installations, system writes, elevation or upgrades.",
             "Shared UZDoom and its runtime remain installed if game installation later fails.",
             "Cancellation waits for an active transaction to finish.", NOTE]
    if target_commit and commands:
        notes.append("Fresh user-scope install is pinned to evidence-backed commit " + target_commit
                     + "; the exact commit is verified before installation. Existing copies are never changed.")
    return {"plan_version": 1, "operation": "prepare-dependency", "dependency": APP,
            "scope": facts["scope"], "dependencies": {"uzdoom": facts}, "actions": [],
            "target_commit": target_commit, "dependency_commands": commands,
            "manual_actions": [{"action_id": "uzdoom-capability-check", "message": NOTE}],
            "notes": notes}


def _verify_remote_commit(facts, target_commit):
    if target_commit and facts["remote_present"]:
        try:
            info = _metadata(probe(
                "remote-info", "--" + facts["scope"], "--commit=" + target_commit, "flathub", REF))
        except DependencyError as e:
            raise DependencyError(
                f"Required tested UZDoom commit {target_commit} is unavailable from the selected Flathub remote: {e}") from e
        if info.get("Commit") != target_commit:
            raise DependencyError(
                f"Flathub did not confirm the exact required UZDoom commit {target_commit}.")


def _journal(path, job_id):
    if not path.exists():
        return []
    previous = json.loads(path.read_text())
    if previous.get("job_id") != job_id or previous.get("dependency") != APP:
        raise DependencyError("Dependency journal belongs to a different job/dependency.")
    if previous.get("active_command", True) is not None or previous.get("detection_pending") is not False:
        raise DependencyError("An earlier dependency transaction is uncertain; reconcile manually before retry.")
    if not isinstance(previous.get("completed"), list) or not isinstance(previous.get("attempts"), list):
        raise DependencyError("Malformed dependency transaction journal; reconcile manually.")
    return previous["attempts"] + [{"completed": previous["completed"]}]


def run(context):
    """Jobs context CLI: preflight proposes commands; apply requires the exact approved envelope."""
    phase = context["phase"]
    facts, completed, plan = None, [], None
    code, outcome, message = 0, "succeeded", "UZDoom prepared; CLI and gameplay remain untested."
    result_path = Path(context["result_file"])
    cancel = Path(context["cancel_file"])
    journal = result_path.parent / "dependency-transactions.json"

    def save(**fields):
        _write_durable(journal, (json.dumps(
            {"job_id": context["job_id"], "dependency": APP, "attempts": attempts,
             "completed": completed, **fields}, sort_keys=True) + "\n").encode())

    try:
        if phase not in ("preflight", "apply") or context.get("scope", "auto") != "auto":
            raise DependencyError("Unsupported dependency phase/scope; installation selection is automatic.")
        if cancel == result_path or cancel.parent != result_path.parent:
            raise DependencyError("Distinct job-local result/cancel paths required.")
        if cancel.exists():
            code, outcome, message = 130, "cancelled", "Cancelled before dependency work."
        else:
            attempts = _journal(journal, context["job_id"])
            facts = detect()
            target_commit = context.get("target_commit")
            if target_commit is not None and (
                    not isinstance(target_commit, str) or not re.fullmatch(r"[a-f0-9]{64}", target_commit)):
                raise DependencyError("Invalid evidence-backed UZDoom commit.")
            if not facts["flatpak_available"]:
                code, outcome, message = 20, "needs_action", (
                    "Flatpak is missing. On Ubuntu 24.04, run `sudo apt update` then "
                    "`sudo apt install flatpak`; retry after installation. Momentum cannot elevate.")
            elif facts.get("running"):
                code, outcome, message = 20, "needs_action", "Close UZDoom before dependency preparation."
            elif phase == "preflight":
                plan = make_plan(facts, target_commit)
                message = ("Review exact user-only dependency commands. Existing UZDoom is never changed; "
                           "a fresh install is pinned only when package evidence supplies a tested commit.")
            else:
                approved = Path(context["approved_plan_file"])
                if approved.parent != result_path.parent or approved in (result_path, cancel, journal):
                    raise DependencyError("Approved dependency plan must be a distinct job-local file.")
                raw = approved.read_bytes()
                if "sha256:" + hashlib.sha256(raw).hexdigest() != context["approved_plan_digest"]:
                    raise DependencyError("The saved dependency plan changed; obtain a new approval.")
                envelope = json.loads(raw)
                plan = envelope.get("plan")
                if (envelope.get("result_version") != 1 or envelope.get("job_id") != context["job_id"]
                        or envelope.get("operation") != "prepare-dependency"
                        or envelope.get("outcome") != "succeeded" or envelope.get("phase") != "preflight"
                        or envelope.get("dependencies") != {"uzdoom": facts}
                        or plan != make_plan(facts, target_commit)):
                    code, outcome, message = 30, "conflicted", "Dependency facts/envelope changed; review a new preflight."
                else:
                    for index, argv in enumerate(plan["dependency_commands"]):
                        if cancel.exists():
                            code, outcome, message = 130, "cancelled", "Cancelled between dependency transactions."
                            break
                        fresh = detect()
                        if (fresh != facts or commands_for(
                                fresh, target_commit, pin_fresh_install=bool(target_commit))
                                != plan["dependency_commands"][index:]):
                            facts = fresh
                            code, outcome, message = 30, "conflicted", (
                                "Dependency facts changed during preparation; review a fresh plan. No upgrade attempted.")
                            break
                        if cancel.exists():
                            code, outcome, message = 130, "cancelled", "Cancelled before the next Flatpak transaction."
                            break
                        emit("step_started", " ".join(argv), step="resolve")
                        save(active_command=argv, detection_pending=False, before=facts)
                        # Never kill or time out an active Flatpak transaction, even after cancellation.
                        transaction_result = subprocess.run(
                            argv, stdin=subprocess.DEVNULL, stdout=sys.stderr, stderr=sys.stderr,
                            env={**os.environ, "LC_ALL": "C"})
                        transaction = {"argv": argv, "exit_code": transaction_result.returncode}
                        completed.append(transaction)
                        save(active_command=None, detection_pending=True)
                        facts = detect()
                        transaction["observed"] = facts
                        save(active_command=None, detection_pending=False, after=facts)
                        if transaction_result.returncode == 0 and argv[1] == "remote-add" and target_commit:
                            _verify_remote_commit(facts, target_commit)
                        if cancel.exists():
                            code, outcome, message = 130, "cancelled", (
                                "Cancellation acknowledged after Flatpak finished; dependency changes retained.")
                            break
                        if transaction_result.returncode:
                            code, outcome, message = 40, "failed", (
                                f"Flatpak transaction failed (exit {transaction_result.returncode}); changes retained.")
                            break
                        if argv[1] == "install" and facts["scope"] != "user":
                            code, outcome, message = 30, "conflicted", (
                                "The approved user installation was not detected; review a fresh plan.")
                            break
                        emit("step_completed", "Transaction finished; detected state recorded.", step="resolve")
                    if code == 0:
                        observed = detect()
                        if observed != facts:
                            facts = observed
                            code, outcome, message = 30, "conflicted", "Dependency changed after preparation; review again."
                        elif not facts["installed"]:
                            raise DependencyError("Flatpak returned success but the exact UZDoom app was not detected.")
                        elif target_commit and facts.get("commit") != target_commit:
                            raise DependencyError(
                                f"UZDoom did not reach required tested commit {target_commit}; "
                                f"observed {facts.get('commit') or 'unknown'}. No game files were installed.")
                        elif cancel.exists():
                            code, outcome, message = 130, "cancelled", "Cancellation acknowledged; dependency retained."
    except (DependencyError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        code, outcome, message = 40, "failed", str(exc)
        print(message, file=sys.stderr)
    result = {"result_version": 1, "job_id": context["job_id"], "phase": phase,
              "operation": "prepare-dependency", "outcome": outcome, "message": message,
              "dependencies": {"uzdoom": facts}, "completed_transactions": completed}
    if plan is not None:
        result["plan"] = plan
    _write_durable(result_path, (json.dumps(result, sort_keys=True) + "\n").encode())
    if outcome == "needs_action":
        emit("needs_action", message, action_id="uzdoom-prerequisites", blocks_play=True)
    elif phase == "apply" and outcome == "succeeded":
        emit("needs_action", NOTE, action_id="uzdoom-capability-check", blocks_play=True)
    emit("result", message, outcome=outcome)
    return code


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--context":
        sys.exit("Usage: uzdoom.py --context /absolute/context.json")
    sys.exit(run(json.loads(Path(sys.argv[2]).read_text())))
