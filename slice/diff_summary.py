"""Axis A summary: what changed inside ONE check (library before/after), what cannot be judged, and how far "same" goes.

Pure Python over diff.json (slice/regression/diff_bundles.py) + run meta + the expected question set. Nothing here re-runs
anything or changes stored JSON. The filter only narrows display; counts are always over the full row set.

Row tiers (priority when a question carries several classes):
  undet   QUERY_MISSING_AFTER, or any class this module does not know (named explicitly, never silently dropped)
  changed RANK_CHANGED, SCORE_CHANGED, DOC_MISSING, DOC_EXTRA     (content/rank/score/set of the top-k changed)
  idonly  ID_CHANGED_SAME_CONTENT only                              (same content hash, rank and score; Document.id differs)
  same    IDENTICAL only
Run states (headline picks exactly one):
  NO_RESULT     queued/running/cancelling/failed, or     GLOBAL_ERROR  RUNTIME_ERROR or CORPUS_CHANGED in diff.global
                no diff.json                              EMPTY         diff has zero rows
  STOPPED       cancelled by the user, or interrupted     PARTIAL       expected questions missing, or undet rows > 0
                (app restarted): artifacts are partial
  CHANGED       changed rows > 0                          IDONLY        idonly > 0, changed 0, undet 0, scope complete
  ALL_SAME      every row same, scope complete
"""

CHANGED = {"RANK_CHANGED", "SCORE_CHANGED", "DOC_MISSING", "DOC_EXTRA"}
IDONLY = {"ID_CHANGED_SAME_CONTENT"}
SAME = {"IDENTICAL"}
UNDET = {"QUERY_MISSING_AFTER"}
KNOWN = CHANGED | IDONLY | SAME | UNDET
GLOBAL_BLOCKING = {"RUNTIME_ERROR", "CORPUS_CHANGED"}
GLOBAL_CONDITION = {"SPLIT_CHANGED", "PIPELINE_CONFIG_CHANGED"}
SCORE_EPS = 1e-6  # must match diff_bundles.EPS

TIER_LABEL = {"same": "동일", "idonly": "ID만 변경", "changed": "내용/순위/점수/집합 변화", "undet": "판정 불가"}
GUARANTEE = ("'같음'의 보장 범위: 상위 k개 결과의 내용 해시·순위·BM25 점수(허용 오차 {eps}) 일치, corpus fingerprint 동일 조건에서만. "
             "top-k 밖·다른 질문·다른 파이프라인 설정은 비교하지 않았다. 변화는 회귀/개선·안전·사용자 수용 판정이 아니다.")


def tier_of(classes):
    cs = set(classes or [])
    unknown = sorted(c for c in cs if c not in KNOWN)
    if unknown or (cs & UNDET):
        return "undet", unknown
    if cs & CHANGED:
        return "changed", []
    if cs & IDONLY:
        return "idonly", []
    if cs <= SAME and cs:
        return "same", []
    return "undet", ["(분류 없음)"]


def summarize(diff, meta=None, expected_ids=None):
    meta = meta or {}
    status = meta.get("status", "done")
    out = {"state": None, "headline": "", "notes": [], "counts": {"same": 0, "idonly": 0, "changed": 0, "undet": 0},
           "rows": {}, "unknown_classes": {}, "total_rows": 0, "expected_total": None, "missing_expected": [], "extra_rows": [],
           "global": [], "guarantee": GUARANTEE.format(eps=SCORE_EPS), "scope_complete": None}
    if status == "cancelling":
        # the cancel was requested but the step has not been confirmed finished: never judge, never claim completion
        out["state"] = "NO_RESULT"
        out["headline"] = (f"중단 요청됨 — 실행 중이던 단계({meta.get('step')})를 정리하는 중이다. "
                           "종료가 확인될 때까지 동일·변화를 판정하지 않는다.")
        return out
    if status in ("cancelled", "interrupted"):
        out["state"] = "STOPPED"
        scope = {"empty": " 그 단계의 프로세스 그룹이 비었음을 확인했다.", "remaining": " 종료 신호 뒤에도 그 그룹에 프로세스가 남아 있었다(로그 참조).",
                 "unknown": " 남은 프로세스 여부는 확인하지 못했다."}.get(meta.get("stop_scope"), "")
        why = ("사용자가 중단했다." + scope if status == "cancelled"
               else "앱이 다시 시작되어 작업 스레드가 사라졌다. 그때 돌던 프로세스가 남아 있는지는 앱이 확인하지 못한다.")
        where = f" 중단 시점: {meta.get('step')}." if meta.get("step") else ""
        rows_n = len((diff or {}).get("queries") or [])
        out["total_rows"] = rows_n
        out["headline"] = (f"중단된 점검 — {why}{where} 여기까지 만들어진 결과는 부분이며 동일·변화를 판정하지 않는다." +
                           (f" 행 {rows_n}개는 참고용으로만 표시한다." if rows_n else " 비교 결과 파일은 없다."))
        return out
    if diff is None or status in ("queued", "running", "failed"):
        out["state"] = "NO_RESULT"
        out["headline"] = f"비교 결과 없음 — 실행 상태 {status}" + (f": {meta.get('error')}" if meta.get("error") else "") + \
            (". diff.json이 없다." if diff is None and status == "done" else "")
        return out
    g = list(diff.get("global") or [])
    out["global"] = g
    rows = list(diff.get("queries") or [])
    out["total_rows"] = len(rows)
    ids = [q.get("id") for q in rows]
    if expected_ids is not None:
        exp = list(expected_ids)
        out["expected_total"] = len(exp)
        out["missing_expected"] = [e for e in exp if e not in ids]
        out["extra_rows"] = [i for i in ids if i not in exp]
        out["scope_complete"] = not out["missing_expected"]
    # tiers per row (always computed; the headline decides whether they may be claimed)
    for q in rows:
        t, unknown = tier_of(q.get("classes"))
        out["rows"][q.get("id")] = t
        out["counts"][t] += 1
        for u in unknown:
            out["unknown_classes"].setdefault(u, []).append(q.get("id"))
    c = out["counts"]
    blocking = [x for x in g if x in GLOBAL_BLOCKING]
    conditions = [x for x in g if x in GLOBAL_CONDITION]
    unknown_global = [x for x in g if x not in GLOBAL_BLOCKING and x not in GLOBAL_CONDITION]
    if blocking or unknown_global:
        out["state"] = "GLOBAL_ERROR"
        why = {"RUNTIME_ERROR": "한쪽 실행이 실패", "CORPUS_CHANGED": "두 실행의 corpus가 달라 차이를 버전에 귀속할 수 없음"}
        out["headline"] = "실행 수준 문제로 질문별 판정을 집계하지 않음 — " + "; ".join(why.get(x, f"알 수 없는 전역 표시 {x}") for x in blocking + unknown_global) + \
            f". 행 {len(rows)}개는 참고용으로만 표시한다."
        return out
    if conditions:
        out["notes"].append("조건 변화 " + ", ".join(conditions) + " (청크 수 또는 파이프라인 설정이 달라짐): 아래 행 분류는 그 영향을 포함한다.")
    scope_txt = ""
    if out["expected_total"] is not None:
        if out["missing_expected"]:
            miss = out["missing_expected"]
            shown = ", ".join(miss[:5]) + (f" 외 {len(miss) - 5}개" if len(miss) > 5 else "")
            scope_txt = f"예상 {out['expected_total']}개 중 {len(rows) - len(out['extra_rows'])}개만 비교됨(누락: {shown})"
        if out["extra_rows"]:
            out["notes"].append(f"예상 목록에 없는 행 {len(out['extra_rows'])}개: {', '.join(out['extra_rows'])}")
    if not rows:
        out["state"] = "EMPTY"
        out["headline"] = "비교할 질문 행이 없다(0행). 동일·변화를 판정하지 않는다." + (f" {scope_txt}." if scope_txt else "")
        return out
    counts_txt = f"동일 {c['same']} · ID만 변경 {c['idonly']} · 내용/순위/점수/집합 변화 {c['changed']} · 판정 불가 {c['undet']} (행 {len(rows)}개)"
    if out["unknown_classes"]:
        out["notes"].append("알 수 없는 분류(판정 불가로 셈): " + "; ".join(f"{k} → {', '.join(v)}" for k, v in out["unknown_classes"].items()))
    if c["undet"] > 0 or scope_txt:
        out["state"] = "PARTIAL"
        parts = []
        if scope_txt:
            parts.append(scope_txt)
        if c["undet"] > 0:
            parts.append(f"판정 불가 {c['undet']}개")
        out["headline"] = "일부만 비교됨 — " + ", ".join(parts) + f". 보이는 범위: {counts_txt}. 전체 동등성은 주장하지 않는다."
        return out
    if c["changed"] > 0:
        out["state"] = "CHANGED"
        out["headline"] = f"내용/순위/점수/집합이 달라진 질문 {c['changed']}개. {counts_txt}."
        return out
    if c["idonly"] > 0:
        out["state"] = "IDONLY"
        out["headline"] = f"비교한 {len(rows)}개 질문 전부에서 상위 결과의 내용·순위·점수는 같고, {c['idonly']}개는 문서 ID만 바뀌었다. {counts_txt}."
        return out
    out["state"] = "ALL_SAME"
    out["headline"] = f"비교한 {len(rows)}개 질문 모두 상위 결과가 동일(ID·내용·순위·점수). {counts_txt}."
    return out


def align_hits(before_hits, after_hits):
    """Side-by-side rows by rank with a per-row mark: same | idchanged | moved | onlybefore | onlyafter."""
    b = {h["content_sha1"]: h for h in before_hits}
    a = {h["content_sha1"]: h for h in after_hits}
    n = max(len(before_hits), len(after_hits))
    rows = []
    for i in range(n):
        hb = before_hits[i] if i < len(before_hits) else None
        ha = after_hits[i] if i < len(after_hits) else None
        mark = "same"
        if hb and ha and hb["content_sha1"] == ha["content_sha1"]:
            mark = "same" if hb["id"] == ha["id"] else "idchanged"
            if hb.get("score") is not None and ha.get("score") is not None and abs(hb["score"] - ha["score"]) > SCORE_EPS:
                mark = "scorechanged"
        else:
            mb = (hb["content_sha1"] in a) if hb else None
            ma = (ha["content_sha1"] in b) if ha else None
            mark = "moved" if (mb or ma) else ("onlybefore" if hb and not ha else "onlyafter" if ha and not hb else "moved")
            if hb and ha and not mb and not ma:
                mark = "replaced"
        rows.append({"rank": i + 1, "before": hb, "after": ha, "mark": mark})
    return rows
