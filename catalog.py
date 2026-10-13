#!/usr/bin/env python3
"""Public Momentum catalog and bounded, verified package downloads; never runs package code."""
import hashlib
import http.client
import json
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import packages
from jobs import _write_durable

REPOSITORY = "jacobm36/momentum-distribution"
CATALOG_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/main/catalog.json"
MAX_CATALOG = 256 << 10
MAX_DOWNLOAD = 512 << 20
TIMEOUT = 20
MAX_SECONDS = 600
PILLARS = ("openbor", "mouse-arcade", "boomer-shooters")


class CatalogError(ValueError):
    pass


def _transport_url(url):
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment or not (host in ("github.com", "raw.githubusercontent.com")
                                      or host.endswith(".githubusercontent.com"))):
        raise CatalogError("Download redirected outside GitHub's HTTPS delivery hosts")


class GitHubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _transport_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url):
    _transport_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "Momentum-Core-Launcher",
                                                  "Accept-Encoding": "identity"})
    return urllib.request.build_opener(GitHubRedirect()).open(request, timeout=TIMEOUT)


def validate(data):
    if not isinstance(data, dict) or data.get("catalog_version") != 1:
        raise CatalogError("Unsupported game catalog format")
    games = data.get("games")
    if not isinstance(games, list) or len(games) > 100:
        raise CatalogError("Invalid game catalog entries")
    seen = set()
    for game in games:
        if not isinstance(game, dict):
            raise CatalogError("Invalid game catalog entry")
        for key, maximum in (("id", 64), ("version", 40), ("name", 160), ("description", 1000)):
            if not isinstance(game.get(key), str) or not 0 < len(game[key]) <= maximum:
                raise CatalogError(f"Invalid catalog {key}")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", game["id"]) or not re.fullmatch(
                r"\d+\.\d+\.\d+", game["version"]) or game["id"] in seen:
            raise CatalogError("Invalid or duplicate catalog game identity")
        seen.add(game["id"])
        identity = f"{game['id']}-{game['version']}"
        expected = f"https://github.com/{REPOSITORY}/releases/download/{identity}/{identity}.zip"
        if game.get("url") != expected:
            raise CatalogError("Installer URL must identify a fixed Momentum release")
        expected_icon = f"https://raw.githubusercontent.com/{REPOSITORY}/main/artwork/{game['id']}.png"
        if game.get("icon_url") != expected_icon:
            raise CatalogError("Invalid catalog artwork URL")
        if not isinstance(game.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", game["sha256"]):
            raise CatalogError("Invalid installer ZIP checksum")
        if not isinstance(game.get("digest"), str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", game["digest"]):
            raise CatalogError("Invalid canonical package digest")
        if type(game.get("size")) is not int or not 0 < game["size"] <= MAX_DOWNLOAD:
            raise CatalogError("Invalid installer download size")
        if "pillar" in game and game["pillar"] not in PILLARS:
            raise CatalogError("Invalid catalog pillar")
        if "runtime" in game and (not isinstance(game["runtime"], str) or not 0 < len(game["runtime"]) <= 40):
            raise CatalogError("Invalid catalog runtime")
        if not isinstance(game.get("platform"), dict):
            raise CatalogError("Missing catalog platform")
        platform = game["platform"]
        if (not isinstance(platform.get("os"), str) or not platform["os"]
                or any(not isinstance(platform.get(key), list) or not platform[key]
                       or len(platform[key]) > 20
                       or any(not isinstance(value, str) or not 0 < len(value) <= 40 for value in platform[key])
                       for key in ("releases", "architectures"))):
            raise CatalogError("Invalid catalog platform values")
        try:
            issues = packages._platform_issues(game["platform"], {"minimum_python": "3.10"})
        except (TypeError, KeyError) as e:
            raise CatalogError(f"Invalid catalog platform: {e}") from e
        game["platform_issues"] = issues
    return data


def load():
    try:
        with _open(CATALOG_URL) as response:
            if response.geturl() != CATALOG_URL:
                raise CatalogError("Unexpected catalog redirect")
            raw = response.read(MAX_CATALOG + 1)
        if len(raw) > MAX_CATALOG:
            raise CatalogError("Game catalog is too large")
        return validate(json.loads(raw))
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
        raise CatalogError(f"Cannot load available games: {e}. Check your connection and try again.") from e


def download(entry, here, cancelled=lambda: False, progress=lambda current, total: None):
    validate({"catalog_version": 1, "games": [entry]})
    if entry["platform_issues"]:
        raise CatalogError("Unsupported platform: " + "; ".join(entry["platform_issues"]))
    started, count, digest = time.monotonic(), 0, hashlib.sha256()
    if cancelled():
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="mcl-download-") as tmp:
            archive = Path(tmp) / "installer.zip"
            with _open(entry["url"]) as response, archive.open("wb") as output:
                _transport_url(response.geturl())
                length = response.headers.get("Content-Length")
                if length is not None and int(length) != entry["size"]:
                    raise CatalogError("Installer download size differs from the catalog")
                progress(0, entry["size"])
                while True:
                    if cancelled():
                        return None
                    if time.monotonic() - started > MAX_SECONDS:
                        raise CatalogError("Installer download took too long; try again")
                    chunk = response.read(64 << 10)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > entry["size"]:
                        raise CatalogError("Installer download exceeds its expected size")
                    output.write(chunk)
                    digest.update(chunk)
                    progress(count, entry["size"])
            if cancelled():
                return None
            if count != entry["size"] or digest.hexdigest() != entry["sha256"]:
                raise CatalogError("Installer download is incomplete or its checksum does not match")
            checked = packages.check(archive)
            if (checked["id"], checked["version"], checked["digest"]) != (
                    entry["id"], entry["version"], entry["digest"]):
                raise CatalogError("Installer identity or package digest differs from the catalog")
            if checked["platform_issues"]:
                raise CatalogError("Unsupported package platform: " + "; ".join(checked["platform_issues"]))
            if cancelled():
                return None
            return packages.import_package(archive, here)
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, packages.PackageError) as e:
        raise CatalogError(f"Cannot download this game's installer: {e}") from e


def submit(here, runner, game_id):
    entry = next((g for g in load()["games"] if g["id"] == game_id), None)
    if entry is None:
        raise CatalogError("This game is no longer listed; refresh available games")
    if entry["platform_issues"]:
        raise CatalogError("Unsupported platform: " + "; ".join(entry["platform_issues"]))
    with runner.lock:
        for job in runner.jobs.values():
            if ((job.get("meta") or {}).get("kind") == "download" and job.get("game") == game_id
                    and job["status"] in ("queued", "running", "cancel-requested")):
                return job["id"]
        return runner.submit(f"Get {entry['name']}", [{
            "name": "Download and check installer", "protocol": True, "declared_steps": ["download"],
            "argv": [sys.executable, str(Path(__file__).resolve()), "--context", "{context_file}"],
            "context": {"entry": entry, "here": str(here)},
        }], game=game_id, meta={"kind": "download", "package_id": entry["id"],
                               "package_version": entry["version"], "package_digest": entry["digest"]})


def run(context):
    def emit(kind, message, **fields):
        print(json.dumps(dict(event_version=1, type=kind, message=message, **fields)), flush=True)

    emit("step_started", "Downloading game installer; no game files or scripts are run.", step="download")
    outcome, code, message = "succeeded", 0, "Installer ready. Choose your game files to continue."
    try:
        result = download(context["entry"], Path(context["here"]),
                          cancelled=lambda: Path(context["cancel_file"]).exists(),
                          progress=lambda current, total: emit("progress", "Downloading installer",
                                                               step="download", current=current, total=total, unit="bytes"))
        if result is None:
            outcome, code, message = "cancelled", 130, "Installer download cancelled."
        else:
            emit("step_completed", "Installer checks passed. No installation changes authorized.", step="download")
    except CatalogError as e:
        outcome, code, message = "failed", 40, str(e)
    _write_durable(Path(context["result_file"]),
                   (json.dumps({"outcome": outcome, "message": message}) + "\n").encode())
    emit("result", message, outcome=outcome)
    return code


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--context":
        sys.exit("Usage: catalog.py --context FILE")
    sys.exit(run(json.loads(Path(sys.argv[2]).read_text())))
