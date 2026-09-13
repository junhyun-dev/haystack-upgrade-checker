#!/usr/bin/env python3
"""Before/after table for two runs produced by slice/run_all.sh, plus the status of evidence-level reports.
  python3 slice/compare_runs.py runtime/eval/runs/<before> runtime/eval/runs/<after>
"""
import json, os, sys, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(run, name):
    p = os.path.join(run, name)
    return json.load(open(p)) if os.path.exists(p) else None


def row(run):
    d = load(run, "diff.json") or {}; e = load(run, "explain.json") or {}
    r = {"run": os.path.basename(run), "git": (open(os.path.join(run, "git.txt")).read().strip() if os.path.exists(os.path.join(run, "git.txt")) else "")}
    r["classes"] = (d.get("summary") or {}).get("classes_by_query_count", {})
    ex = e.get("explanations", [])
    r["explanations"] = len(ex)
    r["ungrounded_sentences"] = sum(x.get("ungrounded", 0) for x in ex)
    r["cited_ratio"] = round(sum(x.get("cited", 0) for x in ex) / max(1, sum(x.get("sentences", 0) for x in ex)), 2) if ex else None
    r["explain_latency_s"] = round(sum(x.get("latency_s", 0) for x in ex), 1) if ex else None
    r["pinned_sources"] = sum(len(x.get("pinned", [])) for x in ex)
    try:
        fb = yaml.safe_load(open(os.path.join(ROOT, "eval", "feedback.yaml"))) or []
        rid = os.path.basename(run)
        r["diff_judgments_human"] = sum(1 for f in fb if f.get("run") == rid and str(f.get("target", "")).startswith("diff:") and f.get("by") == "user")
        r["diff_judgments_ai"] = sum(1 for f in fb if f.get("run") == rid and str(f.get("target", "")).startswith("diff:") and f.get("by") == "main")
    except Exception:
        r["diff_judgments_human"] = r["diff_judgments_ai"] = None
    for split in ("dev", "eval"):
        s = (load(run, f"retrieval-{split}.json") or {}).get("summary", {})
        r[f"recall@3_{split}"] = s.get("mean_recall"); r[f"trap_hits_{split}"] = s.get("trap_hits"); r[f"retrieval_errors_{split}"] = s.get("errors")
    return r


def main():
    before, after = sys.argv[1], sys.argv[2]
    a, b = row(before), row(after)
    keys = ["git", "classes", "diff_judgments_human", "diff_judgments_ai", "explanations", "cited_ratio", "ungrounded_sentences", "pinned_sources", "explain_latency_s",
            "recall@3_dev", "trap_hits_dev", "recall@3_eval", "trap_hits_eval", "retrieval_errors_dev", "retrieval_errors_eval"]
    print(f"{'metric':<24}{'before: ' + a['run']:<34}{'after: ' + b['run']:<34}changed")
    for k in keys:
        va, vb = a.get(k), b.get(k)
        print(f"{k:<24}{str(va):<34}{str(vb):<34}{'*' if va != vb else ''}")
    fb = yaml.safe_load(open(os.path.join(ROOT, "eval", "feedback.yaml"))) or []
    print(f"\nevidence-level reports: {len(fb)} (" + ", ".join(f"{x['target']}={x['verdict']}" for x in fb) + ")")
    print("A report is closed only when a person changes its verdict after the 'after' run; nothing here auto-closes it.")


if __name__ == "__main__":
    main()
