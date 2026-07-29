# Skill Routing Index

이 파일은 설치 전 라우팅용 선언 인덱스다. 실제 실행은 로컬 `SKILL.md`와 lock 검증 후 허용한다.

## 로컬 기본 스킬

- `_local-role-core`: 직원 고정 역할·SOP·증거 기준

## 필수 공개 스킬
- `planning-and-task-breakdown` — `addyosmani/agent-skills:skills/planning-and-task-breakdown` · MIT · 설치 대상 `./skills/planning-and-task-breakdown/SKILL.md`
- `source-driven-development` — `addyosmani/agent-skills:skills/source-driven-development` · MIT · 설치 대상 `./skills/source-driven-development/SKILL.md`
- `writing-plans` — `obra/superpowers:skills/writing-plans` · MIT · 설치 대상 `./skills/writing-plans/SKILL.md`

## 조건부 공개 스킬
- `prd-development` — `deanpeters/Product-Manager-Skills:skills/prd-development` · CC-BY-NC-SA-4.0 · 별도 승인 후 설치
- `discovery-process` — `deanpeters/Product-Manager-Skills:skills/discovery-process` · CC-BY-NC-SA-4.0 · 별도 승인 후 설치
- `prioritization-advisor` — `deanpeters/Product-Manager-Skills:skills/prioritization-advisor` · CC-BY-NC-SA-4.0 · 별도 승인 후 설치
- `user-story` — `deanpeters/Product-Manager-Skills:skills/user-story` · CC-BY-NC-SA-4.0 · 별도 승인 후 설치

## 로딩 규칙

1. 라우팅 단계에서는 이 인덱스만 읽는다.
2. 작업에 선택된 스킬의 실제 `SKILL.md`만 기본 1~3개 연다.
3. `MISSING`, `UNLOCKED`, `HASH_MISMATCH` 상태의 스킬은 열지 않는다.
