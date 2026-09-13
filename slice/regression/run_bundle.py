#!/usr/bin/env python3
"""Run one fixed retrieval pipeline under whichever haystack-ai version is installed and write a bundle.

Pipeline (identical definition for both versions): Markdown files -> DocumentSplitter(word, 200/20)
  -> InMemoryDocumentStore -> InMemoryBM25Retriever(top_k). No embedding model, no LLM.

Usage (run once per isolated env):
  .venv-hs231/bin/python slice/regression/run_bundle.py --label hs231 --out runtime/eval/regression/bundle-hs231.json
  .venv-hs31/bin/python  slice/regression/run_bundle.py --label hs31  --out runtime/eval/regression/bundle-hs31.json
The bundle records: versions, pipeline config, corpus fingerprint, chunk count, and per query the top-k
(rank, Document.id, score, content sha1, source path). Bundles are the only input to diff_bundles.py.
"""
import argparse, hashlib, json, os, platform, sys, time, traceback
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# the pipeline this producer actually builds; recorded in every bundle so a later reader can compare settings
PIPELINE = {"splitter": {"split_by": "word", "split_length": 200, "split_overlap": 20}, "retriever": "InMemoryBM25Retriever"}
DEFAULT_CORPUS = os.path.join(ROOT, "corpus", "haystack-docs-src", "docs-website", "versioned_docs", "version-3.1")


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def load_corpus(corpus_dir, limit=None):
    files = []
    for dp, _, fns in os.walk(corpus_dir):
        for fn in sorted(fns):
            if fn.endswith((".md", ".mdx")):
                files.append(os.path.join(dp, fn))
    files.sort()
    if limit:
        files = files[:limit]
    docs = []
    for f in files:
        text = open(f, encoding="utf-8", errors="replace").read()
        docs.append((os.path.relpath(f, corpus_dir), text))
    return docs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--limit", type=int, default=None, help="use only the first N files (sorted)")
    ap.add_argument("--questions", default=os.path.join(ROOT, "eval", "questions.yaml"))
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--split", default="all", help="all | dev | eval")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    bundle = {"label": args.label, "python": platform.python_version(), "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "pipeline": dict(PIPELINE, top_k=args.top_k),
              "corpus": {"dir": os.path.relpath(args.corpus, ROOT), "limit": args.limit}, "split": args.split,
              "queries": [], "error": None}
    try:
        import haystack
        from haystack import Document, Pipeline
        from haystack.components.preprocessors import DocumentSplitter
        from haystack.components.writers import DocumentWriter
        from haystack.document_stores.in_memory import InMemoryDocumentStore
        from haystack.components.retrievers.in_memory import InMemoryBM25Retriever
        bundle["haystack"] = haystack.__version__

        raw = load_corpus(args.corpus, args.limit)
        bundle["corpus"]["files"] = len(raw)
        bundle["corpus"]["fingerprint"] = sha1("".join(p + sha1(t) for p, t in raw))
        docs = [Document(content=t, meta={"path": p, "version": "3.1"}) for p, t in raw]

        store = InMemoryDocumentStore()
        index = Pipeline()
        index.add_component("splitter", DocumentSplitter(**PIPELINE["splitter"]))
        index.add_component("writer", DocumentWriter(document_store=store))
        index.connect("splitter.documents", "writer.documents")
        t0 = time.time()
        index.run({"splitter": {"documents": docs}})
        bundle["index_seconds"] = round(time.time() - t0, 3)
        bundle["chunks"] = store.count_documents()

        query = Pipeline()
        query.add_component("retriever", InMemoryBM25Retriever(document_store=store, top_k=args.top_k))
        questions = yaml.safe_load(open(args.questions))
        if args.split != "all":
            questions = [q for q in questions if q["split"] == args.split]
        for q in questions:
            t0 = time.time()
            res = query.run({"retriever": {"query": q["question"]}})
            hits = []
            for rank, d in enumerate(res["retriever"]["documents"], 1):
                hits.append({"rank": rank, "id": d.id, "score": round(float(d.score), 6) if d.score is not None else None,
                             "content_sha1": sha1(d.content or ""), "path": (d.meta or {}).get("path")})
            bundle["queries"].append({"id": q["id"], "question": q["question"], "expected_sources": q["expected_sources"],
                                      "latency_s": round(time.time() - t0, 4), "hits": hits})
    except Exception:
        bundle["error"] = traceback.format_exc()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(bundle, open(args.out, "w"), indent=2)
    print(json.dumps({k: bundle.get(k) for k in ("label", "haystack", "chunks", "index_seconds")}),
          "| queries:", len(bundle["queries"]), "| error:", bool(bundle["error"]))
    return 1 if bundle["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
