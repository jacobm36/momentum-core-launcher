"""Tests for package intake (packages.py), contract v1 section 3."""
import hashlib, io, json, os, stat, struct, subprocess, sys, tempfile, unicodedata, unittest, zipfile, zlib
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import packages  # noqa: E402
from packages import PackageError  # noqa: E402

FIXTURE = HERE / "tests" / "fixtures" / "digest-v1"


def png():
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


def manifest(**over):
    m = {
        "contract_version": "1.0.0", "installer_standard_version": "1.0.0",
        "id": "test-game", "name": "Test Game", "version": "1.0.0",
        "platform": {"os": "ubuntu", "releases": ["24.04"], "architectures": ["x86_64"]},
        "inputs": [{"id": "source_dir", "type": "directory", "required": True, "role": "source"},
                   {"id": "games_root", "type": "directory", "required": True, "role": "destination", "default": "home_games"}],
        "destination_name": "Test Game (USA)",
        "requires": [{"id": "flycast", "provider": "flatpak", "app_id": "org.flycast.Flycast", "scope": "user"}],
        "operations": {op: {"entrypoint": f"{op}.sh", "steps": ["validate"]} for op in packages.OPERATIONS},
        "actions": {"network": [], "privileges": [], "files": []},
        "catalog": {"category": "Dreamcast", "tags": ["Rail Shooter"], "description": "", "icon": "assets/icon.png",
                    "cover": None, "screenshots": [], "video": None},
        "state": {"policy": "preserve-existing-seed-absent", "manual_setup": []},
        "testing": {"automated": "not-tested"},
    }
    m.update(over)
    return m


def sums_for(files):
    return "".join(f"{hashlib.sha256(d).hexdigest()}  {p}\n" for p, d in sorted(files.items()) if p != "SHA256SUMS").encode()


def package_files(m=None, extra=None, sums=True):
    files = {"package.json": json.dumps(m or manifest(), indent=2).encode() + b"\n",
             "README.md": b"# Test\n", "assets/icon.png": png()}
    for op in packages.OPERATIONS:
        files[f"{op}.sh"] = f"#!/bin/bash\necho {op}\n".encode()
    files.update(extra or {})
    if sums:
        files["SHA256SUMS"] = sums_for(files)
    return files


def write_tree(root, files):
    root = Path(root)
    for p, d in files.items():
        (root / p).parent.mkdir(parents=True, exist_ok=True)
        (root / p).write_bytes(d)
    return root


def write_zip(path, files, prefix="", infos=()):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for p, d in files.items():
            z.writestr(prefix + p, d)
        for info, data in infos:
            z.writestr(info, data)
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.app = self.t / "app"
        self.app.mkdir()

    def tearDown(self):
        for d, _, _ in os.walk(self.t):
            os.chmod(d, 0o755)
        self.tmp.cleanup()

    def problems(self, src, fn=None):
        with self.assertRaises(PackageError) as cm:
            (fn or packages.check)(src)
        return " | ".join(cm.exception.problems)


class Digest(unittest.TestCase):
    def test_shared_fixture(self):
        root = FIXTURE / "tree"
        hashes = {}
        for d, _, fs in os.walk(root):
            for f in fs:
                p = Path(d) / f
                hashes[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(packages.snapshot_digest(hashes), (FIXTURE / "expected-digest.txt").read_text().strip())

    def test_byte_order_not_locale(self):
        h = {"a": "0" * 64, "B": "1" * 64, "é": "2" * 64}
        expect = hashlib.sha256(b"1" * 64 + b"  B\n" + b"0" * 64 + b"  a\n" + b"2" * 64 + "  é\n".encode()).hexdigest()
        self.assertEqual(packages.snapshot_digest(h), "sha256:" + expect)

    def test_path_rules(self):
        for bad in ["/abs", "../x", "a/../b", "./a", "a//b", "a/", "a\\b", "a\x01b", "a\x7fb", "",
                    unicodedata.normalize("NFD", "café")]:
            with self.subTest(bad=bad), self.assertRaises(PackageError):
                packages.check_path(bad)
        for good in ["a", "dir/file name.txt", "café/é.txt", "House of the Dead 2, The (USA)/x"]:
            self.assertEqual(packages.check_path(good), good)


class Intake(Base):
    def test_folder_import(self):
        src = write_tree(self.t / "pkg", package_files(extra={"helpers/run.sh": b"echo\n"}))
        os.chmod(src / "helpers/run.sh", 0o755)
        r = packages.import_package(src, self.app)
        self.assertEqual((r["status"], r["id"], r["version"]), ("imported", "test-game", "1.0.0"))
        snap = self.app / "packages/test-game/1.0.0/snapshot"
        self.assertEqual((snap / "README.md").read_bytes(), b"# Test\n")
        self.assertFalse(os.stat(snap / "README.md").st_mode & 0o222)
        self.assertTrue(os.stat(snap / "helpers/run.sh").st_mode & 0o100)
        self.assertFalse(os.stat(snap / "install.sh").st_mode & 0o100)
        self.assertEqual([p["id"] for p in packages.list_packages(self.app)], ["test-game"])
        self.assertEqual(packages.snapshot_path(self.app, "test-game", "1.0.0"), snap)
        # The snapshot is a copy: later source edits don't reach it.
        (src / "README.md").write_bytes(b"changed\n")
        self.assertEqual((snap / "README.md").read_bytes(), b"# Test\n")
        self.assertEqual(list((self.app / "packages").glob(".staging-*")), [])

    def test_folder_and_zip_same_digest(self):
        files = package_files()
        a = packages.check(write_tree(self.t / "pkg", files))["digest"]
        b = packages.check(write_zip(self.t / "flat.zip", files))["digest"]
        c = packages.check(write_zip(self.t / "nested.zip", files, prefix="Test Game/"))["digest"]
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertTrue(a.startswith("sha256:") and len(a) == 71)

    def test_reimport_and_collision(self):
        files = package_files()
        self.assertEqual(packages.import_package(write_zip(self.t / "a.zip", files), self.app)["status"], "imported")
        self.assertEqual(packages.import_package(write_tree(self.t / "b", files), self.app)["status"], "already-imported")
        changed = package_files(extra={"README.md": b"# Different\n"})
        msg = self.problems(write_tree(self.t / "c", changed), lambda s: packages.import_package(s, self.app))
        self.assertIn("version collision", msg)
        newer = package_files(manifest(version="1.1.0"), extra={"README.md": b"# Different\n"})
        self.assertEqual(packages.import_package(write_tree(self.t / "d", newer), self.app)["status"], "imported")
        self.assertEqual([p["version"] for p in packages.list_packages(self.app)], ["1.0.0", "1.1.0"])

    def test_failed_import_leaves_nothing(self):
        files = package_files()
        files["README.md"] = b"tampered\n"
        self.problems(write_tree(self.t / "pkg", files), lambda s: packages.import_package(s, self.app))
        self.assertEqual([p.name for p in (self.app / "packages").iterdir()], [".lock"])

    def test_remove(self):
        packages.import_package(write_tree(self.t / "pkg", package_files()), self.app)
        packages.remove_package(self.app, "test-game", "1.0.0")
        self.assertEqual(packages.list_packages(self.app), [])
        with self.assertRaises(PackageError):
            packages.snapshot_path(self.app, "test-game", "../x")

    def test_cli(self):
        src = write_tree(self.t / "pkg", package_files())
        ok = subprocess.run([sys.executable, str(HERE / "packages.py"), "check", str(src)], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertTrue(json.loads(ok.stdout)["ok"])
        (src / "README.md").write_bytes(b"x")
        bad = subprocess.run([sys.executable, str(HERE / "packages.py"), "check", str(src)], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("checksum mismatch: README.md", json.loads(bad.stdout)["problems"])


class Checksums(Base):
    def check_sums(self, sums, files=None):
        files = files or package_files(sums=False)
        files["SHA256SUMS"] = sums
        return self.problems(write_tree(self.t / "pkg", files))

    def test_mismatch_unlisted_missing(self):
        files = package_files(sums=False)
        sums = sums_for(files).replace(b"  README.md\n", b"  README.md\n" + b"0" * 64 + b"  gone.txt\n")
        files["extra.txt"] = b"x"
        files["install.sh"] = b"changed"
        msg = self.check_sums(sums, files)
        self.assertIn("not listed in SHA256SUMS: extra.txt", msg)
        self.assertIn("listed in SHA256SUMS but missing: gone.txt", msg)
        self.assertIn("checksum mismatch: install.sh", msg)

    def test_format_rules(self):
        base = sums_for(package_files(sums=False))
        for name, sums in [("dot-slash", base.replace(b"  README", b"  ./README")),
                           ("crlf", base.replace(b"\n", b"\r\n")),
                           ("binary-star", base.replace(b"  README", b" *README")),
                           ("uppercase hex", base[:64].upper() + base[64:]),
                           ("no final LF", base[:-1]),
                           ("self", base + b"0" * 64 + b"  SHA256SUMS\n"),
                           ("duplicate", base + base.splitlines(True)[0])]:
            with self.subTest(name):
                self.check_sums(sums)


class Manifest(Base):
    def test_valid_passes(self):
        r = packages.check(write_tree(self.t / "pkg", package_files()))
        self.assertEqual(r["files"], 8)

    def test_contract_versions(self):
        self.assertTrue(packages.check(write_tree(self.t / "p", package_files(manifest(contract_version="1.0.7")))))
        for v in ("1.1.0", "2.0.0", "0.9.0"):
            with self.subTest(v):
                files = package_files(manifest(contract_version=v))
                self.assertIn("unsupported contract version", self.problems(write_tree(self.t / v, files)))
        self.assertIn("semantic version", self.problems(write_tree(self.t / "q", package_files(manifest(contract_version="1.0")))))

    def test_rules(self):
        cases = {
            "privileges": dict(actions={"network": [], "privileges": [{"why": "sudo"}], "files": []}),
            "id must": dict(id="Bad_ID"),
            "version must": dict(version="v1"),
            "scope must be 'user'": dict(requires=[{"id": "flycast", "provider": "flatpak", "app_id": "x", "scope": "system"}]),
            "not supported": dict(requires=[{"id": "x", "provider": "apt"}]),
            "destination_name": dict(destination_name="a/b"),
            "type must be one of": dict(inputs=[{"id": "x", "type": "file", "required": True}]),
            "duplicate input id": dict(inputs=[{"id": "x", "type": "string", "required": True}] * 2),
            "default must be one of": dict(inputs=[{"id": "x", "type": "choice", "required": False, "choices": ["a"], "default": "b"}]),
            "operations.repair must be": dict(operations={op: {"entrypoint": f"{op}.sh", "steps": ["v"]} for op in ("install", "verify", "uninstall")}),
            "not in the package": dict(operations=dict(manifest()["operations"], install={"entrypoint": "missing.sh", "steps": ["v"]})),
            "'..' path component": dict(catalog=dict(manifest()["catalog"], cover="../outside.png")),
            "testing must be an object": dict(testing=None),
            "runtime.interpreter": dict(runtime={"interpreter": "python3"}),
            "runtime.minimum_python must": dict(runtime={"minimum_python": 3.1}),
        }
        for i, (expect, over) in enumerate(cases.items()):
            with self.subTest(expect):
                files = package_files(manifest(**over))
                self.assertIn(expect, self.problems(write_tree(self.t / f"p{i}", files)))

    def test_icon_must_be_png(self):
        files = package_files(extra={"assets/icon.png": b"not a png"})
        self.assertIn("not a valid PNG", self.problems(write_tree(self.t / "pkg", files)))

    def test_required_files_and_bad_json(self):
        files = package_files()
        del files["uninstall.sh"]
        files["SHA256SUMS"] = sums_for(files)
        self.assertIn("required file missing: uninstall.sh", self.problems(write_tree(self.t / "a", files)))
        files = package_files(extra={"package.json": b"{nope"})
        self.assertIn("not valid JSON", self.problems(write_tree(self.t / "b", files)))

    def test_platform_issues_reported_not_fatal(self):
        r = packages.check(write_tree(self.t / "pkg", package_files(manifest(platform={"os": "ubuntu", "releases": ["99.04"], "architectures": ["riscv64"]}))))
        self.assertEqual(len(r["platform_issues"]), 2 if packages.host_platform()["os"] == "ubuntu" else 3)
        r = packages.check(write_tree(self.t / "py", package_files(manifest(runtime={"interpreter": "bash", "minimum_python": "99.0"}))))
        self.assertTrue(any("needs Python 99.0" in i for i in r["platform_issues"]))


class UnsafeInput(Base):
    def test_folder_links_and_special_files(self):
        src = write_tree(self.t / "a", package_files())
        os.symlink("/etc/passwd", src / "link")
        self.assertIn("links are not allowed", self.problems(src))
        src = write_tree(self.t / "b", package_files())
        os.mkfifo(src / "fifo")
        self.assertIn("special files", self.problems(src))
        src = write_tree(self.t / "c", package_files())
        os.symlink(src / "assets", src / "dirlink")
        self.assertIn("links are not allowed", self.problems(src))

    def test_folder_needs_package_at_top(self):
        write_tree(self.t / "outer/inner", package_files())
        self.assertIn("package.json not found", self.problems(self.t / "outer"))

    def zip_with(self, name, data=b"x", attr=None):
        info = zipfile.ZipInfo(name)
        if attr is not None:
            info.create_system, info.external_attr = 3, attr << 16
        return write_zip(self.t / "p.zip", package_files(), infos=[(info, data)])

    def test_zip_paths(self):
        for name, expect in [("/etc/evil", "absolute"), ("../evil", "'..'"), ("a/../../evil", "'..'"),
                             ("a\\evil", "backslash"), ("ctl\x01", "control character"),
                             (unicodedata.normalize("NFD", "café.txt"), "NFC")]:
            with self.subTest(name):
                self.assertIn(expect, self.problems(self.zip_with(name)))

    def test_zip_link_special_duplicate(self):
        self.assertIn("links are not allowed", self.problems(self.zip_with("ln", b"/etc/passwd", stat.S_IFLNK | 0o777)))
        self.assertIn("special files", self.problems(self.zip_with("fifo", b"", stat.S_IFIFO | 0o644)))
        with self.assertWarns(UserWarning):
            z = self.zip_with("README.md", b"dup")
        self.assertIn("duplicate path", self.problems(z))
        self.assertIn("both a file and a folder", self.problems(self.zip_with("README.md/x")))

    def test_zip_ambiguous_root(self):
        files = package_files()
        z = write_zip(self.t / "two.zip", {**{f"A/{p}": d for p, d in files.items()}, "B/other.txt": b"x"})
        self.assertIn("ambiguous archive root", self.problems(z))
        z = write_zip(self.t / "deep.zip", files, prefix="A/B/")
        self.assertIn("ambiguous archive root", self.problems(z))
        z = write_zip(self.t / "none.zip", {"readme.txt": b"x"})
        self.assertIn("package.json not found", self.problems(z))

    def test_size_limits_use_actual_bytes(self):
        z = write_zip(self.t / "big.zip", package_files(extra={"big.bin": b"\0" * 300000}))
        with mock.patch.object(packages, "MAX_FILE", 100000):
            self.assertIn("file too large", self.problems(z))
        with mock.patch.object(packages, "MAX_TOTAL", 100000):
            self.assertIn("package too large", self.problems(z))
        with mock.patch.object(packages, "MAX_FILES", 3):
            self.assertIn("too many files", self.problems(z))

    def test_not_a_zip(self):
        (self.t / "x.zip").write_bytes(b"garbage")
        self.assertIn("not a readable ZIP", self.problems(self.t / "x.zip"))
        self.assertIn("not a folder or ZIP", self.problems(self.t / "missing"))


if __name__ == "__main__":
    unittest.main()
