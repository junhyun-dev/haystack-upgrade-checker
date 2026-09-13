#!/usr/bin/env python3
"""The start boundary of a carried-over check: nothing runs before the carried files are in place and read back,
a preparation failure never leaves a finished-looking check, and one click starts one check.

No server, no real check, no model: the worker thread is replaced by a recorder, so no step is ever executed.
Run: .venv-app/bin/python eval/test_resume_start.py
"""
import json, os, shutil, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import app.main as M
M.envs = lambda: [{"label": "hs231", "python": "python3", "version": "2.31.0"}, {"label": "hs31", "python": "python3", "version": "3.1.1"}]  # the environment list is a boundary too: no Haystack venvs needed

fails = []
created = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (" | " + detail if detail else ""))
    if not ok:
        fails.append(name)


class RecordingThread:
    """Stands in for the worker: records what the check folder looked like the moment the worker was created."""
    seen = []

    def __init__(self, target=None, args=(), daemon=None):
        self.args = args

    def start(self):
        rid = self.args[0]
        RecordingThread.seen.append({"rid": rid, "files": sorted(os.listdir(M.run_dir(rid))),
                                     "status": (M.load_json(os.path.join(M.run_dir(rid), "meta.json")) or {}).get("status")})


real_thread = M.threading.Thread
M.threading.Thread = RecordingThread
COND = {"before": "hs231", "after": "hs31", "corpus": "version-3.1", "split": "all", "k": 5, "explain": True, "retrieval": False}

# 1. the worker must not be created until the carried files are there
RecordingThread.seen.clear()
def prepare_ok(new):
    created.append(new)
    with open(os.path.join(M.run_dir(new), "diff.json"), "w") as f:
        json.dump({"carried": True}, f)
rid, err = M.start_run(dict(COND), parent="x", reused=["diff"], resumed_from="x", prepare=prepare_ok)
created.append(rid)
seen = RecordingThread.seen[-1] if RecordingThread.seen else {}
check("1 worker starts only after the carried file is in place",
      err is None and "diff.json" in seen.get("files", []) and seen.get("rid") == rid, str(seen.get("files")))

# 2. a preparation failure must not leave a check that looks finished, and must not start a worker
RecordingThread.seen.clear()
def prepare_fail(new):
    created.append(new)
    raise RuntimeError("복사본이 원본과 다르다")
rid2, err2 = M.start_run(dict(COND), parent="x", reused=["diff"], resumed_from="x", prepare=prepare_fail)
created.append(rid2)
meta2 = M.load_json(os.path.join(M.run_dir(rid2), "meta.json")) or {}
check("2 preparation failure -> failed check, no worker, reason kept",
      err2 and meta2.get("status") == "failed" and "복사본" in (meta2.get("error") or "") and not RecordingThread.seen,
      f"status={meta2.get('status')} workers={len(RecordingThread.seen)}")
sys.path.insert(0, os.path.join(ROOT, "slice"))
from diff_summary import summarize
s2 = summarize(None, meta2, ["q01"])
check("2b that check never reads as a result", s2["state"] == "NO_RESULT" and "failed" in s2["headline"], s2["headline"][:60])

# 3. two clicks at the same moment start one check (the second finds the first in flight)
RecordingThread.seen.clear()
M.threading.Thread = real_thread  # the guard looks at ACTIVE, which start_run fills; no job may run, so stub run_job
real_run_job = M.run_job
M.run_job = lambda rid: time.sleep(0.6)
parent = "test-parent-" + str(os.getpid())
os.makedirs(M.run_dir(parent), exist_ok=True)
json.dump({"id": parent, "status": "cancelled", "stop_scope": "empty", "step": "diff", "conditions": dict(COND),
           "origin": "test", "error": None}, open(os.path.join(M.run_dir(parent), "meta.json"), "w"))
results = []
def click():
    results.append(M.rerun(parent).headers["location"])
t1 = threading.Thread(target=click); t2 = threading.Thread(target=click)
t1.start(); t2.start(); t1.join(); t2.join()
children = [os.path.basename(d) for d in os.listdir(M.RUNS_DIR)
            if (M.load_json(os.path.join(M.RUNS_DIR, d, "meta.json")) or {}).get("parent") == parent]
created.extend(children)
check("3 two clicks at once -> one check", len(children) == 1 and results[0] == results[1], f"children={children} redirects={results}")
M.run_job = real_run_job
time.sleep(0.8)

# 4. the corpus fingerprint must reflect the corpus at the moment of the question, not a cached timestamp:
#    deleting an older file leaves the newest timestamp untouched
import tempfile
tmp = tempfile.mkdtemp()
vdir = os.path.join(tmp, "version-test"); os.makedirs(vdir)
open(os.path.join(vdir, "older.md"), "w").write("old content")
open(os.path.join(vdir, "newer.md"), "w").write("new content")
os.utime(os.path.join(vdir, "older.md"), (100, 100)); os.utime(os.path.join(vdir, "newer.md"), (200, 200))
real_corpus_dir = M.CORPUS_DIR
M.CORPUS_DIR = tmp
first = M.corpus_fingerprint_now("version-test")
os.remove(os.path.join(vdir, "older.md"))
second = M.corpus_fingerprint_now("version-test")
M.CORPUS_DIR = real_corpus_dir
shutil.rmtree(tmp, ignore_errors=True)
check("4 deleting an older file changes the fingerprint (no timestamp-keyed cache)",
      first and second and first != second, f"{(first or '')[:8]} -> {(second or '')[:8]}")

# 5. if a bundle had to be re-run, a carried explanation is no longer its explanation: it must be regenerated,
#    never silently kept. Steps and the model are blocked here: _sh only records, llm_up says the server is down.
calls = []
real_sh, real_llm_up, real_run, real_sleep = M._sh, M.llm_up, M.subprocess.run, M.time.sleep
def fake_sh(rid, cmd, env=None):
    calls.append(os.path.basename(cmd[1] if len(cmd) > 1 else cmd[0]))
    out = cmd[cmd.index("--out") + 1] if "--out" in cmd else None
    if out:
        json.dump({"label": "hs31", "haystack": "3.1.1", "queries": []}, open(out, "w"))
# execution boundary: no step subprocess, no server start (run_job calls subprocess.run for that), no waiting
started = []
M._sh, M.llm_up = fake_sh, (lambda: False)
M.subprocess.run = lambda cmd, **kw: started.append(cmd) or type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()
M.time.sleep = lambda *_a, **_k: None
rid5 = "test-dependency-" + str(os.getpid())
os.makedirs(M.run_dir(rid5), exist_ok=True)
created.append(rid5)
json.dump({"id": rid5, "status": "queued", "step": "queued", "conditions": dict(COND, explain=True, retrieval=False),
           "origin": "app", "error": None, "reused": ["bundle-before", "bundle-after", "explain"], "resumed_from": "x"},
          open(os.path.join(M.run_dir(rid5), "meta.json"), "w"))
json.dump({"label": "hs231"}, open(os.path.join(M.run_dir(rid5), "bundle-before.json"), "w"))   # carried
json.dump({"diff_identity": "stale"}, open(os.path.join(M.run_dir(rid5), "explain.json"), "w"))  # carried
M.ACTIVE[rid5] = {"proc": None, "cancel": False}
M.run_job(rid5)
meta5 = M.load_json(os.path.join(M.run_dir(rid5), "meta.json")) or {}
log5 = open(os.path.join(M.run_dir(rid5), "log.txt")).read()
M._sh, M.llm_up, M.subprocess.run, M.time.sleep = real_sh, real_llm_up, real_run, real_sleep
check("5 a re-run bundle drops the carried explanation (it is regenerated, not kept)",
      "run_bundle.py" in calls and "가져온 설명은 쓰지 않고" in log5 and "explain.py" not in " ".join(calls),
      f"steps={calls} status={meta5.get('status')}")
check("5b and with the model unreachable that check fails instead of claiming a carried explanation",
      meta5.get("status") == "failed" and "not reachable" in (meta5.get("error") or ""), str(meta5.get("error"))[:60])
check("5c the server start run_job attempts is intercepted, not executed",
      any("llm_server.sh" in c[0] for c in started) and not real_llm_up(),
      f"intercepted={len(started)} server_up={real_llm_up()}")

for rid in set(created) | {parent}:
    shutil.rmtree(M.run_dir(rid), ignore_errors=True)
    M.ACTIVE.pop(rid, None)
print("failures:", len(fails))
sys.exit(1 if fails else 0)
