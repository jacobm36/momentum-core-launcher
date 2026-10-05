"""Background jobs (installs and other long tasks) that outlive the browser page.

A job is an ordered list of steps; each step is one command (argv list, never a shell string).
State is saved to jobs/<id>.json and output to jobs/<id>.log after every change, so a closed or
suspended page loses nothing, and a job that failed or was interrupted can be retried: finished
steps are skipped, so steps should be safe to repeat.
"""
import json, os, re, secrets, signal, subprocess, tempfile, threading, time
from pathlib import Path

ACTIVE = ("queued", "running")
FINISHED = ("done", "failed", "cancelled", "interrupted")
ID_RE = re.compile(r"^j[0-9a-f]{8}$")
KEEP_FINISHED = 50


def _kill_group(p, sig):
    try:
        os.killpg(p.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


class Jobs:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = {}      # id -> job dict
        self.procs = {}     # id -> running Popen
        self.cancelled = set()
        self._load()

    # -- storage ------------------------------------------------------------------------------
    def _load(self):
        for f in self.root.glob("j*.json"):
            try:
                j = json.loads(f.read_text())
                if not (ID_RE.match(j["id"]) and isinstance(j["steps"], list)):
                    continue
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if j["status"] in ACTIVE:
                # The launcher closed mid-job. Whatever step was running may be half done.
                j["status"] = "interrupted"
                j["finished"] = j.get("finished") or time.time()
                for s in j["steps"]:
                    if s["status"] == "running":
                        s["status"] = "pending"
                self._save(j)
            self.jobs[j["id"]] = j
        done = sorted((j for j in self.jobs.values() if j["status"] in FINISHED), key=lambda j: j["created"])
        for j in done[:-KEEP_FINISHED]:
            self._remove(j["id"])

    def _save(self, j):
        fd, name = tempfile.mkstemp(dir=self.root, prefix=".j.", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(j, f)
        os.replace(name, self.root / f"{j['id']}.json")

    def _remove(self, jid):
        self.jobs.pop(jid, None)
        for ext in ("json", "log"):
            (self.root / f"{jid}.{ext}").unlink(missing_ok=True)

    # -- views --------------------------------------------------------------------------------
    @staticmethod
    def summary(j):
        steps = j["steps"]
        done = sum(1 for s in steps if s["status"] == "done")
        cur = next((s["name"] for s in steps if s["status"] == "running"), None)
        if cur is None and j["status"] in ("failed", "interrupted", "cancelled"):
            cur = next((s["name"] for s in steps if s["status"] in ("failed", "pending")), None)
        return {"id": j["id"], "title": j["title"], "game": j.get("game"), "status": j["status"],
                "done": done, "total": len(steps), "step": cur, "error": j.get("error"),
                "created": j["created"], "started": j.get("started"), "finished": j.get("finished"),
                "steps": [{"name": s["name"], "status": s["status"]} for s in steps]}

    def list(self):
        with self.lock:
            return [self.summary(j) for j in sorted(self.jobs.values(), key=lambda j: j["created"], reverse=True)]

    def get(self, jid, tail=8000):
        with self.lock:
            j = self.jobs.get(jid)
            if not j:
                return None
            out = self.summary(j)
        out["log"] = self._tail(jid, max(0, min(int(tail), 65536)))
        return out

    def _tail(self, jid, n):
        try:
            with open(self.root / f"{jid}.log", "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - n))
                return f.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def active_count(self):
        with self.lock:
            return sum(1 for j in self.jobs.values() if j["status"] in ACTIVE)

    # -- control ------------------------------------------------------------------------------
    def submit(self, title, steps, game=None):
        """steps: [{"name": str, "argv": [str, ...], "cwd": optional str}]"""
        if not steps or not all(isinstance(s.get("argv"), list) and s["argv"] and all(isinstance(a, str) for a in s["argv"]) for s in steps):
            raise ValueError("a job needs steps with an argv list")
        j = {"id": "j" + secrets.token_hex(4), "title": str(title)[:120], "game": game, "status": "queued",
             "created": time.time(), "steps": [{"name": str(s.get("name") or s["argv"][0])[:120], "argv": s["argv"],
                                                 "cwd": s.get("cwd"), "status": "pending"} for s in steps]}
        with self.lock:
            self.jobs[j["id"]] = j
            self._save(j)
        self._start(j["id"])
        return j["id"]

    def _start(self, jid):
        threading.Thread(target=self._run, args=(jid,), daemon=True).start()

    def retry(self, jid):
        with self.lock:
            j = self.jobs.get(jid)
            if not j or j["status"] not in ("failed", "cancelled", "interrupted"):
                return False
            for s in j["steps"]:
                if s["status"] in ("failed", "running"):
                    s["status"] = "pending"
            j.update(status="queued", error=None, finished=None)
            self.cancelled.discard(jid)
            self._save(j)
        self._start(jid)
        return True

    def cancel(self, jid):
        with self.lock:
            j = self.jobs.get(jid)
            if not j or j["status"] not in ACTIVE:
                return False
            self.cancelled.add(jid)
            p = self.procs.get(jid)
        if p:
            _kill_group(p, signal.SIGTERM)
            threading.Timer(3, _kill_group, (p, signal.SIGKILL)).start()
        return True

    def dismiss(self, jid):
        with self.lock:
            j = self.jobs.get(jid)
            if not j or j["status"] not in FINISHED:
                return False
            self._remove(jid)
        return True

    def shutdown(self):
        """Stop every running job (called when the launcher exits); they can be retried next time."""
        with self.lock:
            ids = [i for i, j in self.jobs.items() if j["status"] in ACTIVE]
            procs = [self.procs.get(i) for i in ids]
            self.cancelled.update(ids)
        for p in filter(None, procs):
            _kill_group(p, signal.SIGKILL)
        time.sleep(0.2)
        with self.lock:
            for i in ids:
                j = self.jobs[i]
                if j["status"] in ACTIVE:
                    j["status"] = "interrupted"
                    for s in j["steps"]:
                        if s["status"] == "running":
                            s["status"] = "pending"
                    self._save(j)

    # -- runner -------------------------------------------------------------------------------
    def _run(self, jid):
        with self.lock:
            j = self.jobs[jid]
            j.update(status="running", started=j.get("started") or time.time())
            self._save(j)
        try:
            log = open(self.root / f"{jid}.log", "ab")
        except OSError:
            log = subprocess.DEVNULL
        try:
            for step in j["steps"]:
                if step["status"] == "done":
                    continue
                with self.lock:
                    if jid in self.cancelled:
                        break
                    step["status"] = "running"
                    self._save(j)
                if log is not subprocess.DEVNULL:
                    log.write(f"\n== {step['name']} ==\n".encode())
                    log.flush()
                try:
                    p = subprocess.Popen(step["argv"], cwd=step.get("cwd") or None, stdin=subprocess.DEVNULL,
                                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                except OSError as e:
                    rc, why = -1, f"could not start: {e}"
                    if log is not subprocess.DEVNULL:
                        log.write(f"{why}\n".encode())
                else:
                    with self.lock:
                        self.procs[jid] = p
                        stop = jid in self.cancelled
                    if stop:  # cancelled in the instant before the process existed
                        _kill_group(p, signal.SIGKILL)
                    rc = p.wait()
                    _kill_group(p, signal.SIGKILL)  # leave nothing from this step running
                    why = f"exit code {rc}"
                with self.lock:
                    self.procs.pop(jid, None)
                    if jid in self.cancelled:
                        step["status"] = "pending"
                        break
                    step["status"] = "done" if rc == 0 else "failed"
                    self._save(j)
                    if rc != 0:
                        j.update(status="failed", error=f"{step['name']}: {why}", finished=time.time())
                        self._save(j)
                        return
            with self.lock:
                if jid in self.cancelled:
                    j.update(status="cancelled", finished=time.time())
                else:
                    j.update(status="done", finished=time.time())
                self._save(j)
        finally:
            if log is not subprocess.DEVNULL:
                log.close()
