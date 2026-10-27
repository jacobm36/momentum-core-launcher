import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import compatibility


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.launcher = Path(__file__).resolve().parents[1]
        compatibility._state.clear()

    def test_remote_records_merge_with_local_evidence(self):
        remote = {"format_version": 1, "records": [{
            "id": "test-engine-game", "version": "1.2.3",
            "digest": "sha256:" + "a" * 64, "runtime": "supermodel",
            "installer_validated": True,
            "software": {"provider": "native", "scope": "user", "sha256": "b" * 64},
            "additional_software": [],
        }]}
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            with mock.patch("compatibility.Path.home", return_value=home), \
                    mock.patch("compatibility._verify", return_value=None), \
                    mock.patch("compatibility._fetch_bytes",
                               side_effect=[json.dumps(remote).encode(), b"sig"]):
                records = compatibility.records(self.launcher)
        self.assertTrue(any(r["id"] == "test-engine-game" and r["version"] == "1.2.3" for r in records))

    def test_cached_remote_records_used_when_refresh_fails(self):
        remote = {"format_version": 1, "records": [{
            "id": "cached-game", "version": "2.0.0",
            "digest": "sha256:" + "c" * 64, "runtime": "eduke32",
            "installer_validated": True,
            "software": {"provider": "native", "scope": "user", "sha256": "d" * 64},
            "additional_software": [],
        }]}
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            cache = home / compatibility.REMOTE_CACHE
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(json.dumps(remote).encode())
            (home / compatibility.REMOTE_CACHE_SIG).write_bytes(b"sig")
            with mock.patch("compatibility.Path.home", return_value=home), \
                    mock.patch("compatibility._verify", return_value=None), \
                    mock.patch("compatibility._fetch_bytes", side_effect=ValueError("offline")):
                records = compatibility.records(self.launcher)
        self.assertTrue(any(r["id"] == "cached-game" and r["version"] == "2.0.0" for r in records))
