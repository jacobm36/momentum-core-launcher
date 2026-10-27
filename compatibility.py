"""Read exact installer evidence without executing a package or probing software."""
import hashlib
import http.client
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RELEASE_URL = "https://github.com/jacobm36/momentum-distribution/releases/latest"
REMOTE_INDEX_URL = ("https://raw.githubusercontent.com/jacobm36/momentum-distribution/main/"
                    "support/compatibility-v1.json")
REMOTE_SIGNATURE_URL = REMOTE_INDEX_URL + ".sig"
MAX_REMOTE_INDEX = 512 << 10
REMOTE_TIMEOUT = 20
REFRESH_SECONDS = 300
PUBLIC_KEY = "docs/support-data-public.pem"
REMOTE_CACHE = ".local/share/momentum-core/support-data/compatibility-v1.json"
REMOTE_CACHE_SIG = REMOTE_CACHE + ".sig"

_state = {}


def software_builds(record):
    return [record["software"], *record.get("additional_software", [])]


def _transport_url(url):
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment or not (host in ("github.com", "raw.githubusercontent.com")
                                      or host.endswith(".githubusercontent.com"))):
        raise ValueError("Compatibility data redirected outside GitHub's HTTPS delivery hosts")


class _GitHubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _transport_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url):
    _transport_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "Momentum-Core-Launcher",
                                                   "Accept-Encoding": "identity"})
    return urllib.request.build_opener(_GitHubRedirect()).open(request, timeout=REMOTE_TIMEOUT)


def _fetch_bytes(url, maximum):
    with _open(url) as response:
        _transport_url(response.geturl())
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Compatibility data payload is too large")
    return data


def _write_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _verify(public_key, payload, signature):
    with tempfile.TemporaryDirectory(prefix="mcl-compat-signature-") as temporary:
        root = Path(temporary)
        data = root / "compatibility-v1.json"
        sig = root / "compatibility-v1.json.sig"
        data.write_bytes(payload)
        sig.write_bytes(signature)
        check = subprocess.run(
            ["openssl", "dgst", "-sha256", "-verify", str(public_key), "-signature", str(sig), str(data)],
            capture_output=True, text=True)
    if check.returncode != 0:
        raise ValueError("Compatibility data signature verification failed")


def _normalize_record(record):
    if not isinstance(record, dict):
        raise ValueError("Invalid compatibility record")
    required = ("id", "version", "digest", "runtime", "installer_validated", "software")
    if any(key not in record for key in required):
        raise ValueError("Compatibility record is missing required fields")
    normalized = dict(record)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", normalized["id"]):
        raise ValueError("Invalid compatibility package id")
    if not re.fullmatch(r"\d+\.\d+\.\d+", normalized["version"]):
        raise ValueError("Invalid compatibility package version")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", normalized["digest"]):
        raise ValueError("Invalid compatibility package digest")
    if normalized["installer_validated"] is not True:
        raise ValueError("Compatibility record must be installer_validated=true")
    software = normalized["software"]
    if not isinstance(software, dict):
        raise ValueError("Compatibility software metadata is invalid")
    for build in [software, *normalized.get("additional_software", [])]:
        if not isinstance(build, dict):
            raise ValueError("Additional compatibility software metadata is invalid")
        for key in ("sha256", "commit", "games_xml_sha256"):
            value = build.get(key)
            if value is not None and not re.fullmatch(r"[a-f0-9]{64}", value):
                raise ValueError(f"Invalid compatibility software {key}")
    return normalized


def _local_records(launcher):
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
    return [_normalize_record(record) for record in result]


def _remote_records(launcher):
    root = Path(launcher)
    key = root / PUBLIC_KEY
    if not key.is_file():
        raise ValueError("Compatibility signing public key is missing")
    data = _fetch_bytes(REMOTE_INDEX_URL, MAX_REMOTE_INDEX)
    signature = _fetch_bytes(REMOTE_SIGNATURE_URL, 8 << 10)
    _verify(key, data, signature)
    payload = json.loads(data)
    if payload.get("format_version") != 1 or not isinstance(payload.get("records"), list):
        raise ValueError("Unsupported compatibility data format")
    records = [_normalize_record(record) for record in payload["records"]]
    cache = Path.home() / REMOTE_CACHE
    cache_sig = Path.home() / REMOTE_CACHE_SIG
    _write_atomic(cache, data)
    _write_atomic(cache_sig, signature)
    return records


def _cached_remote_records(launcher):
    root = Path(launcher)
    key = root / PUBLIC_KEY
    cache = Path.home() / REMOTE_CACHE
    cache_sig = Path.home() / REMOTE_CACHE_SIG
    if not (key.is_file() and cache.is_file() and cache_sig.is_file()):
        return []
    data = cache.read_bytes()
    if len(data) > MAX_REMOTE_INDEX:
        return []
    signature = cache_sig.read_bytes()
    try:
        _verify(key, data, signature)
        payload = json.loads(data)
        if payload.get("format_version") != 1 or not isinstance(payload.get("records"), list):
            return []
        return [_normalize_record(record) for record in payload["records"]]
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
        return []


def _remote_records_resilient(launcher):
    token = str(Path(launcher).resolve())
    now = time.monotonic()
    state = _state.get(token)
    if state and now - state["updated_at"] < REFRESH_SECONDS:
        return state["records"]
    records = None
    try:
        records = _remote_records(launcher)
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError,
            json.JSONDecodeError, subprocess.SubprocessError):
        records = _cached_remote_records(launcher)
    _state[token] = {"updated_at": now, "records": records}
    return records


def records(launcher):
    merged = {}
    for record in [*_local_records(launcher), *_remote_records_resilient(launcher)]:
        key = (record["id"], record["version"], record["digest"])
        existing = merged.get(key)
        if existing is None:
            merged[key] = record
        elif existing != record:
            raise ValueError("Conflicting compatibility evidence records")
    return list(merged.values())


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
                           "A newer package may require refreshed support data or a launcher update. "
                           "If the latest launcher still blocks it, the publisher must validate this version; "
                           "do not bypass approval.",
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
