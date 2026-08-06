# 부서 파이프라인 게이트 설계

날짜: 2026-08-06

## 문제

NAVI 플래너(`select_roster_with_model`, `apps/api/main.py:1099`)는 LLM 호출 1번으로 `phases`(부서·목표·산출물·`depends_on`)를 자유 생성한다. 부서 순서(기획 → 디자인/개발 → 리뷰)를 강제하는 코드가 없어, 플래너가 순서를 어기거나 `depends_on`을 누락해도 그대로 실행된다.

`task_phases.dependencies`는 이미 스케줄러가 집행한다(`apps/api/worker.py:105-143`, `queue_ready_agent_jobs`): 한 phase의 `dependencies`가 전부 `completed`/`skipped` 상태가 되기 전엔 해당 owner의 job이 큐에 안 들어간다. 이 게이트는 이미 70개 테스트로 검증된 안정 경로다.

**결론: 새 상태 머신·새 게이트 불필요.** 플랜 저장 직전에 부서 stage 기준으로 `depends_on`을 강제 주입하면, 기존 스케줄러가 그대로 순서를 집행한다.

## 결정 사항

### 1. 고정 순서 강제 방식

`registry/department-boundaries.json`에 부서별 `stage`(정수) 필드 추가:

| stage | 부서 | 비고 |
|---|---|---|
| 0 | operations-planning | NAVI. 게이트 예외(메타 오케스트레이션) |
| 1 | product-experience, growth-marketing | 기획부. 같은 stage, 병렬 |
| 2 | application, ai-data | 개발부. 같은 stage, 병렬 |
| 3 | platform-reliability, quality-security, service-knowledge | 리뷰·릴리즈. 같은 stage, 병렬 |

`select_roster_with_model`의 phase 확정 직후(`main.py` 기존 dedup 루프 다음), 새 순수 함수 `apply_stage_ordering(phases, boundaries)`를 호출해 각 phase의 `depends_on`에 **이 plan에 실제로 포함된** phase 중 stage가 더 낮은 phase의 id 전부를 union한다. LLM이 선언한 `depends_on`은 유지(교집합 아니라 합집합)하되, stage 역행 편성은 이 단계에서 항상 교정된다.

### 2. 위반 시 처리

주입 방식이라 "위반 감지 후 거부"가 아니라 **위반 상태 자체가 생성되지 않음**. 특정 plan이 상위 stage 부서를 아예 안 쓰는 것(예: 단순 버그 수정에 기획부 불필요)은 순서 위반이 아니라 정상적인 단계 생략이며 허용한다 — 이번 plan에 존재하는 phase 사이의 순서만 강제한다.

**범위 제외**: `must_handoff`(부서가 자기 소유 아닌 산출물 타입을 쓰면 거부)는 이번 스펙에 포함하지 않는다. `owns`/`must_handoff`가 자유 텍스트라 산출물 타입을 구조적으로 분류할 기준이 없고, 억지 분류는 오탐 위험이 크다. 별도 스펙(산출물 taxonomy 정의 선행 필요) 대상으로 남긴다.

### 3. 병렬 허용 범위

같은 stage의 서로 다른 부서는 상호 의존성을 주입하지 않으므로 자동 병렬. 실행 단계 병렬화는 이미 구현돼 있다(`queue_ready_agent_jobs`의 `workspace_supports_parallel_worktrees` 분기) — 이번 변경은 이 경로를 트리거하는 조건(서로 다른 owner, 충족된 dependencies)만 정확하게 만들 뿐 스케줄러 코드는 건드리지 않는다.

## 구현

1. `registry/department-boundaries.json`: 8개 부서에 `"stage"` 필드 추가.
2. `scripts/verify_routing.py`: 모든 부서에 정수 `stage`(0~3)가 있는지 검증하는 룰 추가(기존 `owns`/`must_handoff` 빈값 검증과 동일 패턴).
3. `apps/api/main.py`: `apply_stage_ordering(phases: list[dict], boundaries: dict) -> None` 순수 함수 추가(사이드이펙트: `phases`의 `depends_on`을 in-place 갱신). LLM 호출 없이 단위 테스트 가능하도록 분리. `select_roster_with_model`의 기존 dedup 루프 직후, `agents = list(...)` 이전에 호출.
4. 테스트: `apps/api/test_department_pipeline.py` 신설 — 고정 fixture phases(순서 뒤섞임, depends_on 누락 케이스 포함)로 `apply_stage_ordering` 단위 테스트. 네트워크/모델 호출 없음.

## 테스트 계획

- 신규 unit test: stage 역순 케이스가 교정되는지, 같은 stage는 서로 의존성이 안 생기는지, stage 0(NAVI)은 게이트 예외인지, 이 plan에 없는 부서는 무시되는지.
- 기존 `python -m unittest discover` 70개 회귀 확인.
- `scripts/verify_routing.py` 실행해 registry 무결성 확인.

## 범위 밖 (후속 스펙 후보)

- `must_handoff` 산출물 타입 검증(산출물 taxonomy 필요).
- 병렬 실행 시 두 부서가 같은 파일을 동시에 수정하는 충돌 처리(현재 worktree 격리로 완화되나 명시적 병합 전략은 없음).
