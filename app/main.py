"""업그레이드 점검 도우미 — one browser flow over this project's regression slice.

Own implementation (this file + templates): run history, start a check, progress/failure, before/after diff table,
explanation with citations, evidence viewer, evidence-level reports, re-run under the same conditions, comparison.
Reused as-is: slice/regression/*.py and eval/*.py (the actual work), Open WebUI's retrieval API and knowledge bases
(search preview, "open in Open WebUI"), the local llama.cpp server (explanations). Branding of Open WebUI is untouched.
Runs on 127.0.0.1:8090 only (scripts/app_server.sh).
"""
import glob, json, os, re, shutil, signal, subprocess, sys, threading, time, uuid, urllib.request, urllib.parse
from datetime import datetime

import markdown, yaml
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_DIR = os.path.join(ROOT, "runtime", "eval", "runs")
CORPUS_DIR = os.path.join(ROOT, "corpus", "haystack-docs-src", "docs-website", "versioned_docs")
MIGRATION = os.path.join(ROOT, "corpus", "MIGRATION.md")
FEEDBACK = os.environ.get("FEEDBACK_FILE", os.path.join(ROOT, "eval", "feedback.yaml"))
OPENWEBUI = os.environ.get("OPENWEBUI_URL", "http://127.0.0.1:8080")
OPENWEBUI_PUBLIC = os.environ.get("OPENWEBUI_PUBLIC_URL", "http://localhost:8080")
LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:8081")
# VERIFY_MODE=1 (scripts/app_server.sh start-verify): this app instance does not start the model server, does not run
# inference (even if a server is already up) and does not call Open WebUI retrieval; it says so where it refuses.
# Read-only health probes (llm_up() on the index page) are not blocked. The normal product start leaves the mode off;
# nothing about the shared server or other projects changes.
VERIFY_MODE = os.environ.get("VERIFY_MODE", "0") == "1"
VERIFY_MSG = "검수 모드(VERIFY_MODE=1): 이 앱은 모델 서버 시작·추론·검색 서비스 호출을 하지 않는다"

app = FastAPI(title="업그레이드 점검 도우미")
app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "app", "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(ROOT, "app", "templates"))
_lock = threading.Lock()


# ---------- environments, corpora, runs ----------
def envs():
    out = []
    for d in sorted(glob.glob(os.path.join(ROOT, ".venv-hs*"))):
        label = os.path.basename(d).replace(".venv-", "")
        vfile = os.path.join(d, ".haystack_version")
        if not os.path.exists(vfile):
            try:
                v = subprocess.run([os.path.join(d, "bin", "python"), "-c", "import haystack;print(haystack.__version__)"],
                                   capture_output=True, text=True, timeout=60).stdout.strip()
            except Exception:
                v = "?"
            open(vfile, "w").write(v)
        out.append({"label": label, "python": os.path.join(d, "bin", "python"), "version": open(vfile).read().strip()})
    return out


def corpora():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(CORPUS_DIR, "version-*")))


def questions():
    return yaml.safe_load(open(os.path.join(ROOT, "eval", "questions.yaml")))


def load_json(path):
    return json.load(open(path)) if os.path.exists(path) else None


def run_dir(run_id):
    return os.path.join(RUNS_DIR, run_id)


def read_meta(run_id):
    m = load_json(os.path.join(run_dir(run_id), "meta.json"))
    if m and m.get("status") in ("queued", "running", "cancelling") and run_id not in ACTIVE:
        # the worker thread is gone (the app restarted): record it instead of showing a run that is not running
        m["status"] = "interrupted"; m["interrupted_at"] = datetime.now().isoformat(timespec="seconds")
        try:
            _write_meta(run_id, m)
            _log(run_id, f"INTERRUPTED: the app restarted while the step '{m.get('step')}' was running")
        except Exception:
            pass
    if m is None:  # runs made from the shell before the app existed
        b = load_json(os.path.join(run_dir(run_id), "bundle-hs231.json")) or {}
        a = load_json(os.path.join(run_dir(run_id), "bundle-hs31.json")) or {}
        m = {"id": run_id, "created_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(run_dir(run_id)))),
             "status": "done", "step": "shell", "conditions": {"before": "hs231", "after": "hs31", "corpus": "version-3.1", "split": "all", "k": 5, "explain": True, "retrieval": True},
             "versions": {"before": b.get("haystack"), "after": a.get("haystack")}, "parent": None, "origin": "shell", "error": None}
    return m


def list_runs():
    runs = []
    for d in sorted(glob.glob(os.path.join(RUNS_DIR, "*")), key=os.path.getmtime, reverse=True):
        if not os.path.isdir(d):
            continue
        rid = os.path.basename(d)
        m = read_meta(rid)
        diff = load_json(os.path.join(d, "diff.json")) or {}
        ex = load_json(os.path.join(d, "explain.json")) or {}
        rd = (load_json(os.path.join(d, "retrieval-dev.json")) or {}).get("summary", {})
        re_ = (load_json(os.path.join(d, "retrieval-eval.json")) or {}).get("summary", {})
        m["classes"] = (diff.get("summary") or {}).get("classes_by_query_count", {})
        try:  # closing state of the check (axis A), same rule as the run page
            import sys; sys.path.insert(0, os.path.join(ROOT, "slice"))
            from diff_summary import summarize
            split = (m.get("conditions") or {}).get("split", "all")
            exp_ids = [q["id"] for q in questions() if split == "all" or q["split"] == split]
            sm = summarize(load_json(os.path.join(d, "diff.json")), m, exp_ids)
            m["state"] = sm["state"]; m["counts"] = sm["counts"]
        except Exception:
            m["state"] = None; m["counts"] = {}
        m["n_explanations"] = len(ex.get("explanations", []))
        m["row"] = step_plan.row_summary(m)  # where a not-finished check is, from the same record the detail page uses
        m["action"] = list_action(m) if m.get("status") == "done" else None
        m["recall_dev"] = rd.get("mean_recall"); m["recall_eval"] = re_.get("mean_recall")
        m["n_feedback"] = sum(1 for f in feedback_all() if f.get("run") == rid)
        runs.append(m)
    return runs


def feedback_all():
    try:
        return yaml.safe_load(open(FEEDBACK)) or []
    except Exception:
        return []


def feedback_add(entry):
    with _lock:
        items = feedback_all()
        items.append(entry)
        with open(FEEDBACK, "w") as f:
            f.write(HEADER)
            yaml.safe_dump(items, f, allow_unicode=True, sort_keys=False)


HEADER = """# Evidence-level reports ("이 근거/설명이 틀렸다·놓쳤다"). Written by a person (or via app/main.py on their behalf), read by
# slice/compare_runs.py and the app. Each entry points at one concrete thing from a run: a diff class explanation,
# a retrieval result, a chat citation, or one diff row. Fields: target (explain:<CLASS> | retrieval:<qid> | chat:<qid> | diff:<qid>),
# verdict (correct | wrong | missed | unclear; diff rows: expected | problem | unclear), evidence, note, by (main | user), run (run id), created_at.
# diff:<qid> entries made through the app since 2026-09-13 also carry classes (the row's diff classes) and diff_identity
# (diff_bundles.diff_identity of the comparison judged); older entries lack them and are shown as not pinned to a comparison.
# Entries are never generated by a model.
"""


# ---------- job runner (reuses the existing scripts) ----------
sys.path.insert(0, os.path.join(ROOT, "slice"))
sys.path.insert(0, os.path.join(ROOT, "slice", "regression"))
import step_plan  # the step list the worker writes and the screen reads

ACTIVE = {}  # rid -> {"proc": Popen|None, "cancel": bool} for checks running in THIS app process
ACTIVE_LOCK = threading.Lock()  # closes the window between "cancel requested" and "process registered"
START_LOCK = threading.Lock()   # one check per click: the in-flight check, preparation and launch happen together


class Cancelled(Exception):
    pass
def _write_meta(rid, m):
    json.dump(m, open(os.path.join(run_dir(rid), "meta.json"), "w"), indent=2, ensure_ascii=False)


def _log(rid, line):
    with open(os.path.join(run_dir(rid), "log.txt"), "a") as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {line}\n")


def _sh(rid, cmd, env=None):
    """Run one step so it can be stopped: own process group, registered for cancel, output kept in the run log."""
    with ACTIVE_LOCK:  # spawn and register under the same lock cancel_run takes, so a cancel can never miss the process
        slot = ACTIVE.get(rid)
        if slot and slot["cancel"]:
            raise Cancelled()
        _log(rid, "$ " + " ".join(os.path.relpath(c, ROOT) if c.startswith(ROOT) else c for c in cmd))
        p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        if slot is not None:
            slot["proc"] = p
    out, err = p.communicate()
    with ACTIVE_LOCK:
        if slot is not None:
            slot["proc"] = None
        cancelled = bool(slot and slot["cancel"])
    for stream in (out, err):
        for line in (stream or "").strip().splitlines()[-30:]:
            _log(rid, line)
    if cancelled:
        raise Cancelled()
    if p.returncode != 0:
        raise RuntimeError(f"step failed (exit {p.returncode}): {os.path.basename(cmd[1]) if len(cmd) > 1 else cmd[0]}")


def run_job(rid):
    m = read_meta(rid); c = m["conditions"]; d = run_dir(rid)
    env_by_label = {e["label"]: e for e in envs()}
    try:
        m["status"] = "running"; m["started_at"] = datetime.now().isoformat(timespec="seconds"); _write_meta(rid, m)
        corpus = os.path.join(CORPUS_DIR, c["corpus"])
        reused = set(m.get("reused") or [])
        ran_a_bundle = False
        for name in sorted(reused):  # a record without the file is not a carried result
            if not os.path.exists(os.path.join(d, f"{name}.json")):
                _log(rid, f"{name}: 가져왔다고 기록됐지만 파일이 없어 이 단계를 다시 실행한다")
                reused.discard(name)
        m["steps"] = step_plan.plan(c, reused); _write_meta(rid, m)
        for side in ("before", "after"):
            m["step"] = f"bundle-{side} ({c[side]})"
            if f"bundle-{side}" in reused:
                _write_meta(rid, m)
                _log(rid, f"bundle-{side}: 이전 점검 {m.get('resumed_from')}에서 가져옴 (다시 실행하지 않음)")
            else:
                ran_a_bundle = True
                step_plan.mark(m["steps"], f"bundle-{side}", "running"); _write_meta(rid, m)
                e = env_by_label[c[side]]
                _sh(rid, [e["python"], os.path.join(ROOT, "slice", "regression", "run_bundle.py"), "--label", c[side], "--corpus", corpus,
                          "--top-k", str(c["k"]), "--split", c["split"], "--out", os.path.join(d, f"bundle-{side}.json")])
                step_plan.mark(m["steps"], f"bundle-{side}", "done")
            m.setdefault("versions", {})[side] = (load_json(os.path.join(d, f"bundle-{side}.json")) or {}).get("haystack")
        if ran_a_bundle and "explain" in reused:
            reused.discard("explain")
            step_plan.mark(m["steps"], "explain", "pending", "bundle을 다시 실행해서 가져온 설명은 쓰지 않고 다시 만든다")
            _log(rid, "bundle을 다시 실행했으므로 가져온 설명은 쓰지 않고 다시 만든다 (설명은 비교 내용에 딸린 결과다)")
        m["step"] = "diff"
        if "diff" in reused:
            _write_meta(rid, m)
            _log(rid, f"diff: 이전 점검 {m.get('resumed_from')}에서 가져옴 (다시 실행하지 않음)")
        else:
            step_plan.mark(m["steps"], "diff", "running"); _write_meta(rid, m)
            _sh(rid, ["python3", os.path.join(ROOT, "slice", "regression", "diff_bundles.py"), os.path.join(d, "bundle-before.json"),
                      os.path.join(d, "bundle-after.json"), "--out", os.path.join(d, "diff.json")])
            step_plan.mark(m["steps"], "diff", "done")
        if c.get("explain") and "explain" in reused:
            m["step"] = "explain (local LLM)"; _write_meta(rid, m)
            _log(rid, f"explain: 이전 점검 {m.get('resumed_from')}에서 가져옴 (로컬 모델을 호출하지 않음)")
        elif c.get("explain"):
            m["step"] = "explain (local LLM)"; step_plan.mark(m["steps"], "explain", "running"); _write_meta(rid, m)
            if VERIFY_MODE:  # before any health check, start command or explain.py
                raise RuntimeError(VERIFY_MSG + " — 설명 단계를 실행하지 않았다")
            if not llm_up():
                _log(rid, "local LLM server is down; starting it on demand (scripts/llm_server.sh start)")
                subprocess.run([os.path.join(ROOT, "scripts", "llm_server.sh"), "start"], cwd=ROOT, capture_output=True, text=True)
                for _ in range(60):
                    if llm_up():
                        break
                    time.sleep(2)
            if not llm_up():
                raise RuntimeError(f"local LLM server not reachable at {LLM_URL} (scripts/llm_server.sh start; see runtime/logs/llama-server.log)")
            after_env = env_by_label[c["after"]]
            _sh(rid, [after_env["python"], os.path.join(ROOT, "slice", "regression", "explain.py"), os.path.join(d, "diff.json"), "--out", os.path.join(d, "explain.json")],
                env={**os.environ, "LLM_URL": LLM_URL + "/v1"})
            step_plan.mark(m["steps"], "explain", "done")
        if c.get("retrieval"):
            m["step"] = "retrieval baseline (Open WebUI)"; step_plan.mark(m["steps"], "retrieval", "running"); _write_meta(rid, m)
            if VERIFY_MODE:  # before retrieval_eval.py, which talks to Open WebUI
                raise RuntimeError(VERIFY_MSG + " — 검색 기준선 단계를 실행하지 않았다")
            for split in ("dev", "eval"):
                _sh(rid, [os.path.join(ROOT, ".venv", "bin", "python"), os.path.join(ROOT, "eval", "retrieval_eval.py"), "--split", split, "--k", "3",
                          "--out", os.path.relpath(os.path.join(d, f"retrieval-{split}.json"), ROOT)])
            step_plan.mark(m["steps"], "retrieval", "done")
        try:
            m["git"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        except Exception:
            pass
        m["status"] = "done"; m["step"] = "done"; m["finished_at"] = datetime.now().isoformat(timespec="seconds")
    except Cancelled:
        m["status"] = "cancelled"; m["finished_at"] = datetime.now().isoformat(timespec="seconds")
        for s_ in m.get("steps") or []:
            if s_["state"] == "running":
                s_["state"] = "stopped"
        scope = None  # the cancel handler may still be confirming the process group; wait briefly for its finding
        for _ in range(40):
            scope = (ACTIVE.get(rid) or {}).get("stop_scope")
            if scope:
                break
            time.sleep(0.1)
        m["stop_scope"] = scope or "unknown"
        _log(rid, f"CANCELLED by user at step: {m.get('step')}")
    except Exception as e:
        m["status"] = "failed"; m["error"] = str(e); _log(rid, "ERROR " + str(e))
        for s_ in m.get("steps") or []:
            if s_["state"] == "running":
                s_["state"] = "failed"
    finally:
        _write_meta(rid, m)   # write the terminal status before deregistering, so no reader sees "running with no worker"
        ACTIVE.pop(rid, None)


def start_run(conditions, parent=None, reused=None, resumed_from=None, prepare=None):
    """Create the check, let `prepare` put carried-over files in place, and only then start the worker.
    Returns (rid, error). On a preparation error the check is recorded as failed and never runs."""
    rid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    os.makedirs(run_dir(rid), exist_ok=True)
    m = {"id": rid, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "status": "queued", "step": "queued",
         "conditions": conditions, "parent": parent, "origin": "app", "error": None,
         "reused": list(reused or []), "resumed_from": resumed_from}
    _write_meta(rid, m)
    if VERIFY_MODE and (conditions.get("explain") or conditions.get("retrieval")):
        m["status"] = "failed"; m["error"] = VERIFY_MSG + " — 설명 생성·검색 기준선을 켠 점검은 검수 모드에서 시작하지 않는다"
        _write_meta(rid, m); _log(rid, "ERROR " + m["error"])
        return rid, m["error"]
    if prepare is not None:
        try:
            prepare(rid)
        except Exception as e:
            m["status"] = "failed"; m["error"] = f"이어서 진행 준비 실패: {e}"
            _write_meta(rid, m); _log(rid, "ERROR " + m["error"])
            return rid, m["error"]
    ACTIVE[rid] = {"proc": None, "cancel": False}
    threading.Thread(target=run_job, args=(rid,), daemon=True).start()
    return rid, None


def llm_up():
    try:
        return b"ok" in urllib.request.urlopen(LLM_URL + "/health", timeout=3).read()
    except Exception:
        return False


WINDOW_LOCK = os.path.join(ROOT, "runtime", "llm_window.lock")


def llm_window():
    return open(WINDOW_LOCK).read().strip() if os.path.exists(WINDOW_LOCK) else None


def llm_ctl(action):
    return subprocess.run([os.path.join(ROOT, "scripts", "llm_server.sh"), action], cwd=ROOT, capture_output=True, text=True).stdout.strip()


# ---------- evidence helpers ----------
def md_sections(text):
    import sys; sys.path.insert(0, os.path.join(ROOT, "slice", "regression"))
    from reports import split_sections
    return split_sections(text)


def render_md(text):
    return markdown.markdown(text, extensions=["fenced_code", "tables"])


def doc_path_from_name(name):  # 3.1__overview__migration.md -> corpus path (.mdx or .md)
    stem, _ = os.path.splitext(name)
    ver, _, rest = stem.partition("__")
    base = os.path.join(CORPUS_DIR, f"version-{ver}", rest.replace("__", os.sep))
    for ext in (".mdx", ".md"):
        if os.path.exists(base + ext):
            return base + ext
    return None


def openwebui_token():
    p = os.path.join(ROOT, "runtime", ".token")
    return open(p).read().strip() if os.path.exists(p) else None


def openwebui_api(path, data=None):
    tok = openwebui_token()
    if not tok:
        raise RuntimeError("no Open WebUI token (runtime/.token)")
    req = urllib.request.Request(OPENWEBUI + path, method="POST" if data is not None else "GET")
    req.add_header("Authorization", f"Bearer {tok}")
    body = None
    if data is not None:
        req.add_header("Content-Type", "application/json"); body = json.dumps(data).encode()
    with urllib.request.urlopen(req, body, timeout=120) as r:
        return json.loads(r.read().decode() or "null")


def kb_id_for(version):
    kbs = openwebui_api("/api/v1/knowledge/")
    kbs = kbs.get("items", []) if isinstance(kbs, dict) else kbs
    for kb in kbs:
        if kb["name"] == f"haystack-docs-{version}":
            return kb["id"]
    return None


# ---------- routes ----------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    prefill, prefill_from = None, request.query_params.get("from", "")
    if prefill_from and os.path.isdir(run_dir(prefill_from)):
        prefill = dict((read_meta(prefill_from).get("conditions") or {}))
    return templates.TemplateResponse(request, "index.html", {"runs": list_runs(), "envs": envs(), "corpora": corpora(), "prefill": prefill, "prefill_from": prefill_from, "state_label": STATE_LABEL,
                                                     "n_questions": len(questions()), "openwebui": OPENWEBUI_PUBLIC, "llm_up": llm_up(), "llm_window": llm_window(),
                                                     "msg": request.query_params.get("msg", "")})


@app.post("/llm/{action}")
def llm_action(action: str):
    if VERIFY_MODE and action == "start":
        return RedirectResponse("/?msg=verify", status_code=303)
    if action == "stop" and llm_window():
        return RedirectResponse("/?msg=window", status_code=303)  # an external usage window owns the server right now
    if action in ("start", "stop"):
        llm_ctl(action)
        if action == "start":
            for _ in range(60):
                if llm_up():
                    break
                time.sleep(2)
    return RedirectResponse("/", status_code=303)


@app.post("/runs")
def create_run(before: str = Form(...), after: str = Form(...), corpus: str = Form(...), split: str = Form("all"), k: int = Form(5),
               explain: str = Form(""), retrieval: str = Form(""), parent: str = Form("")):
    # an unchecked checkbox is simply not submitted, so the default must mean "off" — otherwise unchecking
    # "변경 이유 설명 생성" still ran the local model
    cond = {"before": before, "after": after, "corpus": corpus, "split": split, "k": int(k), "explain": explain == "on", "retrieval": retrieval == "on"}
    if cond["explain"] and llm_window():
        return RedirectResponse("/?msg=window", status_code=303)  # do not start an explanation run while another project holds the server
    with START_LOCK:
        rid, _ = start_run(cond, parent or None)
    return RedirectResponse(f"/runs/{rid}", status_code=303)


def _child_in_flight(rid):
    """A child of this check that is already queued/running — so a second click does not start a second check."""
    for other in sorted(glob.glob(os.path.join(RUNS_DIR, "*")), key=os.path.getmtime, reverse=True):
        oid = os.path.basename(other)
        if oid == rid or not os.path.isdir(other):
            continue
        om = load_json(os.path.join(other, "meta.json")) or {}
        if om.get("parent") == rid and oid in ACTIVE:
            return oid
    return None


def corpus_fingerprint_now(corpus_name):
    """The fingerprint of the corpus as it is right now, read fresh (about 15 ms for our corpus), using the producer's
    own functions. It is not cached: a deleted or renamed older file leaves the newest timestamp untouched, so any
    timestamp-keyed cache would report content that is no longer there."""
    d = os.path.join(CORPUS_DIR, corpus_name)
    try:
        import sys; sys.path.insert(0, os.path.join(ROOT, "slice", "regression"))
        from run_bundle import load_corpus, sha1
        return sha1("".join(p + sha1(t) for p, t in load_corpus(d, None)))
    except Exception:
        return None


def resume_context(conditions):
    """What the current system says, for judging what a stopped check left behind (see slice/resume_plan.py)."""
    import sys; sys.path.insert(0, os.path.join(ROOT, "slice", "regression"))
    from run_bundle import PIPELINE
    from diff_bundles import build_diff, diff_identity
    from reports import split_sections, pins_for_class
    import hashlib
    sections = split_sections(open(MIGRATION, encoding="utf-8").read(), min_len=41)
    section_hashes = {t: hashlib.sha1(b.encode("utf-8")).hexdigest() for t, b in sections}
    headings = [t for t, _ in sections]
    return {"corpus_fingerprint": corpus_fingerprint_now(conditions.get("corpus", "")),
            "pipeline": dict(PIPELINE),
            "diff_identity_of": lambda a, b: diff_identity(build_diff(a, b)),
            "section_hashes": section_hashes,
            "pins_now": lambda cls: [p["heading"] for p in pins_for_class(cls, headings, feedback_path=FEEDBACK)[0]]}


def resume_plan_for(rid):
    """What a new check could carry over from this one (pure reading; see slice/resume_plan.py)."""
    import sys; sys.path.insert(0, os.path.join(ROOT, "slice"))
    from resume_plan import plan
    m = read_meta(rid); c = m.get("conditions") or {}
    split = c.get("split", "all")
    expected = [(q["id"], q["question"]) for q in questions() if split == "all" or q["split"] == split]
    return plan(run_dir(rid), m, {e["label"]: e["version"] for e in envs()}, expected, lambda p: json.load(open(p)),
                resume_context(c))


@app.post("/runs/{rid}/rerun")
def rerun(rid: str):
    with START_LOCK:
        if rid in ACTIVE:  # the check itself is still going: the list must not start a second one beside it
            return RedirectResponse(f"/runs/{rid}", status_code=303)
        busy = _child_in_flight(rid)
        if busy:
            return RedirectResponse(f"/runs/{busy}", status_code=303)
        m = read_meta(rid)
        new, _ = start_run(dict(m["conditions"]), parent=rid)
    return RedirectResponse(f"/runs/{new}", status_code=303)


@app.post("/runs/{rid}/resume")
def resume(rid: str):
    """Start a NEW check with the same conditions, carrying over the artifacts that the stored files prove are still valid.
    The old check is never written to."""
    with START_LOCK:
        busy = _child_in_flight(rid)
        if busy:
            return RedirectResponse(f"/runs/{busy}", status_code=303)
        p = resume_plan_for(rid)
        if p["blocked"] or not p["reuse"]:
            return RedirectResponse(f"/runs/{rid}?resume=blocked", status_code=303)
        m = read_meta(rid)
        src = run_dir(rid)

        def prepare(new):
            """Copy every carried artifact and read it back before the check may run. Any gap stops the check."""
            dst = run_dir(new)
            for name in p["reuse"]:
                s_path = os.path.join(src, f"{name}.json")
                if name.startswith("bundle-") and not os.path.exists(s_path):
                    s_path = os.path.join(src, {"bundle-before": "bundle-hs231.json", "bundle-after": "bundle-hs31.json"}[name])
                d_path = os.path.join(dst, f"{name}.json")
                shutil.copy(s_path, d_path)
                if json.load(open(d_path)) != json.load(open(s_path)):
                    raise RuntimeError(f"{name}: 복사본이 원본과 다르다")
            _log(new, f"이전 점검 {rid}에서 가져온 결과(복사·확인 완료): {', '.join(p['reuse'])}")

        new, err = start_run(dict(m["conditions"]), parent=rid, reused=p["reuse"], resumed_from=rid, prepare=prepare)
    return RedirectResponse(f"/runs/{new}", status_code=303)


@app.post("/runs/{rid}/cancel")
def cancel_run(rid: str):
    """Stop a check that is running in this app process. Partial files are kept; the LLM server is not touched."""
    if not os.path.isdir(run_dir(rid)):
        return RedirectResponse("/", status_code=303)
    with ACTIVE_LOCK:
        slot = ACTIVE.get(rid)
        if slot is not None:
            slot["cancel"] = True
            p = slot.get("proc")
    if slot is not None:
        m = read_meta(rid)
        if m.get("status") in ("queued", "running"):
            m["status"] = "cancelling"; _write_meta(rid, m)
        _log(rid, "cancel requested by the user")
        if p and p.poll() is None:
            try:
                pgid = os.getpgid(p.pid)
            except Exception:
                pgid = None
            try:
                if pgid is None:
                    raise OSError("no pgid")
                os.killpg(pgid, signal.SIGTERM)
            except Exception:
                p.terminate()
            for _ in range(20):
                if p.poll() is not None:
                    break
                time.sleep(0.25)
            if p.poll() is None:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception:
                    p.kill()
            scope = "unknown"
            try:  # our own registered group only: never search other processes by name
                if pgid is None:
                    raise RuntimeError("no pgid")
                for _ in range(8):
                    os.killpg(pgid, 0); time.sleep(0.25)
                os.killpg(pgid, signal.SIGKILL); time.sleep(0.5)
                os.killpg(pgid, 0); scope = "remaining"
            except ProcessLookupError:
                scope = "empty"
            except Exception:
                scope = "unknown"
            slot["stop_scope"] = scope
            _log(rid, f"stop signal sent to the step's process group; parent exited: {p.poll() is not None}; group after stop: {scope}")
    else:
        read_meta(rid)  # marks a stale queued/running run as interrupted
    return RedirectResponse(f"/runs/{rid}", status_code=303)


@app.get("/runs/{rid}/status")
def status(rid: str):
    m = read_meta(rid)
    logp = os.path.join(run_dir(rid), "log.txt")
    tail = open(logp).read().splitlines()[-12:] if os.path.exists(logp) else []
    return JSONResponse({"status": m.get("status"), "step": m.get("step"), "error": m.get("error"), "log": tail,
                         "steps": step_plan.view(m)})


STATE_LABEL = {"NO_RESULT": "결과 없음", "STOPPED": "중단됨", "GLOBAL_ERROR": "실행 수준 문제", "EMPTY": "0행", "PARTIAL": "일부만 비교됨",
               "CHANGED": "변화 있음", "IDONLY": "ID만 변경", "ALL_SAME": "모두 동일"}


JUDGEABLE_STATES = ("ALL_SAME", "IDONLY", "CHANGED", "PARTIAL")  # the one rule for "rows exist to judge" (detail and list)


def list_action(m):
    """The list's action for a finished check, promising only what the detail page can do. Judgeable states go to the
    judgment line (#judgments exists only for them); the others go to the first line and its next-action guidance."""
    st = m.get("state")
    if st in JUDGEABLE_STATES:
        return {"label": "판정하러", "href": f"/runs/{m['id']}#judgments"}
    return {"label": f"{STATE_LABEL.get(st, st or '결과')} · 이유와 다음 행동", "href": f"/runs/{m['id']}#guide"}


def next_actions(summary, m, jsum):
    """Closing guidance for one check (axis A only). Content is ours (hypothesis, not a reference feature); links go to existing surfaces."""
    st = summary["state"]; status = m.get("status")
    rerun = {"label": "같은 조건 재실행", "kind": "rerun"}
    change = {"label": "조건 바꿔 점검 (이 점검의 조건으로 채워진 폼)", "href": f"/?from={m['id']}#new"}
    judge = {"label": "행마다 판정 남기기", "href": "#diff"}
    explain = {"label": "변경 이유 설명 읽기", "href": "#explanations"}
    log = {"label": "실행 로그 보기", "href": "#progress" if status in ("queued", "running") else f"/runs/{m['id']}/log"}
    if st == "NO_RESULT" and status == "cancelling":
        return ("중단을 요청했다. 실행 중이던 단계가 정리되면 상태가 '중단됨'으로 바뀐다. 그때까지는 결과를 판정하지 않는다.", [log])
    if st == "STOPPED":
        return ("중단된 점검이다. 여기까지의 파일은 부분이라 판정하지 않는다. 로그에서 어디까지 갔는지 보고, 같은 조건으로 다시 실행하거나 조건을 바꿔 점검한다.", [log, rerun, change])
    if st == "NO_RESULT":
        if status in ("queued", "running"):
            return "실행 중이다. 끝나면 첫 줄이 채워진다.", [log]
        return "결과가 없다. 실패 원인을 로그에서 확인한 뒤 같은 조건으로 다시 실행한다.", [log, rerun]
    if st == "GLOBAL_ERROR":
        return "실행 수준 문제라 행별 차이를 버전에 귀속할 수 없다. 로그·환경·corpus 조건을 확인하고 같은 조건으로 다시 실행한다.", [log, rerun, change]
    if st == "EMPTY":
        return "비교할 행이 없다. 질문 세트·분할 조건을 확인하고 조건을 바꿔 점검한다.", [change]
    if st == "PARTIAL":
        return "누락·판정 불가 행의 원인(이후 실행에서 빠진 질문, 알 수 없는 분류)을 먼저 확인한다. 보이는 범위 안에서만 판정을 남기고, 원인을 없앤 뒤 다시 실행한다.", [judge, rerun, log]
    if st == "CHANGED":
        return "변화 행부터 '나란히 보기'로 근거를 열고 판정을 남긴다. 변경 이유 설명을 읽고, 필요하면 top-k·분할을 바꿔 범위를 넓힌다.", [judge, explain, change, rerun]
    if st == "IDONLY":
        return ("이 범위에서 내용·순위·점수는 그대로이고 문서 ID만 바뀌었다. 저장된 Document.id에 의존하는 코드·인덱스·중복 정책이 있는지 확인하고(설명의 [S1] 참고) 재색인 여부를 정한 뒤, "
                "행마다 '예상됨/문제'를 남긴다. 검색 품질 재검사는 이 범위 안에서는 필요 없다."), [explain, judge, change, rerun]
    return "이 범위에서는 변화가 없다. 판정을 남기고 끝내거나, 다른 분할·top-k로 범위를 넓혀 점검한다.", [judge, change, rerun]


def load_bundles(d):
    """before/after bundles: app runs use bundle-before/after.json, shell runs bundle-hs231/hs31.json."""
    b = load_json(os.path.join(d, "bundle-before.json")) or load_json(os.path.join(d, "bundle-hs231.json"))
    a = load_json(os.path.join(d, "bundle-after.json")) or load_json(os.path.join(d, "bundle-hs31.json"))
    return b, a


@app.get("/runs/{rid}/log", response_class=HTMLResponse)
def run_log(request: Request, rid: str):
    """The check's own execution log (runtime/eval/runs/<id>/log.txt) as a page. Absence or read failure is said explicitly."""
    if not os.path.isdir(run_dir(rid)):
        return HTMLResponse("<p>점검을 찾지 못했다.</p>", status_code=404)
    m = read_meta(rid); p = os.path.join(run_dir(rid), "log.txt")
    if not os.path.exists(p):
        body, state = "", "none"
    else:
        try:
            body, state = open(p, encoding="utf-8", errors="replace").read(), "ok"
        except Exception as e:
            body, state = str(e), "error"
    return templates.TemplateResponse(request, "log.html", {"m": m, "body": body, "state": state, "path": os.path.relpath(p, ROOT), "openwebui": OPENWEBUI_PUBLIC})


@app.get("/runs/{rid}", response_class=HTMLResponse)
def run_page(request: Request, rid: str, compare: str = "", tier: str = "all"):
    d = run_dir(rid); m = read_meta(rid)
    diff = load_json(os.path.join(d, "diff.json")); ex = load_json(os.path.join(d, "explain.json"))
    # axis A summary (one check: library before/after) — pure python over stored JSON; filter narrows display only
    import sys; sys.path.insert(0, os.path.join(ROOT, "slice"))
    from diff_summary import summarize, align_hits, TIER_LABEL
    split = (m.get("conditions") or {}).get("split", "all")
    expected_ids = [q["id"] for q in questions() if split == "all" or q["split"] == split]
    summary = summarize(diff, m, expected_ids)
    tier = tier if tier in ("all", "same", "idonly", "changed", "undet") else "all"
    aligned = {}
    if diff:
        bb, ab = load_bundles(d)
        bq = {q["id"]: q for q in (bb or {}).get("queries", [])}; aq = {q["id"]: q for q in (ab or {}).get("queries", [])}
        for q in diff.get("queries", []):
            if q["id"] in bq and q["id"] in aq:
                aligned[q["id"]] = align_hits(bq[q["id"]]["hits"], aq[q["id"]]["hits"])
    ret = {s: load_json(os.path.join(d, f"retrieval-{s}.json")) for s in ("dev", "eval")}
    fb = [f for f in feedback_all() if f.get("run") == rid]
    prev_fb = [f for f in feedback_all() if f.get("run") == m.get("parent")] if m.get("parent") else []
    qmap = {q["id"]: q for q in questions()}
    cmp_row = None
    if compare and os.path.isdir(run_dir(compare)):
        import sys; sys.path.insert(0, os.path.join(ROOT, "slice"))
        from compare_runs import row
        cmp_row = {"a": row(run_dir(compare)), "b": row(d)}
    others = [r for r in list_runs() if r["id"] != rid]
    # what the next rerun would pin, from current reports (pure python, no model)
    pending_pins = []
    if diff:
        import sys; sys.path.insert(0, os.path.join(ROOT, "slice", "regression"))
        from reports import pins_for_class
        headings = [t for t, _ in md_sections(open(MIGRATION, encoding="utf-8").read())]
        for cls in sorted(set(diff.get("global", [])) | {c for q in diff["queries"] for c in q["classes"] if c != "IDENTICAL"}):
            pins, unmatched = pins_for_class(cls, headings, feedback_path=FEEDBACK)
            if pins or unmatched:
                pending_pins.append((cls, pins, unmatched))
    for e in (ex or {}).get("explanations", []):
        e["html"] = re.sub(r"\[S(\d+)\]", lambda mm: f'<a class="cite" href="/runs/{rid}/evidence/{e["class"]}/S{mm.group(1)}">[S{mm.group(1)}]</a>', e["text"]).replace("\n", "<br>")
    # judgments on axis-A difference rows (target diff:<qid>): human (by=user) vs AI Main (by=main); rows without any = unjudged
    judg = {}
    for f in fb:
        if str(f.get("target", "")).startswith("diff:"):
            judg.setdefault(f["target"].split(":", 1)[1], []).append(f)
    prev_judg = {}
    for f in prev_fb:
        if str(f.get("target", "")).startswith("diff:"):
            prev_judg.setdefault(f["target"].split(":", 1)[1], []).append(f)
    row_ids = list(summary["rows"].keys())
    from judgment_link import link_rows, class_judgments, explain_pairing, summary_counts
    from diff_bundles import diff_identity as _diff_identity
    jlink = link_rows(diff, ex, [f for f in feedback_all() if f.get("run") == rid])   # judgment -> comparison + cited sources
    cjudg = class_judgments(diff, [f for f in feedback_all() if f.get("run") == rid])  # explanation -> judged rows of its class
    cur_identity = _diff_identity(diff) if diff else ""
    explain_pair = explain_pairing(diff, ex)
    jsum = dict(summary_counts(row_ids, jlink), can_judge=summary["state"] in JUDGEABLE_STATES)  # same current/past rule as the rows
    guide_text, guide_actions = next_actions(summary, m, jsum)
    rplan = resume_plan_for(rid) if m.get("status") in ("failed", "cancelled", "interrupted", "cancelling") else None
    sview = step_plan.view(m)
    return templates.TemplateResponse(request, "run.html", {"m": m, "diff": diff, "ex": ex, "ret": ret, "fb": fb, "prev_fb": prev_fb, "judg": judg, "prev_judg": prev_judg, "jsum": jsum,
                                                   "guide_text": guide_text, "guide_actions": guide_actions, "state_label": STATE_LABEL, "rplan": rplan, "sview": sview,
                                                   "jlink": jlink, "cjudg": cjudg, "cur_identity": cur_identity, "explain_pair": explain_pair,
                                                   "resume_msg": request.query_params.get("resume", ""),
                                                   "qmap": qmap, "others": others, "cmp": cmp_row, "compare": compare, "openwebui": OPENWEBUI_PUBLIC, "pending_pins": pending_pins,
                                                   "summary": summary, "tier": tier, "tier_label": TIER_LABEL, "aligned": aligned})


@app.get("/runs/{rid}/evidence/{cls}/{tag}", response_class=HTMLResponse)
def evidence(request: Request, rid: str, cls: str, tag: str):
    ex = load_json(os.path.join(run_dir(rid), "explain.json")) or {}
    e = next((x for x in ex.get("explanations", []) if x["class"] == cls), None)
    src = next((s for s in (e or {}).get("sources", []) if s["tag"] == tag), None)
    body = ""
    if src:
        for title, text in md_sections(open(MIGRATION, encoding="utf-8").read()):
            if title == src["heading"]:
                body = render_md(text); break
    return templates.TemplateResponse(request, "source.html", {"title": f"{tag} — {src['heading'] if src else '?'}",
                                                      "origin": "corpus/MIGRATION.md (Haystack, Apache-2.0)", "body": body, "rid": rid, "cls": cls, "tag": tag})


@app.get("/source/doc", response_class=HTMLResponse)
def source_doc(request: Request, name: str):
    p = doc_path_from_name(name)
    body = render_md(open(p, encoding="utf-8").read()) if p else "<p>문서를 찾지 못했다.</p>"
    return templates.TemplateResponse(request, "source.html", {"title": name, "origin": os.path.relpath(p, ROOT) if p else "", "body": body, "rid": None})


@app.get("/preview")
def preview(q: str, version: str = "3.1", k: int = 3):
    """Search preview through Open WebUI's own retrieval API and knowledge bases (reuse, not our implementation)."""
    if VERIFY_MODE:
        return JSONResponse({"error": VERIFY_MSG})
    try:
        if version == "any":
            ids = [kb_id_for(v) for v in ("2.31", "3.1")]
        else:
            ids = [kb_id_for(version)]
        ids = [i for i in ids if i]
        if not ids:
            return JSONResponse({"error": "knowledge base not found in Open WebUI"})
        res = openwebui_api("/api/v1/retrieval/query/collection", {"collection_names": ids, "query": q, "k": k})
        hits = [{"name": mm.get("name"), "distance": round(dd, 3)} for mm, dd in zip((res.get("metadatas") or [[]])[0], (res.get("distances") or [[]])[0])]
        return JSONResponse({"hits": hits})
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.post("/runs/{rid}/feedback")
def add_feedback(rid: str, target: str = Form(...), verdict: str = Form(...), evidence: str = Form(""), note: str = Form(""),
                 classes: str = Form(""), diff_identity: str = Form("")):
    entry = {"target": target, "verdict": verdict, "evidence": evidence, "note": note, "by": "user", "run": rid,
             "created_at": datetime.now().isoformat(timespec="seconds")}
    if target.startswith("diff:"):  # pin a row judgment to the comparison it was made on (the form sends both; older entries lack them)
        entry["classes"] = [c for c in classes.split(",") if c]
        entry["diff_identity"] = diff_identity
    feedback_add(entry)
    return RedirectResponse(f"/runs/{rid}#feedback", status_code=303)


@app.get("/health")
def health():
    return {"status": True, "verify_mode": VERIFY_MODE, "pid": os.getpid()}
