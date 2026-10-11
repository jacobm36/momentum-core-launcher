"""Pinned Episode Enyo acquisition through the publisher's anonymous download flow."""
import hashlib
import html
import http.cookiejar
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

from dependencies import DependencyError, emit
from jobs import _fsync_dir, _write_durable

PAGE = "https://poppyworks.itch.io/episode-enyo"
UPLOAD = "9503360"
ARCHIVE_SIZE = 139609760
ARCHIVE_SHA = "45ddd187e07af6b3d43a5f9f5597172e43aae7cebe73cdd2a5057ad6a36f570e"
PAK_SIZE = 277593155
PAK_SHA = "93b1fcc32084ca85bc2878e38e7a091eee6965134a36d968c50ce9d08bd4ec9c"
SOURCE = {"provider": "itchio", "page": PAGE, "upload_id": UPLOAD,
          "archive_size": ARCHIVE_SIZE, "archive_sha256": ARCHIVE_SHA,
          "pak_size": PAK_SIZE, "pak_sha256": PAK_SHA}


def safe(path):
    path = Path(path)
    if (not path.is_absolute() or ".." in path.parts
            or any(ord(c) < 32 or ord(c) == 127 for c in str(path))
            or any(p.is_symlink() for p in (path, *path.parents))):
        raise DependencyError(f"Unsafe Enyo source path: {path}")
    return path


def filehash(path, cancel=lambda: None):
    digest = hashlib.sha256()
    with safe(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            cancel()
            digest.update(chunk)
    return digest.hexdigest()


def cache_path():
    return Path.home() / ".cache/momentum-core/enyo" / PAK_SHA / "pak0.pak"


def enabled(package_root, digest):
    import packages
    root = safe(package_root)
    if packages.check(root)["digest"] != digest:
        raise DependencyError("Enyo package bytes changed before source preparation.")
    manifest = json.loads((root / "package.json").read_text())
    declaration = manifest.get("extensions", {}).get("mod_download")
    if declaration is None:
        return False
    if manifest["id"] != "quake-slave-zero-x" or declaration != SOURCE:
        raise DependencyError("Unrecognized Enyo publisher/source declaration.")
    return True


def verify(path, cancel=lambda: None):
    path = safe(path)
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_size != PAK_SIZE
            or filehash(path, cancel) != PAK_SHA):
        raise DependencyError(f"Enyo source differs from the tested publisher release: {path}")


def source_for(inputs, package_root, digest):
    if not enabled(package_root, digest):
        return None
    explicit = inputs.get("mod_dir")
    candidates = ([safe(explicit) / "pak0.pak"] if explicit else [
        safe(inputs["source_dir"]) / "enyo/pak0.pak", cache_path()])
    for candidate in candidates:
        safe(candidate)
        if os.path.lexists(candidate):
            verify(candidate)
            return candidate.parent
    if explicit:
        raise DependencyError("The selected Enyo folder lacks pak0.pak.")
    return None


def download_plan(context):
    source = source_for(context["inputs"], context["package_root"], context["package_digest"])
    return None if source is not None else {
        **SOURCE, "purpose": "mod-source", "target": str(cache_path()),
        "note": "Download through the publisher; no mod files are hosted by Momentum."}


def check_url(url):
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    allowed = (host == "poppyworks.itch.io" or host == "itch.io"
               or host.endswith(".hwcdn.net")
               or re.fullmatch(r"itchio-mirror\.[a-f0-9]{32}\.r2\.cloudflarestorage\.com", host))
    if (parsed.scheme != "https" or not allowed or parsed.username or parsed.password
            or parsed.port not in (None, 443)):
        raise DependencyError("Enyo publisher returned an unsupported download host or redirect.")


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(context, destination):
    import vkquake
    vkquake._cancel(context)
    opener = urllib.request.build_opener(
        Redirects(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with opener.open(PAGE, timeout=20) as response:
        check_url(response.geturl())
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise DependencyError("Enyo publisher page exceeds the expected response limit.")
    page = raw.decode("utf-8")
    token = re.search(r'<meta\s+name="csrf_token"\s+value="([^"]+)"', page)
    if not token or f'data-upload_id="{UPLOAD}"' not in page:
        raise DependencyError("Enyo publisher download flow changed; review is required.")
    request = urllib.request.Request(
        PAGE + "/file/" + UPLOAD,
        data=urllib.parse.urlencode({"csrf_token": html.unescape(token.group(1))}).encode(),
        headers={"Referer": PAGE, "Accept": "application/json",
                 "X-Requested-With": "XMLHttpRequest"})
    with opener.open(request, timeout=20) as response:
        check_url(response.geturl())
        raw = response.read(65537)
    if len(raw) > 65536:
        raise DependencyError("Enyo publisher download response exceeds its limit.")
    url = json.loads(raw).get("url")
    if not isinstance(url, str):
        raise DependencyError("Enyo publisher did not return a download URL.")
    check_url(url)
    deadline = time.monotonic() + 300
    digest, size = hashlib.sha256(), 0
    with opener.open(url, timeout=20) as response, destination.open("xb") as output:
        check_url(response.geturl())
        if response.headers.get("Content-Length") not in (None, str(ARCHIVE_SIZE)):
            raise DependencyError("Enyo publisher archive size changed.")
        while chunk := response.read(65536):
            vkquake._cancel(context)
            if time.monotonic() > deadline:
                raise DependencyError("Enyo download timed out.")
            size += len(chunk)
            if size > ARCHIVE_SIZE:
                raise DependencyError("Enyo archive exceeds the pinned size.")
            digest.update(chunk)
            output.write(chunk)
            emit("progress", "Downloading Episode Enyo from its publisher.", step="resolve",
                 current=size, total=ARCHIVE_SIZE, unit="bytes")
        output.flush()
        os.fsync(output.fileno())
    if size != ARCHIVE_SIZE or digest.hexdigest() != ARCHIVE_SHA:
        raise DependencyError("Enyo publisher archive checksum or size changed; nothing was installed.")


def extract(archive, destination, cancel=lambda: None):
    with zipfile.ZipFile(archive) as bundle:
        files = [entry for entry in bundle.infolist() if not entry.is_dir()]
        if (len(files) != 1 or files[0].filename != "enyo/pak0.pak"
                or files[0].file_size != PAK_SIZE
                or files[0].flag_bits & 1
                or stat.S_ISLNK(files[0].external_attr >> 16)):
            raise DependencyError("Enyo publisher archive layout changed.")
        with bundle.open(files[0]) as source, destination.open("xb") as output:
            size = 0
            while chunk := source.read(65536):
                cancel()
                size += len(chunk)
                if size > PAK_SIZE:
                    raise DependencyError("Enyo expanded content exceeds the pinned size.")
                output.write(chunk)
            output.flush()
            os.fchmod(output.fileno(), 0o644)
            os.fsync(output.fileno())
    verify(destination, cancel)


def prepare(context, journal, attempts, completed, facts):
    import vkquake
    if download_plan(context) is None:
        return
    target = safe(cache_path())
    vkquake._mkdir_durable(target.parent)
    import shutil
    if shutil.disk_usage(target.parent).free < ARCHIVE_SIZE + PAK_SIZE + 64 * 1024**2:
        raise DependencyError("Not enough free space to download and extract Enyo.")
    with tempfile.TemporaryDirectory(prefix=".enyo-download-", dir=target.parent) as temporary:
        root = Path(temporary)
        download(context, root / "download.zip")
        extract(root / "download.zip", root / "pak0.pak", lambda: vkquake._cancel(context))
        vkquake._cancel(context)
        if vkquake.detect() != facts:
            raise DependencyError("vkQuake changed during Enyo preparation; review again.")
        record = {"job_id": context["job_id"], "attempts": attempts, "completed": completed,
                  "active_command": ["publish-enyo", str(target)], "before": facts}
        _write_durable(journal, (json.dumps(record, sort_keys=True) + "\n").encode())
        vkquake._publish(root / "pak0.pak", target)
        completed.append({"target": str(target), "sha256": PAK_SHA, "purpose": "mod-source"})
        record.update(active_command=None, detection_pending=True)
        _write_durable(journal, (json.dumps(record, sort_keys=True) + "\n").encode())
        verify(target)
        record.update(detection_pending=False, after=facts)
        _write_durable(journal, (json.dumps(record, sort_keys=True) + "\n").encode())
    emit("step_completed", "Verified Enyo source prepared; game installation needs separate approval.",
         step="resolve")
