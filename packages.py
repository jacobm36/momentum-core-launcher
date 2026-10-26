#!/usr/bin/env python3
"""Package intake for Momentum Core Package Contract v1, section 3.

A package folder or ZIP is copied into an immutable snapshot under packages/<id>/<version>/,
checked against SHA256SUMS and the manifest, and identified by the exact v1 snapshot digest.
Nothing in the package is executed here.

CLI (also useful to package authors):
  packages.py check  <folder-or-zip>   validate only, print the summary as JSON
  packages.py import <folder-or-zip>   validate and add to this launcher's package cache
"""
import fcntl, hashlib, json, os, platform, re, shutil, stat, sys, tempfile, time, unicodedata, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUPPORTED_CONTRACT = {(1, 0)}  # 1.0.x only; a new minor version is not assumed compatible
# Packages approved to use the exact bundled native OpenBOR 6391 runtime.
OPENBOR_PACKAGES = frozenset({"marvel-infinity-war", "ultimate-double-dragon-3"})
MAX_FILES = 20000
MAX_ENTRIES = 40000
MAX_FILE = 8 << 30
MAX_TOTAL = 16 << 30
MAX_PATH = 1024
MAX_DEPTH = 32
MAX_MANIFEST = 1 << 20
MAX_SUMS = 8 << 20
REQUIRED_FILES = ("package.json", "install.sh", "verify.sh", "repair.sh", "uninstall.sh",
                  "README.md", "assets/icon.png", "SHA256SUMS")
OPERATIONS = ("install", "verify", "repair", "uninstall")
INPUT_TYPES = ("directory", "string", "boolean", "choice")
DIR_DEFAULTS = ("home_games",)
PROVIDERS = ("flatpak", "native", "appimage")

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
INPUT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$")
SUM_LINE_RE = re.compile(rb"^([0-9a-f]{64})  ([^\n]+)$")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


class PackageError(ValueError):
    def __init__(self, problems):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("; ".join(self.problems))


def check_path(rel):
    """Return rel if it is a valid v1 package path, else raise PackageError."""
    if not isinstance(rel, str) or not rel:
        raise PackageError("empty path")
    try:
        raw = rel.encode("utf-8")
    except UnicodeEncodeError:
        raise PackageError(f"path is not valid UTF-8: {rel!r}")
    shown = rel.encode("utf-8", "backslashreplace").decode()
    if CTRL_RE.search(rel):
        raise PackageError(f"control character in path: {shown!r}")
    if "\\" in rel:
        raise PackageError(f"backslash in path: {shown}")
    if rel.startswith("/"):
        raise PackageError(f"absolute path: {shown}")
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise PackageError(f"empty, '.' or '..' path component (no leading './'): {shown}")
    if unicodedata.normalize("NFC", rel) != rel:
        raise PackageError(f"path is not Unicode NFC: {shown}")
    if len(raw) > MAX_PATH or len(parts) > MAX_DEPTH:
        raise PackageError(f"path too long or too deep: {shown[:80]}")
    return rel


def snapshot_digest(hashes):
    """hashes: {relative path: lowercase hex sha256}. Returns 'sha256:<hex>' per contract v1."""
    h = hashlib.sha256()
    for path in sorted(hashes, key=lambda p: p.encode("utf-8")):
        h.update(hashes[path].encode("ascii") + b"  " + path.encode("utf-8") + b"\n")
    return "sha256:" + h.hexdigest()


class _Stager:
    """Writes files into a fresh staging directory, hashing the bytes actually written."""
    def __init__(self, root):
        self.root = Path(root)
        self.hashes, self.execs, self.dirs = {}, set(), set()
        self.total = 0

    def add_dir(self, rel):
        self._claim_dir(check_path(rel))

    def _claim_dir(self, rel):
        parts = rel.split("/")
        for i in range(1, len(parts) + 1):
            d = "/".join(parts[:i])
            if d in self.hashes:
                raise PackageError(f"path is both a file and a folder: {d}")
            self.dirs.add(d)

    def add_file(self, rel, src, executable=False):
        check_path(rel)
        if rel in self.hashes:
            raise PackageError(f"duplicate path: {rel}")
        if rel in self.dirs:
            raise PackageError(f"path is both a file and a folder: {rel}")
        if len(self.hashes) >= MAX_FILES:
            raise PackageError(f"too many files (limit {MAX_FILES})")
        if "/" in rel:
            self._claim_dir(rel.rsplit("/", 1)[0])
        dest = self.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        h, size = hashlib.sha256(), 0
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as out:
            while chunk := src.read(1 << 20):
                size += len(chunk)
                self.total += len(chunk)
                if size > MAX_FILE:
                    raise PackageError(f"file too large (limit {MAX_FILE >> 30} GiB): {rel}")
                if self.total > MAX_TOTAL:
                    raise PackageError(f"package too large (limit {MAX_TOTAL >> 30} GiB)")
                h.update(chunk)
                out.write(chunk)
        self.hashes[rel] = h.hexdigest()
        if executable:
            self.execs.add(rel)


def _stage_folder(src, st):
    src = Path(src)
    if not (src / "package.json").is_file():
        raise PackageError("package.json not found directly inside this folder")

    def walk(d, prefix):
        with os.scandir(d) as it:
            entries = sorted(it, key=lambda e: e.name)
        for e in entries:
            name = e.name
            rel = f"{prefix}{name}"
            try:
                rel.encode("utf-8")
            except UnicodeEncodeError:
                raise PackageError(f"file name is not valid UTF-8: {rel.encode('utf-8', 'backslashreplace').decode()}")
            mode = e.stat(follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode):
                raise PackageError(f"links are not allowed: {rel}")
            if stat.S_ISDIR(mode):
                st.add_dir(rel)
                walk(e.path, rel + "/")
            elif stat.S_ISREG(mode):
                fd = os.open(e.path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as f:
                    if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                        raise PackageError(f"not a regular file: {rel}")
                    st.add_file(rel, f, bool(mode & 0o111))
            else:
                raise PackageError(f"special files are not allowed: {rel}")
    walk(src, "")


def _stage_zip(path, st):
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise PackageError(f"not a readable ZIP file: {e}")
    with z:
        infos = z.infolist()
        if len(infos) > MAX_ENTRIES:
            raise PackageError(f"too many archive entries (limit {MAX_ENTRIES})")
        entries = []
        for info in infos:
            name = info.filename
            if not (info.flag_bits & 0x800) and not name.isascii():
                raise PackageError(f"archive name is not marked as UTF-8: {name!r}")
            if info.flag_bits & 0x1:
                raise PackageError(f"encrypted archive entries are not supported: {name}")
            is_dir = name.endswith("/")
            rel = name[:-1] if is_dir else name
            check_path(rel)
            mode = info.external_attr >> 16 if info.create_system == 3 else 0
            kind = stat.S_IFMT(mode)
            if kind == stat.S_IFLNK:
                raise PackageError(f"links are not allowed: {rel}")
            if kind and kind not in (stat.S_IFREG, stat.S_IFDIR):
                raise PackageError(f"special files are not allowed: {rel}")
            if kind == stat.S_IFDIR and not is_dir:
                is_dir = True
            entries.append((rel, is_dir, info, bool(mode & 0o111)))
        names = [rel for rel, is_dir, _, _ in entries]
        if len(set(names)) != len(names):
            dup = next(n for n in names if names.count(n) > 1)
            raise PackageError(f"duplicate path in archive: {dup}")
        files = {rel for rel, is_dir, _, _ in entries if not is_dir}
        if sum(i.file_size for _, d, i, _ in entries if not d) > MAX_TOTAL:
            raise PackageError(f"package too large (limit {MAX_TOTAL >> 30} GiB)")
        if "package.json" in files:
            strip = ""
        elif not any(f.rsplit("/", 1)[-1] == "package.json" for f in files):
            raise PackageError("package.json not found: this is not a Momentum Core package")
        else:
            tops = {n.split("/", 1)[0] for n in names}
            top = next(iter(tops)) if len(tops) == 1 else None
            if not top or f"{top}/package.json" not in files:
                raise PackageError("ambiguous archive root: package.json must be at the top level "
                                   "or inside a single top-level folder")
            strip = top + "/"
        for rel, is_dir, info, ex in entries:
            if rel + "/" == strip:
                continue
            inner = rel[len(strip):]
            if is_dir:
                st.add_dir(inner)
                continue
            try:
                with z.open(info) as f:
                    st.add_file(inner, f, ex)
            except (zipfile.BadZipFile, NotImplementedError, EOFError, RuntimeError) as e:
                raise PackageError(f"cannot extract {rel}: {e}")


def _read_small(root, rel, limit):
    p = root / rel
    if p.stat().st_size > limit:
        raise PackageError(f"{rel} is too large")
    return p.read_bytes()


def check_sums(root, hashes):
    """Verify SHA256SUMS covers every other file exactly, with matching hashes."""
    if "SHA256SUMS" not in hashes:
        raise PackageError("SHA256SUMS is missing")
    data = _read_small(root, "SHA256SUMS", MAX_SUMS)
    if not data.endswith(b"\n"):
        raise PackageError("SHA256SUMS must end with a newline (LF)")
    listed, problems = {}, []
    for n, line in enumerate(data[:-1].split(b"\n"), 1):
        m = SUM_LINE_RE.match(line)
        if not m:
            problems.append(f"SHA256SUMS line {n} is not '<64 lowercase hex>  <path>' (LF only, no '*')")
            continue
        try:
            rel = check_path(m[2].decode("utf-8"))
        except (UnicodeDecodeError, PackageError) as e:
            problems.append(f"SHA256SUMS line {n}: {e}")
            continue
        if rel in listed:
            problems.append(f"SHA256SUMS lists {rel} twice")
        listed[rel] = m[1].decode()
    if "SHA256SUMS" in listed:
        problems.append("SHA256SUMS must not list itself")
    actual = {p: h for p, h in hashes.items() if p != "SHA256SUMS"}
    for p in sorted(set(actual) - set(listed)):
        problems.append(f"not listed in SHA256SUMS: {p}")
    for p in sorted(set(listed) - set(actual) - {"SHA256SUMS"}):
        problems.append(f"listed in SHA256SUMS but missing: {p}")
    for p in sorted(set(actual) & set(listed)):
        if actual[p] != listed[p]:
            problems.append(f"checksum mismatch: {p}")
    if problems:
        raise PackageError(problems[:50] + ([f"... and {len(problems) - 50} more"] if len(problems) > 50 else []))


def _png_size(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR" or len(data) < 24:
        return None
    w, h = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return (w, h) if w and h else None


def host_platform():
    info = {"os": "", "release": "", "architecture": platform.machine()}
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            k, _, v = line.partition("=")
            v = v.strip().strip('"')
            if k == "ID":
                info["os"] = v
            elif k == "VERSION_ID":
                info["release"] = v
    except OSError:
        pass
    return info


def check_manifest(m, files, root):
    """Type-check the manifest; returns a list of problems (empty when valid)."""
    P = []
    if not isinstance(m, dict):
        return ["package.json must contain a JSON object"]

    def s(key, obj=m, where="", req=True, empty=False):
        v = obj.get(key)
        if v is None and not req:
            return None
        if not isinstance(v, str) or (not empty and not v.strip()):
            P.append(f"{where}{key} must be a {'' if empty else 'non-empty '}string")
            return None
        return v

    def lst(key, obj, where, req=True):
        v = obj.get(key)
        if v is None and not req:
            return []
        if not isinstance(v, list):
            P.append(f"{where}{key} must be a list")
            return []
        return v

    def obj(key, parent=m, where=""):
        v = parent.get(key)
        if not isinstance(v, dict):
            P.append(f"{where}{key} must be an object")
            return {}
        return v

    def pkg_file(v, where, png=False):
        if not isinstance(v, str):
            P.append(f"{where} must be a package path")
            return
        try:
            check_path(v)
        except PackageError as e:
            P.append(f"{where}: {e}")
            return
        if v not in files:
            P.append(f"{where} refers to a file not in the package: {v}")
        elif png and not _png_size(_read_small(root, v, 64 << 20)[:32]):
            P.append(f"{where} is not a valid PNG image: {v}")

    cv = s("contract_version")
    if cv:
        mm = SEMVER_RE.match(cv)
        if not mm:
            P.append("contract_version must be a semantic version")
        elif (int(mm[1]), int(mm[2])) not in SUPPORTED_CONTRACT:
            P.append(f"unsupported contract version {cv} (this launcher supports 1.0.x)")
    v = s("installer_standard_version")
    if v and not SEMVER_RE.match(v):
        P.append("installer_standard_version must be a semantic version")
    v = s("id")
    if v and not ID_RE.match(v):
        P.append("id must be lowercase letters, numbers and hyphens (max 64), starting with a letter or number")
    v = s("name")
    if v and (len(v) > 200 or CTRL_RE.search(v)):
        P.append("name is too long or contains control characters")
    v = s("version")
    if v and not SEMVER_RE.match(v):
        P.append("version must be a semantic version")

    pf = obj("platform")
    if pf:
        s("os", pf, "platform.")
        for k in ("releases", "architectures"):
            vals = lst(k, pf, "platform.")
            if not vals or not all(isinstance(x, str) and x for x in vals):
                P.append(f"platform.{k} must be a non-empty list of strings")

    seen = set()
    for i, inp in enumerate(lst("inputs", m, "")):
        w = f"inputs[{i}]."
        if not isinstance(inp, dict):
            P.append(f"inputs[{i}] must be an object")
            continue
        iid = s("id", inp, w)
        if iid:
            if not INPUT_ID_RE.match(iid):
                P.append(f"{w}id must be lowercase letters, numbers and underscores")
            if iid in seen:
                P.append(f"duplicate input id: {iid}")
            seen.add(iid)
        t = inp.get("type")
        if t not in INPUT_TYPES:
            P.append(f"{w}type must be one of {', '.join(INPUT_TYPES)}")
        if not isinstance(inp.get("required"), bool):
            P.append(f"{w}required must be true or false")
        s("role", inp, w, req=False)
        d = inp.get("default")
        if t == "choice":
            ch = lst("choices", inp, w)
            if not ch or not all(isinstance(c, str) and c for c in ch):
                P.append(f"{w}choices must be a non-empty list of strings")
            elif d is not None and d not in ch:
                P.append(f"{w}default must be one of the choices")
        elif d is not None:
            ok = {"boolean": isinstance(d, bool), "string": isinstance(d, str),
                  "directory": d in DIR_DEFAULTS or (isinstance(d, str) and d.startswith("/"))}.get(t, True)
            if not ok:
                P.append(f"{w}default has the wrong type")

    dn = s("destination_name")
    if dn and (dn in (".", "..") or "/" in dn or CTRL_RE.search(dn) or len(dn.encode()) > 255
               or unicodedata.normalize("NFC", dn) != dn):
        P.append("destination_name must be one safe folder name (no '/', '.', '..' or control characters)")

    for i, r in enumerate(lst("requires", m, "")):
        w = f"requires[{i}]."
        if not isinstance(r, dict):
            P.append(f"requires[{i}] must be an object")
            continue
        rid = s("id", r, w)
        if rid and not ID_RE.match(rid):
            P.append(f"{w}id is not a valid id")
        prov = r.get("provider")
        if prov not in PROVIDERS:
            P.append(f"{w}provider {prov!r} is not supported (v1 supports: {', '.join(PROVIDERS)})")
        elif prov == "flatpak":
            s("app_id", r, w)
            if r.get("scope") != "user":
                P.append(f"{w}scope must be 'user' (v1 does not elevate privileges)")
        elif prov == "appimage":
            vkquake = (rid, r.get("source"), r.get("scope"), r.get("tested_version")) == (
                "vkquake", "github:Novum/vkQuake", "user", "1.36.0")
            openbor = m.get("id") in OPENBOR_PACKAGES and (rid, r.get("source"), r.get("scope"),
                       r.get("tested_version"), r.get("sha256")) == (
                "openbor", "github:DCurrent/openbor", "user", "6391",
                "35895117c2eae94867ee0b094083ae66cd3853372d7447d60cfe92fa929d73eb")
            if not (vkquake or openbor):
                P.append(f"{w}appimage provider supports only pinned user-scope vkQuake 1.36.0 "
                         "or an approved OpenBOR package's exact bundled OpenBOR 6391")
        elif rid == "eduke32":
            if (r.get("source"), r.get("scope"), r.get("source_commit")) != (
                    "https://voidpoint.io/terminx/eduke32", "user",
                    "ec5824db81817866f70da326d3811bb0f52b3517"):
                P.append(f"{w}native EDuke32 requires the pinned official user-scope source")
        elif rid == "ironwail":
            if (r.get("source"), r.get("scope"), r.get("version"), r.get("tested_version"),
                    r.get("url"), r.get("sha256"), r.get("executable_sha256"), r.get("companion_sha256")) != (
                    "github:andrei-drexler/ironwail", "user", "0.8.2", "0.8.2",
                    "https://github.com/andrei-drexler/ironwail/releases/download/v0.8.2/ironwail-0.8.2-linux-x64.tar.gz",
                    "fcb0219d13c50f64728892f0558b4761ba5578319a6cc01021fad981c6333aa5",
                    "484913a479bc1ddb64b405ff55e5c31caead0af1f158f4f911aa57d2368971cf",
                    "be6a546c1b267837d5b6558e9349b1df302a825587b994309b1c955a561292a1"):
                P.append(f"{w}native Ironwail requires the exact official user-scope 0.8.2 release")
        elif (rid, r.get("source"), r.get("scope")) != ("supermodel", "github:trzy/Supermodel", "user"):
            P.append(f"{w}native provider supports only pinned user-scope Supermodel, EDuke32 or Ironwail")

    ops = obj("operations")
    for op in OPERATIONS if ops else ():
        o = ops.get(op)
        w = f"operations.{op}"
        if not isinstance(o, dict):
            P.append(f"{w} must be an object")
            continue
        pkg_file(o.get("entrypoint"), f"{w}.entrypoint")
        steps = o.get("steps")
        if not isinstance(steps, list) or not steps or not all(isinstance(x, str) and x for x in steps):
            P.append(f"{w}.steps must be a non-empty list of strings")

    acts = obj("actions")
    if acts:
        if acts.get("privileges") != []:
            P.append("actions.privileges must be empty: v1 packages cannot require elevated privileges")
        for k in ("network", "files"):
            if not all(isinstance(x, dict) for x in lst(k, acts, "actions.")):
                P.append(f"actions.{k} entries must be objects")

    cat = obj("catalog")
    if cat:
        s("category", cat, "catalog.", empty=True)
        s("description", cat, "catalog.", empty=True)
        if not all(isinstance(x, str) for x in lst("tags", cat, "catalog.")):
            P.append("catalog.tags must be a list of strings")
        pkg_file(cat.get("icon"), "catalog.icon", png=True)
        for k in ("cover", "grid", "video"):
            if cat.get(k) is not None:
                pkg_file(cat[k], f"catalog.{k}")
        for i, x in enumerate(lst("screenshots", cat, "catalog.", req=False)):
            pkg_file(x, f"catalog.screenshots[{i}]")

    st = obj("state")
    if st:
        s("policy", st, "state.")
        if not all(isinstance(x, str) for x in lst("manual_setup", st, "state.", req=False)):
            P.append("state.manual_setup must be a list of strings")
    obj("testing")
    rt = m.get("runtime")
    if rt is not None:
        if not isinstance(rt, dict):
            P.append("runtime must be an object")
        else:
            if rt.get("interpreter", "bash") != "bash":
                P.append("runtime.interpreter must be 'bash' (contract v1 runs entrypoints with bash)")
            mp = rt.get("minimum_python")
            if mp is not None and not (isinstance(mp, str) and re.fullmatch(r"\d+(\.\d+){0,2}", mp)):
                P.append("runtime.minimum_python must be a version like '3.10'")
    return P


def _platform_issues(pf, rt=None):
    host = host_platform()
    issues = []
    mp = rt.get("minimum_python") if isinstance(rt, dict) else None
    if mp and tuple(sys.version_info[:3]) < tuple(int(x) for x in mp.split(".")):
        issues.append(f"needs Python {mp}, this computer has {platform.python_version()}")
    if not isinstance(pf, dict):
        return issues
    if pf.get("os") and host["os"] and pf["os"] != host["os"]:
        issues.append(f"built for {pf['os']}, this computer runs {host['os']}")
    if isinstance(pf.get("releases"), list) and host["release"] and host["release"] not in pf["releases"]:
        issues.append(f"tested on {', '.join(map(str, pf['releases']))}, this computer runs {host['release']}")
    if isinstance(pf.get("architectures"), list) and host["architecture"] not in pf["architectures"]:
        issues.append(f"built for {', '.join(map(str, pf['architectures']))}, this computer is {host['architecture']}")
    return issues


def _inspect(root, st):
    """Validate a staged snapshot; returns (manifest, summary)."""
    missing = [f for f in REQUIRED_FILES if f not in st.hashes]
    if missing:
        raise PackageError([f"required file missing: {f}" for f in missing])
    check_sums(root, st.hashes)
    try:
        manifest = json.loads(_read_small(root, "package.json", MAX_MANIFEST).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise PackageError(f"package.json is not valid JSON: {e}")
    problems = check_manifest(manifest, st.hashes, root)
    if problems:
        raise PackageError(problems)
    summary = {
        "id": manifest["id"], "name": manifest["name"], "version": manifest["version"],
        "contract_version": manifest["contract_version"],
        "digest": snapshot_digest(st.hashes),
        "files": len(st.hashes), "bytes": st.total,
        "platform_issues": _platform_issues(manifest.get("platform"), manifest.get("runtime")),
    }
    return manifest, summary


def _lock_tree(root, execs):
    for dirpath, dirs, files in os.walk(root, topdown=False):
        for f in files:
            rel = os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/")
            os.chmod(os.path.join(dirpath, f), 0o555 if rel in execs else 0o444)
        os.chmod(dirpath, 0o555)


def _rmtree(path):
    path = Path(path)
    if not path.exists():
        return
    for dirpath, dirs, files in os.walk(path):
        os.chmod(dirpath, 0o700)
    shutil.rmtree(path)


def _stage(src, staging):
    src = Path(src)
    st = _Stager(staging)
    if src.is_dir():
        _stage_folder(src, st)
    elif src.is_file():
        _stage_zip(src, st)
    else:
        raise PackageError(f"not a folder or ZIP file: {src}")
    return st


def check(src):
    """Validate a package folder or ZIP without keeping anything. Returns the summary."""
    with tempfile.TemporaryDirectory(prefix="mcl-pkg-") as tmp:
        st = _stage(src, Path(tmp) / "snapshot")
        return _inspect(Path(tmp) / "snapshot", st)[1]


def cache_dir(here=HERE):
    d = Path(here) / "packages"
    d.mkdir(exist_ok=True)
    return d


def import_package(src, here=HERE):
    """Copy/extract into packages/<id>/<version>/snapshot. Returns the summary plus 'status':
    'imported', or 'already-imported' when identical bytes are already cached."""
    cache = cache_dir(here)
    with open(cache / ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        for old in cache.glob(".staging-*"):
            _rmtree(old)
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=cache))
        try:
            st = _stage(src, staging / "snapshot")
            manifest, summary = _inspect(staging / "snapshot", st)
            dest = cache / summary["id"] / summary["version"]
            if dest.exists():
                prev = read_intake(dest)
                if prev and prev.get("digest") == summary["digest"]:
                    return dict(prev, status="already-imported")
                raise PackageError(f"version collision: {summary['id']} {summary['version']} is already imported "
                                   "with different contents; the package author must publish a new version")
            summary.update(source=str(Path(src).resolve()), imported=int(time.time()))
            _lock_tree(staging / "snapshot", st.execs)
            rec = staging / "intake.json"
            with open(rec, "w") as f:
                json.dump(summary, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(staging, 0o755)
            dest.parent.mkdir(exist_ok=True)
            os.rename(staging, dest)
            fd = os.open(dest.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            return dict(summary, status="imported")
        finally:
            _rmtree(staging)


def read_intake(d):
    try:
        rec = json.loads((Path(d) / "intake.json").read_text())
        return rec if isinstance(rec, dict) else None
    except (OSError, ValueError):
        return None


def list_packages(here=HERE):
    out = []
    cache = Path(here) / "packages"
    if not cache.is_dir():
        return out
    for pid in sorted(cache.iterdir()):
        if pid.name.startswith(".") or not ID_RE.match(pid.name) or not pid.is_dir():
            continue
        for ver in sorted(pid.iterdir()):
            rec = read_intake(ver)
            if rec and rec.get("id") == pid.name and rec.get("version") == ver.name:
                out.append(rec)
    return out


def snapshot_path(here, pid, version):
    if not ID_RE.match(pid or "") or not SEMVER_RE.match(version or ""):
        raise PackageError("unknown package")
    d = Path(here) / "packages" / pid / version
    if not read_intake(d):
        raise PackageError("unknown package")
    return d / "snapshot"


def remove_package(here, pid, version):
    with open(cache_dir(here) / ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        _rmtree(snapshot_path(here, pid, version).parent)


def main(argv):
    if len(argv) != 3 or argv[1] not in ("check", "import"):
        print(__doc__.split("CLI", 1)[1].strip(), file=sys.stderr)
        return 2
    try:
        res = check(argv[2]) if argv[1] == "check" else import_package(argv[2])
    except PackageError as e:
        print(json.dumps({"ok": False, "problems": e.problems}, indent=2))
        return 1
    print(json.dumps(dict(res, ok=True), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
