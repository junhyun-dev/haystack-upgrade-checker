"""Evidence-level reports -> what the next explanation must include. Pure Python (no model, no haystack).

A report in eval/feedback.yaml with target `explain:<CLASS>` and verdict `wrong` or `missed` names the evidence the
person expected (a MIGRATION.md heading, quoted loosely). On the next run explain.py pins that section as an extra source
for that class and labels it; evidence that matches no heading is surfaced as unmatched, never silently dropped.
Reports are read only; nothing here changes their verdict.
"""
import os, re
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FEEDBACK = os.path.join(ROOT, "eval", "feedback.yaml")
ACTIONABLE = ("wrong", "missed")


def split_sections(text, min_len=0):
    """Split Markdown into (heading, body) sections. Lines starting with '#' inside fenced code blocks are not headings."""
    secs, title, cur, in_fence = [], "preamble", [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if line.startswith("#") and not in_fence:
            if cur:
                secs.append((title, "\n".join(cur).strip()))
            title, cur = line.lstrip("#").strip(), [line]
        else:
            cur.append(line)
    if cur:
        secs.append((title, "\n".join(cur).strip()))
    return [(t, b) for t, b in secs if len(b) >= min_len]


def load_reports(path=None):
    p = path or FEEDBACK
    try:
        return yaml.safe_load(open(p, encoding="utf-8")) or []
    except FileNotFoundError:
        return []


def _norm(s):
    s = re.sub(r"\[S\d+\]", " ", s or "")
    s = re.sub(r"MIGRATION\.md\s*[—-]\s*", " ", s)
    s = s.replace("`", "").lower()
    return re.sub(r"\s+", " ", s).strip()


def match_heading(evidence, headings):
    """Return the heading the evidence refers to, or None. Loose: normalized substring either way, longest heading wins."""
    ev = _norm(evidence)
    if not ev:
        return None
    best = None
    for h in headings:
        hn = _norm(h)
        if hn and (hn in ev or ev in hn):
            if best is None or len(hn) > len(_norm(best)):
                best = h
    if best:
        return best
    # paraphrase fallback: most of the evidence's content words appear in one heading
    ev_tokens = {t for t in re.findall(r"[a-z0-9_.]{3,}", ev)}
    if len(ev_tokens) < 2:
        return None
    best, best_ratio = None, 0.0
    for h in headings:
        h_tokens = {t for t in re.findall(r"[a-z0-9_.]{3,}", _norm(h))}
        ratio = len(ev_tokens & h_tokens) / len(ev_tokens)
        if ratio >= 0.6 and ratio > best_ratio:
            best, best_ratio = h, ratio
    return best


def pins_for_class(cls, headings, reports=None, feedback_path=None):
    """Split actionable reports for one class into pinned (heading found) and unmatched."""
    reports = load_reports(feedback_path) if reports is None else reports
    pinned, unmatched, seen = [], [], set()
    for r in reports:
        if r.get("target") != f"explain:{cls}" or r.get("verdict") not in ACTIONABLE:
            continue
        h = match_heading(r.get("evidence", ""), headings)
        item = {"target": r.get("target"), "verdict": r.get("verdict"), "evidence": r.get("evidence", ""),
                "note": r.get("note", ""), "by": r.get("by"), "run": r.get("run")}
        if h and h not in seen:
            seen.add(h); pinned.append({"heading": h, "report": item})
        elif not h:
            unmatched.append(item)
    return pinned, unmatched
