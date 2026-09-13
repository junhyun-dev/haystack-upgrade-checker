#!/usr/bin/env python3
"""Verify mode (VERIFY_MODE=1) must refuse every model/search-service call at the real entry points the screen-check app
uses — worker path, submission, manual start, preview — regardless of whether a model server is alive.

Nothing real runs: llm_up is a substitute that says "alive", subprocess.run and _sh only record, the Open WebUI client
only records. Run: .venv-app/bin/python eval/test_verify_boundary.py
"""
import json, os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "slice"))
import app.main as M
M.envs = lambda: [{"label": "hs231", "python": "python3", "version": "2.31.0"}, {"label": "hs31", "python": "python3", "version": "3.1.1"}]  # the environment list is a boundary too: no Haystack venvs needed
import step_plan as SP

fails, made = [], []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (" | " + detail if detail else ""))
    if not ok:
        fails.append(name)


BASE = {"before": "hs231", "after": "hs31", "corpus": "version-3.1", "split": "all", "k": 5}
sh_calls, starts, webui_calls, ctl_calls = [], [], [], []
EVER = {"starts": [], "webui": [], "ctl": [], "explain_sh": []}  # never cleared: the cumulative record across the whole run
real = (M._sh, M.llm_up, M.subprocess.run, M.time.sleep, M.openwebui_api, M.llm_ctl, M.VERIFY_MODE, M.threading.Thread)


def fake_sh(rid, cmd, env=None):
    name = os.path.basename(cmd[1] if len(cmd) > 1 else cmd[0])
    sh_calls.append(name)
    if name in ("explain.py", "retrieval_eval.py") and M.VERIFY_MODE:
        EVER["explain_sh"].append(name)
    out = cmd[cmd.index("--out") + 1] if "--out" in cmd else None
    if out:
        json.dump({"label": "x", "haystack": "0", "queries": []}, open(out if os.path.isabs(out) else os.path.join(ROOT, out), "w"))


M._sh = fake_sh
M.llm_up = lambda: True                      # "a model server is already alive" — the case the old guard let through
M.subprocess.run = lambda cmd, **kw: (starts.append(cmd), EVER["starts"].append(cmd)) and type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()
M.time.sleep = lambda *_a, **_k: None
M.openwebui_api = lambda *a, **k: (webui_calls.append(a), EVER["webui"].append(a)) and {}
M.llm_ctl = lambda action: (ctl_calls.append(action), EVER["ctl"].append(action)) and ""


def worker(tag, cond):
    rid = f"test-verify-{tag}-{os.getpid()}"; d = M.run_dir(rid); os.makedirs(d, exist_ok=True); made.append(rid)
    json.dump({"id": rid, "status": "queued", "step": "queued", "conditions": cond, "origin": "app", "error": None}, open(os.path.join(d, "meta.json"), "w"))
    M.ACTIVE[rid] = {"proc": None, "cancel": False}
    sh_calls.clear(); starts.clear(); M.run_job(rid)
    return M.load_json(os.path.join(d, "meta.json")) or {}


def llm_starts():
    """Only the model-server start command counts; run_job also calls subprocess.run for `git rev-parse` at the end."""
    return [c for c in starts if "llm_server.sh" in str(c[0])]


def reset():
    sh_calls.clear(); starts.clear(); webui_calls.clear(); ctl_calls.clear()


# --- verify mode ON
M.VERIFY_MODE = True
m = worker("explain", dict(BASE, explain=True, retrieval=False))
v = SP.view(m)
check("1 worker, explain on, server 'alive': refused before explain.py; no start; bundles/diff still ran and are recorded",
      m["status"] == "failed" and "검수 모드" in m["error"] and "explain.py" not in sh_calls and not llm_starts() and
      sh_calls == ["run_bundle.py", "run_bundle.py", "diff_bundles.py"] and [s["state"] for s in v["steps"]] == ["done", "done", "done", "failed"],
      f"sh={sh_calls} starts={len(llm_starts())} err={m['error'][:30]}")
m = worker("retrieval", dict(BASE, explain=False, retrieval=True))
check("2 worker, retrieval on: refused before retrieval_eval.py (Open WebUI)", m["status"] == "failed" and "검색 기준선" in m["error"] and "retrieval_eval.py" not in sh_calls, str(sh_calls))
m = worker("plain", dict(BASE, explain=False, retrieval=False))
v = SP.view(m)
check("3 worker, bundle/diff only: completes 3/3 with the progress record", m["status"] == "done" and (v["done"], v["total"]) == (3, 3) and not llm_starts())

class NoThread:
    def __init__(self, target=None, args=(), daemon=None): NoThread.started = True
    def start(self): pass
NoThread.started = False
M.threading.Thread = NoThread
rid, err = M.start_run(dict(BASE, explain=True, retrieval=False)); made.append(rid)
check("4 submission with explain on: recorded as failed with the reason, no worker started", err and "검수 모드" in err and not NoThread.started)
rid, err = M.start_run(dict(BASE, explain=False, retrieval=False)); made.append(rid)
check("4b submission bundle/diff only: accepted", err is None and NoThread.started)
M.threading.Thread = real[7]

reset(); r = M.llm_action("start")
check("5 manual /llm/start: redirected with the verify message, llm_server.sh not called", r.status_code == 303 and "verify" in r.headers["location"] and not ctl_calls)
reset(); r = M.preview("What changed in Document.id?", "3.1", 3)
check("6 /preview: refused, Open WebUI not called", "검수 모드" in json.loads(r.body)["error"] and not webui_calls)
check("7 cumulative over checks 1-6 (records never cleared): model-server starts 0, explain/retrieval scripts in verify mode 0, Open WebUI calls 0, llm_ctl 0",
      not [c for c in EVER["starts"] if "llm_server.sh" in str(c[0])] and not EVER["explain_sh"] and not EVER["webui"] and not EVER["ctl"],
      f"starts={len(EVER['starts'])} (git rev-parse only) explain_sh={EVER['explain_sh']}")

# --- verify mode OFF (product default): the same alive substitute lets the explain step reach explain.py (recorded, not run)
M.VERIFY_MODE = False
m = worker("product", dict(BASE, explain=True, retrieval=False))
check("8 product default with server 'alive': explain.py is reached, no start needed (only the mode differs)", "explain.py" in sh_calls and not llm_starts(), str(sh_calls))

M._sh, M.llm_up, M.subprocess.run, M.time.sleep, M.openwebui_api, M.llm_ctl, M.VERIFY_MODE = real[:7]
for rid in made:
    shutil.rmtree(M.run_dir(rid), ignore_errors=True); M.ACTIVE.pop(rid, None)
print("failures:", len(fails))
sys.exit(1 if fails else 0)
