# Corporate OS v6.2 — Token Efficiency Research & Application

> 조사 기준일: 2026-07-28  
> 범위: 공식 API 문서와 공개 연구를 Corporate OS의 실행 하네스에 적용  
> 주의: 논문 결과는 특정 벤치마크·모델의 결과이며 그대로 재현된다고 보장하지 않는다.

## 결론

가장 실용적인 절감 방법은 “프롬프트를 짧게 쓰기” 하나가 아니다.

```text
필요한 직원만 선택
→ 필요한 스킬의 CORE만 로드
→ 저장소는 JIT로 필요한 범위만 조회
→ 반복 prefix는 캐시
→ 오래된 tool result는 artifact로 치환
→ 임계 초과 시에만 고충실도 압축
→ 저가 모델에서 시작해 품질 gate 실패 시 승격
```

Corporate OS에는 이 순서를 기본 하네스로 반영한다.

---

## 1. Context engineering

Anthropic은 에이전트의 context를 제한된 주의 자원으로 보고, 원하는 행동을 만들 수 있는 가장 작은 고신호 토큰 집합을 구성할 것을 권고한다. 특히 다음 패턴이 Corporate OS와 직접 맞는다.

- 파일 전체를 미리 넣는 대신 경로·검색·head/tail·grep을 통한 JIT 조회
- 대화가 길어질 때 compaction
- 외부 NOTES·상태 파일을 통한 구조화된 메모리
- 서브에이전트가 탐색 원문 대신 압축된 결과만 반환
- 오래된 tool result 제거

적용:

- `ContextPacker`는 role·stage별 must/retrieve/exclude 목록을 사용한다.
- raw output은 `runs/{run}/artifacts/`에 저장한다.
- 상위 에이전트에는 finding·evidence pointer·uncertainty만 전달한다.

출처: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

---

## 2. Prompt/context caching

OpenAI·Anthropic·Google의 공식 문서는 반복되는 공통 prefix를 앞에 두고 동적 입력을 뒤에 배치하면 캐시 hit 가능성이 높아진다고 안내한다.

적용:

```text
고정: 헌법 → Runtime → Role → tools → output schema → skill CORE
동적: 작업 계약 → 파일 일부 → 최신 상태 → 질문
```

- provider adapter가 cached token·cache write·cache hit를 usage ledger에 기록한다.
- 캐시를 위해 무관한 오래된 내용을 보존하지 않는다.
- 고정 prefix의 직렬화 순서와 hash를 version 관리한다.

출처:

- https://developers.openai.com/api/docs/guides/prompt-caching
- https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- https://ai.google.dev/gemini-api/docs/caching

---

## 3. Tool context 관리

Anthropic의 공식 가이드는 큰 도구 집합과 누적 tool result를 줄이기 위해 tool search, programmatic tool calling, prompt caching, context editing을 구분한다.

적용:

- 모든 tool schema를 매번 로드하지 않고 ToolRegistry description만 검색한다.
- 반복되는 읽기·변환 체인은 가능한 한 sandbox script 한 번으로 묶는다.
- 처리된 tool result는 artifact pointer로 대체한다.
- 안정된 tool schema는 cache prefix에 둔다.

출처: https://platform.claude.com/docs/en/agents-and-tools/tool-use/manage-tool-context

---

## 4. SkillReducer와 progressive disclosure

2026년 SkillReducer 사전 공개 연구는 55,315개의 공개 스킬을 분석해 라우팅 설명 누락·장황함과 비실행성 본문의 비중을 문제로 제시한다. 600개 스킬 평가에서는 설명과 본문을 줄이면서 기능 품질이 유지되거나 개선되는 결과를 보고했다.

Corporate OS 적용:

```text
manifest description → CORE → references/examples → scripts
```

- description은 라우팅 용도만 담당한다.
- CORE는 실행 규칙·금지·검증만 유지한다.
- 배경과 예시는 on-demand reference로 이동한다.
- 스킬 최적화는 shadow task와 faithfulness 검사 후 승인한다.

출처: https://arxiv.org/abs/2603.29919

---

## 5. 역할 기반 context routing

RCR-Router 연구는 멀티에이전트가 전체 메모리를 공유하는 대신 역할과 현재 단계에 관련된 subset만 strict token budget 아래 전달하는 방식을 제시한다. 해당 논문은 일부 QA 벤치마크에서 토큰을 줄이면서 품질을 유지하거나 개선했다고 보고한다.

Corporate OS 적용:

- FRONT는 UI 계약·관련 symbol·브라우저 로그만 받는다.
- SHIELD는 trust boundary·권한 diff·의존성만 받는다.
- VOICE는 제품 사실·대상 독자·브랜드 보이스만 받는다.
- 회의 대화 전체가 아니라 구조화된 결정만 공유 메모리에 남긴다.

출처: https://arxiv.org/abs/2508.04903

---

## 6. 장기 작업 context 압축

ACON은 history와 observation을 항상 압축하지 않고 길이 임계치를 넘을 때 적용하며, 실패 분석으로 보존 지침을 개선한다. 2026 개정 논문은 일부 장기 에이전트 벤치마크에서 peak token 감소와 성공률 개선을 보고한다.

Corporate OS 적용:

- 짧은 작업에는 compressor를 추가 호출하지 않는다.
- 프로젝트·환경별 보존 항목을 benchmark failure에서 갱신한다.
- 압축 대상은 대화·tool output이고, Evidence 원본은 외부 artifact로 보존한다.
- 압축기는 Deep worker가 아니라 Cheap 또는 로컬 규칙을 우선한다.

출처: https://arxiv.org/abs/2510.00615

---

## 7. 캐시 연속성과 pruning의 충돌

TokenPilot은 context를 자주 재배열·삭제하면 prefix cache가 무효화되어, 토큰 수는 줄어도 실제 비용이 커질 수 있다는 문제를 다룬다. 2026 사전 공개 연구이므로 Corporate OS는 아이디어만 채택하고 자체 계측으로 검증한다.

Corporate OS 적용:

- 매 turn마다 앞부분을 다시 쓰지 않는다.
- compaction은 checkpoint·batch 경계에서 수행한다.
- 제거 전 raw artifact를 저장한다.
- `uncached_input_tokens`와 `total_input_tokens`를 분리 측정한다.

출처: https://arxiv.org/abs/2606.17016

---

## 8. 모델 라우팅과 cascade

RouteLLM 등 모델 라우팅 연구는 쉬운 요청을 저렴한 모델에 보내고 어려운 요청만 강한 모델로 보내 품질·비용을 절충한다.

Corporate OS의 V1은 학습형 라우터보다 설명 가능한 규칙 기반 cascade로 시작한다.

```text
Deterministic
→ Cheap
→ Balanced
→ Deep
```

승격 조건:

- high/critical risk
- acceptance 해석 충돌
- 보안·아키텍처 결정
- 동일 접근의 검증 실패
- Cheap/Balanced 결과가 평가 rubric 미달

출처: https://arxiv.org/abs/2406.18665

---

## 9. Corporate OS 적용 우선순위

### 즉시 적용

1. 직원·스킬 description-only 라우팅
2. progressive disclosure
3. JIT 파일 조회
4. 안정된 prefix와 provider cache usage 계측
5. tool result artifact 치환
6. 규칙 기반 모델 cascade
7. output schema·길이 제한

### 기준 과제 후 적용

1. LLM 기반 compaction
2. task-specific 압축 지침 최적화
3. 학습형 model router
4. automatic skill debloating

### V1에서 적용하지 않음

1. 의미 손실을 검증하지 않은 공격적 token pruning
2. 모든 기록의 자동 요약
3. 비용만을 목표로 한 품질 gate 제거
4. 스킬 자동 다운로드·자동 업데이트

---

## 10. 평가 설계

기준 과제별로 baseline과 token-efficient run을 동일 commit·동일 acceptance로 비교한다.

```yaml
result:
  task_success: true
  evidence_complete: true
  uncached_input_tokens: 0
  cached_input_tokens: 0
  output_tokens: 0
  tool_result_tokens_retained: 0
  active_profiles: []
  loaded_skills: []
  deep_calls: 0
  elapsed_ms: 0
  estimated_cost: 0
```

판정:

```text
품질·보안·증거 유지 + 비용 감소 → 채택
비용 감소 + 품질 저하 → 기각
품질 향상 + 비용 소폭 증가 → 위험도·가치에 따라 판단
측정 불가 → 최적화 완료로 보고하지 않음
```


## v6.2 적용 보완

스킬을 직원 폴더에 실제 설치하는 것과 매번 전체 스킬을 프롬프트에 주입하는 것은 다르다. v6.2는 역할 소유권은 파일 시스템으로 명확하게 만들고, 라우팅은 `SKILL_INDEX.md`, 실행은 선택된 `SKILL.md`만 사용하는 방식으로 둘을 양립시킨다.
