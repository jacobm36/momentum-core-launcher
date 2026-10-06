"""Reconcile successful package proposals against approval, intents and filesystem evidence."""
import hashlib
import json
import os
import stat
from pathlib import Path

import mcl_intent


class OwnershipError(ValueError):
    pass


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def packed(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def safe_path(value):
    if not isinstance(value, str) or not value.startswith("/") or any(c in value for c in "\0\r\n"):
        raise OwnershipError("Resource path must be absolute and free of control characters")
    path = Path(value)
    if ".." in path.parts or str(path) != value:
        raise OwnershipError(f"Noncanonical resource path: {value}")
    for node in (path, *path.parents):
        if node.is_symlink():
            raise OwnershipError(f"Symlink resource is not supported: {node}")
    return path


def fact(value):
    path = safe_path(str(value))
    try:
        info = path.stat()
    except FileNotFoundError:
        return {"kind": "absent", "sha256": None}
    if stat.S_ISREG(info.st_mode):
        h = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                h.update(chunk)
        return {"kind": "file", "sha256": h.hexdigest(), "mode": stat.S_IMODE(info.st_mode)}
    if stat.S_ISDIR(info.st_mode):
        return {"kind": "directory", "sha256": None}
    raise OwnershipError(f"Special resource is not supported: {path}")


def matches(actual, expected):
    return actual["kind"] == expected["kind"] and all(
        actual.get(key) == expected[key] for key in ("sha256", "mode") if key in expected)


def inventory_paths(action, job_dir, game):
    after = action["after"]
    inv = safe_path(after["inventory"])
    if inv.parent != job_dir:
        raise OwnershipError("Publication inventory must be job-local")
    raw = inv.read_bytes()
    if hashlib.sha256(raw).hexdigest() != after.get("inventory_sha256"):
        raise OwnershipError("Publication inventory digest mismatch")
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise OwnershipError("Publication inventory must be a list")
    resources = {str(game): {"kind": "directory", "sha256": None}}
    for row in rows:
        rel = row.get("relative_path") if isinstance(row, dict) else None
        if not isinstance(rel, str) or Path(rel).is_absolute() or ".." in Path(rel).parts or not rel:
            raise OwnershipError("Invalid inventory relative path")
        path = safe_path(str(game / rel))
        if not path.is_relative_to(game) or str(path) in resources:
            raise OwnershipError("Duplicate or escaping inventory path")
        if not isinstance(row.get("sha256"), str) or not mcl_intent.HEX64.fullmatch(row["sha256"]):
            raise OwnershipError("Invalid inventory hash")
        resources[str(path)] = {"kind": "file", "sha256": row["sha256"], "mode": 0o644}
        for parent in path.parents:
            if parent == game:
                break
            resources.setdefault(str(parent), {"kind": "directory", "sha256": None})
    return rows, resources


def reconcile(job, result, paths):
    """No filesystem existence alone grants ownership. Uncertain/contradictory evidence stops."""
    context = job["steps"][-1]["context"]
    raw = paths["approved_plan_file"].read_bytes()
    if digest(raw) != job.get("approved_plan_digest"):
        raise OwnershipError("Approved plan bytes changed")
    envelope = json.loads(raw)
    if envelope.get("outcome") != "succeeded" or envelope.get("phase") != "preflight":
        raise OwnershipError("Only successful preflight plans authorize a commit")
    plan = envelope["plan"]
    for key in ("package_id", "package_version", "package_digest", "operation", "inputs",
                "game_directory", "paths", "catalog_entry_id"):
        if plan.get(key) != context.get(key):
            raise OwnershipError(f"Approved plan {key} does not match context")
    if plan.get("job_id") != job["id"] or result.get("job_id") != job["id"]:
        raise OwnershipError("Job identity mismatch")
    previous = context.get("previous_receipt")
    if plan.get("previous_receipt_digest") != hashlib.sha256(packed(previous)).hexdigest():
        raise OwnershipError("Approved previous receipt mismatch")
    for key in ("package_id", "package_version", "package_digest", "operation", "game_directory",
                "paths", "catalog_entry_id"):
        if result.get(key) != context.get(key):
            raise OwnershipError(f"Result {key} does not match context")
    if result.get("phase") != "apply" or result.get("outcome") != "succeeded" or result.get("receipt_committed") is not False:
        raise OwnershipError("Invalid apply proposal phase or commit claim")
    if result.get("installation") not in ("installed", "removed") or result.get("readiness") not in (
            "unknown", "setup-required", "checks-passed"):
        raise OwnershipError("Unsupported installation/readiness proposal; gameplay cannot be inferred")
    records, truncated, bad = mcl_intent.read(paths["intent_file"])
    if truncated or bad:
        raise OwnershipError("Intent file is incomplete or malformed")
    actions = plan.get("actions")
    changes = result.get("published_changes")
    if not isinstance(actions, list) or not isinstance(changes, list) or len(actions) != len(records):
        raise OwnershipError("Successful apply must account for every approved action and intent")
    observed = {}
    for change in changes:
        seq = change.get("intent_seq") if isinstance(change, dict) else None
        if not isinstance(seq, int) or seq in observed:
            raise OwnershipError("Invalid or duplicate observed intent sequence")
        observed[seq] = change
    game = safe_path(context["game_directory"])
    support = safe_path(context["paths"]["support"])
    old = {r["path"]: r for r in (previous or {}).get("resources", [])}
    evidence = dict(old)
    for seq, (record, action) in enumerate(zip(records, actions), 1):
        why = mcl_intent.validate(record, seq - 1, job["id"])
        if why or record["seq"] != seq:
            raise OwnershipError(f"Invalid intent {seq}: {why or 'sequence gap'}")
        if record["step"] not in job["steps"][-1]["declared_steps"]:
            raise OwnershipError("Undeclared intent step")
        for key in ("path", "op", "ownership", "before", "after", "backup"):
            if record.get(key) != action.get(key):
                raise OwnershipError(f"Intent {seq} differs from approved action: {key}")
        path = safe_path(record["path"])
        change = observed.get(seq)
        if not change or change.get("path") != str(path) or change.get("ownership") != record["ownership"]:
            raise OwnershipError("Intent lacks matching observed completion")
        after = record["after"]
        if not matches(change, after):
            raise OwnershipError("Observed change contradicts intent")
        # A staging directory is consumed by the approved no-replace publication.
        consumed = after["kind"] == "directory" and "inventory" in after and record["op"] != "publish"
        if consumed:
            if not any(a["op"] == "publish" and a["path"] == str(game) for a in actions):
                raise OwnershipError("Staged inventory lacks approved publication")
            if path.exists():
                raise OwnershipError("Successful publication left its staging directory behind")
        elif not matches(fact(path), after):
            raise OwnershipError(f"Filesystem contradicts completed intent: {path}")
        if record["op"] == "publish":
            if path != game or record["before"]["kind"] != "absent" or record["ownership"] != "managed":
                raise OwnershipError("Game publication cannot adopt an existing directory")
            rows, media = inventory_paths(record, paths["job_dir"], game)
            if rows != plan.get("media_inventory"):
                raise OwnershipError("Durable inventory differs from approved media")
            owners = plan.get("media_ownership", {})
            for name, expected in media.items():
                if not matches(fact(name), expected):
                    raise OwnershipError(f"Published inventory mismatch: {name}")
                ownership = owners.get(Path(name).relative_to(game).as_posix()) if expected["kind"] == "file" else "managed"
                if ownership not in ("managed", "user-state"):
                    raise OwnershipError("Missing or invalid media ownership")
                evidence[name] = dict(expected, path=name, ownership=ownership)
        elif path == game or path.is_relative_to(game) or path.is_relative_to(support) or str(path) in (
                context["paths"]["launcher"], context["paths"]["desktop_entry"], context["paths"]["icon"]):
            if after["kind"] == "absent":
                evidence.pop(str(path), None)
            else:
                if record["before"]["kind"] != "absent" and str(path) not in old:
                    raise OwnershipError(f"Replacement has no established ownership: {path}")
                if str(path) in old and old[str(path)]["ownership"] != record["ownership"]:
                    raise OwnershipError("A mutation cannot silently change existing resource ownership")
                evidence[str(path)] = dict(change)
    if set(observed) != set(range(1, len(records) + 1)):
        raise OwnershipError("Unexpected observed mutations")
    resources = result.get("resources")
    if not isinstance(resources, list):
        raise OwnershipError("Resources must be a list")
    seen = set()
    for resource in resources:
        name = resource.get("path") if isinstance(resource, dict) else None
        path = safe_path(name)
        if name in seen or name not in evidence:
            raise OwnershipError(f"Ownership lacks approved mutation or previous receipt evidence: {name}")
        seen.add(name)
        expected = evidence[name]
        comparison = expected
        if name in old and expected["ownership"] in ("user-state", "borrowed"):
            # These are retained facts, never deletion grants. Their contents may legitimately evolve.
            comparison = {"kind": expected["kind"]}
        if resource.get("ownership") != expected.get("ownership") or not matches(resource, comparison):
            raise OwnershipError(f"Resource ownership/hash differs from evidence: {name}")
        if not matches(fact(path), resource):
            raise OwnershipError(f"Resource changed before receipt commit: {name}")
    if set(evidence) != seen:
        raise OwnershipError("Proposal dropped retained ownership resources")
    if not records and not previous:
        raise OwnershipError("A fresh installation cannot claim ownership without intents")
    proposal = result.get("catalog_proposal")
    if not isinstance(proposal, dict):
        raise OwnershipError("Missing catalog proposal")
    if result["installation"] == "installed":
        if proposal.get("launch_argv") != [context["paths"]["launcher"]] or proposal.get("working_directory") != str(game):
            raise OwnershipError("Launch facts differ from validated installation paths")
        if context["paths"]["launcher"] not in seen:
            raise OwnershipError("No validated launcher resource")
    elif proposal.get("launch_argv") != [] or proposal.get("working_directory") is not None:
        raise OwnershipError("Removed installations cannot publish launch commands")
    return plan
