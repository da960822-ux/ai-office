# Phase 0 — 직원별 실제 스킬 설치

```bash
python scripts/install_skills.py --employee ALL
python scripts/verify_skills.py --employee ALL
python scripts/render_skill_indexes.py
```

합격 조건: 활성 대상 직원의 모든 required skill에 실제 `SKILL.md`, commit SHA, tree hash가 존재한다.

---

# Corporate OS v6.2 — MVP 구현 범위

## 제품 한 문장

사용자의 소프트웨어 요청을 작업 계약으로 바꾸고, 격리된 환경에서 실행·검증한 뒤, 신뢰 가능한 증거가 있는 결과만 전달한다.

## 반드시 구현

1. 요청 → 작업 계약 변환
2. 24명 Registry와 필요한 직원만 선택하는 라우터
3. 6개 공통 Runtime
4. container/worktree 격리와 지정 파일 쓰기
5. 단순 상태 머신과 상태 전이 guard
6. 실제 build·test·lint 실행
7. Verifier 전용 Evidence Ledger
8. commit·artifact·log hash와 stale evidence 무효화
9. 코드·문서 범위의 체크포인트 복구
10. diff·증거·위험 중심 최종 보고
11. TokenBudgeter·ContextPacker·cache usage 계측
12. 사용자 로컬 스킬 inbox·instruction_only 등록·hash lock
13. 실제 이벤트를 표현하는 최소 24인 오피스 UI

## 전문성은 유지하되 V1 자동 실행을 제한

- 마케팅팀: 조사·포지셔닝·카피·측정 계획 허용, 광고·게시 자동 실행 금지
- SRE: 기본 건강도·실패율·runbook만, 완전한 온콜·SEV 플랫폼은 실제 운영 후
- SHIP: preview·staging 제안과 release manifest, 운영 배포는 승인 후 기존 CI/CD 사용
- 자기개선: 개선안·shadow evaluation까지만, 자동 적용 금지
- 스킬: 사용자가 로컬로 직접 삽입 가능, 기본 instruction_only·검토 후 Registry 승인, 외부 마켓·자동 다운로드 금지
- 외부 API: rollback 보장 대신 compensation 또는 manual 지정
- DB migration: 초안·위험 분석·staging 검증까지만

## V1에서 제외

- 24개 별도 실행 엔진과 장기 메모리
- 다중 사용자 SaaS·결제·멀티테넌시
- 스킬·템플릿 공개 마켓
- 8개 팀장 전사 회의 자동 호출
- 복잡한 circuit breaker 시각화
- 무승인 운영 배포·공개 게시·광고비 소비
- 프로덕션 migration 자동 실행
- 실데이터 없는 A/B 승자·SLO 성과 판정

## 토큰 효율 V1 합격 기준

기준 과제 A·B·C를 기존 v6 방식과 비교한다.

```yaml
must_improve:
  - uncached_input_tokens
  - tokens_per_success
  - unnecessary_skill_loads
must_not_regress:
  - task_pass_rate
  - required_evidence_coverage
  - security_gate
  - scope_compliance
```

권장 시작 기준선이며 절대 성능 보장은 아니다.

- 라우팅에는 직원·스킬 description만 사용한다.
- 활성 직원 프로필 외의 역할 본문은 0개 로드한다.
- 활성 스킬은 일반 작업 1~3개, 최대 4개다.
- 처리 완료된 대형 tool result는 artifact pointer로 교체한다.
- 동일 고정 prefix의 cache hit 여부와 cached token을 기록한다.
- Deep 모델 사용은 사유가 기록된 승격만 허용한다.
- 압축 전후 acceptance·오류·evidence ID 보존 테스트를 통과한다.

## BYO Skill V1 합격 기준

```text
로컬 폴더 선택
→ manifest 검사
→ 요청 권한·script·network diff 표시
→ instruction_only 등록
→ 직원에게 bind
→ shadow task 실행
→ 사용자 승인
→ hash 고정·approved 이동
→ revoke 가능
```

## 합격 데모

```text
요청 등록
→ 작업 계약과 활성 직원 표시
→ 격리 workspace 생성
→ 지정 파일만 수정
→ 변경 전 실패와 변경 후 성공 검증
→ Evidence Ledger 생성
→ 코드 변경 시 기존 evidence 무효화
→ GUARD 독립 판정
→ 최종 보고
```

## 구현 순서

1. Core Contract
2. Token-Efficient Context & BYO Skill
3. Safe Builder
4. Trusted Verification
5. Selective Collaboration
6. Office Experience
7. Controlled Expansion

조직 UI보다 1~3단계를 먼저 완성한다.
