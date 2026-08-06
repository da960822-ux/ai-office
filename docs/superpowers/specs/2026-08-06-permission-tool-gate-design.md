# 권한 → 도구 게이트 설계

날짜: 2026-08-06

## 문제

`employees/*/*/PERMISSIONS.yaml` 24개는 서로 다른 `permissions` 목록을 갖지만, `main.py:1525`에서 프롬프트 문자열로만 주입되고 실제 도구 호출을 막는 코드가 없다. `P0_READ`(읽기 전용) 직원도 `replace_exact_text`/`create_file`을 실제로 호출할 수 있다.

## 실측 (설계 전 확인)

- `permissions` 코드는 실제로 18종이다(1차 PM 리뷰에서 가정한 6종은 오판): `P0_READ`, `P1_PROPOSE`, `P2_ANALYTICS_DOC_WRITE`, `P2_ARCH_WRITE`, `P2_CONTENT_WRITE`, `P2_DESIGN_SPEC_WRITE`, `P2_DOC_WRITE`, `P2_MARKETING_DOC_WRITE`, `P2_SPEC_WRITE`, `P2_STATE_WRITE`, `P2_WRITE_SCOPED`, `P3_DOC_CHECK`, `P3_PROCESS_CONTROL`, `P3_SECURITY_SCAN`, `P3_TEST_LOCAL`, `P4_EVIDENCE_READ`, `P4_EVIDENCE_WRITE`, `P4_GIT_SAFE`, `P4_REVIEW`, `P5_STAGING_WITH_APPROVAL`.
- `network`/`scripts`/`write_scope`/`external_skill_default_mode` 4개 필드는 24개 파일 전부 동일한 값이다. 이미 다른 메커니즘으로 전역 집행 중이라 값이 갈릴 이유가 없다: `network: deny_by_default`는 `agent_tools.py:120`의 private/local 주소 차단으로, `write_scope: task_contract_only`는 `WorkspaceAgentTools`의 `allowed_paths` 검사로 이미 실집행됨. **이번 작업 대상 아님.**
- 도구 필터 지점이 이미 존재한다(`main.py:1520-1534`, `enabled_bounded_tools` 집합). `TaskContract.allowed_commands`에 따라 `git_commit`/`git_push`를 켜고, `payload.employee_id == "NAVI"`면 write류를 하드코드로 뺀다. **이 패턴을 확장한다. 새 메커니즘을 만들지 않는다.**

## 결정 사항

### Tier 매핑

18개 코드 중 도구 단위로 실제 구분 가능한 것만 매핑한다. `P2_*` 9종은 전부 같은 쓰기 도구(`create_file`/`replace_exact_text`/`apply_unified_patch`)를 쓰므로 tier에서 하나로 합친다 — "무엇을 쓰는가"(마케팅 문서 vs 아키텍처 문서)는 도구가 구분할 수 없고 내용 taxonomy가 필요하며, 이는 이전 스펙(`2026-08-06-department-pipeline-gate-design.md`)에서 `must_handoff` 검증을 제외한 것과 동일한 한계다.

| Tier | 코드 | 추가 tool |
|---|---|---|
| read | P0_READ, P1_PROPOSE | list_files, read_file, search_files, find_symbols, find_references, git_status, git_diff, discover_tests, language_diagnostics, read_required_skill |
| write_content | P2_ANALYTICS_DOC_WRITE, P2_ARCH_WRITE, P2_CONTENT_WRITE, P2_DESIGN_SPEC_WRITE, P2_DOC_WRITE, P2_MARKETING_DOC_WRITE, P2_SPEC_WRITE, P2_STATE_WRITE, P2_WRITE_SCOPED | create_file, replace_exact_text, apply_unified_patch |
| verify | P3_DOC_CHECK, P3_TEST_LOCAL, P3_SECURITY_SCAN | run_verification |
| evidence | P4_EVIDENCE_WRITE | record_research_claim |
| git_safe | P4_GIT_SAFE | git_commit (기존 `"git commit *" in allowed_commands` 체크와 AND) |
| staging | P5_STAGING_WITH_APPROVAL | git_push (기존 `"git push *" in allowed_commands` 체크와 AND) |
| (미매핑) | P3_PROCESS_CONTROL, P4_EVIDENCE_READ, P4_REVIEW | 없음 — 대응하는 agent tool 개념이 없음(프로세스 제어는 API 레벨 동작, evidence read/review는 tool call이 아니라 컨텍스트 주입/별도 리뷰 job). YAML엔 유지하되 이 게이트에서는 no-op. |

### 위반 시 처리

허용 안 된 tool은 애초에 `tools` 배열에서 제외한다(모델이 존재 자체를 모름). 기존 `enabled_bounded_tools` 계산 직후 permission tier의 합집합과 **교집합**을 취한다 — TaskContract가 막으면 permission이 허용해도 막히고, 그 반대도 마찬가지. NAVI 하드코드는 그 위에 추가 제약으로 유지(변경 없음).

### 범위 제외

- `P2_*` 9종의 내용 기반 세부 구분 — 산출물 taxonomy 필요, 후속 스펙.
- 웹 도구(`web_search`/`read_web_source`/`fetch_public_source`/`fetch_public_pdf`/`render_public_page`) — 18개 코드 어느 것도 웹 접근을 명시하지 않는다. 코드를 새로 발명해 24개 직원 YAML을 바꾸는 건 이번 스코프 밖(다른 세션에서 직원 권한 정의 자체를 재설계해야 함). 현재 상태(모두 접근 가능) 유지, 갭으로만 기록.
- `P3_PROCESS_CONTROL`/`P4_EVIDENCE_READ`/`P4_REVIEW` 대응 tool 신설 여부 — 필요성 불확실, 이번엔 안 함.

## 구현 계획 (다음 단계, 이번엔 실행 안 함)

1. `apps/api/main.py`에 `PERMISSION_TIER_TOOLS: dict[str, set[str]]` 상수 + `permission_tool_scope(employee_id: str) -> set[str]` 함수(순수 함수, PERMISSIONS.yaml 파싱은 기존 `main.py:486` 로직 재사용).
2. `main.py:1534` 이후, 기존 `tools = [...]` 필터링 줄에 permission scope 교집합 추가.
3. 단위 테스트: `P0_READ`만 가진 가상 직원이 `create_file` tool을 못 받는지, `P4_GIT_SAFE` 없는 직원이 `allowed_commands`에 `"git commit *"` 있어도 `git_commit`을 못 받는지(AND 검증), 매핑 없는 코드가 조용히 no-op인지.
4. 회귀: 기존 77개 테스트 통과 확인 — 특히 실제 정상 실행 경로에서 필요한 tool이 누락돼 job이 깨지지 않는지(각 직원의 PERMISSIONS.yaml이 실제 업무에 필요한 tier를 포함하는지 24개 파일 훑어서 사전 확인 필요).

## 리스크

기존 24개 PERMISSIONS.yaml이 "선언만 되고 아무 효과 없던" 상태였기 때문에, 실제로 집행을 켜면 일부 직원이 지금까지 (의도치 않게) 쓰던 tool을 못 쓰게 될 수 있다. 구현 단계에서 24개 파일 각각의 `permissions` 목록이 해당 직원의 실제 업무(task_kind)에 필요한 tier를 다 포함하는지 먼저 대조해야 한다 — 빠졌으면 YAML 수정이 선행돼야 하고, 이건 코드 변경보다 리스크가 크다(잘못하면 특정 직원이 조용히 막혀서 job이 전부 실패).
