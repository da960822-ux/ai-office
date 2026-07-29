# Skill Routing Index

이 파일은 설치 전 라우팅용 선언 인덱스다. 실제 실행은 로컬 `SKILL.md`와 lock 검증 후 허용한다.

## 로컬 기본 스킬

- `_local-role-core`: 직원 고정 역할·SOP·증거 기준

## 필수 공개 스킬
- `api-and-interface-design` — `addyosmani/agent-skills:skills/api-and-interface-design` · MIT · 설치 대상 `./skills/api-and-interface-design/SKILL.md`
- `auth-implementation-patterns` — `wshobson/agents:plugins/developer-essentials/skills/auth-implementation-patterns` · MIT · 설치 대상 `./skills/auth-implementation-patterns/SKILL.md`
- `sql-optimization-patterns` — `wshobson/agents:plugins/developer-essentials/skills/sql-optimization-patterns` · MIT · 설치 대상 `./skills/sql-optimization-patterns/SKILL.md`
- `security-and-hardening` — `addyosmani/agent-skills:skills/security-and-hardening` · MIT · 설치 대상 `./skills/security-and-hardening/SKILL.md`

## 조건부 공개 스킬
- 없음

## 로딩 규칙

1. 라우팅 단계에서는 이 인덱스만 읽는다.
2. 작업에 선택된 스킬의 실제 `SKILL.md`만 기본 1~3개 연다.
3. `MISSING`, `UNLOCKED`, `HASH_MISMATCH` 상태의 스킬은 열지 않는다.
