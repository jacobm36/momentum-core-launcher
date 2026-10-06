"""Background job runner: installs and other long tasks that outlive the launcher window.

A job is an ordered list of steps; each step is one command (argv list, never a shell string).
State is saved to jobs/<id>.json, diagnostics to jobs/<id>.log and protocol files to jobs/<id>/.

Steps marked "protocol" follow the Momentum Core Package Contract v1: stdout carries JSON events,
stderr goes to the log, exit codes 0/20/30/40/130 map to job outcomes, every run writes a result
file that must agree with its exit code, and cancellation is cooperative through a cancel file.
A step marked "approve_after" pauses the job in "awaiting-approval" until its result (the plan)
is approved by digest; a retry that produces the identical plan does not ask again. Approving saves
the plan's exact bytes as approved-plan.json in the job directory. A step with a "context" template
gets it written to context-<n>.json just before launch, with the runner's own paths filled in.
Once a package has recorded an intent, its job can't be retried; a new job must check again.

The runner never kills a step. Quitting the launcher leaves jobs running. Every launch is recorded
before the process exists (boot ID and an execution token passed in the environment), then its
session ID and start time; after a crash, surviving processes are found again from those facts and
block retries until they exit. Only one runner may own a jobs directory at a time.
"""
import fcntl, hashlib, json, os, re, secrets, shutil, subprocess, threading, time
from pathlib import Path

ID_RE = re.compile(r"^j[0-9a-f]{8}$")
RUNNING = ("queued", "running", "cancel-requested")  # a worker thread owns these
FINISHED = ("succeeded", "needs-action", "conflicted", "failed", "cancelled", "interrupted")
KEEP_FINISHED = 50
EXIT_OUTCOME = {0: "succeeded", 20: "needs-action", 30: "conflicted", 40: "failed", 130: "cancelled"}
RESULT_OUTCOME = {"succeeded": "succeeded", "needs_action": "needs-action", "conflicted": "conflicted",
                  "failed": "failed", "cancelled": "cancelled"}
EVENT_TYPES = ("step_started", "progress", "step_completed", "warning", "needs_action", "result")
STEP_EVENTS = ("step_started", "progress", "step_completed")
MAX_EVENT = 16384
MAX_EVENTS = 20000
MAX_RESULT = 1 << 20
MAX_ACTIONS = 20
ENV_KEEP = ("HOME", "USER", "LOGNAME", "PATH", "LANG", "LANGUAGE", "TZ", "SHELL", "DISPLAY",
            "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS")
INTENT_HELPER = Path(__file__).resolve().parent / "mcl_intent.py"


class RunnerBusy(RuntimeError):
    pass


# -- process identity ---------------------------------------------------------------------------
def boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip() or None
    except OSError:
        return None


def proc_stat(pid):
    """(state, session id, start time in clock ticks since boot) of a process, or None if gone."""
    try:
        s = Path(f"/proc/{pid}/stat").read_bytes()
    except (FileNotFoundError, ProcessLookupError):
        return None
    rest = s[s.rindex(b")") + 2:].split()  # the command name may contain spaces and parentheses
    return rest[0].decode(), int(rest[3]), int(rest[19])


def find_survivors(launches):
    """Processes still alive from recorded launches: (sorted pids, identity_uncertain).

    A launch is {"token", "boot", "sid", "start"}. A session ID can't be reused while any member
    of that session exists, so members of a session whose leader is gone are ours; a live leader
    must also still have the recorded start time. Processes that left the session are recognised
    by the execution token inherited in their environment.
    """
    boot = boot_id()
    if boot is None:
        return [], True
    live = [l for l in launches if l and l.get("boot") == boot]
    if not live:
        return [], False  # a different boot: nothing from those launches can still be running
    tokens = {f"MCL_EXEC_TOKEN={l['token']}".encode() for l in live if l.get("token")}
    sessions, uncertain = set(), False
    for l in live:
        if l.get("sid"):
            try:
                st = proc_stat(l["sid"])
            except OSError:
                uncertain = True
                continue
            if st is None or st[2] == l.get("start"):
                sessions.add(l["sid"])
    me, found = os.getpid(), []
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) == me:
            continue
        pid = int(d)
        try:
            st = proc_stat(pid)
            if st is None or st[0] in ("Z", "X"):
                continue
            if st[1] in sessions:
                found.append(pid)
                continue
            env = Path(f"/proc/{pid}/environ").read_bytes()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue  # gone, or another user's process (ours are always readable)
        except (OSError, ValueError, IndexError):
            uncertain = True
            continue
        if tokens & set(env.split(b"\0")):
            found.append(pid)
    return sorted(found), uncertain


# -- durable files ------------------------------------------------------------------------------
def _fsync_dir(d):
    fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_durable(path, data):
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_event(ev, declared=None):
    """Return why a protocol event is invalid, or None."""
    if not isinstance(ev, dict) or ev.get("event_version") != 1:
        return "event_version must be 1"
    t = ev.get("type")
    if t not in EVENT_TYPES:
        return f"unknown event type {t!r}"
    if not isinstance(ev.get("message"), str):
        return f"{t} event needs a message"
    if t in STEP_EVENTS:
        s = ev.get("step")
        if not isinstance(s, str) or not s:
            return f"{t} event needs a step"
        if declared and s not in declared:
            return f"undeclared step {s!r}"
    if t == "progress" and not (_num(ev.get("current")) and (ev.get("total") is None or _num(ev.get("total")))):
        return "progress needs a numeric current and a numeric or null total"
    if t == "step_completed" and "resources" in ev:
        r = ev["resources"]
        if not (isinstance(r, list) and all(isinstance(x, dict) and isinstance(x.get("path"), str) for x in r)):
            return "resources must be a list of objects with a path"
    if t == "result" and ev.get("outcome") not in RESULT_OUTCOME:
        return "result needs a valid outcome"
    return None


class Jobs:
    def __init__(self, root, intent_helper=INTENT_HELPER, poll=2.0, on_success=None):
        """on_success(job) runs after a protocol job's last step succeeds and before the job is
        marked succeeded; returning a string fails the job with that reason (e.g. receipt not committed)."""
        self.root = Path(root)
        self.root.mkdir(exist_ok=True)
        self._lockf = open(self.root / ".runner.lock", "w")
        try:
            fcntl.flock(self._lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lockf.close()
            raise RunnerBusy(f"another launcher already owns {self.root}") from None
        self.intent_helper = str(intent_helper)
        self.poll = poll
        self.on_success = on_success
        self.lock = threading.RLock()
        self.jobs = {}
        self._load()

    def close(self):
        """Release the runner lock (tests; the server keeps it for its lifetime)."""
        self._lockf.close()

    # -- storage ------------------------------------------------------------------------------
    def _load(self):
        watch = []
        for f in self.root.glob("j*.json"):
            try:
                j = json.loads(f.read_text())
                if not (ID_RE.match(j["id"]) and isinstance(j["steps"], list)):
                    continue
            except (OSError, ValueError, KeyError, TypeError):
                continue
            j.setdefault("protocol", any(s.get("protocol") for s in j["steps"]))
            if j["status"] == "done":  # records from before the package contract
                j["status"] = "succeeded"
            self.jobs[j["id"]] = j
            if j["status"] in RUNNING:
                self._interrupt(j, "The launcher stopped while this job was running.")
            elif j.get("surviving"):
                pids, _ = find_survivors(self._launches(j))
                j["surviving"] = pids
                self._save(j)
            if self.dependency_uncertain(j["id"]):
                j["manual"] = True
                j["error"] = "An unfinished dependency transaction needs reconciliation; its journal is retained."
                self._save(j)
            if j.get("surviving"):
                watch.append(j["id"])
        done = sorted((j for j in self.jobs.values() if j["status"] in FINISHED and not j.get("surviving")
                       and not (self.paths(j["id"])["job_dir"] / "catalog-pending.json").exists()
                       and not self.dependency_uncertain(j["id"])
                       and not (j["status"] != "succeeded" and j["protocol"] and self._intents_recorded(j["id"]))),
                      key=lambda j: j["created"])
        for j in done[:-KEEP_FINISHED]:
            self._remove(j["id"])
        for jid in watch:
            self._watch_survivors(jid)

    def _interrupt(self, j, why):
        pids, uncertain = find_survivors(self._launches(j))
        for s in j["steps"]:
            if s["status"] == "running":
                s["status"] = "pending"
        j.update(status="interrupted", finished=time.time(), surviving=pids, manual=uncertain,
                 error=why + (" Its processes are still running; retry is available once they finish." if pids else "")
                 + (" Couldn't confirm whether its processes are still running; check before retrying." if uncertain else ""))
        self._save(j)

    def _save(self, j):
        _write_durable(self.root / f"{j['id']}.json", json.dumps(j).encode())

    def _remove(self, jid):
        self.jobs.pop(jid, None)
        for ext in ("json", "log"):
            (self.root / f"{jid}.{ext}").unlink(missing_ok=True)
        d = self.root / jid
        if d.is_dir() and not d.is_symlink():
            shutil.rmtree(d, ignore_errors=True)

    def paths(self, jid):
        d = self.root / jid
        return {"job_dir": d, "cancel_file": d / "cancel", "intent_file": d / "intents.jsonl",
                "result_file": d / "result.json", "events_file": d / "events.jsonl", "results_dir": d / "results",
                "approved_plan_file": d / "approved-plan.json"}

    @staticmethod
    def _launches(j):
        return [s["launch"] for s in j["steps"] if s.get("launch")]

    # -- views --------------------------------------------------------------------------------
    @staticmethod
    def summary(j):
        steps = j["steps"]
        done = sum(1 for s in steps if s["status"] == "done")
        run = next((s for s in steps if s["status"] == "running"), None)
        cur = run["name"] if run else None
        if cur is None and j["status"] not in ("succeeded", "queued"):
            cur = next((s["name"] for s in steps if s["status"] != "done"), None)
        return {"id": j["id"], "title": j["title"], "game": j.get("game"), "status": j["status"],
                "kind": (j.get("meta") or {}).get("kind"),
                "installation": j.get("installation"), "readiness": j.get("readiness"),
                "done": done, "total": len(steps), "step": cur, "error": j.get("error"),
                "progress": run.get("progress") if run else None, "actions": j.get("actions") or [],
                "plan_digest": j.get("plan_digest") if j["status"] == "awaiting-approval" else None,
                "surviving": len(j.get("surviving") or []), "manual": bool(j.get("manual")),
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
            if j["status"] == "awaiting-approval":
                try:
                    idx = next(i for i, s in enumerate(j["steps"]) if s.get("result_digest") == j["plan_digest"])
                    data = (self.paths(jid)["results_dir"] / f"step-{idx}.json").read_bytes()
                    if "sha256:" + hashlib.sha256(data).hexdigest() != j["plan_digest"]:
                        raise ValueError("saved plan digest mismatch")
                    out["plan"] = json.loads(data).get("plan")
                    if out["plan"] is None:
                        raise ValueError("no resolved plan was supplied")
                except (OSError, ValueError, StopIteration) as e:
                    out["plan_error"] = f"Cannot review this plan: {e}"
            if (j.get("meta") or {}).get("kind") == "install" and not j["meta"].get("install_enabled"):
                out["approval_blocked"] = ("This package/emulator build lacks matching target evidence. "
                                           "Installation is currently enabled only for tested HOD2 0.1.1 "
                                           "with the verified user-scope Flycast v2.7 build.")
            if (j.get("meta") or {}).get("kind") == "dependency" and j["status"] in FINISHED:
                try:
                    out["dependency_result"] = json.loads((self.paths(jid)["results_dir"] /
                                                          "step-1.json").read_text())
                except FileNotFoundError:
                    pass  # preflight failure has no apply result
                except (OSError, ValueError) as e:
                    out["dependency_error"] = f"Cannot read dependency outcome: {e}"
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
            return sum(1 for j in self.jobs.values() if j["status"] in RUNNING)

    # -- control (each returns True, or a reason it can't) ------------------------------------
    def submit(self, title, steps, game=None, meta=None):
        """steps: [{"name", "argv": [str, ...], "cwd"?, "env"?: {str: str}, "protocol"?: bool,
        "approve_after"?: bool, "declared_steps"?: [str], "context"?: {...}}]
        meta: JSON data kept with the job for whoever submitted it (e.g. what an install is for)."""
        def ok(s):
            return (isinstance(s.get("argv"), list) and s["argv"] and all(isinstance(a, str) for a in s["argv"])
                    and all(isinstance(k, str) and isinstance(v, str) for k, v in (s.get("env") or {}).items())
                    and isinstance(s.get("context") or {}, dict))
        if not steps or not all(isinstance(s, dict) and ok(s) for s in steps):
            raise ValueError("a job needs steps with an argv list")
        jid = "j" + secrets.token_hex(4)
        j = {"id": jid, "title": str(title)[:120], "game": game, "status": "queued", "created": time.time(),
             "protocol": any(bool(s.get("protocol")) for s in steps),
             "steps": [{"name": str(s.get("name") or s["argv"][0])[:120], "argv": s["argv"], "cwd": s.get("cwd"),
                        "env": dict(s.get("env") or {}), "protocol": bool(s.get("protocol")),
                        "approve_after": bool(s.get("approve_after")),
                        "declared_steps": [str(x) for x in s.get("declared_steps") or []], "status": "pending",
                        **({"context": json.loads(json.dumps(s["context"]))} if s.get("context") else {})}
                       for s in steps]}
        if meta is not None:
            j["meta"] = json.loads(json.dumps(meta))
        p = self.paths(jid)
        p["job_dir"].mkdir()
        p["results_dir"].mkdir()
        if j["protocol"]:
            # The intent file exists, empty and durable, before any step can append to it.
            fd = os.open(p["intent_file"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.fsync(fd)
            os.close(fd)
            _fsync_dir(p["job_dir"])
        _fsync_dir(self.root)
        with self.lock:
            self.jobs[jid] = j
            self._save(j)
        self._start(jid)
        return jid

    def _start(self, jid):
        threading.Thread(target=self._run, args=(jid,), daemon=True).start()

    def approve(self, jid, digest):
        with self.lock:
            j = self.jobs.get(jid)
            if not j or j["status"] != "awaiting-approval":
                return "this job isn't waiting for approval"
            if not digest or digest != j.get("plan_digest"):
                return "the plan changed; review it again"
            # Keep the exact approved bytes; the package checks its apply against them.
            p = self.paths(jid)
            i = next((i for i, s in enumerate(j["steps"]) if s.get("result_digest") == digest), None)
            try:
                data = (p["results_dir"] / f"step-{i}.json").read_bytes() if i is not None else b""
            except OSError:
                data = b""
            if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
                return "the saved plan is missing or changed; retry to make a new one"
            _write_durable(p["approved_plan_file"], data)
            j.update(status="queued", approved_plan_digest=digest, plan_digest=None, error=None)
            self._save(j)
        self._start(jid)
        return True

    def cancel(self, jid):
        with self.lock:
            j = self.jobs.get(jid)
            if not j:
                return "unknown job"
            if j["status"] == "awaiting-approval":  # nothing is running and nothing was applied
                j.update(status="cancelled", finished=time.time(), plan_digest=None)
                self._save(j)
                return True
            if j["status"] not in RUNNING:
                return "this job isn't running"
            if j.get("cancel"):
                return True
            j["cancel"] = True
            if j["status"] == "running":
                j["status"] = "cancel-requested"
            self._save(j)
            _write_durable(self.paths(jid)["cancel_file"], b"cancel\n")
        return True

    def retry(self, jid):
        with self.lock:
            j = self.jobs.get(jid)
            if not j or j["status"] not in FINISHED or j["status"] == "succeeded":
                return "this job can't be retried"
            if self.dependency_uncertain(jid):
                return "an unfinished dependency transaction needs reconciliation before retry"
            if j.get("manual"):
                return "check this job's processes by hand, then dismiss it"
            if j["protocol"] and self._intents_recorded(jid):
                return "this job already started changing files; start a new one, which checks what's there first"
            if j.get("surviving"):
                pids, _ = find_survivors(self._launches(j))
                j["surviving"] = pids
                self._save(j)
                if pids:
                    return "its processes are still running"
            for s in j["steps"]:
                # Package jobs always start again from preflight; plain jobs resume after the last done step.
                if j["protocol"] or s["status"] != "done":
                    s.update(status="pending", progress=None)
            j.update(status="queued", error=None, finished=None, cancel=False, actions=[], surviving=[])
            self.paths(jid)["cancel_file"].unlink(missing_ok=True)
            self._save(j)
        self._start(jid)
        return True

    def _intents_recorded(self, jid):
        try:
            return self.paths(jid)["intent_file"].stat().st_size > 0
        except FileNotFoundError:
            return False
        except OSError:
            return True

    def dependency_uncertain(self, jid):
        path = self.paths(jid)["job_dir"] / "dependency-transactions.json"
        try:
            record = json.loads(path.read_text())
        except FileNotFoundError:
            return False
        except (OSError, ValueError):
            return True
        return (not isinstance(record, dict) or record.get("job_id") != jid
                or "active_command" not in record or not isinstance(record.get("completed"), list)
                or bool(record.get("active_command")) or bool(record.get("detection_pending")))

    def dismiss(self, jid):
        with self.lock:
            j = self.jobs.get(jid)
            if not j or j["status"] not in FINISHED:
                return "only finished jobs can be dismissed"
            if j.get("surviving"):
                return "its processes are still running"
            if self.dependency_uncertain(jid):
                return "unfinished dependency evidence must be reconciled before dismissal"
            if (self.paths(jid)["job_dir"] / "catalog-pending.json").exists() or (
                    j["status"] != "succeeded" and j["protocol"] and self._intents_recorded(jid)):
                return "recovery evidence must be reconciled before this job can be dismissed"
            self._remove(jid)
        return True

    def _watch_survivors(self, jid):
        def watch():
            while True:
                time.sleep(self.poll)
                with self.lock:
                    j = self.jobs.get(jid)
                    if not j or not j.get("surviving"):
                        return
                    launches = self._launches(j)
                pids, _ = find_survivors(launches)
                with self.lock:
                    if j.get("surviving") != pids:
                        j["surviving"] = pids
                        self._save(j)
                    if not pids:
                        self._note(jid, "All of this job's processes have exited.")
                        return
        threading.Thread(target=watch, daemon=True).start()

    def _note(self, jid, text):
        try:
            with open(self.root / f"{jid}.log", "ab") as f:
                f.write(f"[runner] {text}\n".encode())
        except OSError:
            pass

    # -- runner -------------------------------------------------------------------------------
    def _finish(self, j, status, error=None):
        if self.dependency_uncertain(j["id"]):
            j["manual"] = True
        j.update(status=status, error=error, finished=time.time())
        self._save(j)

    def _run(self, jid):
        with self.lock:
            j = self.jobs[jid]
            if j.get("cancel"):
                return self._finish(j, "cancelled")
            j.update(status="running", started=j.get("started") or time.time())
            self._save(j)
        steps = j["steps"]
        for i, step in enumerate(steps):
            if step["status"] == "done":
                continue
            with self.lock:
                if j.get("cancel"):
                    return self._finish(j, "cancelled")
                # Record the launch before the process exists, so a crash in between can still find it.
                step.update(status="running", progress=None,
                            launch={"token": secrets.token_hex(16), "boot": boot_id(), "t": time.time()})
                self._save(j)
            outcome, why = self._run_step(j, i, step)
            pids, _ = find_survivors([step["launch"]])
            with self.lock:
                if pids:
                    step["status"] = "failed"
                    j["surviving"] = pids
                    self._finish(j, "failed", f"{step['name']}: left {len(pids)} process(es) running; "
                                 "retry is available once they finish")
                    self._watch_survivors(jid)
                    return
                if outcome != "succeeded":
                    step["status"] = "pending" if outcome in ("cancelled", "interrupted") else outcome
                    return self._finish(j, outcome, f"{step['name']}: {why}" if why else None)
                step["status"] = "done"
                if step.get("approve_after") and step.get("result_digest") != j.get("approved_plan_digest"):
                    if j.get("cancel"):
                        return self._finish(j, "cancelled")
                    j.update(status="awaiting-approval", plan_digest=step.get("result_digest"))
                    self._save(j)
                    return
                self._save(j)
        if self.on_success and j["protocol"]:
            try:
                why = self.on_success(j)
            except Exception as e:  # never leave a job running because the commit step broke
                why = f"couldn't record the result: {e}"
            if why:
                self._note(jid, why)
                with self.lock:
                    return self._finish(j, "failed", str(why)[:500])
        with self.lock:
            self._finish(j, "succeeded")

    def _env(self, j, step, token):
        if step.get("protocol"):
            env = {k: v for k, v in os.environ.items() if k in ENV_KEEP or k.startswith(("XDG_", "LC_"))}
        else:
            env = dict(os.environ)
        env.update(step.get("env") or {})
        p = self.paths(j["id"])
        env.update(MCL_JOB_ID=j["id"], MCL_EXEC_TOKEN=token, MCL_JOB_DIR=str(p["job_dir"]),
                   MCL_CANCEL_FILE=str(p["cancel_file"]), MCL_INTENT_FILE=str(p["intent_file"]),
                   MCL_RESULT_FILE=str(p["result_file"]), MCL_INTENT_HELPER=self.intent_helper,
                   MCL_APPROVED_PLAN_DIGEST=j.get("approved_plan_digest") or "")
        return env

    def _context(self, j, step):
        """The step's context template plus the runner-owned fields (Package Contract v1 §5)."""
        p = self.paths(j["id"])
        approved = None if step.get("approve_after") else j.get("approved_plan_digest")
        ctx = dict(step["context"], job_id=j["id"], cancel_file=str(p["cancel_file"]),
                   intent_file=str(p["intent_file"]), result_file=str(p["result_file"]),
                   intent_helper=self.intent_helper, approved_plan_digest=approved)
        if approved:
            ctx["approved_plan_file"] = str(p["approved_plan_file"])
        return ctx

    def _argv(self, j, i, step):
        p = self.paths(j["id"])
        sub = {"{job_dir}": str(p["job_dir"]), "{cancel_file}": str(p["cancel_file"]),
               "{context_file}": str(p["job_dir"] / f"context-{i}.json"),
               "{intent_file}": str(p["intent_file"]), "{result_file}": str(p["result_file"]),
               "{intent_helper}": self.intent_helper, "{approved_plan_digest}": j.get("approved_plan_digest") or ""}
        out = []
        for a in step["argv"]:
            for k, v in sub.items():
                a = a.replace(k, v)
            out.append(a)
        return out

    def _run_step(self, j, i, step):
        """Run one step to completion; returns (outcome, reason)."""
        jid, p = j["id"], self.paths(j["id"])
        protocol = step.get("protocol")
        if protocol:
            p["result_file"].unlink(missing_ok=True)
        if step.get("context"):
            try:
                _write_durable(p["job_dir"] / f"context-{i}.json", json.dumps(self._context(j, step)).encode())
            except OSError as e:
                return "failed", f"could not write the context file: {e}"
        try:
            log = open(self.root / f"{jid}.log", "ab")
        except OSError:
            log = None
        try:
            if log:
                log.write(f"\n== {step['name']} ==\n".encode())
                log.flush()
            try:
                proc = subprocess.Popen(self._argv(j, i, step), cwd=step.get("cwd") or None, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE if protocol else (log or subprocess.DEVNULL),
                                        stderr=log or subprocess.DEVNULL, env=self._env(j, step, step["launch"]["token"]),
                                        start_new_session=True)
            except OSError as e:
                if log:
                    log.write(f"could not start: {e}\n".encode())
                return "failed", f"could not start: {e}"
            try:
                st = proc_stat(proc.pid)
            except OSError:
                st = None
            with self.lock:
                step["launch"].update(sid=proc.pid, start=st[2] if st else None)
                self._save(j)
            perr = []
            reader = None
            if protocol:
                reader = threading.Thread(target=self._read_events, args=(j, i, step, proc.stdout, perr, log), daemon=True)
                reader.start()
            rc = proc.wait()
            if reader:
                reader.join(5)  # a leftover child holding stdout is caught as a survivor
        finally:
            if log:
                log.close()
        if rc < 0:
            return "interrupted", f"stopped by signal {-rc}"
        if not protocol:
            return ("succeeded", None) if rc == 0 else ("failed", f"exit code {rc}")
        if perr:
            return "failed", f"protocol error: {perr[0]}"
        expected = EXIT_OUTCOME.get(rc)
        if expected is None:
            return "failed", f"exit code {rc}"
        res, err = self._take_result(j, i, step)
        if err:
            return "failed", err
        got = RESULT_OUTCOME.get(res.get("outcome"))
        if got != expected:
            return "failed", f"exit code {rc} contradicts result outcome {res.get('outcome')!r}"
        if expected == "cancelled" and not j.get("cancel"):
            return "failed", "reported a cancellation that wasn't requested"
        msg = res.get("message") if isinstance(res.get("message"), str) else ""
        return expected, (msg[:300] or None)

    def _take_result(self, j, i, step):
        """Validate the step's result file and keep a copy; returns (result, error)."""
        p = self.paths(j["id"])
        try:
            if p["result_file"].stat().st_size > MAX_RESULT:
                return None, "result file is too large"
            data = p["result_file"].read_bytes()
            res = json.loads(data.decode("utf-8"))
        except FileNotFoundError:
            return None, "no result file was written"
        except (OSError, ValueError) as e:
            return None, f"unreadable result file: {e}"
        if not isinstance(res, dict):
            return None, "result file must be a JSON object"
        _write_durable(p["results_dir"] / f"step-{i}.json", data)
        with self.lock:
            step["result_digest"] = "sha256:" + hashlib.sha256(data).hexdigest()
            self._save(j)
        return res, None

    def _read_events(self, j, i, step, pipe, perr, log):
        """Journal and apply protocol events from a step's stdout until it closes."""
        p = self.paths(j["id"])
        declared = step.get("declared_steps") or None
        try:
            ev_file = open(p["events_file"], "ab")
        except OSError as e:
            perr.append(f"can't record events: {e}")
            ev_file = None
        count = 0
        try:
            while True:
                line = pipe.readline(MAX_EVENT + 1)
                if not line:
                    break
                if not line.endswith(b"\n") and len(line) > MAX_EVENT:
                    while line and not line.endswith(b"\n"):
                        line = pipe.readline(MAX_EVENT + 1)
                    perr.append("event longer than 16 KiB")
                    continue
                if perr or not line.strip():
                    continue  # after a protocol error, keep draining so the step isn't blocked
                count += 1
                try:
                    ev = json.loads(line.decode("utf-8"))
                    bad = validate_event(ev, declared) if count <= MAX_EVENTS else "too many events"
                except ValueError:
                    bad = "stdout line is not a JSON event"
                if bad:
                    perr.append(bad)
                    if log:
                        log.write(f"[runner] protocol error: {bad}\n".encode())
                        log.flush()
                    continue
                self._apply_event(j, i, step, ev, ev_file, log)
        finally:
            pipe.close()
            if ev_file:
                ev_file.close()

    def _apply_event(self, j, i, step, ev, ev_file, log):
        t = ev["type"]
        with self.lock:
            j["event_seq"] = j.get("event_seq", 0) + 1
            if ev_file:
                ev_file.write((json.dumps({"seq": j["event_seq"], "t": time.time(), "step_index": i, "event": ev}) + "\n").encode())
                ev_file.flush()
                if t != "progress":
                    os.fsync(ev_file.fileno())
            if t in STEP_EVENTS:
                step["progress"] = {"step": ev["step"], "message": ev["message"][:300]}
                if t == "progress":
                    step["progress"].update(current=ev["current"], total=ev.get("total"), unit=str(ev.get("unit") or "")[:20])
            elif t == "warning" and log:
                log.write(f"[warning] {ev['message']}\n".encode())
                log.flush()
            elif t == "needs_action":
                acts = j.setdefault("actions", [])
                if len(acts) < MAX_ACTIONS:
                    acts.append({"message": ev["message"][:500], "action_id": str(ev.get("action_id") or "")[:64],
                                 "blocks_play": bool(ev.get("blocks_play"))})
            if t != "progress":
                self._save(j)
