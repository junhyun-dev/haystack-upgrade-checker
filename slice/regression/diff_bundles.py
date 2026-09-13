#!/usr/bin/env python3
"""Diff two bundles from run_bundle.py and classify every difference. Deterministic, no LLM.

Classes (per query, top-k compared by rank):
  IDENTICAL               same ids, same order, same scores
  ID_CHANGED_SAME_CONTENT same content (sha1) at the same rank, different Document.id
  RANK_CHANGED            same set of contents, different order
  SCORE_CHANGED           same content at same rank, score differs by > eps
  DOC_MISSING / DOC_EXTRA content present only in before / only in after
Global:
  SPLIT_CHANGED           chunk count differs         RUNTIME_ERROR  a run failed
  CORPUS_CHANGED          corpus fingerprint differs (then per-query diffs are not attributable to the version)

Usage: python3 slice/regression/diff_bundles.py before.json after.json --out runtime/eval/regression/diff.json
"""
import argparse, hashlib, json, os, sys
from collections import Counter

EPS = 1e-6


def classify_query(qa, qb):
    ha, hb = qa["hits"], qb["hits"]
    sa = [h["content_sha1"] for h in ha]; sb = [h["content_sha1"] for h in hb]
    classes, details = [], []
    if not ha and not hb:
        return ["IDENTICAL"], details
    if set(sa) != set(sb):
        for h in ha:
            if h["content_sha1"] not in sb:
                classes.append("DOC_MISSING"); details.append({"rank_before": h["rank"], "path": h["path"], "sha1": h["content_sha1"][:10]})
        for h in hb:
            if h["content_sha1"] not in sa:
                classes.append("DOC_EXTRA"); details.append({"rank_after": h["rank"], "path": h["path"], "sha1": h["content_sha1"][:10]})
    elif sa != sb:
        classes.append("RANK_CHANGED"); details.append({"before": [h["path"] for h in ha], "after": [h["path"] for h in hb]})
    for a, b in zip(ha, hb):
        if a["content_sha1"] == b["content_sha1"]:
            if a["id"] != b["id"]:
                classes.append("ID_CHANGED_SAME_CONTENT")
                details.append({"rank": a["rank"], "path": a["path"], "id_before": a["id"][:12], "id_after": b["id"][:12]})
            if a["score"] is not None and b["score"] is not None and abs(a["score"] - b["score"]) > EPS:
                classes.append("SCORE_CHANGED"); details.append({"rank": a["rank"], "path": a["path"], "before": a["score"], "after": b["score"]})
    if not classes:
        classes.append("IDENTICAL")
    return classes, details


def diff_identity(diff):
    """Stable identity of a comparison's content: versions, global flags, and the per-query classification. No timings."""
    core = {"before": diff.get("before"), "after": diff.get("after"), "global": sorted(diff.get("global") or []),
            "queries": [{"id": q.get("id"), "question": q.get("question"), "classes": sorted(q.get("classes") or []),
                         "details": q.get("details")} for q in diff.get("queries", [])]}
    return hashlib.sha1(json.dumps(core, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def build_diff(A, B):
    """The comparison itself, so a reader can recompute it from two bundles instead of trusting a stored file."""
    out = {"before": {"label": A["label"], "haystack": A.get("haystack")}, "after": {"label": B["label"], "haystack": B.get("haystack")},
           "global": [], "queries": [], "summary": {}}
    if A.get("error") or B.get("error"):
        out["global"].append("RUNTIME_ERROR")
    if A.get("corpus", {}).get("fingerprint") != B.get("corpus", {}).get("fingerprint"):
        out["global"].append("CORPUS_CHANGED")
    if A.get("chunks") != B.get("chunks"):
        out["global"].append("SPLIT_CHANGED")
    if A.get("pipeline") != B.get("pipeline"):
        out["global"].append("PIPELINE_CONFIG_CHANGED")
    counter = Counter()
    qb_by_id = {q["id"]: q for q in B["queries"]}
    for qa in A["queries"]:
        qb = qb_by_id.get(qa["id"])
        if qb is None:
            out["queries"].append({"id": qa["id"], "classes": ["QUERY_MISSING_AFTER"], "details": []}); counter["QUERY_MISSING_AFTER"] += 1; continue
        classes, details = classify_query(qa, qb)
        for c in set(classes):
            counter[c] += 1
        out["queries"].append({"id": qa["id"], "question": qa["question"], "classes": sorted(set(classes)),
                               "n_details": len(details), "details": details[:10],
                               "latency_before_s": qa["latency_s"], "latency_after_s": qb["latency_s"]})
    out["summary"] = {"queries": len(out["queries"]), "classes_by_query_count": dict(counter), "global": out["global"],
                      "chunks": [A.get("chunks"), B.get("chunks")], "index_seconds": [A.get("index_seconds"), B.get("index_seconds")]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before"); ap.add_argument("after"); ap.add_argument("--out", default=None)
    args = ap.parse_args()
    A = json.load(open(args.before)); B = json.load(open(args.after))
    out = build_diff(A, B)
    print(json.dumps(out["summary"], indent=2))
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        json.dump(out, open(args.out, "w"), indent=2); print("written", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
