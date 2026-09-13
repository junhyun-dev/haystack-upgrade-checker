#!/usr/bin/env python3
"""The check list read by someone coming back: each not-finished row names its step position from the same record the
detail page uses (no list-only rule), finished rows keep their result state, and the list's rerun cannot start a second
check beside one that is still running.

No app, no server, no model: run_job is never called; the rerun guard is exercised with ACTIVE set by hand.
Run: .venv-app/bin/python eval/test_list_scene.py
"""
import json, os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "slice"))
import step_plan as SP
import app.main as M

fails, made = [], []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (" | " + detail if detail else ""))
    if not ok:
        fails.append(name)


COND = {"before": "hs231", "after": "hs31", "corpus": "version-3.1", "split": "all", "k": 5, "explain": True, "retrieval": False}
def rec(*states):
    keys = ["bundle-before", "bundle-after", "diff", "explain"]
    return [{"key": k, "label": SP.LABEL[k], "state": st, "note": ""} for k, st in zip(keys, states)]

r = SP.row_summary({"status": "done", "conditions": COND, "steps": rec("done", "done", "done", "done")})
check("1 finished check: no step line (its result state is the summary)", r is None)
r = SP.row_summary({"status": "running", "conditions": COND, "steps": rec("done", "done", "running", "pending")})
check("2 running: count and the step in progress", r["kind"] == "running" and r["text"] == "진행 중 · 2/4 · 비교", r["text"])
r = SP.row_summary({"status": "cancelled", "conditions": COND, "steps": rec("done", "done", "done", "stopped")})
check("3 stopped at explain: '3/4에서 중단됨 · 설명 생성'", r["kind"] == "stopped" and r["text"].startswith("3/4에서 중단됨 · 설명 생성") and "추정" not in r["text"], r["text"])
r = SP.row_summary({"status": "failed", "conditions": COND, "steps": rec("done", "done", "failed", "pending")})
check("4 failed at diff", r["text"].startswith("2/4에서 실패 · 비교"), r["text"])
r = SP.row_summary({"status": "interrupted", "conditions": COND, "steps": rec("done", "running", "pending", "pending")})
check("5 interrupted while a bundle ran: says it is unknown whether it finished", "1/4에서 끊김" in r["text"] and "알 수 없음" in r["text"], r["text"])
r = SP.row_summary({"status": "cancelled", "step": "diff", "conditions": dict(COND, explain=False)})
check("6 old check without a step record: derived and marked '추정', denominator from its own conditions", r["text"] == "2/3에서 중단됨 · 비교 · 추정", r["text"])
r = SP.row_summary({"status": "cancelling", "conditions": COND, "steps": rec("done", "done", "running", "pending")})
check("7 cancelling reads as cleanup, not as progress", r["text"].startswith("중단 정리 중 · 2/4"), r["text"])
r = SP.row_summary({"status": "queued", "conditions": COND})
check("8 queued: 0/total", r["text"] == "대기 중 · 0/4", r["text"])

# finished rows promise only what the detail can do: #judgments exists only for judgeable states (same rule as the detail)
for st, label, anchor in [("IDONLY", "판정하러", "#judgments"), ("CHANGED", "판정하러", "#judgments"), ("PARTIAL", "판정하러", "#judgments"),
                          ("EMPTY", "0행 · 이유와 다음 행동", "#guide"), ("GLOBAL_ERROR", "실행 수준 문제 · 이유와 다음 행동", "#guide"),
                          ("NO_RESULT", "결과 없음 · 이유와 다음 행동", "#guide")]:
    a = M.list_action({"id": "x", "status": "done", "state": st})
    check(f"10 done+{st}: '{label}' -> {anchor}", a["label"] == label and a["href"] == "/runs/x" + anchor, f"{a['label']} -> {a['href']}")
check("10b the list uses the detail's own judgeable rule", set(M.JUDGEABLE_STATES) == {"ALL_SAME", "IDONLY", "CHANGED", "PARTIAL"})

# the list's rerun on a check that is itself still running: no second check, redirect to the running one
rid = "test-list-running-" + str(os.getpid()); d = M.run_dir(rid); os.makedirs(d, exist_ok=True); made.append(rid)
json.dump({"id": rid, "status": "running", "step": "diff", "conditions": dict(COND, explain=False), "origin": "test", "error": None}, open(os.path.join(d, "meta.json"), "w"))
M.ACTIVE[rid] = {"proc": None, "cancel": False}
before = set(os.listdir(M.RUNS_DIR))
resp = M.rerun(rid)
after = set(os.listdir(M.RUNS_DIR))
check("9 rerun on a running check: redirected to it, no new check created", resp.headers["location"] == f"/runs/{rid}" and before == after, f"new={sorted(after - before)}")
M.ACTIVE.pop(rid, None)
for r_ in made:
    shutil.rmtree(M.run_dir(r_), ignore_errors=True)
print("failures:", len(fails))
sys.exit(1 if fails else 0)
