#!/usr/bin/env python3
"""Append one durable intent record before a package changes anything (Package Contract v1, §8).

Usage: mcl_intent.py <intent_file> '<json record>'

Exit 0 means the record is on disk (written and fsynced) and the change may proceed. Any other
exit means do NOT make the change: 2 = invalid record or usage, 1 = the file couldn't be written.
The runner creates the intent file; this helper only appends whole lines to it, one writer at a time.
"""
import fcntl, json, os, re, sys

OPS = ("create", "replace", "merge", "remove", "mkdir", "publish")
OWNERSHIP = ("managed", "borrowed", "user-state", "shared-dependency")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_LINE = 65536


def _abs(p):
    return isinstance(p, str) and os.path.isabs(p) and not any(c in p for c in "\0\n\r")


def _state(v):
    if not isinstance(v, dict) or not isinstance(v.get("kind"), str) or not v["kind"]:
        return False
    h = v.get("sha256")
    return h is None or (isinstance(h, str) and bool(HEX64.match(h)))


def validate(rec, last_seq=0, job_id=None):
    """Return why a record is invalid, or None."""
    if not isinstance(rec, dict):
        return "record must be a JSON object"
    if rec.get("intent_version") != 1:
        return "intent_version must be 1"
    if not isinstance(rec.get("job_id"), str) or not rec["job_id"]:
        return "job_id is required"
    if job_id and rec["job_id"] != job_id:
        return "job_id doesn't match this job"
    seq = rec.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq <= last_seq:
        return f"seq must be an integer greater than {last_seq}"
    if not isinstance(rec.get("step"), str) or not rec["step"]:
        return "step is required"
    if rec.get("op") not in OPS:
        return f"op must be one of {', '.join(OPS)}"
    if not _abs(rec.get("path")):
        return "path must be absolute"
    if rec.get("ownership") not in OWNERSHIP:
        return f"ownership must be one of {', '.join(OWNERSHIP)}"
    if not (_state(rec.get("before")) and _state(rec.get("after"))):
        return "before and after need a kind and a sha256 (64 lowercase hex characters, or null)"
    if rec.get("backup") is not None and not _abs(rec["backup"]):
        return "backup must be an absolute path or null"
    return None


def parse(data):
    """Split intent file bytes into (records, truncated_final_line, invalid_line_numbers)."""
    lines = data.split(b"\n")
    truncated = lines[-1] != b""
    records, bad = [], []
    for n, line in enumerate(lines[:-1], 1):
        try:
            rec = json.loads(line.decode("utf-8"))
        except ValueError:
            bad.append(n)
            continue
        records.append(rec) if isinstance(rec, dict) else bad.append(n)
    return records, truncated, bad


def read(path):
    with open(path, "rb") as f:
        return parse(f.read())


def append(path, rec, job_id=None):
    """Validate and durably append one record. Raises ValueError (invalid) or OSError (I/O)."""
    line = (json.dumps(rec, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    if len(line) > MAX_LINE:
        raise ValueError("record is too large")
    fd = os.open(path, os.O_RDWR | os.O_APPEND)  # never create: the runner owns the file
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        size = os.fstat(fd).st_size
        data = os.pread(fd, size, 0) if size else b""
        records, truncated, bad = parse(data)
        if truncated or bad:
            raise ValueError("the intent file has a damaged record; stop and let the runner recover")
        last = max((r.get("seq") for r in records if isinstance(r.get("seq"), int)), default=0)
        err = validate(rec, last, job_id)
        if err:
            raise ValueError(err)
        n = os.write(fd, line)
        if n != len(line):
            raise OSError("short write")
        os.fsync(fd)
    finally:
        os.close(fd)


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    try:
        rec = json.loads(argv[2])
        append(argv[1], rec, os.environ.get("MCL_JOB_ID") or None)
    except ValueError as e:
        print(f"mcl_intent: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"mcl_intent: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
