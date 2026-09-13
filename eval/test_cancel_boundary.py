#!/usr/bin/env python3
"""Deterministic checks for the cancel boundary in app/main.py. No server, no real check, no model, no sleeps as timing.

1. cancel requested before the step spawns      -> Cancelled raised, no process created.
2. cancel requested while the step registers    -> the registered process is signalled and the step does not run to
   completion unsignalled (the fake process only finishes when it is terminated).
3. status 'cancelling'                          -> the summary never claims a completed comparison and offers no judgment.
Run: .venv-app/bin/python eval/test_cancel_boundary.py
"""
import json, os, shutil, sys, threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "slice"))
import app.main as M
from diff_summary import summarize

RID = "test-cancel-boundary"
fails = []


def make_run():
    d = M.run_dir(RID)
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    json.dump({"id": RID, "created_at": "test", "status": "running", "step": "bundle-before (hs231)",
               "conditions": {"before": "hs231", "after": "hs31", "corpus": "version-3.1", "split": "dev", "k": 5,
                              "explain": False, "retrieval": False}, "origin": "test", "error": None},
              open(os.path.join(d, "meta.json"), "w"))


class FakePopen:
    """Stands in for the step process. communicate() returns only once the process is signalled (like a real one)."""
    instances = []

    def __init__(self, *a, on_construct=None, **kw):
        self.pid = 2 ** 30  # a pid that does not exist: cancel_run must fall back to terminate(), never signal a real group
        self.returncode = None
        self.signalled = threading.Event(); self.terminate_calls = 0; self.communicate_timed_out = False
        FakePopen.instances.append(self)
        if on_construct:
            on_construct()

    def communicate(self):
        if not self.signalled.wait(timeout=5):
            self.communicate_timed_out = True
        self.returncode = -15
        return "", ""

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1; self.returncode = -15; self.signalled.set()

    def kill(self):
        self.terminate()


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (" | " + detail if detail else ""))
    if not ok:
        fails.append(name)


# --- 1. cancel before the step spawns
make_run()
M.ACTIVE[RID] = {"proc": None, "cancel": True}
FakePopen.instances.clear()
M.subprocess.Popen = lambda *a, **kw: FakePopen(*a, **kw)
try:
    M._sh(RID, ["/bin/true"]); raised = False
except M.Cancelled:
    raised = True
check("1 cancel before spawn -> Cancelled, no process", raised and not FakePopen.instances,
      f"raised={raised} processes={len(FakePopen.instances)}")

# --- 2. cancel exactly at the registration boundary (cancel_run runs in another thread, as a request would)
make_run()
M.ACTIVE[RID] = {"proc": None, "cancel": False}
FakePopen.instances.clear()
cancel_thread = {}


def on_construct():
    t = threading.Thread(target=M.cancel_run, args=(RID,)); t.start(); cancel_thread["t"] = t


M.subprocess.Popen = lambda *a, **kw: FakePopen(*a, on_construct=on_construct, **kw)
try:
    M._sh(RID, ["/bin/true"]); raised2 = False
except M.Cancelled:
    raised2 = True
cancel_thread["t"].join(timeout=10)
p = FakePopen.instances[-1] if FakePopen.instances else None
check("2 cancel at registration -> process signalled, step not left running", bool(p) and p.terminate_calls >= 1 and not p.communicate_timed_out and raised2,
      f"terminate_calls={getattr(p, 'terminate_calls', None)} communicate_timed_out={getattr(p, 'communicate_timed_out', None)} Cancelled={raised2}")

# --- 3. 'cancelling' must not look complete
diff = {"global": [], "queries": [{"id": "demo", "classes": ["ID_CHANGED_SAME_CONTENT"], "details": [], "n_details": 0,
                                   "latency_before_s": 0, "latency_after_s": 0}]}
s_cancelling = summarize(diff, {"status": "cancelling", "step": "diff"}, ["demo"])
s_done = summarize(diff, {"status": "done", "step": "done"}, ["demo"])
text, actions = M.next_actions(s_cancelling, {"id": RID, "status": "cancelling", "step": "diff"}, {"can_judge": False})
check("3 cancelling -> not a completed claim", s_cancelling["state"] != "IDONLY" and "같" not in s_cancelling["headline"] and "중단 요청" in s_cancelling["headline"],
      f"state={s_cancelling['state']}")
check("3b same input with status done still reads IDONLY (no over-correction)", s_done["state"] == "IDONLY")
check("3c cancelling guidance does not offer judging", "판정" not in text or "판정하지 않는다" in text, text[:60])

shutil.rmtree(M.run_dir(RID), ignore_errors=True)
M.ACTIVE.pop(RID, None)
print("failures:", len(fails))
sys.exit(1 if fails else 0)
