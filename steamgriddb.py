"""SteamGridDB artwork lookup; credentials stay outside launcher/library data."""
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request


class GridError(ValueError):
    pass


def key_path():
    return Path.home() / ".config" / "momentum-core" / "steamgriddb-key"


def read_key():
    try:
        return key_path().read_text().strip()
    except FileNotFoundError:
        return ""


def save_key(value):
    if not isinstance(value, str) or (value and not re.fullmatch(r"[a-fA-F0-9]{32}", value)):
        raise GridError("Enter a 32-character SteamGridDB API key, or leave blank to remove it.")
    path = key_path()
    if not value:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".steamgriddb-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(value + "\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(route):
    key = read_key()
    if not key:
        raise GridError("Set up your SteamGridDB API key first.")
    req = urllib.request.Request("https://www.steamgriddb.com/api/v2/" + route,
                                 headers={"Authorization": "Bearer " + key,
                                          "User-Agent": "MomentumCoreLauncher"})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as response:
            body = response.read((2 << 20) + 1)
        if len(body) > 2 << 20:
            raise GridError("SteamGridDB response is too large.")
        data = json.loads(body)
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        messages = {401: "SteamGridDB rejected the API key.",
                    403: "SteamGridDB denied access. Check your API key.",
                    429: "SteamGridDB rate limit reached. Try again later."}
        raise GridError(messages.get(status, f"SteamGridDB request failed (HTTP {status}).")) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GridError("SteamGridDB could not be reached or returned an invalid response.") from exc
    if not isinstance(data, dict) or data.get("success") is not True or not isinstance(data.get("data"), list):
        raise GridError("SteamGridDB returned an unexpected response.")
    return data["data"]


def game_id(value):
    value = str(value)
    if not re.fullmatch(r"[1-9][0-9]{0,9}", value):
        raise GridError("Invalid SteamGridDB game ID.")
    return value


def search(query):
    if not isinstance(query, str) or not query.strip() or len(query) > 100:
        raise GridError("Enter an artwork search title (up to 100 characters).")
    results = []
    for item in request("search/autocomplete/" + urllib.parse.quote(query.strip(), safe=""))[:20]:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or "id" not in item:
            raise GridError("SteamGridDB returned an unexpected game result.")
        results.append({"id": game_id(item["id"]), "name": item["name"]})
    return results


def artwork(identity, kind):
    identity = game_id(identity)
    if kind not in ("heroes", "grids", "icons"):
        raise GridError("Choose backgrounds, grids or icons.")
    query = urllib.parse.urlencode({"types": "static", "nsfw": "false", "humor": "false",
                                    "epilepsy": "false", "limit": 20})
    images = []
    for item in request(f"{kind}/game/{identity}?{query}")[:20]:
        if not isinstance(item, dict):
            raise GridError("SteamGridDB returned an unexpected artwork result.")
        if item.get("nsfw") or item.get("humor") or item.get("epilepsy"):
            continue
        urls = [item.get("url"), item.get("thumb")]
        if not all(isinstance(url, str) and urllib.parse.urlparse(url).scheme == "https"
                   and urllib.parse.urlparse(url).hostname == "cdn2.steamgriddb.com"
                   and not urllib.parse.urlparse(url).username for url in urls):
            raise GridError("SteamGridDB returned an unsupported artwork URL.")
        images.append({"url": urls[0], "thumb": urls[1]})
    return images
