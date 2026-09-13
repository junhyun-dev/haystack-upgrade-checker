# 업그레이드 점검 도우미 (Haystack 2.31 → 3.x)

> 이 저장소는 개발 저장소의 **공개용 사본**(기준 커밋 `9798c40`에 공개 사본 준비 커밋 `0a01c91`의 두 수정 — 새 체크아웃의 runtime 디렉터리 생성, 검사의 환경 목록 대체물 — 을 더한 상태, 2026-09-13)입니다. 개인 학습·포트폴리오 목적으로 만든 로컬 도구이며,
> 회사 배포·실사용자·매출은 없습니다. 이 사본에 들어 있는 실행 결과는 전부 **합성 자료**입니다(아래 "재현" 참고).

## 무엇을 하는가

Haystack 파이프라인을 2.31에서 3.x로 올리는 개발자가, **같은 문서·같은 질문**을 두 버전으로 실행해 검색 결과가 조용히 달라졌는지 표로 보고,
달라진 이유를 원문(MIGRATION.md) 인용과 함께 읽고, 행마다 "예상됨/문제/불명확"을 남기고, 멈춘 점검을 안전하게 이어가는 브라우저 흐름입니다.
`http://127.0.0.1:8090` 한 화면에서 끝나며 모든 것이 로컬(CPU)에서 돕니다.

## 원본 OSS와 자체 구현의 구분

| 구분 | 무엇 | 어디 |
|---|---|---|
| 재사용(원본 그대로) | **Open WebUI** 0.11.3 — 문서 지식 저장소·검색 API·채팅·인용 표시 (브랜딩·라이선스 보존; 이 사본에는 포함하지 않음) | `scripts/serve.sh`, `config/openwebui.env` |
| 재사용 | **llama.cpp** + Qwen3-4B(로컬 추론), **Haystack** 2.31.0 / 3.1.1(두 venv), Haystack 공식 docs·MIGRATION.md(Apache-2.0) | `scripts/`, `corpus/` |
| 자기 구현 | 두 버전 실행 캡처(`run_bundle.py`) → 비교·분류(`diff_bundles.py`) → 원문 인용 강제 설명과 비인용 계수(`explain.py`) → 신고 고정(`reports.py`) | `slice/regression/` |
| 자기 구현 | 점검 상태 요약(`diff_summary.py`), 중단·복구 규칙(`resume_plan.py`), 진행 단계 기록(`step_plan.py`), 판정↔비교↔근거 연결(`judgment_link.py`) | `slice/` |
| 자기 구현 | 브라우저 흐름(목록·시작·진행·차이·근거·판정·중단·이어서 진행·재실행), 검수 모드 | `app/`(FastAPI) |
| 자기 변경(원본 최소 수정, 기본 꺼짐 플래그) | Open WebUI 검색 결과의 파일 단위 중복 제거 | `patches/0001-rag-dedup-by-file.patch` (+ 원본 라이선스 `patches/OPEN-WEBUI-LICENSE`) |

Haystack·Open WebUI·llama.cpp는 이 프로젝트의 구현이 아닙니다. 이 프로젝트가 만든 것은 그 위의 **비교·판정·복구·검수 흐름**입니다.

## 한 완성 장면 (이 사본으로 그대로 볼 수 있음)

1. 목록에서 `synthetic-done`을 열면 3개 질문의 전/후 결과와 등급이 보입니다 — 한 행은 "ID만 변경", 한 행은 "동일", 한 행은 "변화(문서 교체)".
   첫 줄은 **"일부만 비교됨"**입니다: dev 질문 세트 7개 중 합성 자료는 3개뿐이라 앱이 그렇게 말하는 것이 맞습니다(빠진 행을 완료로 꾸미지 않는다).
2. 행의 **판정** 폼으로 "예상됨/문제/불명확"을 남기면, 그 판정 옆에 "이 비교의 판정 · 분류 … · 설명이 인용한 절 [S1] …"이 붙고, [S1]을 누르면 MIGRATION.md의 해당 절이 열립니다.
   설명 블록에는 "이 비교에서 이 분류의 행 판정: 예상됨 n · 문제 n …"이 나타납니다.
3. `synthetic-stopped`(설명 단계에서 중단)를 열면 **"이미 남은 결과"** 표가 산출물마다 "가져옴/다시 실행"과 **이유**를 보여 줍니다.
   이 사본에는 문서 묶음이 없고 합성 질문이 3개뿐이므로 bundle은 "지금 문서 묶음의 내용을 확인하지 못했다; 질문 세트가 그때와 다르다"로 가져오지 않고, 비교는 언제나 다시 계산한다고 적힙니다.
   그래서 "이어서 진행" 단추가 없는 것이 **의도된 동작**입니다(증명 못 하면 가져오지 않는다). 설명 생성을 켠 이 점검을 검수 모드에서 재실행하면 제출 단계에서 거부되어 실패로 기록됩니다.
4. 목록으로 돌아오면 끝나지 않은 행에 "3/4에서 중단됨 · 설명 생성", "2/4에서 실패 · 비교"처럼 위치가 적혀 있고, 행마다 할 수 있는 행동만 링크됩니다.

## 실제로 선택·교정한 이유 (두 가지)

**1. "중단"은 무엇을 약속하는가.** 처음 구현은 중단 뒤 "사용자가 중단함"만 적고 결과 화면이 부분 파일을 정상 결과처럼 요약했습니다.
총괄 검토가 반례를 냈습니다: 중단 정리 중인 점검이 "ID만 변경"으로 읽히고, 취소 요청과 프로세스 등록 사이의 틈에서 자식이 살아남을 수 있었습니다.
교정: 상태를 `cancelling → cancelled/interrupted`로 나누고 결과 요약은 **STOPPED**(판정하지 않음)로 고정, 종료 신호는 그 단계의 프로세스 그룹에만 보내고
그룹이 비었는지 확인한 범위(`stop_scope`)만 화면에 적습니다. 그 범위가 확인되지 않은 점검의 산출물은 **다음 점검이 가져오지 않습니다**.
(`eval/test_cancel_boundary.py`, `eval/test_resume_plan.py`)

**2. 판정은 어느 비교에 대한 것인가.** 행 판정을 설명 근거와 잇는 첫 구현은 분류 라벨만 같으면 옛 판정을 현재 설명의 후보 근거와 붙이고 현재 집계에 셌습니다.
총괄이 순수 함수로 반례를 재현했습니다(다른 비교에서 한 판정이 현재 S1과 연결되고 사람 1로 집계됨).
교정: 판정에 비교의 내용 식별자(`diff_identity`)와 행의 분류를 기록하고, **식별자·행·분류가 모두 지금과 같을 때만** "이 비교의 판정"으로 연결·집계합니다.
아니면 이유와 함께 "과거·미확인"으로 남기고 세지 않습니다. 설명의 `sources`는 검색기의 후보 목록이고 본문의 `[S번호]`만 실제 인용으로 표시합니다.
근거 링크는 "지금 MIGRATION.md의 해당 절"을 열지 판정 당시 스냅샷이 아니라고 화면에 적었습니다. (`eval/test_judgment_link.py`)

## AI가 한 일과 사람의 역할

- **AI(Claude Code, "Main")**: 요구를 장면으로 구체화, 설계·구현·검사 작성, 합성 자료로 직접 검수, README(정본) 기록, Git 커밋.
- **Codex 총괄 AI**: 각 결과를 코드·화면과 대조해 **반례**를 재현하고 되돌려 보냈습니다. 위 두 교정과 아래 조건 위반 기록이 그 결과입니다.
- **사람(사용자)**: 목표와 승인 범위(무료·로컬·비공개·모델 다운로드 승인)를 정하고 방향을 골랐습니다.
- 주장하지 않는 것: 실제 사용자의 사용 만족, 사람이 남긴 제품 내 판정(`by: user`)의 존재, 이 코드를 사람이 직접 작성·검수했다는 것.
- **검수 조건 위반 기록**: 개발 중 "모델 호출 0" 조건의 검수에서 세 번 로컬 모델 서버가 켜졌고, 그중 두 차례에는 각각 추론 1건이 실행됐습니다(체크박스 기본값 오류, 단위 검사가 서버 자동 기동 경로를 막지 못함,
  화면 검수 스크립트가 설명 켠 합성 점검을 재실행). 그래서 **검수 모드**(`VERIFY_MODE=1`, `scripts/app_server.sh start-verify`)를 만들었습니다: 그 앱 인스턴스는 모델 서버 시작·추론·검색 서비스 호출을
  호출 직전 지점에서 거부하고, 시작 명령은 PID의 환경·8090 listener·`/health`가 모두 맞을 때만 "confirmed"를 돌려줍니다.

## 재현

```bash
python3 -m venv .venv-app && .venv-app/bin/pip install -r requirements-app.txt
python3 examples/make_synthetic_runs.py          # 합성 점검 3개를 runtime/eval/runs 에 씀 (모델·문서·서버 불필요)
./scripts/app_server.sh start-verify              # 검수 모드: 모델 서버 시작·추론·검색 호출을 하지 않음
# http://127.0.0.1:8090  →  synthetic-done / synthetic-stopped / synthetic-failed
./scripts/app_server.sh stop

python3 eval/test_diff_summary.py                 # 순수 검사 (python3만)
python3 eval/test_resume_plan.py
python3 eval/test_judgment_link.py
.venv-app/bin/python eval/test_step_plan.py       # 앱 모듈을 읽는 검사 (실행 경계는 모두 대체물)
.venv-app/bin/python eval/test_list_scene.py
.venv-app/bin/python eval/test_verify_boundary.py
.venv-app/bin/python eval/test_cancel_boundary.py
.venv-app/bin/python eval/test_resume_start.py
```

이 사본에서 **확인한 범위**: 위 검사 8개가 통과하고, 검수 모드 앱에서 합성 점검 3개의 화면(목록·상세·판정·이어서 진행 표·근거 절)이 열립니다.
**실행하지 않은 범위**: 실제 Haystack 두 환경 설치(`scripts/setup_haystack_envs.sh`), 문서 묶음 내려받기(`scripts/fetch_corpus.sh`), Open WebUI·llama.cpp·모델(`scripts/serve.sh`, `scripts/fetch_models.sh`, `scripts/llm_server.sh`).
그 경로는 스크립트로 남겨 두었고, 실제 비교·설명 생성은 그 환경이 있어야 돕니다. 검색 기준선(`eval/retrieval_eval.py`)은 Open WebUI 토큰(`runtime/.token`)이 필요합니다.

## 한계

- 사람의 실제 사용 감각·효용은 확인되지 않았습니다. 판정과 원문의 연결은 "그 분류의 설명이 인용한 절"이지 판정자가 고른 절이 아닙니다.
- 복구의 산출물 대조는 우리가 쓴 파일들 사이의 **일관성 검사**이지 위조 방지가 아닙니다.
- 설명 생성은 로컬 4B 모델의 출력이며 원문 인용을 강제하지만, 비인용 문장·잘림을 세어 보여 줄 뿐 정답을 보장하지 않습니다.

## 자료와 라이선스

- `corpus/MIGRATION.md`: deepset-ai/haystack 저장소의 문서(Apache-2.0, `corpus/haystack-LICENSE`, 커밋 `corpus/haystack-docs-src.commit`). 버전별 docs 본문은 포함하지 않았습니다(`scripts/fetch_corpus.sh`).
- `patches/`: Open WebUI에 대한 최소 패치. 원본 라이선스는 `patches/OPEN-WEBUI-LICENSE`.
- `eval/questions.yaml`: 이 프로젝트가 쓴 질문 세트(모델이 만든 답 없음). `eval/feedback.yaml`: 사본에서는 비어 있음(개발 중 신고 파일은 포함하지 않음).
- `examples/make_synthetic_runs.py`가 쓰는 실행 결과는 AI가 작성한 고정 합성 자료이며, 그 안의 "설명"은 모델 출력이 아닌 고정 문구입니다.
- 자체 코드에는 별도 공개 라이선스를 부여하지 않았습니다. 업스트림 자료의 라이선스는 각 자료에 적용됩니다.
