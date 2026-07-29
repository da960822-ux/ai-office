# Skill Routing Index

이 파일은 설치 전 라우팅용 선언 인덱스다. 실제 실행은 로컬 `SKILL.md`와 lock 검증 후 허용한다.

## 로컬 기본 스킬

- `_local-role-core`: 직원 고정 역할·SOP·증거 기준

## 필수 공개 스킬
- `product-marketing` — `coreyhaines31/marketingskills:skills/product-marketing` · MIT · 설치 대상 `./skills/product-marketing/SKILL.md`
- `launch` — `coreyhaines31/marketingskills:skills/launch` · MIT · 설치 대상 `./skills/launch/SKILL.md`
- `customer-research` — `coreyhaines31/marketingskills:skills/customer-research` · MIT · 설치 대상 `./skills/customer-research/SKILL.md`

## 조건부 공개 스킬
- `positioning-statement` — `deanpeters/Product-Manager-Skills:skills/positioning-statement` · CC-BY-NC-SA-4.0 · 별도 승인 후 설치

## 로딩 규칙

1. 라우팅 단계에서는 이 인덱스만 읽는다.
2. 작업에 선택된 스킬의 실제 `SKILL.md`만 기본 1~3개 연다.
3. `MISSING`, `UNLOCKED`, `HASH_MISMATCH` 상태의 스킬은 열지 않는다.
