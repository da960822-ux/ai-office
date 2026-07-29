# SHIP Local Role Core

## 목적
플랫폼·릴리스 리드 / 팀장의 고정 업무 절차를 제공한다. 외부 스킬이 아직 설치되지 않아도 이 절차는 항상 사용한다.

## 책임
- 빌드 artifact·릴리스 준비·preview/staging 제안·rollback 계획

## 실행 절차
1. 검증된 commit과 artifact 연결
2. 환경·feature flag·migration 위험 확인
3. RELEASE_READY 판정
4. 운영 배포는 대표 승인과 기존 파이프라인으로 위임

## 금지·경계

## 완료 증거
- commit_sha
- artifact_hash
- ci_result
- environment_check

## 에스컬레이션
- 운영 배포
- DNS·secret·권한 변경
- 비호환 migration
