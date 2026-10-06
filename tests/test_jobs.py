"""Job runner tests with fake packages only (no games, emulators or library files are touched)."""
import json, os, signal, subprocess, sys, tempfile, textwrap, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jobs as jobsmod  # noqa: E402
from jobs import Jobs, RunnerBusy, find_survivors, proc_stat, validate_event  # noqa: E402

PY = sys.executable


def script(body):
    """A fake package step: python code with helpers for events and results."""
    pre = textwrap.dedent("""\
        import json, os, sys, time
        def ev(t, msg, **k):
            print(json.dumps(dict(event_version=1, type=t, message=msg, **k)), flush=True)
        def result(outcome, msg="", **k):
            p = os.environ["MCL_RESULT_FILE"]
            with open(p + ".tmp", "w") as f: json.dump(dict(outcome=outcome, message=msg, **k), f)
            os.replace(p + ".tmp", p)
        def cancelled(): return os.path.exists(os.environ["MCL_CANCEL_FILE"])
        """)
    return [PY, "-c", pre + textwrap.dedent(body)]


def wait(cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("timed out")


def kill_quietly(pid, group=False):
    try:
        (os.killpg if group else os.kill)(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "jobs"
        self.j = Jobs(self.root, poll=0.2)

    def tearDown(self):
        self.j.close()
        self.tmp.cleanup()

    def status(self, jid):
        return self.j.get(jid)["status"]

    def until(self, jid, *states):
        return wait(lambda: self.status(jid) in states and self.j.get(jid))


class PlainJobs(Base):
    def test_success_and_failure_and_resume(self):
        ok = self.j.submit("ok", [{"name": "a", "argv": [PY, "-c", "print('hi')"]}])
        self.assertEqual(self.until(ok, "succeeded")["done"], 1)
        self.assertIn("hi", self.j.get(ok)["log"])
        marker = Path(self.tmp.name) / "m"
        bad = self.j.submit("bad", [{"name": "a", "argv": [PY, "-c", f"open({str(marker)!r},'a').write('x')"]},
                                    {"name": "b", "argv": [PY, "-c", "raise SystemExit(3)"]}])
        info = self.until(bad, "failed")
        self.assertIn("exit code 3", info["error"])
        self.assertIs(self.j.retry(bad), True)
        self.until(bad, "failed")
        self.assertEqual(marker.read_text(), "x")  # plain jobs resume after the last done step

    def test_cancel_waits_for_step_boundary_without_killing(self):
        marker = Path(self.tmp.name) / "finished"
        jid = self.j.submit("c", [{"name": "slow", "argv": [PY, "-c", f"import time; time.sleep(1.5); open({str(marker)!r},'w')"]},
                                  {"name": "next", "argv": [PY, "-c", "raise SystemExit(9)"]}])
        self.until(jid, "running")
        self.assertIs(self.j.cancel(jid), True)
        self.assertEqual(self.status(jid), "cancel-requested")
        self.until(jid, "cancelled")
        self.assertTrue(marker.exists())  # the running step was allowed to finish

    def test_step_leaving_a_process_running_blocks_retry(self):
        jid = self.j.submit("leak", [{"name": "a", "argv": ["bash", "-c", "sleep 30 >/dev/null 2>&1 & exit 0"]}])
        info = self.until(jid, "failed")
        self.assertIn("left 1 process", info["error"])
        self.assertEqual(info["surviving"], 1)
        self.assertNotEqual(self.j.retry(jid), True)
        self.assertNotEqual(self.j.dismiss(jid), True)
        kill_quietly(self.j.jobs[jid]["surviving"][0])  # our own fake process
        wait(lambda: self.j.get(jid)["surviving"] == 0)
        self.assertIs(self.j.dismiss(jid), True)

    def test_legacy_done_status_is_migrated(self):
        self.j.close()
        rec = {"id": "j0000abcd", "title": "old", "status": "done", "created": 1,
               "steps": [{"name": "a", "argv": ["true"], "status": "done"}]}
        (self.root / "j0000abcd.json").write_text(json.dumps(rec))
        self.j = Jobs(self.root, poll=0.2)
        self.assertEqual(self.status("j0000abcd"), "succeeded")


class ProtocolJobs(Base):
    def pkg(self, preflight, apply):
        return [{"name": "Preflight", "argv": script(preflight), "protocol": True, "approve_after": True,
                 "declared_steps": ["validate"]},
                {"name": "Apply", "argv": script(apply), "protocol": True, "declared_steps": ["stage", "configure"]}]

    PRE = """
        ev("step_started", "Checking", step="validate")
        result("succeeded", "plan ok", phase="preflight", plan={"files": ["a"]})
        """

    def test_preflight_approval_apply(self):
        out = Path(self.tmp.name) / "applied"
        jid = self.j.submit("pkg", self.pkg(self.PRE, f"""
            ev("step_started", "Copying", step="stage")
            ev("progress", "Copying", step="stage", current=1, total=2, unit="MiB")
            print("diagnostic", file=sys.stderr)
            open({str(out)!r}, "w").write(os.environ["MCL_APPROVED_PLAN_DIGEST"])
            ev("step_completed", "Copied", step="stage", resources=[{{"path": "/tmp/x", "ownership": "managed"}}])
            result("succeeded", "done", phase="apply")
            """))
        info = self.until(jid, "awaiting-approval")
        digest = info["plan_digest"]
        self.assertTrue(digest.startswith("sha256:"))
        self.assertFalse(out.exists())  # nothing applied before approval
        self.assertNotEqual(self.j.approve(jid, "sha256:wrong"), True)
        self.assertIs(self.j.approve(jid, digest), True)
        self.until(jid, "succeeded")
        self.assertEqual(out.read_text(), digest)
        self.assertIn("diagnostic", self.j.get(jid)["log"])  # stderr goes to the log
        events = [json.loads(l) for l in (self.root / jid / "events.jsonl").read_text().splitlines()]
        self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))
        self.assertEqual(events[-1]["event"]["resources"][0]["path"], "/tmp/x")
        self.assertTrue((self.root / jid / "results" / "step-1.json").exists())

    def test_retry_reruns_preflight_and_only_asks_again_when_plan_changes(self):
        flag = Path(self.tmp.name) / "fail-once"
        plan = Path(self.tmp.name) / "plan"
        plan.write_text("A")
        pre = f"""
            result("succeeded", "plan", phase="preflight", plan=open({str(plan)!r}).read())
            """
        apply = f"""
            if os.path.exists({str(flag)!r}):
                os.remove({str(flag)!r}); result("failed", "disk full"); sys.exit(40)
            result("succeeded", "ok")
            """
        flag.write_text("")
        jid = self.j.submit("pkg", self.pkg(pre, apply))
        self.j.approve(jid, self.until(jid, "awaiting-approval")["plan_digest"])
        self.assertIn("disk full", self.until(jid, "failed")["error"])
        self.assertIs(self.j.retry(jid), True)
        self.until(jid, "succeeded")  # same plan: no second approval
        flag.write_text("")
        jid2 = self.j.submit("pkg2", self.pkg(pre, apply))
        d1 = self.until(jid2, "awaiting-approval")["plan_digest"]
        self.j.approve(jid2, d1)
        self.until(jid2, "failed")
        plan.write_text("B")
        self.j.retry(jid2)
        self.assertNotEqual(self.until(jid2, "awaiting-approval")["plan_digest"], d1)  # changed plan asks again

    def test_exit_codes_and_results(self):
        cases = [
            ('ev("needs_action", "Map the lightgun", action_id="lightgun-mapping", blocks_play=True); result("needs_action", "setup"); sys.exit(20)', "needs-action", None),
            ('result("conflicted", "folder exists"); sys.exit(30)', "conflicted", "folder exists"),
            ('sys.exit(0)', "failed", "no result file"),
            ('result("failed", "x"); sys.exit(0)', "failed", "contradicts"),
            ('result("cancelled"); sys.exit(130)', "failed", "wasn't requested"),
            ('result("succeeded"); sys.exit(7)', "failed", "exit code 7"),
            ('print("not json", flush=True); result("succeeded")', "failed", "protocol error"),
            ('ev("progress", "x", step="nope", current=1, total=2); result("succeeded")', "failed", "undeclared step"),
        ]
        for body, status, err in cases:
            with self.subTest(body=body):
                jid = self.j.submit("t", [{"name": "Preflight", "argv": script(body), "protocol": True, "declared_steps": ["validate"]}])
                info = self.until(jid, *jobsmod.FINISHED)
                self.assertEqual(info["status"], status)
                if err:
                    self.assertIn(err, info["error"] or "")
        needs = [j for j in self.j.list() if j["status"] == "needs-action"][0]
        self.assertEqual(needs["actions"][0]["action_id"], "lightgun-mapping")

    def test_cooperative_cancel(self):
        jid = self.j.submit("c", [{"name": "Apply", "protocol": True, "argv": script("""
            while not cancelled(): time.sleep(0.05)
            result("cancelled", "stopped at a safe point"); sys.exit(130)
            """)}])
        self.until(jid, "running")
        time.sleep(0.2)
        self.j.cancel(jid)
        self.assertEqual(self.status(jid), "cancel-requested")
        self.until(jid, "cancelled")

    def test_cancel_while_awaiting_approval(self):
        jid = self.j.submit("pkg", self.pkg(self.PRE, 'result("succeeded")'))
        self.until(jid, "awaiting-approval")
        self.assertIs(self.j.cancel(jid), True)
        self.assertEqual(self.status(jid), "cancelled")

    def test_minimal_environment_and_paths(self):
        os.environ["MCL_TEST_SECRET"] = "1"
        try:
            jid = self.j.submit("env", [{"name": "s", "protocol": True, "argv": script("""
                assert "MCL_TEST_SECRET" not in os.environ
                assert os.path.exists(os.environ["MCL_INTENT_FILE"])
                assert os.environ["MCL_EXEC_TOKEN"] and os.environ["MCL_JOB_ID"]
                result("succeeded")
                """)}])
            self.until(jid, "succeeded")
        finally:
            del os.environ["MCL_TEST_SECRET"]

    def test_intent_helper_from_a_step(self):
        jid = self.j.submit("intent", [{"name": "s", "protocol": True, "argv": script("""
            import subprocess
            rec = dict(intent_version=1, job_id=os.environ["MCL_JOB_ID"], seq=1, step="configure", op="create",
                       path="/tmp/example", ownership="managed", before={"kind": "absent", "sha256": None},
                       after={"kind": "file", "sha256": "a" * 64}, backup=None)
            h = os.environ["MCL_INTENT_HELPER"]
            assert subprocess.run([sys.executable, h, os.environ["MCL_INTENT_FILE"], json.dumps(rec)]).returncode == 0
            assert subprocess.run([sys.executable, h, os.environ["MCL_INTENT_FILE"], json.dumps(rec)]).returncode == 2
            result("succeeded")
            """)}])
        self.until(jid, "succeeded")
        self.assertEqual(len((self.root / jid / "intents.jsonl").read_text().splitlines()), 1)


class Recovery(unittest.TestCase):
    """A runner that dies mid-step; a new runner must find the surviving step and not retry over it."""

    def test_crash_with_surviving_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "jobs"
            here = Path(__file__).resolve().parent.parent
            crash = textwrap.dedent(f"""
                import sys, time, os
                sys.path.insert(0, {str(here)!r})
                from jobs import Jobs
                j = Jobs({str(root)!r})
                jid = j.submit("crash", [{{"name": "long", "argv": ["bash", "-c", "sleep 30 & wait"]}}])
                while not j.jobs[jid]["steps"][0].get("launch", {{}}).get("sid"): time.sleep(0.05)
                time.sleep(0.3)
                print(jid, flush=True)
                os._exit(1)
                """)
            jid = subprocess.run([PY, "-c", crash], capture_output=True, text=True, timeout=20).stdout.strip()
            self.assertTrue(jid)
            j = Jobs(root, poll=0.2)
            try:
                info = j.get(jid)
                self.assertEqual(info["status"], "interrupted")
                self.assertEqual(info["surviving"], 2)  # bash and its sleep child
                self.assertIn("still running", info["error"])
                self.assertNotEqual(j.retry(jid), True)
                for pid in j.jobs[jid]["surviving"]:
                    kill_quietly(pid)  # our own fake processes
                wait(lambda: j.get(jid)["surviving"] == 0)
                old = j.jobs[jid]["steps"][0]["launch"]["sid"]
                self.assertIs(j.retry(jid), True)
                new = wait(lambda: (j.jobs[jid]["steps"][0].get("launch") or {}).get("sid") not in (None, old)
                           and j.jobs[jid]["steps"][0]["launch"]["sid"])
                kill_quietly(new, group=True)
                self.assertEqual(wait(lambda: j.get(jid)["status"] in jobsmod.FINISHED and j.get(jid))["status"], "interrupted")
            finally:
                for s in j.jobs.get(jid, {}).get("steps", []):
                    if (s.get("launch") or {}).get("sid"):
                        kill_quietly(s["launch"]["sid"], group=True)
                j.close()

    def test_other_boot_means_no_survivors(self):
        self.assertEqual(find_survivors([{"token": "x", "boot": "not-this-boot", "sid": os.getpid(), "start": 0}]), ([], False))

    def test_pid_reuse_is_not_identity(self):
        st = proc_stat(os.getpid())
        launch = {"token": "nope", "boot": jobsmod.boot_id(), "sid": st[1], "start": st[2] + 1}
        self.assertEqual(find_survivors([launch])[0], [])

    def test_only_one_runner_per_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Jobs(Path(tmp) / "jobs")
            try:
                with self.assertRaises(RunnerBusy):
                    Jobs(Path(tmp) / "jobs")
            finally:
                a.close()

    def test_awaiting_approval_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "jobs"
            a = Jobs(root)
            jid = a.submit("p", [{"name": "pre", "protocol": True, "approve_after": True, "argv": script('result("succeeded")')},
                                 {"name": "apply", "protocol": True, "argv": script('result("succeeded")')}])
            wait(lambda: a.get(jid)["status"] == "awaiting-approval")
            digest = a.get(jid)["plan_digest"]
            a.close()
            b = Jobs(root)
            try:
                self.assertEqual(b.get(jid)["status"], "awaiting-approval")
                self.assertIs(b.approve(jid, digest), True)
                wait(lambda: b.get(jid)["status"] == "succeeded")
            finally:
                b.close()


class Events(unittest.TestCase):
    def test_validation(self):
        self.assertIsNone(validate_event({"event_version": 1, "type": "warning", "message": "x"}))
        self.assertIsNotNone(validate_event({"event_version": 2, "type": "warning", "message": "x"}))
        self.assertIsNotNone(validate_event({"event_version": 1, "type": "progress", "message": "x", "step": "s", "current": True}))
        self.assertIsNone(validate_event({"event_version": 1, "type": "progress", "message": "x", "step": "s", "current": 1, "total": None}))
        self.assertIsNotNone(validate_event({"event_version": 1, "type": "result", "message": "x", "outcome": "done"}))

    def test_stat_parses_odd_command_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "a) b (c"
            exe.symlink_to("/bin/sleep")
            p = subprocess.Popen([str(exe), "5"])
            try:
                time.sleep(0.2)
                self.assertEqual(proc_stat(p.pid)[1], os.getsid(p.pid))
            finally:
                p.kill()
                p.wait()


if __name__ == "__main__":
    unittest.main()
