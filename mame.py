"""Read-only detection of the exact Time Crisis II MAME Flatpak build."""
import configparser
import re
import shutil
import time

from dependencies import DependencyError, probe, REMOTE_URL

APP = "org.mamedev.MAME"
VERSION = "0.289"
COMMIT = "41ebdb5c266627f4d1f02ba11f8109e793d2381081b68afc48714dd48a703788"
REF = f"app/{APP}/x86_64/stable"
RUNTIME = "org.kde.Platform/x86_64/6.11"
RUNTIME_COMMIT = "fe192771c0992ad873e6a9ccc6e4f087c76314ce5ced165650cc7ea045a6bbaa"


def running(facts=None):
    if not shutil.which("flatpak"):
        return False
    deadline = time.monotonic() + 5
    while APP in probe("ps", "--columns=application").splitlines():
        if time.monotonic() >= deadline:
            return True
        time.sleep(.1)
    return False


def detect():
    candidates = discover()
    return candidates[0] if candidates else missing()


def missing():
    return {"provider": "flatpak", "scope": "user", "app_id": APP,
            "arch": "x86_64", "branch": "stable", "origin": "flathub",
            "flatpak_available": bool(shutil.which("flatpak")),
            "installed": False, "remote_present": False, "version": None, "commit": None,
            "capabilities_checked": False, "running": False,
            "launch_argv": ["flatpak", "run", "--user", APP],
            "capability_note": "Metadata only; package gameplay requires separate acceptance."}


def discover():
    if not shutil.which("flatpak"):
        return []
    candidates = []
    for scope in ("user", "system"):
        rows = [line.split("\t") for line in probe(
            "list", "--" + scope, "--app", "--columns=application,arch,branch,origin").splitlines()]
        matches = [row for row in rows if row[0] == APP]
        if not matches:
            continue
        if matches != [[APP, "x86_64", "stable", "flathub"]]:
            raise DependencyError(f"Unexpected MAME ref/origin in {scope}; reconcile manually.")
        remotes = [line.split("\t") for line in probe(
            "remotes", "--" + scope, "--columns=name,url").splitlines()]
        trusted = [row for row in remotes if row[0] == "flathub"]
        if len(trusted) != 1 or trusted[0] not in (
                ["flathub", REMOTE_URL], ["flathub", REMOTE_URL.rstrip("/")]):
            raise DependencyError("MAME requires the trusted Flathub remote.")
        info = probe("info", "--" + scope, APP)
        values = {}
        for key in ("Ref", "Version", "Commit"):
            fields = re.findall(r"^\s*" + key + r":\s*(.*?)\s*$", info, re.M)
            if len(fields) != 1:
                raise DependencyError("Incomplete or duplicate MAME metadata: " + key)
            values[key] = fields[0]
        if (values["Ref"] != REF or not re.fullmatch(r"[a-f0-9]{64}", values["Commit"])
                or values["Commit"] != probe("info", "--" + scope, "--show-commit", APP).strip()):
            raise DependencyError("MAME identity changed during detection.")
        facts = missing()
        facts.update(scope=scope, installed=True, remote_present=True,
                     version=values["Version"], commit=values["Commit"],
                     launch_argv=["flatpak", "run", "--" + scope, APP],
                     location=f"Flatpak ({scope})", running=running())
        candidates.append(facts)
    return candidates


def check_host(facts):
    if (facts.get("scope") not in ("user", "system") or facts.get("app_id") != APP
            or facts.get("provider") != "flatpak" or not facts.get("installed")
            or facts.get("version") != VERSION or facts.get("commit") != COMMIT
            or facts.get("launch_argv") != ["flatpak", "run", "--" + facts["scope"], APP]):
        raise DependencyError("Only the exact approved MAME 0.289 build is supported.")
    selected = "--" + facts["scope"]
    if (probe("info", selected, "--show-ref", APP).strip() != REF
            or probe("info", selected, "--show-commit", APP).strip() != COMMIT):
        raise DependencyError("MAME ref/commit changed; review setup again.")
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(probe("info", selected, "--show-metadata", APP))
        app = parser["Application"]
        if (app["name"], app["command"], app["runtime"]) != (APP, "mame", RUNTIME):
            raise DependencyError("Unexpected MAME application/runtime metadata.")
    except (configparser.Error, KeyError) as exc:
        raise DependencyError(f"Malformed MAME metadata: {exc}") from exc
    if probe("info", selected, "--show-runtime", APP).strip() != RUNTIME:
        raise DependencyError("MAME runtime declaration changed.")
    runtime_scope = None
    for candidate in (("user", "system") if facts["scope"] == "user" else ("system",)):
        if RUNTIME in probe("list", "--" + candidate, "--runtime", "--columns=ref").splitlines():
            runtime_scope = candidate
            break
    if runtime_scope is None or probe(
            "info", "--" + runtime_scope, "--show-commit", RUNTIME).strip() != RUNTIME_COMMIT:
        raise DependencyError("The approved MAME runtime commit is not deployed.")
    return {"metadata_checked": True, "runtime_installed": True, "runtime": RUNTIME,
            "runtime_scope": runtime_scope, "runtime_commit": RUNTIME_COMMIT,
            "capabilities_checked": False, "gameplay_checked": False}
