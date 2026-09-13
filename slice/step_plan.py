"""The steps one check will go through, and where it is now.

Pure Python. The plan is derived from the check's conditions (which optional steps are on) and from what the check
carried over from a stopped check (those steps need no execution). The worker (app/main.py run_job) writes the state of
each step into meta["steps"] as it goes, so the screen reads what actually happened rather than guessing.

States:  pending   not reached yet
         running   in progress now
         done      finished in this check
         carried   copied from an earlier check after the carry-over rules; nothing executed
         stopped   this is the step that was running when the user stopped the check
         failed    this step raised the error the check ended with
         interrupted  the app lost the worker while this step was running; whether it finished is unknown

The count shown is "steps finished or carried / steps in this plan". Carried steps count as finished because nothing
remains to do for them; steps switched off by the conditions are not in the plan at all.
"""

STEPS = [("bundle-before", "이전 버전 검색 묶음"), ("bundle-after", "이후 버전 검색 묶음"), ("diff", "비교"),
         ("explain", "설명 생성 (로컬 모델)"), ("retrieval", "검색 기준선 (Open WebUI)")]
LABEL = dict(STEPS)
STATE_LABEL = {"pending": "남음", "running": "진행 중", "done": "끝남", "carried": "가져옴", "stopped": "중단됨",
               "failed": "실패", "interrupted": "끊김(끝났는지 알 수 없음)"}


def plan(conditions, reused=()):
    """Ordered steps for these conditions; carried ones are marked from the start."""
    out = []
    for key, label in STEPS:
        if key == "explain" and not conditions.get("explain"):
            continue
        if key == "retrieval" and not conditions.get("retrieval"):
            continue
        out.append({"key": key, "label": label, "state": "carried" if key in set(reused) else "pending", "note": ""})
    return out


def mark(steps, key, state, note=None):
    for s in steps:
        if s["key"] == key:
            s["state"] = state
            if note is not None:
                s["note"] = note
    return steps


def progress(steps):
    """(finished-or-carried, total). Total is the number of steps in this plan, never the fixed five."""
    return sum(1 for s in steps if s["state"] in ("done", "carried")), len(steps)


def _key_of(step_string):
    for key, _ in STEPS:
        if (step_string or "").startswith(key):
            return key
    return None


def view(meta):
    """What to show for a check. Uses meta["steps"] when the worker wrote it; for checks recorded before that existed,
    derives a best effort from the step string and the status, and says so."""
    steps = meta.get("steps")
    derived = False
    if not steps:
        derived = True
        c = meta.get("conditions") or {}
        steps = plan(c, meta.get("reused") or [])
        cur = _key_of(meta.get("step"))
        status = meta.get("status")
        seen_cur = False
        for s in steps:
            if s["state"] == "carried":
                continue
            if status == "done":
                s["state"] = "done"
            elif cur is None or seen_cur:
                s["state"] = "pending"
            elif s["key"] == cur:
                seen_cur = True
                s["state"] = {"running": "running", "cancelling": "running", "cancelled": "stopped", "failed": "failed",
                              "interrupted": "interrupted", "queued": "pending"}.get(status, "pending")
            else:
                s["state"] = "done"
    else:
        steps = [dict(s) for s in steps]
        if meta.get("status") == "interrupted":
            for s in steps:
                if s["state"] == "running":
                    s["state"] = "interrupted"
    done, total = progress(steps)
    for s in steps:
        s["state_label"] = STATE_LABEL.get(s["state"], s["state"])
    return {"steps": steps, "done": done, "total": total, "derived": derived}


def row_summary(meta):
    """One line for the check list, from the same step record the detail page shows. Finished checks get nothing here
    (their result state is the summary); every other status names the step it is at, with the count."""
    status = meta.get("status")
    if status == "done":
        return None
    v = view(meta)
    est = " · 추정" if v["derived"] else ""
    cur = next((s for s in v["steps"] if s["state"] in ("running", "stopped", "failed", "interrupted")), None)
    n = f"{v['done']}/{v['total']}"
    if status == "queued":
        return {"kind": "running", "text": f"대기 중 · 0/{v['total']}"}
    if status in ("running", "cancelling"):
        head = "중단 정리 중" if status == "cancelling" else "진행 중"
        return {"kind": "running", "text": f"{head} · {n} · {cur['label'] if cur else ''}".rstrip(" · ")}
    if status == "cancelled":
        return {"kind": "stopped", "text": f"{n}에서 중단됨 · {cur['label'] if cur else '단계 불명'}{est}"}
    if status == "failed":
        return {"kind": "stopped", "text": f"{n}에서 실패 · {cur['label'] if cur else '단계 불명'}{est}"}
    if status == "interrupted":
        return {"kind": "stopped", "text": f"{n}에서 끊김 · {cur['label'] if cur else '단계 불명'} (끝났는지 알 수 없음){est}"}
    return {"kind": "other", "text": status or ""}
