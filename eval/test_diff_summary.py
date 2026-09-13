#!/usr/bin/env python3
"""Independent expectations for slice/diff_summary.py over project-owned synthetic fixtures (eval/fixtures/diff-summary/*.json).
Each fixture states the expected state/counts/headline phrases BEFORE the summary is computed. Run: python3 eval/test_diff_summary.py"""
import glob, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "slice"))
from diff_summary import summarize

fails = 0
for path in sorted(glob.glob(os.path.join(ROOT, "eval", "fixtures", "diff-summary", "*.json"))):
    c = json.load(open(path, encoding="utf-8")); e = c["expect"]
    s = summarize(c["diff"], c["meta"], c.get("expected_ids"))
    problems = []
    if s["state"] != e["state"]:
        problems.append(f"state {s['state']} != {e['state']}")
    if "counts" in e and s["counts"] != e["counts"]:
        problems.append(f"counts {s['counts']} != {e['counts']}")
    for t in e.get("headline_contains", []):
        if t not in s["headline"]:
            problems.append(f"headline missing '{t}'")
    for t in e.get("headline_not_contains", []):
        if t in s["headline"]:
            problems.append(f"headline must not contain '{t}'")
    for t in e.get("notes_contains", []):
        if not any(t in n for n in s["notes"]):
            problems.append(f"notes missing '{t}'")
    name = os.path.basename(path)
    if problems:
        fails += 1; print("FAIL", name, "|", "; ".join(problems)); print("     headline:", s["headline"])
    else:
        print("ok  ", name, "|", s["state"], "|", s["headline"][:90])
print("fixtures:", len(glob.glob(os.path.join(ROOT, "eval", "fixtures", "diff-summary", "*.json"))), "failures:", fails)
sys.exit(1 if fails else 0)
