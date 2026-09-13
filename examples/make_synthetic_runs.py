#!/usr/bin/env python3
"""Write three SYNTHETIC checks into runtime/eval/runs so the browser flow can be seen without Haystack environments,
the documents corpus, a model server or Open WebUI. Deterministic; safe to re-run (it replaces only these three ids).

Nothing here is a real measurement:
  - the two "bundles" are hand-written retrieval results (3 questions from eval/questions.yaml, 2 hits each);
  - the comparison IS real: it is recomputed by the project's own diff producer (slice/regression/diff_bundles.build_diff);
  - the "explanation" is a fixture text marked as such; its [S1] cites a real section heading of corpus/MIGRATION.md so
    the evidence link opens that section. No language model produced it.

  synthetic-done       finished: one row ID-only change, one unchanged, one document replaced -> "변화" tier, judgeable
  synthetic-stopped    stopped by the user during the explanation step (bundles + comparison exist) -> recovery flow
  synthetic-failed     failed during the comparison step -> list shows "2/4에서 실패 · 비교"
"""
import hashlib, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "slice")); sys.path.insert(0, os.path.join(ROOT, "slice", "regression"))
import yaml
from diff_bundles import build_diff, diff_identity
from run_bundle import PIPELINE
from reports import split_sections
import step_plan

RUNS = os.path.join(ROOT, "runtime", "eval", "runs")
COND = {"before": "hs231", "after": "hs31", "corpus": "version-3.1", "split": "dev", "k": 2, "explain": True, "retrieval": False}
QS = [q for q in yaml.safe_load(open(os.path.join(ROOT, "eval", "questions.yaml"))) if q["split"] == "dev"][:3]


def sha(s):
    return hashlib.sha1(s.encode()).hexdigest()


def hit(rank, doc, content, score):
    return {"rank": rank, "id": sha(doc + content)[:32], "score": score, "content_sha1": sha(content), "path": doc}


def bundle(label, version, after=False):
    qs = []
    for i, q in enumerate(QS):
        if i == 0:      # same content, new auto-generated id in the new version
            hits = [hit(1, "components/tools.md", "ToolInvoker text", 1.0), hit(2, "components/agents.md", "Agent text", 0.8)]
            if after:
                hits[0]["id"] = sha("new-id-" + hits[0]["id"])[:32]
        elif i == 1:    # unchanged
            hits = [hit(1, "concepts/pipelines.md", "Pipeline text", 1.0), hit(2, "concepts/components.md", "Component text", 0.7)]
        else:           # top document replaced in the new version
            hits = [hit(1, "overview/migration.md" if after else "development/tracing.md", "migration text" if after else "tracing text", 0.9),
                    hit(2, "integrations/opentelemetry.md", "otel text", 0.5)]
        qs.append({"id": q["id"], "question": q["question"], "hits": hits, "latency_s": 0.01})
    return {"label": label, "haystack": version, "split": "dev", "pipeline": dict(PIPELINE, top_k=2),
            "corpus": {"dir": "SYNTHETIC/versioned_docs/version-3.1", "fingerprint": "synthetic"}, "chunks": 3,
            "queries": qs, "error": None, "synthetic": "hand-written fixture, not a measurement"}


def write(rid, status, step, files, steps, extra=None):
    d = os.path.join(RUNS, rid); os.makedirs(d, exist_ok=True)
    for name, obj in files.items():
        json.dump(obj, open(os.path.join(d, name), "w"), ensure_ascii=False, indent=1)
    meta = {"id": rid, "created_at": "synthetic", "status": status, "step": step, "conditions": dict(COND), "origin": "examples/make_synthetic_runs.py",
            "error": None, "versions": {"before": "2.31.0", "after": "3.1.1"}, "steps": steps, "synthetic": True}
    meta.update(extra or {})
    json.dump(meta, open(os.path.join(d, "meta.json"), "w"), ensure_ascii=False, indent=1)
    open(os.path.join(d, "log.txt"), "w").write(f"[00:00:00] SYNTHETIC check written by examples/make_synthetic_runs.py (status {status})\n")


B, A = bundle("hs231", "2.31.0"), bundle("hs31", "3.1.1", after=True)
diff = build_diff(json.loads(json.dumps(B)), json.loads(json.dumps(A)))
sections = split_sections(open(os.path.join(ROOT, "corpus", "MIGRATION.md"), encoding="utf-8").read(), min_len=41)
heading, body = next((t, b) for t, b in sections if "Document.id" in t)
cls = "ID_CHANGED_SAME_CONTENT"
explain = {"before": diff["before"], "after": diff["after"], "llm": {"url": "none", "model": "SYNTHETIC FIXTURE"},
           "diff_identity": diff_identity(diff),
           "explanations": [{"class": cls, "example_query": QS[0]["id"], "query_used": cls,
                             "sources": [{"tag": "S1", "heading": heading, "score": 1.0, "pinned": False}],
                             "pinned": [], "source_hashes": {heading: sha(body)}, "unmatched_reports": [],
                             "text": "SYNTHETIC FIXTURE — not a model output. The migration guide says document ids are generated differently for documents with metadata [S1]. Content and ranking are unchanged in this example [S1].",
                             "html": "<b>SYNTHETIC FIXTURE — not a model output.</b> The migration guide says document ids are generated differently for documents with metadata [S1]. Content and ranking are unchanged in this example [S1].",
                             "sentences": 3, "cited": 2, "no_source": 0, "ungrounded": 1, "ungrounded_sentences": ["SYNTHETIC FIXTURE — not a model output."],
                             "latency_s": 0.0, "usage": {}, "tokens_per_s": 0, "human_review": "pending"}]}

plan = step_plan.plan(COND)
done = [dict(s, state="done") for s in plan]
write("synthetic-done", "done", "done", {"bundle-before.json": B, "bundle-after.json": A, "diff.json": diff, "explain.json": explain}, done)
stopped = [dict(s, state="done") for s in plan]; stopped[3]["state"] = "stopped"
write("synthetic-stopped", "cancelled", "explain (local LLM)", {"bundle-before.json": B, "bundle-after.json": A, "diff.json": diff}, stopped, {"stop_scope": "empty"})
failed = [dict(s, state="pending") for s in plan]; failed[0]["state"] = failed[1]["state"] = "done"; failed[2]["state"] = "failed"
write("synthetic-failed", "failed", "diff", {"bundle-before.json": B, "bundle-after.json": A}, failed, {"error": "SYNTHETIC: diff step failed (example)"})
print("wrote synthetic-done, synthetic-stopped, synthetic-failed under", RUNS)
print("classes per row:", [(q["id"], q["classes"]) for q in diff["queries"]])
