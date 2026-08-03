# 작업 기록 — 중복 작업 방지용 체크리스트

이 문서의 목적은 하나다: **다른 AI 세션이 이미 끝난 일을 다시 하지 않게 막는 것.**

작업을 시작하기 전에 이 문서를 먼저 읽는다. 항목을 끝내면 여기에 파일 경로와 검증 명령을 남긴다. 계획은 [RUNTIME_ROADMAP.md](RUNTIME_ROADMAP.md), 런타임 동작 사실은 [RUNTIME_HARDENING.md](RUNTIME_HARDENING.md)에 있고, 이 문서는 **진행 상태**만 다룬다.

마지막 갱신: 2026-07-31 (항목 10~13 추가 — 다른 세션 점유 표시와 겹치는 부분 있음, "진행 중" 절 상단 안내 참고)

---

## 완료 — 다시 만들지 말 것

### 1. Fixture acceptance harness (RUNTIME_ROADMAP P2 기반)

데이터 주도 harness다. **새 검증 케이스를 추가할 때 Python을 건드리지 않는다. `apps/api/fixtures/cases/`에 JSON 파일 하나만 추가한다.**

| 파일 | 역할 |
|---|---|
| `apps/api/fixtures/schema.py` | fixture JSON 스키마·로더 (`Fixture`, `load_all_fixtures`) |
| `apps/api/test_fixture_harness.py` | fixture를 실제 코드 경로로 실행하는 러너 |
| `apps/api/fixtures/cases/*.json` | fixture 31개 (최신 현황은 아래 §7) |

mock 하는 지점은 `main.run_agent` **하나뿐**이다. phase 의존성 게이트, `persist_deliverable`, `store_execution_plan`, `validate_selected_skills`, `assert_completion_invariants`, `render_bundle`은 전부 실코드가 돈다.

최초 5개로 RUNTIME_ROADMAP P2가 요구한 카테고리 5개를 각각 1건씩 커버했다 (아래 표는 그 최초 구성이며, 현재는 31개다 — §7 참조):

| fixture | 카테고리 | 검증 대상 |
|---|---|---|
| `research_to_prd_001.json` | research_to_prd | research→PRD 의존성 게이트 |
| `prd_to_code_001.json` | prd_to_code | `backend_implementation`은 passing run 없으면 완료 불가 |
| `missing_final_deliverable_001.json` | failure_matrix | 최종 산출물 없으면 완료 차단 + 에러 사유 문자열 |
| `policy_market_research_ui_skill_001.json` | policy_regression | `market_research`에서 UI 스킬 로드 금지 |
| `document_office_formats_001.json` | document | 요청 문구→포맷 선택→DOCX/PDF/XLSX/PPTX/HWPX 실제 렌더·재오픈 |

**설계 의도 (지우지 말 것):** document fixture는 포맷 목록을 하드코딩하지 않는다. `formats_for_request`가 사용자 요청 문장을 실제로 읽게 하고, 그 결과를 검증한다. 그래서 `.pptx`를 기대한다는 것은 런타임이 요청문의 "슬라이드"를 진짜 해석했다는 증거가 된다. 포맷 배열을 fixture에 적어 넣고 통과시키는 방식으로 "단순화"하면 이 검증력이 사라진다.

검증:

```bash
.venv/Scripts/python.exe -m unittest apps.api.test_fixture_harness -v
```

### 2. XLSX 렌더 검증의 파일 핸들 누수 수정

`apps/api/artifact_renderer.py`의 `_validate_rendered`가 `load_workbook(path, read_only=True)`를 닫지 않았다. read_only 모드는 zip 핸들을 열어둔 채로 두기 때문에 Windows에서 렌더된 `FINAL.xlsx`가 잠긴 상태로 남는다. 테스트 flake만이 아니라 **실제 worker에서도 매 XLSX 렌더마다 핸들이 누수**돼서 이후 checkpoint restore·workspace 정리·worktree 제거가 실패할 수 있는 경로였다. `try/finally`로 닫도록 수정했다.

결과: 이전에 실패하던 `test_runtime_hardening.test_markdown_renders_to_office_formats_and_manifest`가 통과한다 (3회 연속 확인).

### 3. 조사 품질 지표 모듈 (Phase 2의 절반)

| 파일 | 역할 |
|---|---|
| `apps/api/research_quality.py` | 순수 지표 함수 4개 + 집계 게이트 |
| `apps/api/test_research_quality.py` | 단위 테스트 13건 |

공개 함수: `load_task_research`, `claim_source_coverage`, `primary_source_ratio`, `contradiction_resolution`, `recommendation_linkage`, `evaluate_research_quality`.

기본 임계값 (`DEFAULT_THRESHOLDS`):

| 지표 | 값 | 근거 |
|---|---|---|
| `claim_source_coverage` | 0.9 | RUNTIME_ROADMAP release gate 문구 그대로 |
| `primary_source_ratio` | 0.7 | 보조적 `web_search` 조회는 정상이나 1차 출처가 지배해야 함 |
| `contradiction_resolution` | 0.6 | resolution 컬럼이 없어 "언급됨"은 근사 신호. 과잉 차단 방지 |
| `recommendation_linkage` | 0.5 | 산출물은 종합하는 것이 정상. 과반만 요구 |

**중요한 설계 결정 (되돌리지 말 것):** 분모가 0일 때 모든 지표는 `1.0`이 아니라 **`0.0`을 반환한다**. claim이 아예 없는 조사가 조용히 만점으로 통과하는 것이 바로 이 모듈이 막으려는 구멍이다. 텍스트 매칭에는 `MIN_NEEDLE_CHARS = 8` 하한이 있다 — 빈 문자열이 모든 텍스트에 매칭돼서 전 지표가 1.0이 되는 것을 막는다. 두 경우 모두 테스트가 있다.

검증:

```bash
.venv/Scripts/python.exe -m unittest apps.api.test_research_quality -v
```

### 4. 조사 품질 게이트 배선 (Phase 2 나머지 절반)

`research_quality.py`를 `assert_completion_invariants` (`apps/api/main.py:1212` 부근)에 편입했다. 판별 조건은 문서화된 대로 `task_kind`가 아니라 이미 로드된 `plan_json`의 `requires_web_research` 불리언이다 — `final_owner`를 파싱하던 자리에서 `plan` 딕셔너리 전체를 한 번만 파싱해 재사용한다. 게이트가 뜨면 이미 해시 검증까지 끝난 최종 산출물 경로(`path`)를 그대로 읽어 텍스트로 넘긴다. 실패 시 `RuntimeError("Research quality gate failed: <metric>=<score> (threshold <t>, offenders: [...])"...)` 형태로 실패한 지표마다 점수·임계값·offender 일부를 나열한다.

fixture 하네스(`apps/api/fixtures/schema.py`, `apps/api/test_fixture_harness.py`)에 선택적 `research` 블록(`sources`/`claims`)을 추가했다. 선언한 fixture만 완료 판정 직전에 `research_sources`/`research_claims`에 실제 INSERT한다. 새 fixture 2건 추가:

| fixture | 검증 대상 |
|---|---|
| `research_quality_gate_pass_001.json` | 검증된 1차 출처로 뒷받침된 claim + 두 출처를 실제로 인용한 최종 산출물 → 게이트 통과 |
| `research_quality_gate_fail_001.json` | claim의 출처가 `verified-original`로 확인된 적 없음, 최종 산출물도 아무 출처를 인용하지 않음 → `claim_source_coverage=0.00`으로 차단 (다른 invariant가 먼저 걸리지 않음을 fixture 통과로 확인) |

**게이트가 실제로 작동함을 mutation test로 확인했다.** `main.py`의 `if plan.get("requires_web_research"):`를 일시적으로 `if False:`로 바꾸자 `research_quality_gate_fail_001`이 아무 예외도 던지지 않았다(`AssertionError: RuntimeError not raised`). 즉 이 fixture는 다른 invariant가 먼저 걸려서 실패하는 것이 아니라, **오직 조사 품질 게이트만이** 차단하고 있다. 이후 원상 복구하고 45건 전부 통과를 재확인했다. 게이트나 이 fixture를 수정할 때 같은 mutation test로 여전히 load-bearing인지 확인할 것 — 게이트를 우회해도 통과한다면 그 fixture는 아무것도 검증하지 않는 것이다.

**주의 — 기존 fixture 2건도 함께 수정했다 (되돌리지 말 것):** `research_to_prd_001.json`, `policy_market_research_ui_skill_001.json`은 `requires_web_research: true`이지만 원래 어떤 research 행도 기록하지 않았다. 게이트가 없을 때는 문제되지 않았지만, 배선 이후에는 실제로 근거 없는 조사로 읽혀 완료가 막힌다. 두 fixture 모두 실제 조사 업무이므로(가격 조사, 경쟁사 조사) `requires_web_research`를 끄는 대신 최소한의 진짜 검증된 출처·claim을 채워 넣어 계속 통과하게 했다.

검증:

```bash
.venv/Scripts/python.exe -m unittest apps.api.test_fixture_harness -v
.venv/Scripts/python.exe -m unittest apps.api.test_research_quality -v
```

### 5. Fixture 19건으로 확장 + vacuous fixture 구멍 차단

fixture를 7건 → **19건**으로 늘렸다. 카테고리 분포: research_to_prd 4, prd_to_code 3, document 3, failure_matrix 4, policy_regression 3, research_quality_gate 2.

**검수에서 발견한 결함 — 같은 실수를 반복하지 말 것.** `policy_regression` fixture 3건이 전부 아무것도 검증하지 않는 상태였다. harness가 `assertRaises(Exception)`으로 예외 발생만 확인하고 **이유를 따지지 않았기** 때문이다. `validate_selected_skills`는 전혀 다른 두 이유로 403을 던진다:

| 메시지 | 의미 | 검증 가치 |
|---|---|---|
| `Skills are not bound to <직원>: <스킬>` | 그 직원이 애초에 그 스킬을 안 가짐 | **없음.** 지어낸 문자열(`definitely-not-a-real-skill-xyz`)도 똑같이 이 403을 낸다 |
| `Skills are blocked for <task_kind>: <스킬>` | 직원이 스킬을 정당하게 보유하지만 업무 종류가 금지 | **이것이 실제 정책 규칙** |

세 fixture 모두 전자에 걸려 있었다. 즉 "존재하지 않는 스킬은 거부된다"만 증명했다. 실제로 검증 가치가 있는 조합은 **보유하지만 task_kind로 차단되는** 삼중 조합이다 (직접 호출로 확인):

| 직원 | 스킬 | task_kind 없음 | task_kind 지정 |
|---|---|---|---|
| `MOSS` | `ui-ux-pro-max` | 허용 | `market_research` → 차단 |
| `LINK` | `context-engineering` | 허용 | `backend_implementation` → 차단 |
| `TRACE` | `screen-reader-testing` | 허용 | `backend_implementation` → 차단 |

**구조적으로 막았다 (약화시키지 말 것):** `prohibited_skills`의 각 항목은 이제 `error_contains`로 예상 거부 이유를 반드시 선언해야 한다. 선언하지 않은 fixture는 실행이 아니라 **`load_fixture` 단계에서 `ValueError`로 거부**된다. 이유를 안 적고 넘어가는 것이 불가능하다. 케이스별로 고친 것이 아니라 구멍 자체를 닫은 것이므로, 이 검사를 완화하면 vacuous fixture가 다시 들어온다.

**mutation test로 확인했다.** `policy_market_research_ui_skill_001.json`의 `error_contains`를 옛 vacuous 메시지로 바꾸자 즉시 실패했다: `'Skills are not bound to MOSS' not found in '403: Skills are blocked for market_research: ui-ux-pro-max'`. 이후 원복하고 전체 통과를 재확인했다.

**failure_matrix fixture는 설계상 vacuous가 될 수 없다** — `expected.error_contains`가 필수라서 의도한 invariant가 아닌 다른 invariant가 먼저 걸리면 테스트가 실패한다.

### 6. ARCHITECTURE.md worker 서술 정정

`docs/ARCHITECTURE.md`의 실행 구성 다이어그램이 `Single local worker`라고 적혀 있어 P1의 실제 구현(ready phase마다 별도 OS 프로세스)과 불일치했다. `Local worker processes (one OS process per ready phase)`로 고쳤다. `AI_OFFICE_WORKER_MODE=thread`는 로컬 디버깅 전용이라는 사실은 [RUNTIME_ROADMAP.md](RUNTIME_ROADMAP.md) P1에 이미 있다.

### 7. Fixture 31건 + 중복·허위명 fixture 제거

fixture를 19 → **31건**으로 늘렸다. RUNTIME_ROADMAP P2가 요구한 "30~50건" 범위에 진입했다.

**검수에서 잡은 결함 — fixture를 늘릴 때 반드시 확인할 것.** 새로 추가된 failure fixture 중 2건이 기존 fixture와 `error_contains`가 **완전히 동일**했다(중복 커버리지), 그리고 2건은 **파일명이 실제 검증 대상과 달랐다**. 허위명이 중복보다 나쁘다 — 커버리지가 실제보다 넓어 보이게 만들기 때문이다.

조치: 중복 2건은 이름만 바꾸지 않고 **실제로 다른 invariant를 검증하도록 재작성**했고, 이름이 틀린 1건은 파일명·`id`·검증 대상이 일치하도록 고쳤다.

조사 게이트의 지표 4개를 이제 **각각 독립적으로** 실패시키는 fixture가 있다:

| fixture | 격리해서 실패시키는 지표 |
|---|---|
| `research_quality_gate_fail_001.json` | 4개 전부 (provenance 총체 부실 catch-all) |
| `failure_primary_source_ratio_008.json` | `primary_source_ratio`만 |
| `failure_contradiction_resolution_003.json` | `contradiction_resolution`만 |
| `failure_recommendation_linkage_009.json` | `recommendation_linkage`만 |

**`error_contains`만으로는 격리를 증명할 수 없다 (중요).** 게이트 에러 메시지는 실패한 지표를 `; `로 **전부** 나열하므로, 지표 3개가 동시에 실패해도 substring 하나는 매칭된다. 즉 fixture가 "지표 하나만 검증한다"는 주장은 `error_contains` 통과만으로 성립하지 않는다. 실제로 이 방식으로 검사했더니 `failure_reviewer_is_owner_004.json`이 의도(리뷰어=최종소유자)와 무관하게 `contradiction_resolution`도 깨져 있었다 — 리뷰어 검사가 조사 게이트보다 **먼저 실행되기 때문에** 우연히 통과하던 것이다. 순서가 바뀌면 조용히 다른 이유로 실패하게 되는 취약한 fixture였고, 조사 데이터를 정상화해 고쳤다.

fixture를 추가·수정한 뒤에는 `evaluate_research_quality`를 직접 호출해 **각 fixture가 자신이 주장하는 지표만 실패시키는지** 확인할 것. 현재 stray 0건이다.

### 8. 문서·런타임 불일치 CI 검사기

| 파일 | 역할 |
|---|---|
| `scripts/verify_docs_consistency.py` | 문서 표류 검사기 (`verify_routing.py`와 같은 CLI 관례) |
| `apps/api/test_docs_consistency.py` | 검사기 자체 로직 단위 테스트 20건 |

검사 3종: (1) `docs/*.md`가 참조하는 파일 경로 실존 여부, (2) 백틱으로 감싼 코드 심볼과 `file.py:123` 참조의 실존·행수 검증, (3) `apps/web`이 쓰는 상태 문자열이 `apps/api`의 `JOB_STATES`/`TASK_STATES` 부분집합인지.

**오탐 억제가 이 검사기의 핵심이다 (약화시키지 말 것).** 늑대 소년이 되면 삭제된다. 주요 장치: 펜스 코드블록을 먼저 비우고(계획용 미구현 경로·SQL·HTTP는 전부 펜스 안에 산다), 백틱 경로는 실제 저장소 최상위 디렉터리로 시작할 때만 검사하며, 심볼은 snake_case/CONST_CASE/PascalCase 형태일 때만 후보로 삼는다. 파일·행 참조 실패는 **ERROR**(결정적), 심볼 미해결은 **WARNING**(휴리스틱이라 부재를 증명할 수 없음)로 나눈다. CI 실패는 ERROR에서만 난다.

현재 저장소 검사 결과: ERROR 0건, WARNING 2건 — 대화형 에이전트의 메시지 테이블과 VibeOffice의 ArtifactVersion 모델로, 둘 다 해당 문서가 스스로 "미구현"이라고 적은 것이라 WARNING이 정확한 분류다. 종료 코드 0.

(이 문단에서 두 심볼 이름을 백틱으로 감싸지 않은 것은 의도적이다. 검사기의 경고 내용을 백틱으로 문서화하면 검사기가 그 문장 자체를 새 경고로 집는 자기참조 오탐이 생긴다. 검사기를 약화시키는 대신 문서 쪽 표기를 바꾼 것이다.)

검증:

```bash
.venv/Scripts/python.exe -m unittest apps.api.test_docs_consistency -v
.venv/Scripts/python.exe scripts/verify_docs_consistency.py
```

---

### 9. 제품 계층 S1 — Intake → Blueprint → 기획 승인

VibeOffice 제품 파이프라인의 첫 수직 슬라이스. 근거: [VIBEOFFICE_IMPLEMENTATION_GUIDE.md](VIBEOFFICE_IMPLEMENTATION_GUIDE.md) §7 S1. 담당: Kiro 세션 (2026-07-30).

| 파일 | 역할 |
|---|---|
| `apps/api/vibeoffice/schema.py` | `vo_projects`·`vo_blueprints` 멱등 생성, `ProjectState` enum(전체 상태 머신), `S1_STATES`/`S1_TRANSITIONS`, `vibeoffice_database()` |
| `apps/api/vibeoffice/models.py` | pydantic v2 blueprint 모델(`extra="forbid"`) + **스키마 파일을 읽어 해석하는 최소 JSON Schema 검증기** |
| `apps/api/vibeoffice/intake.py` | 결정론적 규칙 추정 10키, 시작 카드 5장, `MAX_QUESTIONS=3`, 3선택지 질문, `apply_answers` |
| `apps/api/vibeoffice/blueprint.py` | blueprint 조립·Gate B·DB+파일 동시 저장·sha256·승인·`approved_blueprint_for_handoff` |
| `apps/api/vibeoffice/routes.py` | `/api/vibe/*` 라우터 8개 엔드포인트 (404/409/422 매핑) |
| `apps/api/test_vibeoffice_intake.py` | 테스트 18건 |

`apps/api/main.py`는 **라우터 mount 한 줄만** 건드렸다 (`app.add_middleware(...)` 직후, 조사 품질 게이트가 있는 1265행과 무관한 위치). import를 그 자리에 둔 이유는 주석에 남겼다 — `vibeoffice` 패키지가 `main`을 함수 본문에서 지연 import하므로, 파일 상단 import 블록에 넣으면 순환 참조가 닫힌다.

**되돌리지 말 것:**

- **`main` import는 함수 본문 안에서만.** 모듈 스코프 import는 순환 참조를 만들고 `DB_PATH`를 import 시점에 고정시켜, `main.DB_PATH`를 임시 경로로 바꾸는 기존 테스트 패턴을 깨뜨린다.
- **`InferredValue`를 blueprint 본문에 넣지 않는다.** `project-blueprint.schema.json`이 `additionalProperties: false`이므로 넣는 순간 검증 실패다. 기계용 메타데이터는 `vo_blueprints.inference_json`, 사람용 흔적은 스키마가 허용하는 `assumptions`(문자열) + `confidence`(숫자 맵)로만 반영한다. 회귀 테스트가 있다.
- **Must 3~5는 스키마가 아니라 우리 게이트가 강제한다.** 스키마는 `minItems: 1`로 느슨하다(손으로 쓴 blueprint도 받아야 하므로). `assert_scope_gate`를 "스키마가 통과시키니까" 이유로 제거하면 Must 1개 blueprint가 기획을 통과한다.
- **스키마 규칙을 파이썬으로 베끼지 않는다.** `validate_blueprint`가 스키마 파일을 읽어 해석하고, 모르는 키워드를 만나면 `UnsupportedSchemaKeyword`로 큰 소리로 실패한다. 조용히 건너뛰면 무효 blueprint가 통과한다.
- **파일 = 산출물, 해시 = 증거.** sha256은 메모리 문자열이 아니라 디스크 바이트에서 계산하고, `vo_blueprints.path`는 상대 경로로 저장한다(가이드 §11: 산출물에 로컬 절대경로 금지).
- **모델 호출 없음.** 추정은 순수 한국어 키워드 규칙이다. 테스트가 결정론적이어야 하기 때문이며, 모델 보조는 이후 슬라이스에서 같은 dataclass 뒤에 붙인다.

알려진 제한: 프로젝트당 working version 1개(버전 승계는 S2), `approved_blueprint_for_handoff`는 HTTP 엔드포인트 없이 파이썬 공개 함수로만 존재(S2의 handoff가 호출할 진입점), 어휘 밖 도메인은 fallback으로 떨어지고 fallback은 신뢰도가 낮아 질문 후보가 된다(의도된 동작).

검증:

```bash
.venv/Scripts/python.exe -m unittest apps.api.test_vibeoffice_intake -v   # 18건 통과
```

---

### 10. 제품 계층 S2 마무리 — 시안 승인(승인 2) 엔드포인트

아래 "진행 중" 절 Kiro 세션의 S2 점유 목록에 있던 파일을 이 세션이 건드렸다. **겹침 주의.** S2의 handoff/design/artifacts 본체는 이미 완성돼 있었다(이 세션 시작 시점에 `test_vibeoffice_handoff.py` 30건 전부 통과 확인). 빠져 있던 것은 가이드 §10의 3회 승인(기획·시안·출고) 중 "시안 승인" 하나뿐이었다 — `DESIGN_REVIEW → DESIGN_APPROVED` 전이 자체는 S2가 이미 legal로 열어뒀는데 호출할 엔드포인트가 없었다.

| 파일 | 변경 |
|---|---|
| `apps/api/vibeoffice/design.py` | `approve_design()` 추가 (기존 함수는 무변경) |
| `apps/api/vibeoffice/routes.py` | `POST /projects/{id}/artifacts/design/approve` 추가 |

검증: `apps/api/test_vibeoffice_contracts.py`의 `test_design_approve_*` 2건 (아래 §11에 포함).

### 11. 제품 계층 S3 — 디자인 승인 → 기술설계 계약

근거: [VIBEOFFICE_IMPLEMENTATION_GUIDE.md](VIBEOFFICE_IMPLEMENTATION_GUIDE.md) §7 S3, 09A Gate D/E.

| 파일 | 역할 |
|---|---|
| `apps/api/vibeoffice/architecture.py` | 신규. `ApiEndpoint`/`DataEntity`/`TechnicalTask` 결정론적 생성(화면 kind별 고정 필드셋 재사용 → API/Data 필드 일치가 구성상 보장), `assert_gate_d`(생성기와 독립적으로 재검증), `run_architecture` |
| `apps/api/vibeoffice/schema.py` | `S3_TRANSITIONS` 추가 (`DESIGN_APPROVED→ARCHITECTURE→ARCHITECTURE_REVIEW`, Gate D 반송 경로) |
| `apps/api/vibeoffice/artifacts.py` | `ARTIFACT_API_CONTRACT`/`ARTIFACT_DATA_MODEL`/`ARTIFACT_TECHNICAL_TASKS` 등록 (기존 `record_artifact` 등은 타입 무관 제네릭이라 로직 변경 없음) |
| `apps/api/vibeoffice/routes.py` | `POST /projects/{id}/departments/architecture/run` |
| `apps/api/test_vibeoffice_contracts.py` | 신규, 18건 |

**되돌리지 말 것:**

- **`REWORK_REQUIRED`는 두 가지 원인을 공유한다.** Gate C 반송(디자인 미승인 상태)과 Gate D 반송(디자인은 승인됐지만 기술설계 실패) 둘 다 이 상태를 쓴다. 재시도 진입 조건을 raw state만으로 판단하면 구분이 안 된다 — `vo_artifacts`에 `SCREEN_SPEC`이 기록돼 있는지로 구분한다(`architecture._has_recorded_design`).
- **blueprint 재조회는 `get_blueprint`를 쓴다, `approved_blueprint_for_handoff`가 아니다.** 후자는 `PLANNING_APPROVED` 상태를 강제하는데, S3 시점엔 이미 두 부서 지나서 그 상태가 아니다. 실제로 이 실수를 했다가 테스트로 잡았다.

검증: `.venv/Scripts/python.exe -m unittest apps.api.test_vibeoffice_contracts -v` (18건)

### 12. 제품 계층 S3.5 — 기술설계 승인 → Product Execution Baseline

근거: [VIBEOFFICE_IMPLEMENTATION_GUIDE.md](VIBEOFFICE_IMPLEMENTATION_GUIDE.md) §7 S3.5, 06_OUTPUT_STANDARD.md.

| 파일 | 역할 |
|---|---|
| `apps/api/vibeoffice/execution_baseline.py` | 신규. `Requirement`/`KeyResult`/`Decision`/`RiskEntry`/`TraceabilityRow` 결정론적 파생, `assert_gate_pe`, `run_execution_baseline` |
| `apps/api/vibeoffice/schema.py` | `S35_TRANSITIONS` 추가 |
| `apps/api/vibeoffice/artifacts.py` | `ARTIFACT_PRD`/`ARTIFACT_DECISION_REGISTER`/`ARTIFACT_RISK_REGISTER`/`ARTIFACT_TRACEABILITY`/`ARTIFACT_TRACEABILITY_MAP` 등록 |
| `apps/api/vibeoffice/routes.py` | `POST /projects/{id}/departments/execution-baseline/run` |
| `apps/api/test_vibeoffice_execution_baseline.py` | 신규, 15건 |

**되돌리지 말 것:**

- **새 project state를 만들지 않았다.** 가이드 §5의 상태 목록에 S3.5 전용 상태가 없다 — "기존 Planning 산출물을 대체하지 않는다"는 파생 산출물 고정 작업이라 성공해도 `ARCHITECTURE_REVIEW`에 머문다. Gate PE 실패 시에만 `REWORK_REQUIRED`로 갔다가 돌아온다.
- **OKR/Decision 상태(`confirmed`/`assumption`/`deferred`)는 Blueprint 스키마에 없는 필드다.** `project-blueprint.schema.json`을 확장하지 않고 `openQuestions`(handoff.py의 기존 `DEFERRED_MARKER` 재사용)와 `risks`에서 순수 함수로 파생한다. S1 스키마를 건드리지 않는 것이 의도다.
- **Gate PE의 구조적 결정 차단 규칙은 S2의 `handoff.STRUCTURAL_DECISION_LABELS`를 재사용한다.** 두 번째 목록을 만들지 않는다.

검증: `.venv/Scripts/python.exe -m unittest apps.api.test_vibeoffice_execution_baseline -v` (15건)

### 13. 제품 계층 S4 — 기술설계 승인 → 내부 MVP 빌드

근거: [VIBEOFFICE_IMPLEMENTATION_GUIDE.md](VIBEOFFICE_IMPLEMENTATION_GUIDE.md) §7 S4, 09A Gate F. 위 "진행 중" 절에 "다른 세션이 S4를 진행 중"이라는 메모가 있었으나, 이 세션 착수 시점에 `apps/api/vibeoffice/build.py`·`test_vibeoffice_build.py`는 존재하지 않았다(새로 작성, 덮어쓴 파일 없음).

| 파일 | 역할 |
|---|---|
| `apps/api/vibeoffice/build.py` | 신규. 정적 HTML+vanilla JS 스캐폴드(프레임워크 설치 없음 — mock 경계), 실제 `node scripts/build.js`/`node scripts/test.js` 서브프로세스 실행, `assert_gate_f`, `run_build` |
| `apps/api/vibeoffice/artifacts.py` | `_write_doc`/`record_artifact`에 선택적 `directory` 인자 추가(기본값 `docs/`로 하위호환), `ARTIFACT_PROJECT_STATUS`(workspace root)/`ARTIFACT_BUILD_REPORT`(docs/)/`ARTIFACT_CURRENT_STATE`(.vibeoffice/) 등록 |
| `apps/api/vibeoffice/schema.py` | `S4_TRANSITIONS` 추가 (`ARCHITECTURE_REVIEW→BUILD→BUILD_VERIFICATION`, 가이드 §5에 이미 있던 상태를 처음 실제로 씀) |
| `apps/api/vibeoffice/routes.py` | `POST /projects/{id}/departments/build/run` |
| `apps/api/test_vibeoffice_build.py` | 신규, 10건. `shutil.which("node") is None`이면 skip |

**되돌리지 말 것:**

- **명령 실행은 `apps/api/policy.py`의 `validate_command`를 재사용한다.** `main.tasks`/`TaskContract`/Job 큐에는 올라타지 않는다 — S1~S3.5와 같은 자기완결 원칙을 유지했다. 실행 계층 통합은 아직 미착수 목표다(§0 결론 참고 — [VIBEOFFICE_GAP_ANALYSIS.md](VIBEOFFICE_GAP_ANALYSIS.md)).
- **스캐폴드에 React/Vite를 설치하지 않는다.** `apps/web`의 실제 빌드는 네트워크·시간이 든다. 정적 골격 + 의존성 없는 Node 스크립트 2개로 "진짜로 실패할 수 있는" 명령을 유지하면서 오프라인·결정론을 지켰다 — 이게 가이드가 말하는 "mock 경계"이고 PROJECT_STATUS.md/BUILD_REPORT.md에 명시했다.
- **S2/S3/S3.5와 달리 게이트 전에 파일을 쓴다.** Gate F는 실제 명령의 실제 exit code를 판정해야 해서 인메모리 대체가 없다 — `build_scaffold`가 먼저 디스크에 쓰고, `run_smoke_commands`가 실제로 실행한 뒤, `assert_gate_f`가 결과를 본다.

검증: `.venv/Scripts/python.exe -m unittest apps.api.test_vibeoffice_build -v` (10건, node 필요)

전체 회귀(2026-07-31): **161건 중 158 pass, 3 error**(rg 미설치, §"알려진 환경 문제" 참고). 진짜 실패는 0건.

---

### 14. Phase 0/1 — 위생 + 계기판 복구 (2026-08-01)

`main.py:1315` vibeoffice 라우터를 `AI_OFFICE_ENABLE_VIBEOFFICE=1` 환경변수 게이트 뒤로(기본 off, 삭제 아님). `_doccheck.txt` 삭제, 스크래치 파일 패턴 `.gitignore`에 추가. 실행 안 된 계획 문서 4개(`VIBEOFFICE_GAP_ANALYSIS`/`VIBEOFFICE_IMPLEMENTATION_GUIDE`/`LAUNCH_HARNESS_PLAN`/`CONVERSATIONAL_AGENT_TARGET`) `reference/legacy/`로 이동. `CONTRIBUTING.md`에 "코드 변경 없는 신규 계획 문서 금지" 규칙 추가, "현재 unittest 스위트는 배관 회귀 테스트지 완료·릴리스 판정 근거가 아니다" 명시.

계기판: `apps/api/pricing.py` 신규 — OpenRouter `/models` 응답의 실제 pricing을 캐시해 사용(하드코딩 표 아님, `openrouter_models()` 재사용). `main.record_usage()`가 `model_usage` insert 10곳(main.py 2 / worker.py 2 / task_routes.py 6)을 대체, `cost_usd`가 이제 실제 값. `check_budget()` — `AI_OFFICE_TASK_BUDGET_USD`/`AI_OFFICE_DAILY_BUDGET_USD`(0=무제한) 초과 시 `enqueue_job`이 402. `job_events`: `job.heartbeat`가 15초마다 영구히 쌓이는 게 4000건의 실제 원인이었음(코드로 확인, DB 없이) — job당 최근 5개만 ring-buffer로 보존. `purge_old_job_events()`가 종료 30일 지난 job의 이벤트를 지우고 VACUUM, worker 메인 루프에서 6시간마다(스로틀) 실행. `jobs.error_class` 컬럼 + `classify_error()` — `set_job()` 단일 지점에서 분류.

**검수에서 잡은 버그**: `check_budget()`이 raise하는 `HTTPException`을 `schedule_autonomous_tasks()`/`schedule_ready_phase_jobs()`가 잡지 않아 예산 초과 시 worker 메인 루프 전체가 죽을 수 있었다. `main_loop()`의 반복 본문 전체를 `try/except Exception: traceback.print_exc()`로 감싸 해결 — 하나의 스케줄링 틱 실패가 dispatcher를 죽이지 않게.

검증: 전체 165건 중 baseline과 동일한 4 error(HWPX 렌더러 미설치 3, git identity 미설정 1 — 둘 다 이 머신 환경 문제, 코드 결함 아님). 회귀 0.

### 15. 회의 자동 스케줄 — `awaiting_lead_selection` 병목 해소 (2026-08-01)

**발견**: `schedule_autonomous_tasks()`는 `awaiting_worker_selection` 상태부터만 자동 진행한다. 거기 도달하려면 회의(`meeting`) job이 끝나야 하는데, 그 job은 `task_routes.py`(`POST /api/tasks/{id}/select-leads`)나 `job_routes.py`의 사람 액션으로만 큐잉됐다 — 자동 스케줄 없음. 프론트가 안 누르면 태스크가 `awaiting_lead_selection`에서 영구히 멈춘다. "완료 0건 / 취소 6건" 증상의 유력 원인.

`worker.py`에 `schedule_lead_selection()` 추가 — `select_leads` 라우트 로직을 그대로 재현(NAVI가 제안한 팀장 후보 전원 자동 승인 후 회의 시작), `main_loop()`에 배선. 테스트는 라우트를 직접 호출하는 방식이라 회귀 없음(6/6 pass).

### 16. Skill 개인 바인딩 → 부서 풀 전환 + 정상화 (2026-08-01)

**배경**: skill이 `employee-skill-bindings.json`에 직원 개인 단위로 고정 바인딩되어 있었다. 팀장이 위임해도 실행은 "이 skill=이 사람" 고정 매핑이라 병목이었다(사용자 지적). 개인 바인딩을 제거하고 **부서(team) 단위 풀**로 재구조화 — 팀장이 위임 시 부서 skill 중 최대 3개를 명령하는 구조로 변경.

- `registry/employee-skill-bindings.json` — 24명 개인 키 → 8개 부서 키, `{"skills":[...]}` 단일 목록(required/optional 구분 폐지, `skill_ids_for_task`가 항상 `[]`라 애초에 자동 로드된 적이 없었음).
- `main.py` — `team_skill_pool()`/`employee_skill_pool()` 신규. `validate_selected_skills`/`employee_security`가 개인 bindings 대신 부서 풀 조회.
- `scripts/install_skills.py`/`verify_skills.py` — 부서 풀 기준으로 재작성. `source: local`(직원 개인 소유 proprietary skill 3종: `sales-operations`, `customer-support-operations`, `document-artifact-production`) 복사 로직 추가 — 원래 스킵되던 것.
- 447개 신규 설치, `verify_skills.py --employee ALL` exit 0 (453 OK).

**정상화 (실측 기반)**: 별도 8-부서 병렬 감사(Sonnet)로 실제 SKILL.md 내용 대 부서 책임 대조.

1. **`per_skill_limit` 3000→16000** (`main.py`) — 3000에서는 151개 중 19개(13%)만 온전히 전달, 중앙값 39%만 도달했다(실측: `code-review-and-quality`는 리뷰 프로세스 5단계·체크리스트·출력 양식이 전부 잘림). 16000에서 133/151(88%) 온전 전달.
2. **`application`(BUILD/FRONT/BACK, 실제 코더) 팀에 엔지니어링 skill이 0개였음** — superpowers 7종(`systematic-debugging`/`test-driven-development`/`verification-before-completion`/`writing-plans`/`executing-plans`/`using-git-worktrees` 등)이 전부 `operations-planning`(기획팀, 구현을 `must_handoff`로 명시)에 있었다. 8종을 `application`으로 이동, 미바인딩 카탈로그 항목(`debugging-strategies`, `error-handling-patterns`)도 추가.
3. **`default_task_kind`가 부서 단위라 자기 풀을 스스로 막는 경우 다수** — `application` 기본값이 `"general"`이라 코딩 특화 skill 8개가, `quality-security` 기본값이 `"quality_review"`라 보안 skill 8개가 활성화 게이트에서 차단됐다. `EMPLOYEE_TASK_KIND`(직원 21명 개별 매핑) 추가, `default_task_kind(department, employee_id=None)`로 하위호환 유지.
4. **리드 모델 등급이 선택 난이도와 역상관** — skill 38개 중 3개를 고르는 GROW, 17개인 LENS가 flash 등급이었고, 10개뿐인 LINK가 최상위였다. GROW·LENS를 `complex_design_integration`으로 승격(비용 증가, 사용자 확인 대기 중).
5. **misfit 정리** — `doubt-driven-development`(스스로 "페르소나에 넣지 말 것" 명시, quality-security에서 제거), finance-* 2종(platform-reliability→인프라와 무관, 제거), `code-review-and-quality`/`cro`(service-knowledge, 경계 위반) 등.

**검수에서 잡은 것**:
- Sonnet이 `default_task_kind` 호출부 1곳만 고치라는 지시를 문자 그대로 따랐으나(정직하게 flag), 실제로 employee를 쥔 호출부는 7곳(`main.py` 4 + `worker.py` 3)이었다 — 나머지 6곳을 마저 통일. 지시가 부실했던 것, Sonnet 잘못 아님.
- `sync_registry_yaml.py`가 파생 데이터(`team_skills`)를 `employees.json` 24명 전원에 주입(+413줄, 계획 외 변경) — 실 소비자 0(둘 다 bindings에서 직접 계산), 단일 진실원천 붕괴 위험이라 되돌림.
- `render_skill_indexes.py`가 **디스크의 skills/ 폴더를 스캔**하지 바인딩을 안 봐서, 부서 풀에서 뺀 skill의 폴더가 디스크에 남으면 `SKILL_INDEX.md`가 계속 광고 — 팀장이 그걸 고르면 `validate_selected_skills` 403 → 예외를 잡아 **조용히 `skill_ids=[]`로 퇴화**하는 버그(고아 폴더 55개 실측). 생성기를 바인딩 교집합 기준으로 수정, 24명 전원 index==pool 확인.

검증: 전체 165건 baseline 4 error 그대로, `verify_skills`/`verify_routing`/`audit_package` 전부 exit 0.

### 17. `_local-role-core` 상시 로드 전환 + 24개 매뉴얼 작성 (2026-08-01)

**발견**: 직원별 "회사 고유 운영 매뉴얼"인 `_local-role-core`가 `skill-definitions.json`에도 부서 풀에도 등록돼 있지 않았다. 즉 **선택하면 항상 403 → 조용히 무시**, 애초에 아무에게도 전달된 적이 없었다(24개 중 23개가 빈 섹션인 채 방치된 이유이기도 함). 실측: `main.validate_selected_skills('BUILD', ['_local-role-core'], ...)` → `403 Skills are not bound to BUILD`.

`main.py`에 `ROLE_CORE_SKILL_ID` 상수 + `employee_skill_context()`가 이걸 **선택 목록과 무관하게 항상 먼저 로드**하도록 변경(부서 풀 3개 선택 슬롯과 경쟁하지 않음). `render_skill_indexes.py`의 선택 가능 목록에서는 제외(항상 로드되니 골라봤자 403). `test_workflow_acceptance.py`의 관련 단언을 새 동작에 맞게 갱신(빈 리스트가 아니라 role-core 1개만 있어야 함).

`registry/role-core-template.md` 신규 — 8섹션 고정 형식. 섹션 3(도구 15종)·4(계약 게이트)·5(인계 규약)는 24명 전원 글자 그대로 동일, 1·2·6·7·8은 역할 고유. Sonnet 8마리(부서당 1, 팀원 3명 동시 작성 — 부서 맥락 공유가 일관성에 유리)에 배정, Haiku 1마리로 기계적 형식 검사(섹션 누락/공백/도구명 오용/금지 항목 개수) 배정.

- 24개 전량 8665~10503 bytes(이전 평균 690B), 빈 섹션 0, 금지 항목 3~6개.
- `queue_ready_agent_jobs`의 인계 규칙(산출물 없는 phase 완료는 하류를 영구히 막는다)을 섹션 5에 전 직원 공통으로 명문화 — 이 시스템은 이미 회의에서 정한 `depends_on`/`handoff_to`로 부서 간 자동 인계가 되는 구조였으나, 그걸 아는 매뉴얼이 없었다.

**검수에서 잡은 것**: 내 자동 검사 스크립트가 번호 목록(`1.`~)을 안 세고 `- ` 불릿만 세서 NAVI/ROUTE/CLOCK "금지 항목 0개"로 오탐(실제론 5개씩 있었음 — 검사 버그, 매뉴얼 버그 아님). GUARD가 공통 섹션5에 "독립 리뷰어로 투입될 때" 문단을 추가한 것은 형식 위반처럼 보였으나 내용이 GUARD 고유의 실제 상황(유일한 부서 간 리뷰어)이라 유지, 대신 계약 게이트·인계 규약 핵심 문장 7종이 24명 전원에 글자 그대로 보존됐는지 별도 검사로 확인(전원 통과).

**비용 주의**: 매뉴얼이 이제 항상 로드되어 에이전트 호출당 평균 ~1,475 토큰 고정 추가(업무 skill 3개 최대 13,700 토큰과 합쳐 호출당 상한 ~15,000 토큰). `pricing.py`(§14)로 실측 가능해졌으니 Phase 3에서 이 비용이 값을 하는지 데이터로 볼 것.

검증: 전체 165건 baseline 4 error 그대로, `audit_package` OK, 실제 `employee_skill_context` 호출로 전달 확인.

### 18. 스킬 풀 정리 + 부서별 복사본 → 공용 풀 전환 (2026-08-03)

**실측 먼저**: 스킬 정의 126개 중 8개는 어떤 부서에도 바인딩되지 않은 고아였고, 디스크에는 부서 풀보다 넓은 superset이 복사돼 있었다(`employees/` 24M, growth-marketing 한 부서만 5.5M/558파일). 같은 스킬 텍스트가 직원마다 1부씩, 부서당 3~4부. lock도 `직원:스킬` 키라 같은 트리 해시를 3~4번 저장했다(372 entries).

**중복 통합** — 기능이 겹치는 스킬을 하나로: 디버깅 3종 → `systematic-debugging`, 계획 3종 → `writing-plans`+`executing-plans`, 리뷰 2종 → `code-review-and-quality`, 스펙 2종 → `spec-driven-development`, git 2종 → `git-workflow-and-versioning`. 제거된 쪽(`debugging-and-error-recovery`, `debugging-strategies`, `planning-and-task-breakdown`, `code-review-excellence`, `source-driven-development`, `git-advanced-workflows`)은 정의·바인딩·디스크에서 삭제.

**고아 8개 판정** — 버린 게 아니라 필요 여부로 갈랐다: `finance-unit-economics`·`finance-driver-based-model` → platform-reliability(COST가 비용 담당인데 바인딩만 빠져 있었음), `pm-foundation-meeting-synthesize` → service-knowledge(회의 자동 스케줄과 짝), 나머지 5개(`gsap-core`, `gsap-timeline`, `startup-financial-modeling`, `git-advanced-workflows`, `writing-skills`)는 설치본조차 없거나 중복이라 삭제. growth-marketing이 쥐고 있던 PM 발견 스킬 3종(`pm-define-jtbd-canvas`, `pm-discover-competitive-analysis`, `pm-discover-market-sizing`)은 product-experience로 이관 — 부서 경계상 발견은 제품 조직 소유.

**마케팅 축소는 2단계로**: 18개(`ads`, `aso`, `attribution`, `co-marketing`, `cold-email`, `community-marketing`, `competitor-profiling`, `content-strategy`, `copy-editing`, `emails`, `marketing-plan`, `pricing`, `programmatic-seo`, `referrals`, `social`, `brand-consistency-checker`, `content-repurposer`)를 **물리 삭제하지 않고** `status: disabled` + 바인딩 해제만 했다. 정의·파일은 남겨 두고 참조 검사 후 다음 단계에서 지운다. growth-marketing 38 → 17. `sales-operations`는 마케팅 저장소가 아니라 `source: local` 자체 제작 스킬이라 되살려 유지(1차 목록에 잘못 들어갔던 것). `ui-ux-pro-max`는 `status: shadow` — 정의는 남기고 바인딩만 해제해 대체 스킬과 비교용으로 보관.

`skill-definitions.json`에 `status` 필드 신설(active/shadow/disabled), `verify_routing.py`가 **active가 아닌 스킬이 바인딩되면 에러**를 내도록 게이트 추가. 작업당 스킬 상한은 이미 `validate_selected_skills(limit=3)`로 강제되고 있어 `task-profiles.json`은 비운 채 유지(라우팅 검사가 그걸 요구함).

**공용 풀 전환** — 심볼릭 링크는 Windows·git·배포에서 깨지므로 쓰지 않고, 런타임이 풀 경로를 직접 참조하게 바꿨다. `skills/<id>/` 1부만 두고 `employees/*/*/skills/`에는 `_local-role-core`만 남긴다. `main.SKILL_POOL_PATH` 신설, `employee_security()`가 풀 경로를 보고 lock을 **스킬 id 키**로 조회. `install_skills.py`(풀에 1회 설치), `verify_skills.py`(id당 1회 해시 검증), `refresh_local_skill_lock.py`, `render_skill_indexes.py`, `audit_package.py` 동반 수정.

**VFF2 진단 원칙 흡수**: `constitution/DIAGNOSIS.md` 신규(결론 우선·측정 먼저·불확실성 공개·단서 전체 설명·완료 전 검증) — 스킬이 아니라 헌법으로 넣어 24명 전원 상속, 선택 슬롯을 쓰지 않는다. `audit_package.py`가 5번째 헌법 참조를 강제.

- 정의 126 → 116(active 97 / disabled 18 / shadow 1), 바인딩 합계 125, lock 372 → 98 entries.
- 디스크 `employees/` 24M → 948K, 공용 풀 `skills/` 6.8M. 중복 복사본 323개 제거, 미바인딩 잔여 폴더 139개 정리.
- `TASK_KINDS`에서 담당 스킬이 사라진 6종(`paid_acquisition`, `app_store_optimization`, `lifecycle_marketing`, `community_growth`, `partner_marketing`, `seo_growth`) 제거 — `test_lifecycle_capabilities`가 "모든 특화 task_kind는 바인딩된 스킬을 가져야 한다"를 강제하므로 스킬만 빼면 실패한다.
- fixture 2종(`policy_market_research_ui_skill_001`, `policy_test_engineering_skill_011`)은 `ui-ux-pro-max` 대신 여전히 바인딩된 `design-first-ui-prompting`으로 교체 — 검사 대상은 "바인딩 없음"이 아니라 **task_kind 정책 차단 경로**라 바인딩된 UI 스킬이어야 의미가 있다.
- `GROW`의 `positioning-statement` 깨진 참조(정의·설치본 모두 없음) 제거: `EMPLOYEE.md`, `SKILLS.md`, `reference/corporate-os/02-EMPLOYEE_REGISTRY_v6.2.md`.

검증: `pytest apps/api` 163 passed, 실패 4건은 baseline과 동일(`test_runtime_hardening` 2 + 문서 fixture 2, HEAD 워크트리에서 동일 재현 확인). `audit_package` OK, `verify_routing` OK, `verify_skills` 0.

**남은 일**: disabled 18개 물리 삭제(참조 검사에서 코드 참조는 발견되지 않음, 바이너리 이미지 파일명 오탐만 있었음), shadow `ui-ux-pro-max` A/B, Meng To·Vercel 선별 추가는 보류(현행 유지 결정).

---

## 진행 중

**⚠️ 위 10~13번 항목과 겹침 주의.** 아래 두 "점유" 항목이 나열하는 파일(`schema.py`, `artifacts.py`, `routes.py`, `design.py`, `test_vibeoffice_handoff.py`, `test_vibeoffice_contracts.py`) 중 상당수를 이 세션이 이미 수정·완료했다(§10~13). Kiro 세션이 이 항목을 아직 "진행 중"으로 보고 같은 파일을 다시 건드리면 충돌한다 — 이 절을 다시 읽는 세션은 먼저 `git status`/`git diff`로 실제 파일 상태를 확인하고, 이미 끝난 부분은 재작업하지 말 것.

### LAUNCH_HARNESS_PLAN B0 + S0~S3.5 보강 (Kiro 세션 점유, 2026-07-30 시작)

다른 세션이 S4(`apps/api/vibeoffice/build.py`, `test_vibeoffice_build.py`)를 진행 중이라 겹치지 않는 영역만 잡는다.

**점유 파일:**

```text
apps/api/agent_tools.py           (rg 부재 시 순수 Python fallback 검색기 추가)
scripts/preflight.py              (신규)
apps/api/vibeoffice/artifacts.py  (STALE_IMPACT에 S3 산출물 추가)
apps/api/vibeoffice/routes.py     (GET /handoffs/{id} 라우트 추가)
apps/api/test_vibeoffice_handoff.py, test_vibeoffice_contracts.py (해당 회귀 테스트)
```

실측 기준선(2026-07-30, `rg` PATH 상태): **161건 전부 통과.** S1~S3.5가 이미 상당히 견고하다 — 각 슬라이스가 자체 Gate(B/C/D·E/PE)와 `REWORK_REQUIRED` 반송 경로, 순수 함수 재현성 테스트를 갖추고 있었다. 재작업하지 말 것.

완료 사항:

1. **B0** — `apps/api/agent_tools.py`의 `search_files`에 `rg` 부재 시 순수 Python fallback(`_search_files_fallback`) 추가. `find_symbols`/`find_references`는 `search_files`를 재사용해 자동으로 fallback 적용. `scripts/preflight.py` 신설(`rg`/`node`/`.venv`/`git` 점검, 없어도 `[WARN]`만 내고 종료 코드 0 유지).
2. **artifacts.py stale 전파 보강** — `STALE_IMPACT[CHANGE_TECH_STACK]`에 S3 산출물(`ARTIFACT_API_CONTRACT`/`ARTIFACT_DATA_MODEL`/`ARTIFACT_TECHNICAL_TASKS`) 추가. 가이드 §9 "기술 스택 변경 → Architecture·API·Data Model·Tasks"를 실제로 지키게 됐다. 부수적으로 `schema.py`의 `S35_TRANSITIONS`에 `ARCHITECTURE_REVIEW → STALE_ARTIFACTS` 엣지가 빠져 있어 이 stale 전파 자체가 도달 불가능했던 것도 함께 고쳤다.
3. **`GET /handoffs/{handoff_id}` 라우트 추가** — `handoff.get_handoff`가 라우트 없이 테스트에서만 호출되는 죽은 코드였다. `routes.py`에 엔드포인트 추가, 404 매핑.

수정 후 실측: `test_vibeoffice_handoff` 39건, `test_vibeoffice_contracts` 18건, 전체 `discover` **165건 중 164건 통과, 1건 실패**(`test_job_workflow.test_navi_to_review_completes_with_one_user_choice`).

**이 1건 실패는 내 작업과 무관하다 — 손대지 않았다.** 원인: 어떤 세션이(S4도 아니고 나도 아님) `apps/api/main.py`·`apps/api/worker.py`의 리뷰어 배정 로직을 `"LENS" if lead == "GUARD" else "GUARD"`에서 `reviewer = "NAVI"` 고정으로, 모델 선택도 `task_model_assignment`/`final_completion_model` 같은 새 헬퍼로 바꿔놓았다(`git diff HEAD -- apps/api/worker.py` 168줄 변경, 아직 어떤 커밋에도 없음). 오래된 테스트 단정이 `{"GUARD"}`를 기대해서 깨진다. `main.py`/`worker.py`는 VibeOffice 슬라이스 소유가 아니라 손대지 않았다. **다음에 이 파일을 만지는 세션은 먼저 `test_job_workflow.py`의 리뷰어 단정을 이 변경에 맞게 갱신할 것.**

### 제품 계층 S2 — 기획 승인 → 디자인 패키지 + handoff 계약 (Kiro 세션 점유)

담당: Kiro 세션 (2026-07-30 12:3x 시작). 근거: [VIBEOFFICE_IMPLEMENTATION_GUIDE.md](VIBEOFFICE_IMPLEMENTATION_GUIDE.md) §7 S2, `reference/product-context/05A_DEPARTMENT_HANDOFF_CONTRACTS.md` §3, `schemas/department-handoff.schema.json`, 09A Gate C.

**점유 파일 — 다른 세션은 건드리지 말 것:**

```text
apps/api/vibeoffice/handoff.py        (신규)
apps/api/vibeoffice/design.py         (신규)
apps/api/vibeoffice/artifacts.py      (신규)
apps/api/vibeoffice/schema.py         (테이블 3개 추가)
apps/api/vibeoffice/models.py         (handoff 모델 추가)
apps/api/vibeoffice/routes.py         (엔드포인트 추가)
apps/api/test_vibeoffice_handoff.py   (신규)
```

`apps/api/main.py`는 **추가로 건드리지 않는다.** S1에서 넣은 라우터 mount 한 줄로 신규 엔드포인트까지 함께 열린다.

### main.py 리팩토링 1차 — 자립 블록 2개 분리 (Kiro 세션, 2026-07-31)

`apps/api/main.py`가 2,940줄 / 21개 요청 모델 / 100개 이상 함수 / 라우트 핸들러 50여 개를 한 파일에 담고 있었다. 가이드 §2 코드 원칙 5번("신규 코드는 `main.py`에 넣지 않는다")은 이미 신규 기능에 적용돼 있지만, 기존 덩어리 자체는 그대로였다.

| 신규 파일 | 옮긴 것 |
|---|---|
| `apps/api/api_models.py` | Pydantic 요청 바디 21개 클래스 |
| `apps/api/mcp_client.py` | `mcp_headers`·`mcp_http_call`·`mcp_initialize` |

`main.py`는 두 모듈을 **이름으로 import해서 재수출**한다. `main.CreateTask`, `main.mcp_initialize` 같은 기존 참조가 전부 그대로 동작한다. 결과: 175,860 → 170,582자 (5,278자 감소).

**옮기지 않은 것과 그 이유 (중요 — 나중에 "왜 이것만 옮겼나" 싶을 때 볼 것):** 테스트는 `patch.object(main, ...)`로 `model_client`, `model_key`, `select_roster_with_model`, `run_agent`, `require_skill_ready` 5개를 가로챈다. 이 패치는 `main`이 그 속성을 **직접 소유**하고 호출자가 `main.<name>`으로 접근할 때만 유효하다. 다른 모듈로 옮겨 재수출하면 import는 계속 동작하면서 **패치만 조용히 무력화**된다 — 테스트가 초록인데 실제로는 실모델을 호출하는 최악의 상태가 된다. 그래서 이 5개는 `main.py`에 남겼고, 스모크 체크(`patched_still_in_main_dict`)로 5개가 여전히 `vars(main)`에 있는지 확인했다.

**`mcp_client.KEYRING_SERVICE`를 재선언하지 않은 이유:** 값이 `"AI-Automation-Office"`인데 처음에 `"ai-automation-office"`로 잘못 베껼 뻔했다. 자격증명을 **쓰는** 쪽은 `main.save_mcp_connection`이고 **읽는** 쪽이 이 모듈이라, 리터럴이 두 곳에 있으면 한쪽만 수정되는 순간 keyring 조회가 조용히 `None`을 반환한다(인증 실패가 에러도 없이 발생). `_keyring_service()`가 `main`에서 지연 import로 읽어 오게 했다.

검증 (실측):

```bash
.venv/Scripts/python.exe -m unittest discover -s apps/api -p "test_*.py"   # 165건, 실패 1건(아래 기존 실패와 동일)
```

리팩토링 전 165건 중 1건 실패 → 리팩토링 후 165건 중 **같은** 1건 실패. 새 실패 0건. 추가로 스모크 체크로 확인: 요청 모델 21개 전부 `main`에서 resolve, MCP 헬퍼 3개 resolve, keyring 서비스명 일치, `/api/health`·`/api/runtime/version`·`/api/vibe/start-cards` 200, 라우트 75개(그중 `/api/vibe/*` 19개) 정상 마운트.

### main.py 리팩토링 2차 — 라우트 핸들러 51개 분리 (Kiro 세션, 2026-07-31)

S4 완료로 `main.py` 동시 편집이 멈춘 것을 확인한 뒤(수정 시각·줄 수 실측) 진행했다. 라우트 핸들러 52개 중 51개를 도메인별 모듈로 옮겼다.

| 신규 모듈 | 라우트 | 줄 수 |
|---|---|---|
| `apps/api/admin_routes.py` | 15 | 169 |
| `apps/api/project_routes.py` | 5 | 104 |
| `apps/api/job_routes.py` | 6 | 150 |
| `apps/api/task_routes.py` | 25 | 689 |

`main.py`: 2,809 → **1,903줄**. 1차(2,940 → 2,809)까지 합치면 **2,940 → 1,903 (−35%)**.

**되돌리지 말 것 — 이 리팩토링이 지켜야 하는 3가지:**

1. **`run_agent`는 `main.py`에 남는다.** `POST /api/tasks/{task_id}/agent/run` 핸들러(약 495줄)는 테스트가 `patch.object(main, "run_agent", ...)`로 가로챈다. 다른 모듈로 옮기면 import는 계속 되면서 **패치만 조용히 무력화**돼, 테스트는 초록인데 실제로는 실모델을 호출하고 비용이 발생한다. `model_client`·`model_key`·`select_roster_with_model`·`require_skill_ready`도 같은 이유로 `main.py`에 남겼다.
2. **라우트 모듈은 헬퍼를 `main.<name>`으로만 호출한다.** `from apps.api.main import database` 같은 직접 import는 금지 — 위 패치 의미가 깨진다. 순환 import는 `main.py`가 **파일 맨 아래에서** 라우터를 import하는 방식으로 해결했다(그 시점에 헬퍼가 전부 정의돼 있어 부분 초기화 모듈 객체로 안전).
3. **핸들러 함수 이름 51개를 `main.py`가 다시 import해 재수출한다.** 분리 전 모든 핸들러가 `main` 모듈 속성이었고, 테스트가 HTTP가 아니라 **직접** 호출하는 경우가 있다 — `test_runtime_hardening`이 `main.restore_checkpoint`를 직접 부른다. 재수출을 빼면 그 호출이 `AttributeError`가 된다(1차 시도에서 실제로 발생).

**라우트 등록 순서가 바뀐 것에 대한 검증:** 라우트가 모듈별로 묶이면서 75개 중 40개 위치가 이동했다. FastAPI는 등록 순서로 매칭하므로, 선언된 모든 경로에 대해 구체 URL을 만들어 `route.path_regex`로 리팩토링 전/후 승자 핸들러를 비교했다 — **79개 method+URL 쌍 전부 동일**. 경로가 서로를 가리는 관계가 없어 재정렬은 동작상 무해하다.

검증 (제가 하위 에이전트와 **독립적으로** 재실행한 실측):

```bash
.venv/Scripts/python.exe -m unittest discover -s apps/api -p "test_*.py"
```

| 항목 | 리팩토링 전 | 후 |
|---|---|---|
| 테스트 | 165건 중 1 실패 | 165건 중 **같은** 1건 실패 |
| 전체 라우트 | 75 | 75 |
| `/api/vibe/*` | 19 | 19 |
| (path, method) 쌍 | 79 | 79 |

`handlers_missing_on_main` 0건, `models_missing_on_main` 0건, `mcp_missing_on_main` 0건, 패치 대상 5개 전부 `vars(main)`에 존재. `/api/health`·`/api/runtime/version`·`/api/vibe/start-cards`·`/api/registry/employees`·`/api/tasks`·`/api/projects`·`/api/lessons`·`/api/usage/summary` 전부 200, 없는 경로는 404.

그 1건 실패는 다른 세션의 미커밋 리뷰어 변경(GUARD→NAVI) 때문이며 리팩토링과 무관하다 — 아래 해당 항목 참조.

**발견한 기존 결함(그대로 둠):** `run_meeting`의 예외 분기가 정의되지 않은 `settings`를 참조한다. 첫 문장이 `raise HTTPException(410, ...)`이라 도달 불가능한 죽은 코드이므로 "고치지 않고" 그대로 옮겼다. 손대려면 별도 작업으로 할 것.

## 미완료 — 아직 손대지 않음

우선순위 순. 상세는 [RUNTIME_ROADMAP.md](RUNTIME_ROADMAP.md), [VIBEOFFICE_GAP_ANALYSIS.md](VIBEOFFICE_GAP_ANALYSIS.md).

1. ~~**Fixture 30~50개로 확장**~~ → **완료 (31건, §7).** 더 늘릴 때는 §7의 격리 검증 절차를 반드시 따를 것.
2. **실제 모델 호출 fixture** — 현재 harness는 `main.run_agent`를 mock한다. 실모델·실 Git diff·실 테스트로 도는 별도 CI 경로가 아직 없다. **P2에서 남은 가장 큰 항목이다.**
3. **24명 조직의 실제 동시 실행 pool** — 현재는 직원별 세션·권한·스킬·기록을 가진 역할 실행자다. 24개 독립 지속 에이전트가 아니다. 장기 메모리와 전문 도구 분리가 없다.
4. **회의 fallback 팀장 실행** — 제거하거나 사용자 승인 필수로 바꿀지 미결정. 승인 게이트를 택하면 기존 `permission_rules` ask→HTTP 428 메커니즘을 재사용한다.
5. ~~**문서·UI·runtime 상태 불일치 CI**~~ → **완료 (§8).** 검사기는 있으나 아직 CI 파이프라인에 등록되지 않았다 — 등록은 남은 일이다.

---

## 알려진 환경 문제 (코드 결함 아님)

- ~~**`ripgrep` (`rg`) 미설치**~~ → **해결됨 (2026-07-30 11:2x).** `winget install BurntSushi.ripgrep.MSVC`로 설치. 설치 경로는 `%LOCALAPPDATA%\Microsoft\WinGet\Packages\BurntSushi.ripgrep.MSVC_*\ripgrep-15.2.0-x86_64-pc-windows-msvc\rg.exe`이며, 디렉터리 이름은 15.2.0이지만 `rg --version`은 **14.1.1**을 보고한다. `apps/api/test_agent_tools.py` 3건이 통과로 바뀐다.
  **중요 — 3 error를 코드 결함으로 오진하지 말 것.** 이 3건은 `rg`가 PATH에 없을 때만 실패한다. 새 셸에서 PATH가 갱신되지 않은 경우가 흔하다. PowerShell: `$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')`. Git Bash: 위 설치 경로를 `PATH`에 `export`한다. 실패가 이 3건뿐이면 환경 문제이지 회귀가 아니다.
- **`rg --version`이 세션마다 다르게 보이는 것은 정상이다. 쫓지 말 것.** 실측으로 확인했다: winget `rg.exe`를 절대경로로 호출하면 **15.2.0 (rev e89fff89ac)**, 같은 셸에서 그냥 `rg`를 호출하면 **14.1.1 (rev f6d0fcd24a)** 이 나온다. winget 디렉터리에는 `rg.exe` 하나뿐이고 기본 PATH에는 `rg`가 아예 없다(`which: no rg`). 즉 에이전트 셸이 **PATH에 노출되지 않는 번들 ripgrep을 먼저 잡는다.** 이전 기록의 "14.1.1이 보이면 잘못된 바이너리"라는 진단은 원인은 맞지만 결론이 틀렸다 — **두 버전 모두 테스트를 통과시키므로 조치할 것이 없다.** 버전 불일치를 원인으로 의심하며 시간을 쓰지 말고, `test_agent_tools` 3건이 통과하는지만 볼 것.
- 루트에 `_verify.py`, `_mountcheck.py`, `_scratch_*.txt`, `.vo_*.txt` 같은 임시 스크립트가 남아 있을 수 있다. 추적되지 않는 스크래치 파일이며 제품 코드가 아니다. 커밋에 포함시키지 말고, 발견하면 지워도 된다.
- **`test_agent_worktree_requires_review_gate_before_base_integration` 1건은 git identity 미설정 시 error가 된다.** `git config user.email`/`user.name`이 로컬에 없으면 `agent_worktree.integrate_reviewed`의 cherry-pick이 "Please tell me who you are"로 실패한다. 코드 결함 아님 — 이 세션은 사용자 git config를 임의로 바꾸지 않았으므로 그대로 둠. 고치려면 `git config --global user.email/user.name`을 실행할 사람이 직접 설정할 것.
- **HWPX 렌더러 미설치 시 3건 error** (`test_fixture_harness`의 `document-hwpx-4-korean-005`/`document-office-formats-001`, `test_runtime_hardening`의 `test_markdown_renders_to_office_formats_and_manifest`). `artifact_renderer.render_bundle`이 외부 HWPX 변환 도구를 요구하는데 이 머신엔 없다. 위 `rg` 항목과 같은 성격 — 실패가 이 3건 + git identity 1건뿐이면 baseline이지 회귀가 아니다.
- **이 머신에는 원래 진짜 Python이 없었다** (`WindowsApps\python.exe`는 스토어 실행 스텁). `winget install Python.Python.3.12`로 설치 후 `.venv` 재생성, `pip install -r requirements.txt`, `apps/web`은 `npm install` 필요(`node_modules` 없었음). 새 세션에서 `.venv/Scripts/python.exe -m unittest ...`가 즉시 실패하면 이 문제부터 의심할 것.
- **배경 프로세스를 남기지 말 것.** `Start-Sleep -Seconds 3600` 같은 대기 명령으로 터미널을 붙잡아 두면 다른 세션의 셸이 응답하지 않게 된다. 실제로 한 번 발생했다. 작업이 끝나면 프로세스를 종료할 것.

## 전체 검증 명령

```bash
.venv/Scripts/python.exe -m unittest discover -s apps/api -p "test_*.py"
```

기준선: **63건 전부 통과** (2026-07-30 12:29, `rg`를 PATH에 올린 상태에서 실측. 라우터 mount 후 재확인).

숫자가 세 번 바뀐 이유를 남긴다 — 두 세션이 서로의 추가분을 모르고 측정한 결과다. 앞으로는 이 표를 갱신할 것.

| 실측 시점 | 건수 | 구성 |
|---|---|---|
| ripgrep 설치 전 | 32 (E 3) | S1·조사품질 이전 |
| 조사 품질 모듈 추가 후 | 45 | 32 + `test_research_quality` 13 |
| S1 추가 후 | 63 | 45 + `test_vibeoffice_intake` 18 |
| S2 + 문서 검사기 추가 후 (현재) | **113** | 63 + `test_vibeoffice_handoff` + `test_docs_consistency` 20 |

이보다 실패가 늘면 회귀다. `rg`가 PATH에 없으면 `test_agent_tools` 3건이 error가 되는데, 그건 환경 문제이지 회귀가 아니다.

같은 방식으로 확인한 나머지 검증 (전부 exit 0):

```bash
.venv/Scripts/python.exe scripts/verify_routing.py      # 24 employees, 8 departments, 0 static profiles, 16 standards
.venv/Scripts/python.exe scripts/verify_skills.py --employee ALL   # 바인딩 66건 lock hash 일치
.venv/Scripts/python.exe scripts/audit_package.py       # employees=24, bindings=169, skills=126
cd apps/web && npm.cmd test -- --run && npm.cmd run build          # vitest 4 passed, build OK
```
