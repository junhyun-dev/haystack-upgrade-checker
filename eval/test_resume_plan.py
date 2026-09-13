#!/usr/bin/env python3
"""Independent expectations for slice/resume_plan.py, on project-owned synthetic run directories.
No app, no server, no model. Run: python3 eval/test_resume_plan.py"""
import json, os, shutil, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "slice"))
sys.path.insert(0, os.path.join(ROOT, "slice", "regression"))
from resume_plan import plan
from diff_bundles import build_diff, diff_identity
from run_bundle import PIPELINE

ENVS = {"hs231": "2.31.0", "hs31": "3.1.1"}
IDS = ["q01", "q02"]
COND = {"before": "hs231", "after": "hs31", "corpus": "version-3.1", "split": "dev", "k": 5, "explain": True, "retrieval": True}
CORPUS_DIR = "corpus/haystack-docs-src/docs-website/versioned_docs/version-3.1"
fails = []


TEXTS = {"q01": "a", "q02": "b"}
HIT = {"rank": 1, "id": "x", "score": 1.0, "content_sha1": "A", "path": "A.md"}
SECTIONS = {"Auto-generated `Document.id` changes": "sec-hash"}


def hits(cid="A", did="x"):
    return [dict(HIT, id=did, content_sha1=cid, path=f"{cid}.md")]


def bundle(label, hs, split="dev", k=5, corpus=CORPUS_DIR, ids=None, error=None, texts=None, chunks=10, cid="A", did="x"):
    t = texts or TEXTS
    return {"label": label, "haystack": hs, "split": split, "pipeline": dict(PIPELINE, top_k=k),
            "corpus": {"dir": corpus, "fingerprint": "fp"}, "chunks": chunks,
            "queries": [{"id": i, "question": t.get(i, "?"), "hits": hits(cid, did), "latency_s": 0.001} for i in (ids or IDS)],
            "error": error}


def make(tmp, files, status="cancelled", stop_scope="empty", cond=None):
    d = os.path.join(tmp, "run"); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    for name, content in files.items():
        with open(os.path.join(d, name), "w") as f:
            f.write(content if isinstance(content, str) else json.dumps(content))
    meta = {"status": status, "stop_scope": stop_scope, "conditions": dict(cond or COND), "step": "explain (local LLM)"}
    return d, meta


def ctx(fingerprint="fp", sections=None, pins=None):
    return {"corpus_fingerprint": fingerprint, "pipeline": dict(PIPELINE),
            "diff_identity_of": lambda a, b: diff_identity(build_diff(a, b)),
            "section_hashes": SECTIONS if sections is None else sections,
            "pins_now": (lambda cls: []) if pins is None else pins}


def run(tmp, files, fingerprint="fp", sections=None, pins=None, **kw):
    d, meta = make(tmp, files, **kw)
    return plan(d, meta, ENVS, [(i, TEXTS[i]) for i in IDS], lambda p: json.load(open(p)), ctx(fingerprint, sections, pins))


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (" | " + detail if detail else ""))
    if not ok:
        fails.append(name)


GOOD = {"bundle-before.json": bundle("hs231", "2.31.0", did="old"), "bundle-after.json": bundle("hs31", "3.1.1", did="new"),
        "diff.json": {"before": {"label": "hs231", "haystack": "2.31.0"}, "after": {"label": "hs31", "haystack": "3.1.1"},
                      "queries": [{"id": i, "question": TEXTS[i], "classes": ["ID_CHANGED_SAME_CONTENT"]} for i in IDS],
                      "global": [], "summary": {"chunks": [10, 10]}},
        "explain.json": {"before": {"label": "hs231", "haystack": "2.31.0"}, "after": {"label": "hs31", "haystack": "3.1.1"},
                         "diff_identity": diff_identity(build_diff(bundle("hs231", "2.31.0", did="old"), bundle("hs31", "3.1.1", did="new"))),
                         "explanations": [{"class": "ID_CHANGED_SAME_CONTENT", "example_query": "q01",
                                           "source_hashes": dict(SECTIONS), "pinned": []}]},
        "retrieval-dev.json": {"summary": {}}}

with tempfile.TemporaryDirectory() as tmp:
    p = run(tmp, GOOD)
    check("1 cancelled+group empty: bundles and the matching explanation carried; diff recomputed, retrieval never",
          p["reuse"] == ["bundle-before", "bundle-after", "explain"] and not p["blocked"], str(p["reuse"]))
    check("1c the comparison is always recomputed", any(i["name"] == "diff" and not i["reuse"] and "다시 계산" in i["why"] for i in p["artifacts"]))
    check("1b retrieval reason names the live index", any(i["name"] == "retrieval-dev" and "색인" in i["why"] for i in p["artifacts"]))

    p = run(tmp, GOOD, status="interrupted")
    check("2 interrupted: nothing carried (a writer may have survived)", p["reuse"] == [] and "확인할 수 없다" in (p["blocked"] or ""), str(p["blocked"])[:40])

    p = run(tmp, GOOD, status="cancelled", stop_scope="unknown")
    check("3 cancelled but group not confirmed empty: nothing carried", p["reuse"] == [] and bool(p["blocked"]))

    p = run(tmp, GOOD, status="running")
    check("4 still running: nothing carried", p["reuse"] == [] and bool(p["blocked"]))

    bad = dict(GOOD); bad["bundle-after.json"] = bundle("hs31", "3.2.0")
    p = run(tmp, bad)
    check("5 env version moved on: that bundle and everything derived is redone",
          p["reuse"] == ["bundle-before"] and any(i["name"] == "bundle-after" and "haystack 버전" in i["why"] for i in p["artifacts"]), str(p["reuse"]))

    bad = dict(GOOD); bad["bundle-before.json"] = bundle("hs231", "2.31.0", ids=["q01", "q02", "q99"])
    p = run(tmp, bad)
    check("6 question set changed: that bundle is redone", "bundle-before" not in p["reuse"] and any("질문 세트" in i["why"] for i in p["artifacts"]))

    bad = dict(GOOD); bad["explain.json"] = "{ truncated"
    p = run(tmp, bad)
    check("7 truncated explanation: not carried, said plainly",
          "explain" not in p["reuse"] and any(i["name"] == "explain" and "잘렸을" in i["why"] for i in p["artifacts"]))

    bad = dict(GOOD); bad["diff.json"] = "{ truncated"
    p = run(tmp, bad)
    check("7b a damaged stored comparison does not matter: it is recomputed, and the explanation is judged against that",
          p["reuse"] == ["bundle-before", "bundle-after", "explain"], str(p["reuse"]))

    only_bundles = {k: v for k, v in GOOD.items() if k.startswith("bundle")}
    p = run(tmp, only_bundles)
    check("8 stopped before diff: bundles carried, nothing else", p["reuse"] == ["bundle-before", "bundle-after"])

    bad = dict(GOOD); bad["explain.json"] = {"before": {"label": "hs231", "haystack": "2.30.0"}, "after": {"label": "hs31", "haystack": "3.1.1"}}
    p = run(tmp, bad)
    check("9 explanation from another comparison: redone (one more model call)", "explain" not in p["reuse"])

    old_style = {"bundle-before.json": {k: v for k, v in bundle("hs231", "2.31.0").items() if k != "split"},
                 "bundle-after.json": {k: v for k, v in bundle("hs31", "3.1.1").items() if k != "split"}}
    p = run(tmp, old_style)
    check("11 bundle written before a split was recorded: question ids decide", p["reuse"] == ["bundle-before", "bundle-after"], str(p["reuse"]))

    old_style_wrong = {"bundle-before.json": {k: v for k, v in bundle("hs231", "2.31.0", ids=["q01"]).items() if k != "split"}}
    p = run(tmp, old_style_wrong)
    check("11b ... and still catch a different question set", p["reuse"] == [] and any("질문 세트" in i["why"] for i in p["artifacts"]))

    p = run(tmp, GOOD, cond=dict(COND, k=7))
    check("10 top-k changed: bundles redone", p["reuse"] == [] and any("top-k" in i["why"] for i in p["artifacts"]))

    # --- linkage and content identity (the file must prove it belongs to these conditions and to these artifacts)
    bad = dict(GOOD); bad["diff.json"] = {"before": {"label": "hs231", "haystack": "2.31.0"},
                                          "after": {"label": "hs31", "haystack": "3.1.1"},
                                          "queries": [{"id": "q99", "question": "other"}], "summary": {"chunks": [10, 10]}}
    p = run(tmp, bad)
    check("12 stored comparison is over other questions: never carried, and judgement uses the recomputed one",
          "diff" not in p["reuse"] and p["reuse"] == ["bundle-before", "bundle-after", "explain"], str(p["reuse"]))

    bad = dict(GOOD); bad["bundle-before.json"] = bundle("hs231", "2.31.0", texts={"q01": "질문이 바뀌었다", "q02": "b"})
    p = run(tmp, bad)
    check("13 question text edited under the same id: that bundle is not carried",
          "bundle-before" not in p["reuse"] and any("질문 내용" in i["why"] for i in p["artifacts"]), str(p["reuse"]))

    p = run(tmp, GOOD, fingerprint="다른-fingerprint")
    check("14 corpus content changed since: bundles not carried", p["reuse"] == [] and any("문서 묶음 내용" in i["why"] for i in p["artifacts"]))

    p = run(tmp, GOOD, fingerprint=None)
    check("15 corpus fingerprint could not be computed: do not claim sameness", p["reuse"] == [] and any("확인하지 못" in i["why"] for i in p["artifacts"]))

    bad = dict(GOOD); bad["explain.json"] = {"before": {"label": "hs231", "haystack": "2.31.0"},
                                             "after": {"label": "hs31", "haystack": "3.1.1"},
                                             "explanations": [{"class": "RANK_CHANGED", "example_query": "q99"}]}
    p = run(tmp, bad)
    check("16 explanation whose recorded comparison does not match: not carried", "explain" not in p["reuse"])

    # --- the counterexample: bundles whose hits really differ, but a stored diff/explanation that says otherwise
    mism = {"bundle-before.json": bundle("hs231", "2.31.0", cid="A", did="old"),
            "bundle-after.json": bundle("hs31", "3.1.1", cid="B", did="new"),
            "diff.json": {"before": {"label": "hs231", "haystack": "2.31.0"}, "after": {"label": "hs31", "haystack": "3.1.1"},
                          "queries": [{"id": i, "question": TEXTS[i], "classes": ["ID_CHANGED_SAME_CONTENT"]} for i in IDS],
                          "global": [], "summary": {"chunks": [10, 10]}},
            "explain.json": {"before": {"label": "hs231", "haystack": "2.31.0"}, "after": {"label": "hs31", "haystack": "3.1.1"},
                             "diff_identity": "whatever-was-stored",
                             "explanations": [{"class": "ID_CHANGED_SAME_CONTENT", "example_query": "q01",
                                               "source_hashes": dict(SECTIONS), "pinned": []}]}}
    p = run(tmp, mism)
    check("17 the bundles really disagree with the stored comparison: only the bundles are carried",
          p["reuse"] == ["bundle-before", "bundle-after"] and any(i["name"] == "explain" and "다시 계산한 비교와 다른" in i["why"] for i in p["artifacts"]),
          str(p["reuse"]))
    real = build_diff(json.loads(json.dumps(mism["bundle-before.json"])), json.loads(json.dumps(mism["bundle-after.json"])))
    check("17b and the real classification of those bundles is not ID-only",
          sorted(real["queries"][0]["classes"]) == ["DOC_EXTRA", "DOC_MISSING"], str(real["queries"][0]["classes"]))

    old_fmt = dict(GOOD); old_fmt["explain.json"] = {"before": {"label": "hs231", "haystack": "2.31.0"},
                                                     "after": {"label": "hs31", "haystack": "3.1.1"},
                                                     "explanations": [{"class": "ID_CHANGED_SAME_CONTENT"}]}
    p = run(tmp, old_fmt)
    check("18 explanation from before provenance was recorded: not carried", "explain" not in p["reuse"] and any("옛 형식" in i["why"] for i in p["artifacts"]))

    p = run(tmp, GOOD, sections={"Auto-generated `Document.id` changes": "다른-해시"})
    check("19 the cited source section changed since: explanation not carried", "explain" not in p["reuse"] and any("인용한 원문 절" in i["why"] for i in p["artifacts"]))

    p = run(tmp, GOOD, pins=lambda cls: ["새로 고정될 절"])
    check("20 a report would now pin a different source: explanation not carried", "explain" not in p["reuse"] and any("신고로 고정될 근거" in i["why"] for i in p["artifacts"]))

    bad_pipe = dict(GOOD)
    b = bundle("hs231", "2.31.0", did="old"); b["pipeline"] = {"splitter": {"split_by": "sentence"}, "retriever": "InMemoryBM25Retriever", "top_k": 5}
    bad_pipe["bundle-before.json"] = b
    p = run(tmp, bad_pipe)
    check("21 bundle built with other pipeline settings: not carried", "bundle-before" not in p["reuse"] and any("파이프라인 설정" in i["why"] for i in p["artifacts"]))

print("failures:", len(fails))
sys.exit(1 if fails else 0)
