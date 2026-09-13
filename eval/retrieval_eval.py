#!/usr/bin/env python3
"""Retrieval-only evaluation against the running Open WebUI (v0.11.3) using its own API.

What it measures (no LLM involved):
  - expected-source recall@k: does the fixed retrieval path (POST /api/v1/retrieval/query/collection)
    surface every document listed in eval/questions.yaml `expected_sources` within the top k?
  - wrong-version hits: does the top-k contain the `wrong_version_trap` document?
It needs an embedding model loaded in the product (otherwise the API returns the upstream
"No embedding model is loaded" error) and the corpus already ingested into knowledge bases whose names
map version folders: haystack-docs-2.31, haystack-docs-3.1.

Usage:
  .venv/bin/python eval/retrieval_eval.py --split dev [--k 3] [--hybrid] [--out runtime/eval/<name>.json]
Results are written as JSON so two runs (before/after a setting or code change) can be diffed.
Nothing here generates answers; retrieval hits are not "Agent behavior".
"""
import argparse, json, os, sys, time, urllib.request, urllib.error
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("OPENWEBUI_URL", "http://127.0.0.1:8080")


def api(path, token, data=None, method=None):
    req = urllib.request.Request(BASE + path, method=method or ("POST" if data is not None else "GET"))
    req.add_header("Authorization", f"Bearer {token}")
    body = None
    if data is not None:
        req.add_header("Content-Type", "application/json")
        body = json.dumps(data).encode()
    try:
        with urllib.request.urlopen(req, body, timeout=120) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "null")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "eval", "all"])
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--hybrid", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    token = open(os.path.join(ROOT, "runtime", ".token")).read().strip()
    questions = yaml.safe_load(open(os.path.join(ROOT, "eval", "questions.yaml")))
    if args.split != "all":
        questions = [q for q in questions if q["split"] == args.split]

    status, kbs = api("/api/v1/knowledge/", token)
    if status != 200:
        print("cannot list knowledge bases:", status, kbs); sys.exit(2)
    if isinstance(kbs, dict):  # v0.11.x returns {"items": [...], ...}
        kbs = kbs.get("items", [])
    kb_by_name = {kb["name"]: kb for kb in kbs}

    results = []
    for q in questions:
        version = q["version"]
        names = [f"haystack-docs-{version}"] if version != "any" else [n for n in kb_by_name if n.startswith("haystack-docs-")]
        collections = [kb_by_name[n]["id"] for n in names if n in kb_by_name]
        if not collections:
            results.append({"id": q["id"], "error": f"knowledge base(s) missing: {names}"}); continue
        t0 = time.time()
        status, res = api("/api/v1/retrieval/query/collection", token,
                          {"collection_names": collections, "query": q["question"], "k": args.k,
                           "hybrid": True if args.hybrid else None})
        dt = time.time() - t0
        if status != 200:
            results.append({"id": q["id"], "error": f"{status}: {res}"}); continue
        metas = (res or {}).get("metadatas") or (res or {}).get("metadata") or [[]]
        hit_files = []
        for m in metas[0] if metas else []:
            hit_files.append(m.get("name") or m.get("source") or "")
        def ingest_stem(path):  # version-3.1/overview/migration.mdx -> 3.1__overview__migration
            return os.path.splitext(path.replace("version-", "").replace("/", "__"))[0]
        hit_stems = [os.path.splitext(h)[0] for h in hit_files]
        expected = [ingest_stem(p) for p in q["expected_sources"]]
        if version == "any":  # a version-agnostic question is answered by either version's copy of the document
            strip = lambda st: st.split("__", 1)[1] if "__" in st else st
            hit_cmp, exp_cmp = [strip(h) for h in hit_stems], [strip(e) for e in expected]
        else:
            hit_cmp, exp_cmp = hit_stems, expected
        found = [e for e, ec in zip(expected, exp_cmp) if ec in hit_cmp]
        trap = ingest_stem(q["wrong_version_trap"]) if q.get("wrong_version_trap") else ""
        trap_hit = bool(trap) and trap in hit_stems
        results.append({"id": q["id"], "version": version, "k": args.k, "hybrid": args.hybrid,
                        "expected": expected, "found": found, "recall": len(found) / len(expected),
                        "trap": trap, "trap_hit": trap_hit, "hits": hit_files, "latency_s": round(dt, 3)})

    ok = [r for r in results if "error" not in r]
    summary = {"n": len(results), "errors": len(results) - len(ok),
               "mean_recall": round(sum(r["recall"] for r in ok) / len(ok), 3) if ok else None,
               "trap_hits": sum(1 for r in ok if r["trap_hit"]),
               "mean_latency_s": round(sum(r["latency_s"] for r in ok) / len(ok), 3) if ok else None}
    out = {"split": args.split, "k": args.k, "hybrid": args.hybrid, "summary": summary, "results": results}
    print(json.dumps(summary, indent=2))
    if args.out:
        os.makedirs(os.path.dirname(os.path.join(ROOT, args.out)), exist_ok=True)
        json.dump(out, open(os.path.join(ROOT, args.out), "w"), indent=2)
        print("written", args.out)
    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
