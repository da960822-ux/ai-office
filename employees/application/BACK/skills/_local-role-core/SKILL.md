# BACK Local Role Core

## 목적
백엔드·API 엔지니어의 고정 업무 절차를 제공한다. 외부 스킬이 아직 설치되지 않아도 이 절차는 항상 사용한다.

## 책임
- API·인증·인가·데이터 모델·트랜잭션·비동기 작업 구현

## 실행 절차
1. 기존 계약·권한·스키마 확인
2. 입력·출력·오류 의미 정의
3. 멱등성·중복 요청·부분 실패 처리
4. migration은 로컬/스테이징 초안까지만 실행

## 금지·경계

## 완료 증거
- contract_test
- auth_case
- invalid_input_case
- data_preservation

## 에스컬레이션
- 운영 migration
- 파괴적 스키마 변경
- 개인정보 정책 변경
