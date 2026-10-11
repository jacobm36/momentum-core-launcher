"""Read exact installer evidence without executing a package or probing software."""
import json
from pathlib import Path

RELEASE_URL = "https://github.com/jacobm36/momentum-distribution/releases/latest"


def software_builds(record):
    return [record["software"], *record.get("additional_software", [])]


def records(launcher):
    docs = Path(launcher) / "docs"
    result = []
    for path in sorted(docs.glob("*-installer-evidence.json")):
        result.extend(json.loads(path.read_text())["packages"])
    hod = json.loads((docs / "hod2-target-evidence.json").read_text())
    for revision in [{"version": hod["package_version"], "digest": hod["package_digest"]},
                     *hod.get("derived_packages", [])]:
        result.append({
            "id": hod["package_id"], "version": revision["version"], "digest": revision["digest"],
            "runtime": "flycast", "installer_validated": True,
            "software": {"provider": hod["provider"], "scope": hod["scope"],
                         "app_id": hod["app_id"], "version": hod["emulator_version"],
                         "commit": hod["emulator_commit"]},
            "additional_software": revision.get("additional_software", []),
        })
    return result


def find_record(launcher, package_id, version, digest):
    matches = [r for r in records(launcher)
               if (r["id"], r["version"], r["digest"]) == (package_id, version, digest)]
    if len(matches) > 1:
        raise ValueError("Duplicate exact compatibility evidence")
    return matches[0] if matches else None


def guidance(platform_issues, supported, enabled, prerequisites, facts):
    if platform_issues:
        return {"reason": "unsupported-platform", "title": "This platform is not supported",
                "message": "; ".join(platform_issues)}
    if not supported:
        return {"reason": "missing-evidence", "title": "Update Momentum or check package support",
                "message": "This launcher has no approved evidence for these exact package bytes. "
                           "A newer package may require a launcher update. If the latest launcher still blocks it, "
                           "the publisher must validate this version; do not bypass approval.",
                "url": RELEASE_URL}
    if prerequisites:
        return {"reason": "host-prerequisites", "title": "Action required: install system prerequisites",
                "message": "Run the commands below yourself, then return and start a new setup review. "
                           "Momentum does not install these system packages automatically."}
    if not enabled and any(f.get("installed") for f in facts.values()):
        return {"reason": "software-mismatch", "title": "This installed engine build has not been validated",
                "message": "No tested existing copy was found for this package. This is not proof that the "
                           "engine is broken. Check the supported and detected builds below. Momentum leaves "
                           "existing copies untouched; automatic upgrades and downgrades are not performed."}
    if not enabled:
        return {"reason": "software-missing", "title": "Required software needs preparation",
                "message": "Review the required software preparation before installing the game."}
    return None
