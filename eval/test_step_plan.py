#!/usr/bin/env python3
"""The progress list must match the plan the worker actually follows: same steps, same denominator, carried and
recomputed steps shown as such, and the stopped/failed/interrupted boundary landing on the step that was running.

Part 1 is pure (slice/step_plan.py). Part 2 drives the real run_job with every execution boundary replaced:
_sh records instead of running, subprocess.run is intercepted (so the model server cannot be started), llm_up says down.
No app, no server, no model. Run: .venv-app/bin/python eval/test_step_plan.py
"""
import json, os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "slice"))
import step_plan as SP

fails = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (" | " + detail if detail else ""))
    if not ok:
        fails.append(name)


def keys(steps):
    return [s["key"] for s in steps]


def states(steps):
    return [s["state"] for s in steps]


BASE = {"before": "hs231", "after": "hs31", "corpus": "version-3.1", "split": "all", "k": 5}

# --- 1. the plan and its denominator follow the conditions, not a fixed five
p = SP.plan(dict(BASE, explain=False, retrieval=False))
check("1 explain/retrieval off: 3 steps", keys(p) == ["bundle-before", "bundle-after", "diff"] and SP.progress(p) == (0, 3), str(keys(p)))
p = SP.plan(dict(BASE, explain=True, retrieval=True))
check("1b both on: 5 steps", SP.progress(p) == (0, 5))
p = SP.plan(dict(BASE, explain=True, retrieval=False), reused=["bundle-before", "bundle-after"])
check("2 carried bundles count as finished from the start: 2/4", SP.progress(p) == (2, 4) and states(p)[:2] == ["carried", "carried"], str(states(p)))

# --- 2. the view for old checks (no steps record) is derived and says so
v = SP.view({"status": "cancelled", "step": "diff", "conditions": dict(BASE, explain=True, retrieval=False)})
check("3 old cancelled check at diff: bundles done, diff stopped, explain pending, marked derived",
      v["derived"] and states(v["steps"]) == ["done", "done", "stopped", "pending"] and (v["done"], v["total"]) == (2, 4), str(states(v["steps"])))
v = SP.view({"status": "done", "step": "done", "conditions": dict(BASE, explain=False, retrieval=False)})
check("3b old finished check: all done 3/3", (v["done"], v["total"]) == (3, 3))
v = SP.view({"status": "interrupted", "step": "bundle-after (hs31)", "conditions": dict(BASE, explain=False, retrieval=False)})
check("3c old interrupted check: the running step is 'interrupted', not done", states(v["steps"]) == ["done", "interrupted", "pending"])
v = SP.view({"status": "interrupted", "conditions": dict(BASE, explain=False, retrieval=False),
             "steps": [{"key": "bundle-before", "label": "", "state": "done", "note": ""}, {"key": "bundle-after", "label": "", "state": "running", "note": ""},
                       {"key": "diff", "label": "", "state": "pending", "note": ""}]})
check("3d recorded steps + interrupted status: the running step reads as interrupted", states(v["steps"]) == ["done", "interrupted", "pending"] and not v["derived"])

# --- 3. the real worker writes the same list it follows (all execution replaced)
import app.main as M
M.envs = lambda: [{"label": "hs231", "python": "python3", "version": "2.31.0"}, {"label": "hs31", "python": "python3", "version": "3.1.1"}]  # the environment list is a boundary too: no Haystack venvs needed
calls, started = [], []
real = (M._sh, M.llm_up, M.subprocess.run, M.time.sleep)


def fake_sh(rid, cmd, env=None):
    calls.append(os.path.basename(cmd[1] if len(cmd) > 1 else cmd[0]))
    out = cmd[cmd.index("--out") + 1] if "--out" in cmd else None
    if out:
        json.dump({"label": "x", "haystack": "0", "queries": []}, open(out if os.path.isabs(out) else os.path.join(ROOT, out), "w"))


M._sh, M.llm_up = fake_sh, (lambda: False)
M.subprocess.run = lambda cmd, **kw: started.append(cmd) or type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()
M.time.sleep = lambda *_a, **_k: None
made = []


def run_worker(tag, cond, reused=(), files=()):
    rid = f"test-steps-{tag}-{os.getpid()}"; d = M.run_dir(rid); os.makedirs(d, exist_ok=True); made.append(rid)
    json.dump({"id": rid, "status": "queued", "step": "queued", "conditions": cond, "origin": "app", "error": None,
               "reused": list(reused), "resumed_from": "x"}, open(os.path.join(d, "meta.json"), "w"))
    for f in files:
        json.dump({"label": "hs231", "haystack": "2.31.0", "queries": []}, open(os.path.join(d, f), "w"))
    M.ACTIVE[rid] = {"proc": None, "cancel": False}
    calls.clear(); M.run_job(rid)
    return M.load_json(os.path.join(d, "meta.json")) or {}


m = run_worker("plain", dict(BASE, explain=False, retrieval=False))
v = SP.view(m)
check("4 plain check: worker's list == plan, 3/3 done, one _sh call per step",
      not v["derived"] and states(v["steps"]) == ["done", "done", "done"] and (v["done"], v["total"]) == (3, 3) and calls == ["run_bundle.py", "run_bundle.py", "diff_bundles.py"],
      f"{states(v['steps'])} calls={calls}")

m = run_worker("carried", dict(BASE, explain=False, retrieval=False), reused=["bundle-before", "bundle-after"], files=["bundle-before.json", "bundle-after.json"])
v = SP.view(m)
check("5 both bundles carried: shown as carried, only diff ran, 3/3",
      states(v["steps"]) == ["carried", "carried", "done"] and calls == ["diff_bundles.py"], f"{states(v['steps'])} calls={calls}")

m = run_worker("dropped", dict(BASE, explain=True, retrieval=False), reused=["bundle-before", "explain"], files=["bundle-before.json", "explain.json"])
v = SP.view(m)
ex = [s for s in v["steps"] if s["key"] == "explain"][0]
check("6 explain carried but a bundle re-ran: explain shown as failed-to-regenerate (model down), never as carried; note says why",
      m.get("status") == "failed" and ex["state"] == "failed" and "다시 만든다" in ex["note"] and states(v["steps"])[:3] == ["carried", "done", "done"],
      f"{states(v['steps'])} note={ex['note'][:30]}")
check("6b the model-server start on that path was intercepted, not executed", any("llm_server.sh" in c[0] for c in started) and not real[1]())

m = run_worker("ghost", dict(BASE, explain=False, retrieval=False), reused=["bundle-after"])  # recorded as carried, file absent
v = SP.view(m)
check("7 'carried' without the file: plan shows it as done by execution, not carried", states(v["steps"]) == ["done", "done", "done"] and calls.count("run_bundle.py") == 2)

# the verification mode: the explain step fails before any start command is issued (full coverage: eval/test_verify_boundary.py)
started.clear(); M.VERIFY_MODE = True
m = run_worker("guard", dict(BASE, explain=True, retrieval=False))
v = SP.view(m)
check("7b VERIFY_MODE: explain step fails with the mode message and no start command is even attempted",
      m.get("status") == "failed" and "검수 모드" in (m.get("error") or "") and not [c for c in started if "llm_server.sh" in str(c[0])]
      and states(v["steps"]) == ["done", "done", "done", "failed"],
      f"started={len(started)} err={(m.get('error') or '')[:40]}")
M.VERIFY_MODE = False

# stop boundary: cancel flag set before the diff step -> diff is the stopped step
def cancelling_sh(rid, cmd, env=None):
    fake_sh(rid, cmd, env)
    if "diff_bundles.py" in cmd[1]:
        raise M.Cancelled()
M._sh = cancelling_sh
rid = f"test-steps-stop-{os.getpid()}"; d = M.run_dir(rid); os.makedirs(d, exist_ok=True); made.append(rid)
json.dump({"id": rid, "status": "queued", "step": "queued", "conditions": dict(BASE, explain=True, retrieval=False), "origin": "app", "error": None},
          open(os.path.join(d, "meta.json"), "w"))
M.ACTIVE[rid] = {"proc": None, "cancel": False, "stop_scope": "empty"}
M.run_job(rid)
v = SP.view(M.load_json(os.path.join(d, "meta.json")) or {})
check("8 stopped during diff: bundles done, diff 'stopped', explain pending, 2/4",
      states(v["steps"]) == ["done", "done", "stopped", "pending"] and (v["done"], v["total"]) == (2, 4), str(states(v["steps"])))

M._sh, M.llm_up, M.subprocess.run, M.time.sleep = real
for rid in made:
    shutil.rmtree(M.run_dir(rid), ignore_errors=True); M.ACTIVE.pop(rid, None)
print("failures:", len(fails))
sys.exit(1 if fails else 0)
