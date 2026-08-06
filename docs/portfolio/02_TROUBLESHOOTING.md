# 트러블슈팅 문서: AI Office (Corporate OS v6.2)

실제 커밋 이력(`git log`) 기반으로 정리. 재현 조건 → 원인 → 해결 → 검증 순서로 기술한다.

---

## 1. Windows에서 스킬 해시 102개 중 98개가 불일치

**증상**
`verify_skills.py`가 새로 clone한 Windows 환경에서 서브디렉토리를 가진 스킬 102개 중 98개를 `HASH-MISMATCH`로 판정. macOS/Linux에서는 통과.

**원인**
두 가지가 겹쳤다.
1. `tree_hash()`가 파일의 상대 경로를 해시에 포함하는데, `str(Path)`로 변환하면 Windows는 백슬래시(`\`)로, 다른 OS는 슬래시(`/`)로 렌더링된다. 내용이 같아도 경로 문자열이 달라 해시가 달라짐.
2. `.gitattributes`가 없어서 Git for Windows의 `core.autocrlf=true`가 checkout 시점에 모든 LF를 CRLF로 재작성. `registry/skills.lock.json`은 LF 기준으로 기록돼 있어, 내용이 전혀 바뀌지 않은 파일도 checkout만으로 해시가 깨짐. 이 lock 시스템이 원래 잡아야 할 "변조"가 아니라 "정상 checkout"에서 오탐이 발생한 것.

**해결**
- `tree_hash()`의 경로 직렬화를 `str()` → `.as_posix()`로 변경해 플랫폼 무관하게 통일.
- `* text=auto eol=lf`로 `.gitattributes` 추가. 바이너리 타입은 제외 처리, `.cmd`/`.bat`/`.ps1`은 `cmd.exe`가 LF 전용 배치를 오해석하므로 CRLF 유지.
- 세 스크립트(`verify_skills.py`, `install_skills.py`, `refresh_local_skill_lock.py` 등)에 중복 복붙돼 있던 `tree_hash()`를 `scripts/skill_pool.py` 공용 모듈로 추출. 이렇게 안 하면 다음 수정 때 세 곳 중 하나를 빠뜨려 lock/verify가 다시 어긋날 수 있음.
- `registry/skills.lock.json`을 posix 경로 기준으로 일괄 재생성.

**검증**
`verify_skills.py` 102/102 통과, 백슬래시 경로 0건, 해시 불일치 0건(from-scratch 재계산 기준)을 직접 확인. (`b0dffdb`, `9ddabdc`)

**교훈**
크로스 플랫폼 프로젝트에서 "경로를 해시에 넣는다"와 "줄바꿈 문자를 신경 안 쓴다"는 각각 따로는 안 보이다가 Windows에서만 동시에 터지는 전형적 조합. lock 파일을 신뢰의 근거로 쓰는 시스템일수록 원본 바이트 자체를 플랫폼 무관하게 고정해야 한다.

---

## 2. 모델 응답 JSON 파싱 실패가 로그 없이 조용히 넘어감

**증상**
리뷰/회의 단계에서 모델이 기대한 JSON 형식이 아닌 응답을 반환하면 `except Exception: verdict, findings = "changes_requested", raw`로 조용히 대체값 처리. 실패와 정상 fallback이 로그상 구분 불가능해 디버깅 시 원인 추적 불가.

**원인**
모델 출력 파싱 실패를 캐치는 하되 어디에도 기록하지 않는 설계. 운영 중 이런 실패가 몇 번, 어느 단계에서 발생하는지 알 방법이 없었음.

**해결**
`record_parse_failure()` 헬퍼를 추가해 파싱 실패 시 `job_events`에 `parse.failure` 이벤트로 원본 응답 앞 2000자와 함께 기록. `integration_review_verdict`, `meeting_worker_assignment` 등 파싱 지점마다 삽입.

동시에 발견한 인접 문제: `maintain_job_lease()`의 `sqlite3.OperationalError` 캐치가 무한 재시도 루프였음 (`# A short SQLite writer overlap is not a dead worker. Retry next tick.` 주석과 달리 상한 없음). 연속 5회(~10초) 이상 lock 획득 실패 시 예외를 다시 던지도록 상한 추가.

**검증**
`apps/api/test_worker_hardening.py`에 60줄 분량 테스트 추가. 파싱 실패 이벤트 기록 여부, lock 재시도 상한 동작 검증. (`5ce5649`)

**교훈**
"실패해도 서비스는 안 죽게" fallback 처리 자체는 맞는 방향이지만, fallback이 조용하면 장애 원인 파악이 사실상 불가능해진다. 방어적 fallback과 관측 가능성(observability)은 항상 같이 가야 함.

---

## 3. 부서 파이프라인 게이트가 설정 파일 누락으로 HEAD 시점에 무력화

**증상**
`registry/department-boundaries.json`에 `stage` 필드가 빠져 있어, 부서 소유권 검증 게이트가 실제로는 아무것도 막지 못하는 상태로 HEAD에 커밋돼 있었음.

**원인**
게이트 로직(`main.py`)은 먼저 구현·커밋됐지만, 그 로직이 참조하는 레지스트리 파일에 필요한 필드를 채우는 커밋이 누락됨. 코드는 있는데 설정이 없어 조용히 통과(silently inert)하는 상태. 테스트가 이 조합을 못 잡았다는 뜻이기도 함.

**해결**
`department-boundaries.json`에 `stage` 필드 24줄 분량 추가. `scripts/verify_routing.py`에 stage 필드 존재 여부를 검사하는 정합성 체크 추가해 같은 종류의 "설정 누락"이 재발하면 CI에서 바로 걸리게 함.

**검증**
`verify_routing.py` 재실행 통과. (`61413ea`)

**교훈**
"코드는 배포됐지만 설정이 안 됐다"는 배포 사고의 흔한 패턴. 로직과 그 로직이 의존하는 데이터 파일을 분리해서 커밋하면, 둘 중 하나만 누락돼도 겉으로는 정상 동작처럼 보일 수 있어 별도 정합성 검사가 필수라는 걸 확인.

---

## 4. Fallback plan 경로가 부서 스테이지 게이트를 우회

**증상**
정상 플래닝 경로는 부서 소유권 게이트를 통과해야 하지만, 모델 응답 파싱 실패 등으로 fallback plan이 생성되는 경로는 같은 게이트를 거치지 않고 그대로 진행됨.

**원인**
게이트 체크가 "정상 플랜 생성" 코드 경로에만 있고, 예외 상황에서 쓰는 대체 경로(fallback)에는 동일 검증이 빠져 있었음. 정상 경로만 리뷰/테스트하고 예외 경로는 놓치는 전형적 누락.

**해결**
`apps/api/main.py`에서 fallback plan 생성 경로도 동일한 스테이지 게이트를 통과하도록 수정(33줄 변경). `test_department_pipeline.py`에 72줄 분량 회귀 테스트 추가해 우회 시나리오를 명시적으로 커버.

**검증**
신규 테스트로 fallback 경로도 게이트를 통과해야만 진행됨을 확인. (`9ef703a`)

**교훈**
보안·정합성 게이트를 넣을 때는 "정상 경로"뿐 아니라 모든 에러/fallback 분기까지 게이트가 적용되는지 확인해야 한다. 코드 경로가 여러 개면 게이트도 그만큼 여러 곳에 있어야 함.

---

## 5. E2E 테스트가 조용히 무력화, 도달 불가능한 API 경로 방치

**증상**
유일한 전체 라이프사이클 E2E 테스트(`test_workflow_e2e.py`)가 60번째 줄의 bare `return`으로 회의 → 리뷰 → 승인 절반을 건너뛰고 있었음. 테스트는 항상 초록불이었지만 실제로는 절반만 검증하는 중.

**원인**
디버깅 중 임시로 넣었을 가능성이 높은 `return`이 제거되지 않고 남아, 이후 로직 변경이 있어도 해당 구간 회귀를 전혀 못 잡는 상태로 방치됨. 같은 커밋에서 `task_routes.py`의 manual-review 엔드포인트도 프론트엔드(`App.tsx`/`api.ts`)에서 전혀 호출되지 않아 항상 HTTP 409만 반환하는 죽은 코드로 확인.

**해결**
bare `return` 제거, 원래 있어야 할 assertion 복원. 도달 불가능한 manual-review 엔드포인트와 그 프론트엔드 호출부를 삭제. 부수적으로 프론트엔드 의존성이 전부 `"latest"`로 고정돼 있어 빌드가 매번 다른 버전을 받는 문제도 같이 발견해 현재 resolve된 버전으로 pin하고 `package-lock.json` 재생성.

**검증**
복원된 assertion으로 전체 라이프사이클(회의→리뷰→승인)이 실제로 검증됨을 확인. (`07c73e8`)

**교훈**
"테스트가 통과한다"는 "테스트가 실제로 검증하고 있다"의 증명이 아니다. 커버리지 숫자보다 assertion이 실제로 실행되는지를 주기적으로 점검해야 하고, 죽은 API 경로는 프론트엔드 호출부 기준으로 역추적하면 빠르게 찾을 수 있다.

---

## 6. API·worker 버전 불일치로 인한 조용한 실행 실패 방지

**증상 (설계 단계에서 선제 대응)**
API 프로세스와 worker 프로세스를 분리 배포하는 구조라, 재시작 순서에 따라 서로 다른 build가 동시에 떠 있을 수 있음. 이 상태에서 Job을 실행하면 스키마 불일치로 인한 실패가 사용자에게는 원인 불명의 오류로만 보임.

**해결**
`/api/runtime/version`에서 API build id, worker build id, schema version을 대조해 불일치 시 UI 실행 버튼을 하드 차단. 이후 `6273423` 커밋에서 dispatcher 에러 연속 발생 횟수(error streak)까지 같은 엔드포인트에 노출해, worker가 반복 실패 중인지 UI에서 바로 확인 가능하게 확장.

**검증**
런처(`start-ai-office.ps1`)가 API·worker·Vite를 항상 같은 build로 기동하고, 실행 시작 시 `/api/runtime/version`으로 재확인하는 절차를 표준화.

**교훈**
분산 프로세스 구조에서는 "버전이 다르면 아예 실행을 막는다"는 하드 게이트가, 모호한 런타임 오류를 며칠씩 쫓는 것보다 훨씬 싸다.
