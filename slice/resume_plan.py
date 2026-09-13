"""What of a stopped/failed check can be carried into a new check, and why not.

Pure Python over the stored files. Nothing here writes, runs, or judges. The rule is conservative: an artifact may be
carried over only when the stored file itself proves it matches the conditions the new check will run under.

Carry-over is always into a NEW check (new id, new directory). A past result is never overwritten and never promoted to
a normal completion; the new check records what it reused and from where.

Blocked wholesale when the old check cannot be trusted to be finished writing:
  interrupted            the app lost the worker; whether a process was still writing is unknown
  cancelling / running   not finished yet
  cancelled with the step's process group not confirmed empty
"""
import os

ARTIFACTS = ["bundle-before", "bundle-after", "diff", "explain", "retrieval-dev", "retrieval-eval"]
TERMINAL_REUSABLE_STATUS = ("failed", "cancelled", "done")


def _bundle_names(d, side):
    """App runs write bundle-before/after.json; shell runs wrote bundle-hs231/hs31.json."""
    legacy = {"before": "bundle-hs231.json", "after": "bundle-hs31.json"}[side]
    for name in (f"bundle-{side}.json", legacy):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def _load(path, loader):
    try:
        return loader(path), None
    except Exception as e:
        return None, f"파일을 읽지 못했다({type(e).__name__}): 중간에 잘렸을 수 있다"


def blocked_reason(meta):
    st = meta.get("status")
    if st in ("queued", "running", "cancelling"):
        return "아직 끝나지 않은 점검이다. 정리가 끝난 뒤에 판단한다."
    if st == "interrupted":
        return "앱이 끊긴 실행이라 그때 돌던 프로세스가 파일을 쓰는 중이었는지 확인할 수 없다. 남은 결과를 가져오지 않는다."
    if st == "cancelled" and meta.get("stop_scope") != "empty":
        return "중단 시 그 단계의 프로세스 그룹이 비었는지 확인하지 못했다. 남은 결과를 가져오지 않는다."
    if st not in TERMINAL_REUSABLE_STATUS:
        return f"알 수 없는 실행 상태({st})."
    return None


def plan(run_path, meta, env_versions, expected_questions, json_loader, ctx):
    """Return {"blocked": reason|None, "artifacts": [{name, exists, reuse, why}], "reuse": [names]}.

    env_versions      {"hs231": "2.31.0", ...} as the app currently reports
    expected_questions [(id, question text), ...] for this check's split, from the current question set
    ctx                what the current system says, supplied by the caller:
                       corpus_fingerprint  the corpus fingerprint now (producer's own computation), None if unavailable
                       pipeline            the pipeline settings the producer builds today (without top_k)
                       diff_identity_of    (bundle_before, bundle_after) -> identity of the comparison they produce now
                       section_hashes      {heading: sha1(body)} of the migration guide now
                       pins_now            class -> [headings] the reports would pin now

    What is compared is written next to each artifact. These are consistency checks over files this app produced, not
    cryptographic provenance: they catch an edited question, a moved corpus, a changed version and artifacts that do not
    belong together, and they refuse anything they cannot check.
    """
    c = meta.get("conditions") or {}
    corpus_fingerprint = ctx.get("corpus_fingerprint")
    out = {"blocked": blocked_reason(meta), "artifacts": [], "reuse": []}  # not "items": a dict key named items shadows dict.items in templates
    corpus_suffix = os.path.join("versioned_docs", c.get("corpus", ""))
    bundles = {}

    def add(name, exists, reuse, why):
        out["artifacts"].append({"name": name, "exists": exists, "reuse": reuse, "why": why})
        if reuse:
            out["reuse"].append(name)

    for side in ("before", "after"):
        p = _bundle_names(run_path, side)
        name = f"bundle-{side}"
        if not p:
            add(name, False, False, "없다 (이 단계까지 가지 못했다)")
            continue
        b, err = _load(p, json_loader)
        if err:
            add(name, True, False, err)
            continue
        label = c.get(side)
        reasons = []
        if b.get("error"):
            reasons.append("그때 실행이 오류로 끝났다")
        if b.get("label") != label:
            reasons.append(f"환경이 다르다({b.get('label')} ≠ {label})")
        if env_versions.get(label) and b.get("haystack") != env_versions.get(label):
            reasons.append(f"haystack 버전이 지금과 다르다({b.get('haystack')} ≠ {env_versions.get(label)})")
        if not str(b.get("corpus", {}).get("dir", "")).endswith(corpus_suffix):
            reasons.append("문서 묶음이 다르다")
        fp = b.get("corpus", {}).get("fingerprint")
        if corpus_fingerprint is None:
            reasons.append("지금 문서 묶음의 내용을 확인하지 못했다")
        elif fp != corpus_fingerprint:
            reasons.append("문서 묶음 내용이 그때와 다르다")
        if b.get("split") is not None and b.get("split") != c.get("split"):
            reasons.append(f"질문 분할이 다르다({b.get('split')} ≠ {c.get('split')})")
        pipe = dict(b.get("pipeline") or {})
        if pipe.pop("top_k", None) != c.get("k"):
            reasons.append(f"top-k가 다르다({b.get('pipeline', {}).get('top_k')} ≠ {c.get('k')})")
        if ctx.get("pipeline") is not None and pipe != ctx["pipeline"]:
            reasons.append("파이프라인 설정이 지금 producer가 쓰는 것과 다르다")
        # the recorded questions are the stronger evidence: the ids confirm the split even in bundles written before
        # run_bundle.py recorded one, and the stored text catches a question edited under the same id
        asked = [(q.get("id"), q.get("question")) for q in b.get("queries", [])]
        if expected_questions is not None:
            if [i for i, _ in asked] != [i for i, _ in expected_questions]:
                reasons.append("질문 세트가 그때와 다르다")
            elif asked != list(expected_questions):
                reasons.append("질문 내용이 그때와 다르다(같은 id, 다른 본문)")
        ok = not reasons
        if ok:
            bundles[side] = b
        add(name, True, ok, "대조한 것이 모두 같다: 환경 라벨·haystack 버전·문서 묶음 내용(fingerprint)·파이프라인 설정·top-k·질문 id와 본문" if ok else "; ".join(reasons))

    # the comparison is cheap and deterministic, so it is never carried: the new check recomputes it from the bundles
    # it carried. That also gives us the only sound way to judge an old explanation.
    dp = os.path.join(run_path, "diff.json")
    add("diff", os.path.exists(dp), False, "가져오지 않고 가져온 bundle로 다시 계산한다 (싸고 결정적이며, 저장된 비교가 그 bundle의 결과인지 따로 증명할 필요가 없다)")
    recomputed = None
    if len(bundles) == 2 and ctx.get("diff_identity_of"):
        try:
            recomputed = ctx["diff_identity_of"](bundles["before"], bundles["after"])
        except Exception:
            recomputed = None

    ep = os.path.join(run_path, "explain.json")
    if not os.path.exists(ep):
        add("explain", False, False, "없다" + ("" if c.get("explain") else " (이 점검은 설명 생성을 끄고 시작했다)"))
    else:
        e, err = _load(ep, json_loader)
        if err:
            add("explain", True, False, err)
        elif len(bundles) < 2:
            add("explain", True, False, "두 bundle을 가져오지 못해 그 위의 설명도 가져오지 않는다")
        elif not e.get("diff_identity"):
            add("explain", True, False, "어떤 비교로 만들어졌는지 기록이 없는 옛 형식이라 지금 비교와 대응하는지 확인할 수 없다")
        elif recomputed is None:
            add("explain", True, False, "가져온 bundle로 비교를 다시 계산하지 못해 대응을 확인할 수 없다")
        elif e.get("diff_identity") != recomputed:
            add("explain", True, False, "가져온 bundle로 다시 계산한 비교와 다른 비교에 대한 설명이다")
        else:
            why = []
            sect = ctx.get("section_hashes") or {}
            for x in e.get("explanations", []):
                for heading, h in (x.get("source_hashes") or {}).items():
                    if sect.get(heading) != h:
                        why.append(f"설명이 인용한 원문 절이 지금과 다르다({heading[:40]})")
                        break
                if not x.get("source_hashes"):
                    why.append("어떤 원문 절을 인용했는지 기록이 없다")
                if ctx.get("pins_now") and x.get("class"):
                    now = sorted(ctx["pins_now"](x["class"]))
                    then = sorted(p.get("heading") for p in (x.get("pinned") or []))
                    if now != then:
                        why.append("신고로 고정될 근거가 그때와 달라 다시 만들어야 한다")
                if why:
                    break
            if why:
                add("explain", True, False, "; ".join(why))
            else:
                add("explain", True, True, "가져온 bundle로 다시 계산한 비교와 같은 비교에 대한 설명이고, 인용한 원문 절과 고정된 신고도 그대로다 "
                                           "(다시 만들면 로컬 모델을 한 번 더 호출한다)")

    for split in ("dev", "eval"):
        name = f"retrieval-{split}"
        exists = os.path.exists(os.path.join(run_path, f"{name}.json"))
        add(name, exists, False, "그때의 Open WebUI 색인을 잰 값이라 지금 값이 아니다. 가져오지 않고 다시 잰다" if exists else "없다")

    if out["blocked"]:
        for it in out["artifacts"]:
            it["reuse"] = False
        out["reuse"] = []
    return out
