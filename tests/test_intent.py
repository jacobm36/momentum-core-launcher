"""Tests for the intent-record helper (mcl_intent.py)."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import mcl_intent  # noqa: E402


def rec(seq=1, **k):
    r = dict(intent_version=1, job_id="j1", seq=seq, step="configure", op="create", path="/home/x/.local/bin/game",
             ownership="managed", before={"kind": "absent", "sha256": None}, after={"kind": "file", "sha256": "b" * 64},
             backup=None)
    r.update(k)
    return r


class Intent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = Path(self.tmp.name) / "intents.jsonl"
        self.f.write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def run_helper(self, record, path=None, job="j1"):
        env = dict(os.environ, MCL_JOB_ID=job)
        return subprocess.run([sys.executable, str(HERE / "mcl_intent.py"), str(path or self.f), record],
                              env=env, capture_output=True, text=True).returncode

    def test_appends_one_line_per_record(self):
        self.assertEqual(self.run_helper(json.dumps(rec(1))), 0)
        self.assertEqual(self.run_helper(json.dumps(rec(2, op="merge", backup="/tmp/b"))), 0)
        records, truncated, bad = mcl_intent.read(self.f)
        self.assertEqual([r["seq"] for r in records], [1, 2])
        self.assertFalse(truncated or bad)

    def test_rejects_invalid_records(self):
        self.assertEqual(self.run_helper(json.dumps(rec(1))), 0)
        for bad in (rec(1), rec(2, path="relative/x"), rec(2, op="chmod"), rec(2, ownership="mine"),
                    rec(2, after={"kind": "file", "sha256": "XYZ"}), rec(2, backup="b"), rec(2, job_id="other"),
                    rec(2, intent_version=2)):
            with self.subTest(bad=bad):
                self.assertEqual(self.run_helper(json.dumps(bad)), 2)
        self.assertEqual(self.run_helper("not json"), 2)
        self.assertEqual(len(self.f.read_text().splitlines()), 1)

    def test_never_creates_the_file(self):
        self.assertEqual(self.run_helper(json.dumps(rec(1)), path=Path(self.tmp.name) / "missing"), 1)

    def test_truncated_record_stops_further_appends(self):
        self.f.write_bytes(json.dumps(rec(1)).encode() + b"\n" + b'{"intent_version":1,"se')
        records, truncated, bad = mcl_intent.read(self.f)
        self.assertEqual((len(records), truncated, bad), (1, True, []))
        self.assertEqual(self.run_helper(json.dumps(rec(2))), 2)


if __name__ == "__main__":
    unittest.main()
