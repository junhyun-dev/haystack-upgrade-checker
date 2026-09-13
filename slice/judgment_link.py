"""Ties a person's judgment of one diff row to the comparison it was made on and to the explanation's cited sources —
only when the stored records agree; otherwise the judgment is kept and shown as past/unconfirmed, never merged into the
current comparison's judgments.

Pure Python over the run's diff.json, explain.json and the feedback entries for that run. Nothing here judges or writes.
These are consistency checks over records this app wrote (the form sends classes and diff_identity back; they are
compared with what the server computes now). They are not authentication or anti-forgery.

A diff judgment (target "diff:<qid>") may carry, since 2026-09-13, the row's `classes` and the `diff_identity` of the
comparison it was made on. Older entries have neither.

status  "current"  identity equals the current comparison, the row exists and its classes equal the recorded ones
        "past"     anything else; `why` says which: identity-missing | no-comparison | identity-differs | row-missing | classes-differ

Explanation pairing (explain.json vs the current comparison): "this" when its recorded diff_identity equals the current
one, "other" when it differs, "unknown" when the file predates provenance (then it is a reference, not this comparison's).
The explanation's `sources` are the retriever's candidate list; only tags that appear as [S<n>] in the text were used.
Evidence links open the current MIGRATION.md section of that heading, not a snapshot from judgment time.
"""
import os
import re
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "regression"))
from diff_bundles import diff_identity  # noqa: E402

VERDICTS = ("expected", "problem", "unclear")


def explain_pairing(diff, ex):
    if not ex or not ex.get("explanations"):
        return "unknown"
    rec = ex.get("diff_identity")
    if not rec:
        return "unknown"
    return "this" if diff and rec == diff_identity(diff) else "other"


def sources_by_class(ex):
    """{class: {"used": [...], "candidates": [...], "marks": bool}} — used = candidate sources whose tag the text cites."""
    out = {}
    for e in (ex or {}).get("explanations", []):
        marks = set(re.findall(r"\[(S\d+)\]", e.get("text") or ""))
        srcs = [{"tag": s.get("tag"), "heading": s.get("heading"), "pinned": bool(s.get("pinned"))} for s in e.get("sources", [])]
        out[e.get("class")] = {"used": [s for s in srcs if s["tag"] in marks], "candidates": [s for s in srcs if s["tag"] not in marks],
                               "marks": bool(marks)}
    return out


def _status(j, ident, row):
    rec = j.get("diff_identity")
    if not rec:
        return "past", "identity-missing"
    if not ident:
        return "past", "no-comparison"
    if rec != ident:
        return "past", "identity-differs"
    if row is None:
        return "past", "row-missing"
    if sorted(j.get("classes") or []) != sorted(row.get("classes") or []):
        return "past", "classes-differ"
    return "current", ""


def link_rows(diff, ex, judgments):
    """{qid: [judgment + {status, why, classes, classes_from, evidence_links}]}; the entry's own fields are kept."""
    ident = diff_identity(diff) if diff else None
    rows = {q.get("id"): q for q in (diff or {}).get("queries", [])}
    srcs = sources_by_class(ex)
    pairing = explain_pairing(diff, ex)
    out = {}
    for j in judgments:
        if not str(j.get("target", "")).startswith("diff:"):
            continue
        qid = j["target"].split(":", 1)[1]
        row = rows.get(qid)
        status, why = _status(j, ident, row)
        if j.get("classes"):
            classes, origin = list(j["classes"]), "recorded"
        else:
            classes, origin = list((row or {}).get("classes") or []), "current"
        links = []
        if status == "current" and pairing != "other":
            links = [{"class": c, "pairing": pairing, **srcs[c]} for c in classes if c in srcs]
        out.setdefault(qid, []).append(dict(j, status=status, why=why, classes=classes, classes_from=origin, evidence_links=links))
    return out


def class_judgments(diff, judgments):
    """{class: {expected, problem, unclear, human, qids, past}} — current judgments per class; past/unconfirmed ones only counted."""
    ident = diff_identity(diff) if diff else None
    rows = {q.get("id"): q for q in (diff or {}).get("queries", [])}
    out = {}
    for j in judgments:
        if not str(j.get("target", "")).startswith("diff:"):
            continue
        qid = j["target"].split(":", 1)[1]
        row = rows.get(qid)
        status, _ = _status(j, ident, row)
        classes = j.get("classes") or (row or {}).get("classes") or []
        for c in classes:
            d = out.setdefault(c, {"expected": 0, "problem": 0, "unclear": 0, "human": 0, "qids": [], "past": 0})
            if status != "current":
                d["past"] += 1
                continue
            if j.get("verdict") in VERDICTS:
                d[j["verdict"]] += 1
            if j.get("by") == "user":
                d["human"] += 1
            if qid not in d["qids"]:
                d["qids"].append(qid)
    return out


def summary_counts(row_ids, linked):
    """The page-top summary over the current comparison's rows, from link_rows output: a row counts as judged by a
    person / by AI Main only through judgments with status "current"; past/unconfirmed entries are counted apart and
    leave the row unjudged. Denominator is the row count; a row with several judgments still counts once."""
    cur = {q: [j for j in linked.get(q, []) if j["status"] == "current"] for q in row_ids}
    past = sum(1 for js in linked.values() for j in js if j["status"] != "current")
    return {"human": sum(1 for q in row_ids if any(j.get("by") == "user" for j in cur[q])),
            "ai": sum(1 for q in row_ids if any(j.get("by") == "main" for j in cur[q])),
            "unjudged": sum(1 for q in row_ids if not cur[q]), "rows": len(row_ids), "past": past}
