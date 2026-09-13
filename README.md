# Haystack Upgrade Checker

Haystack 버전 변경 전후의 검색 결과를 비교하고, 변경 설명과 원문을 읽으며 행별 판정을 남기는 로컬 점검 도구입니다.
공개 사본에는 모델 없이 볼 수 있는 합성 점검 세 개를 제공합니다.

## 주요 기능

- 같은 질문의 버전별 검색 결과 비교
- 변경 설명, 인용한 원문, 행별 판정 연결
- 실행 상태와 진행 단계, 중단 및 남은 결과 확인
- 재사용 조건을 확인하는 복구 흐름
- 모델·검색 실행을 차단하는 시연용 검수 모드

현재 비교의 판정과 과거 기록을 구분합니다. 기존 기록을 보존하면서 지금 무엇을 확인했는지가 화면에서 읽히도록 구성했습니다.

## 모델 없이 시연하기

```bash
python3 -m venv .venv-app
.venv-app/bin/pip install -r requirements-app.txt
python3 examples/make_synthetic_runs.py
./scripts/app_server.sh start-verify
# http://127.0.0.1:8090
./scripts/app_server.sh stop
```

`synthetic-done`에서 비교 결과 → 판정 → 근거 링크를 따라갑니다.
`synthetic-stopped`에서는 남은 결과와 재사용할 수 없는 이유를 확인할 수 있습니다.
합성 자료는 실제 질문 세트의 일부만 포함하므로 "일부만 비교됨"으로 표시합니다.
이 사본에 문서 묶음과 두 버전 실행 환경은 포함하지 않아, 합성 점검에서 실제 이어서 실행까지 시연하지는 않습니다.

## 자체 구현과 업스트림

| 구분 | 내용 |
|---|---|
| 자체 구현 | 비교·판정·복구·진행 표시와 브라우저 화면 |
| 기반 제품 | Haystack 2.31.0 / 3.1.1, 선택적으로 Open WebUI·llama.cpp |
| 포함 자료 | 합성 fixture, Haystack MIGRATION 문서, Open WebUI 최소 패치와 해당 라이선스 |
| 별도 준비 | 실제 문서 묶음, 버전별 실행 환경, 모델과 서비스 |

AI와 요구사항·설계·구현·검증을 함께 진행했습니다. 개발 과정에서 상태 표시와 기록의 연결을 점검하고 보완했습니다.
실제 기업 운영이나 사용자 효용을 입증한 프로젝트는 아닙니다.

## 검사와 한계

```bash
python3 eval/test_diff_summary.py
python3 eval/test_resume_plan.py
python3 eval/test_judgment_link.py
.venv-app/bin/python eval/test_verify_boundary.py
```

공개 사본 준비 과정에서는 검사 파일 8개와 검수 모드의 합성 화면을 확인했습니다.
실제 모델·검색 환경의 새 설치 및 실행은 이 사본에서 하지 않았습니다.
복구와 판정 연결은 저장 기록의 일관성을 확인하며 인증·위조 방지나 설명의 정답을 보장하지 않습니다.

자체 코드에는 별도 공개 라이선스를 부여하지 않았습니다. 업스트림 자료는 `corpus/haystack-LICENSE`와 `patches/OPEN-WEBUI-LICENSE`를 따릅니다.
