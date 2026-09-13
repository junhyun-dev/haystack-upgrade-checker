#!/usr/bin/env python3
"""A diff-row judgment must point at the comparison it was made on and at the explanation's cited sources; older
entries stay readable but are not claimed as pinned. Fixtures only — the explanation below is synthetic, not a model
output. Run: python3 eval/test_judgment_link.py"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "slice")); sys.path.insert(0, os.path.join(ROOT, "slice", "regression"))
from judgment_link import link_rows, class_judgments, explain_pairing, sources_by_class, summary_counts
from diff_bundles import diff_identity

fails = []
def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (" | " + detail if detail else ""))
    if not ok: fails.append(name)

DIFF = {"before": {"label": "hs231", "haystack": "2.31.0"}, "after": {"label": "hs31", "haystack": "3.1.1"}, "global": [],
        "queries": [{"id": "q01", "question": "a", "classes": ["ID_CHANGED_SAME_CONTENT"], "details": []},
                    {"id": "q02", "question": "b", "classes": ["DOC_MISSING", "DOC_EXTRA"], "details": []},
                    {"id": "q03", "question": "c", "classes": [], "details": []}]}
IDENT = diff_identity(DIFF)
EX = {"diff_identity": IDENT,
      "explanations": [{"class": "ID_CHANGED_SAME_CONTENT", "text": "SYNTHETIC FIXTURE, not a model output [S1]",
                        "sources": [{"tag": "S1", "heading": "Auto-generated `Document.id` changes", "pinned": False},
                                    {"tag": "S2", "heading": "Other section", "pinned": True}]}]}
J = [{"target": "diff:q01", "verdict": "problem", "by": "user", "run": "r", "classes": ["ID_CHANGED_SAME_CONTENT"], "diff_identity": IDENT},
     {"target": "diff:q01", "verdict": "expected", "by": "main", "run": "r"},                                            # old format
     {"target": "diff:q02", "verdict": "unclear", "by": "user", "run": "r", "classes": ["DOC_MISSING", "DOC_EXTRA"], "diff_identity": "stale"},
     {"target": "explain:ID_CHANGED_SAME_CONTENT", "verdict": "correct", "by": "main", "run": "r"}]

rows = link_rows(DIFF, EX, J)
a, b = rows["q01"]
check("1 same comparison, same classes: current; links = the explanation's USED source only, candidates named apart",
      a["status"] == "current" and a["evidence_links"][0]["pairing"] == "this"
      and [x["tag"] for x in a["evidence_links"][0]["used"]] == ["S1"] and [x["tag"] for x in a["evidence_links"][0]["candidates"]] == ["S2"],
      f"status={a['status']} ev={a['evidence_links']}")
check("2 entry without identity: past (기록 없음), no links, classes shown from the current row for reading only",
      b["status"] == "past" and b["why"] == "identity-missing" and b["evidence_links"] == [] and b["classes"] == ["ID_CHANGED_SAME_CONTENT"] and b["classes_from"] == "current")
c = rows["q02"][0]
check("3 entry recorded on a different comparison: past, no links", c["status"] == "past" and c["why"] == "identity-differs" and c["evidence_links"] == [])
check("3b the entry's own evidence (tier label) is preserved", not isinstance(a.get("evidence"), list))
check("4 explain: targets are not diff-row judgments", set(rows) == {"q01", "q02"})
rows2 = link_rows(None, None, J)
check("5 no diff/explanation (stopped check): entries listed as past, nothing linked",
      all(j["status"] == "past" for js in rows2.values() for j in js) and rows2["q01"][0]["why"] == "no-comparison")

# --- the coordinator's counterexample: different comparison, current explanation has a different source
J2 = [{"target": "diff:q01", "run": "r", "diff_identity": "different-old-comparison", "classes": ["DOC_MISSING"], "by": "user", "verdict": "problem"}]
D2 = {"before": DIFF["before"], "after": DIFF["after"], "global": [], "queries": [{"id": "q01", "question": "a", "classes": ["DOC_MISSING"], "details": []}]}
E2 = {"diff_identity": diff_identity(D2), "explanations": [{"class": "DOC_MISSING", "text": "fixture [S1]", "sources": [{"tag": "S1", "heading": "CURRENT DIFFERENT SOURCE"}]}]}
r2 = link_rows(D2, E2, J2)["q01"][0]
cj2 = class_judgments(D2, J2)
check("7 different comparison: not linked to the current S1 and not counted as a current judgment of this class",
      r2["status"] == "past" and r2["evidence_links"] == [] and cj2["DOC_MISSING"]["problem"] == 0 and cj2["DOC_MISSING"]["human"] == 0 and cj2["DOC_MISSING"]["past"] == 1,
      f"status={r2['status']} cj={cj2}")
# recorded classes disagree with the current row (same identity cannot happen then, but a tampered/edited entry can)
J3 = [{"target": "diff:q01", "run": "r", "diff_identity": IDENT, "classes": ["DOC_MISSING"], "by": "user", "verdict": "problem"}]
r3 = link_rows(DIFF, EX, J3)["q01"][0]
check("8 identity matches but recorded classes differ from the row: unconfirmed/past, no links", r3["status"] == "past" and r3["why"] == "classes-differ" and r3["evidence_links"] == [])
J4 = [{"target": "diff:q99", "run": "r", "diff_identity": IDENT, "classes": ["ID_CHANGED_SAME_CONTENT"], "by": "user", "verdict": "expected"}]
r4 = link_rows(DIFF, EX, J4)["q99"][0]
check("9 row no longer in the current comparison: past", r4["status"] == "past" and r4["why"] == "row-missing")

# --- explanation <-> comparison pairing and citation marks
check("10 explanation with matching provenance: pairing 'this'", explain_pairing(DIFF, EX) == "this")
check("10b explanation without provenance (old format): 'unknown', never assumed to be this comparison's", explain_pairing(DIFF, {"explanations": []}) == "unknown")
check("10c explanation of another comparison: 'other'", explain_pairing(DIFF, dict(EX, diff_identity="x")) == "other")
sb = sources_by_class({"explanations": [{"class": "C", "text": "no marks at all", "sources": [{"tag": "S1", "heading": "h"}]}]})
check("11 explanation without any [S] mark: used=[], candidates listed, marks=False", sb["C"]["used"] == [] and len(sb["C"]["candidates"]) == 1 and sb["C"]["marks"] is False)
EXU = {"explanations": [{"class": "ID_CHANGED_SAME_CONTENT", "text": "fixture [S1]", "sources": [{"tag": "S1", "heading": "h"}]}]}  # no provenance
ru = link_rows(DIFF, EXU, [J[0]])["q01"][0]
check("12 current judgment but the explanation's pairing is unknown: links carry pairing='unknown' (참고), not 'this'",
      ru["status"] == "current" and ru["evidence_links"][0]["pairing"] == "unknown")
ro = link_rows(DIFF, dict(EX, diff_identity="x"), [J[0]])["q01"][0]
check("12b explanation of another comparison: no links even for a current judgment", ro["status"] == "current" and ro["evidence_links"] == [])

cj = class_judgments(DIFF, J)
check("6 per class: only current judgments counted; past ones counted apart",
      cj["ID_CHANGED_SAME_CONTENT"] == {"expected": 0, "problem": 1, "unclear": 0, "human": 1, "qids": ["q01"], "past": 1}
      and cj["DOC_MISSING"]["past"] == 1 and cj["DOC_MISSING"]["unclear"] == 0, str(cj))
# --- page-top summary uses the same current/past rule
sc = summary_counts(["q01"], link_rows(D2, E2, J2))
check("13 counterexample: one row, judgment from another comparison -> 사람0 AI0 미판정1 (과거 1)", sc == {"human": 0, "ai": 0, "unjudged": 1, "rows": 1, "past": 1}, str(sc))
sc = summary_counts(["q01", "q02", "q03"], link_rows(DIFF, EX, J))
check("14 normal current judgment counts; old-format and other-comparison entries do not; rows stay the denominator",
      sc == {"human": 1, "ai": 0, "unjudged": 2, "rows": 3, "past": 2}, str(sc))
print("failures:", len(fails)); sys.exit(1 if fails else 0)
