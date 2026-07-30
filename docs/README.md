# 문서 지도

문서는 역할이 하나씩만 있다. 같은 내용을 두 곳에 쓰지 않는다.

- `docs/` — 살아 있는 개발 문서. 코드와 함께 갱신한다.
- `reference/` — 참고 자료와 보관 산출물. 명세 원본, 폐기 문서, 완료된 업무 결과물.

## 1. 지금 무엇을 만들어야 하는가

| 문서 | 역할 |
|---|---|
| [VIBEOFFICE_IMPLEMENTATION_GUIDE.md](VIBEOFFICE_IMPLEMENTATION_GUIDE.md) | **작업 시작 시 1순위**. 원칙, 계층 분리, 부서 매핑, 스키마·API 추가안, 수직 슬라이스 순서, 게이트, 금지사항 |
| [VIBEOFFICE_GAP_ANALYSIS.md](VIBEOFFICE_GAP_ANALYSIS.md) | 구현됨 / 부분 구현 / 미구현 목록과 근거 파일 |
| [../reference/product-context/](../reference/product-context/) | 목표 제품 명세 원본(vibe_coding_office_context_pack_v3). 요약본을 따로 만들지 않는다 |
| [../reference/product-context/reference-output/](../reference/product-context/reference-output/) | H4 내보내기 정답 예시. 출고 산출물의 목표 형태 |
| [../reference/product-context/schemas/](../reference/product-context/schemas/) | blueprint · handoff · review-finding JSON Schema |

## 2. 현재 시스템은 어떻게 동작하는가

| 문서 | 역할 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 프로세스 구성, task/job 상태, 영속성, 워크스페이스 |
| [RUNTIME_HARDENING.md](RUNTIME_HARDENING.md) | 현재 런타임 동작 사실(세션·체크포인트·도구·권한·조사·완료 조건) |
| [RUNTIME_ROADMAP.md](RUNTIME_ROADMAP.md) | 런타임 P0/P1 완료 항목과 P2 수용 harness 계획 |

## 3. 조직·정책 명세 (v6.2 원본)

| 문서 | 역할 |
|---|---|
| [../reference/corporate-os/01-CORPORATE_OS_v6.2.md](../reference/corporate-os/01-CORPORATE_OS_v6.2.md) | 조직·정책·토큰 경제 본문 |
| [../reference/corporate-os/02-EMPLOYEE_REGISTRY_v6.2.md](../reference/corporate-os/02-EMPLOYEE_REGISTRY_v6.2.md) | 24명 직원 단일 진실 공급원 |
| [../reference/corporate-os/03-FACEFIT_PROFILE_v6.2.yaml](../reference/corporate-os/03-FACEFIT_PROFILE_v6.2.yaml) | 예시 프로젝트 프로필 |
| [../reference/corporate-os/04-MVP_IMPLEMENTATION_v6.2.md](../reference/corporate-os/04-MVP_IMPLEMENTATION_v6.2.md) | v6.2 MVP 범위·합격 기준 |
| [../reference/corporate-os/05-SKILL_BUNDLING_AND_INSTALLATION_v6.2.md](../reference/corporate-os/05-SKILL_BUNDLING_AND_INSTALLATION_v6.2.md) | 스킬 번들·설치 규칙 |
| [../reference/corporate-os/06-TOKEN_EFFICIENCY_RESEARCH_v6.2.md](../reference/corporate-os/06-TOKEN_EFFICIENCY_RESEARCH_v6.2.md) | 토큰 효율 근거 |
| [../reference/corporate-os/07-SOURCE_LICENSE_MATRIX_v6.2.md](../reference/corporate-os/07-SOURCE_LICENSE_MATRIX_v6.2.md) | 외부 스킬 출처·라이선스 |

## 4. 폐기 문서

[../reference/legacy/](../reference/legacy/)에 둔다. 삭제하지 않고 상단에 폐기 사유를 적는다.

## 5. 산출물 위치 규칙

| 종류 | 위치 |
|---|---|
| 실행 중 산출물 | 작업 워크스페이스의 `AI_OFFICE_OUTPUTS/<TASK-ID>/departments/*.md`, `FINAL.md` (Git 추적 제외) |
| 보관할 완료 산출물 | `reference/outputs/<TASK-ID>/` |
| 제품 파이프라인 산출물 | 대상 프로젝트 워크스페이스의 `docs/`, `.vibeoffice/` |
| 저장소 루트 | 실행·설치·정책 문서만. 작업 보고서를 만들지 않는다 |
