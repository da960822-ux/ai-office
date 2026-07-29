# Skill Routing Index

이 파일은 설치 전 라우팅용 선언 인덱스다. 실제 실행은 로컬 `SKILL.md`와 lock 검증 후 허용한다.

## 로컬 기본 스킬

- `_local-role-core`: 직원 고정 역할·SOP·증거 기준

## 필수 공개 스킬
- `embedding-strategies` — `wshobson/agents:plugins/llm-application-dev/skills/embedding-strategies` · MIT · 설치 대상 `./skills/embedding-strategies/SKILL.md`
- `hybrid-search-implementation` — `wshobson/agents:plugins/llm-application-dev/skills/hybrid-search-implementation` · MIT · 설치 대상 `./skills/hybrid-search-implementation/SKILL.md`
- `rag-implementation` — `wshobson/agents:plugins/llm-application-dev/skills/rag-implementation` · MIT · 설치 대상 `./skills/rag-implementation/SKILL.md`
- `sql-optimization-patterns` — `wshobson/agents:plugins/developer-essentials/skills/sql-optimization-patterns` · MIT · 설치 대상 `./skills/sql-optimization-patterns/SKILL.md`

## 조건부 공개 스킬
- 없음

## 로딩 규칙

1. 라우팅 단계에서는 이 인덱스만 읽는다.
2. 작업에 선택된 스킬의 실제 `SKILL.md`만 기본 1~3개 연다.
3. `MISSING`, `UNLOCKED`, `HASH_MISMATCH` 상태의 스킬은 열지 않는다.
