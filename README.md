# AI Office

전문 스킬을 가진 AI 직원들이 팀을 이루어 실제 로컬 프로젝트를 조사·수정·검증하는 가상 회사 운영 프로그램입니다.

## 주요 기능

- NAVI(`z-ai/glm-5.2`)가 요청을 판단하고 필요한 팀장 후보만 제안
- 사용자가 팀장을 선택하면 회의, 실행자 배정, 실행, 팀장 리뷰가 자동 진행
- 팀장 아바타에서 소규모 업무 직접 지시
- 별도 local worker와 SQLite Job queue를 통한 지속 실행
- Job heartbeat, pause, resume, cancel, 실패 단계 재시도
- 실제 모델 호출·도구 호출·파일 변경·검증·Evidence를 SSE로 UI에 표시
- 작업별 격리 workspace에서 파일 읽기와 문서·코드 수정
- 시장조사 등 최신 근거가 필요한 업무에서 웹 출처 저장
- 8개 팀·24명 직원과 직원별 로컬 스킬·권한 registry

## 업무 흐름

```text
대표 요청
→ NAVI 팀장 후보 제안
→ 대표가 팀장 선택
→ NAVI + 선택 팀장 실제 회의
→ 팀장이 실행자 자동 배정
→ 실행자가 파일·검색·명령 도구로 작업
→ 담당 팀장 별도 리뷰
→ 완료 또는 수정 요청
```

팀장에게 직접 지시한 소규모 업무는 NAVI 판단과 전체 팀장 회의를 생략하지만, 실행 뒤 해당 팀장의 별도 리뷰를 거칩니다.

## 요구 사항

- Windows 10/11
- Python 3.12 이상
- Node.js 20 이상과 npm
- OpenRouter API key

API key는 브라우저 설정 화면에서 입력하며 OS keyring에 저장됩니다. 저장소나 SQLite에 평문으로 기록하지 않습니다.

## 설치

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd apps\web
npm install
cd ..\..
```

내장 스킬을 다시 설치·검증하려면:

```powershell
.\.venv\Scripts\python.exe scripts\install_skills.py --employee ALL
.\.venv\Scripts\python.exe scripts\verify_skills.py --employee ALL
.\.venv\Scripts\python.exe scripts\render_skill_indexes.py
```

인터넷이 차단된 환경은 `manual-drop/README.md`를 따릅니다.

## 실행

`AI_Office_실행.cmd`를 실행하거나:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\start-ai-office.ps1
```

launcher가 다음 프로세스를 같은 build로 시작합니다.

- Web: `http://127.0.0.1:5175`
- API: `http://127.0.0.1:8011`
- Worker: 단일 local worker

API와 worker build가 다르면 UI의 실행 기능은 차단됩니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s apps\api -p "test_*.py" -v
cd apps\web
npm.cmd test -- --run
npm.cmd run build
```

## 프로젝트 구조

```text
apps/api/       FastAPI, SQLite schema, 모델·도구 API
apps/web/       React/Vite 오피스 UI
employees/      직원 persona, 권한, 내장 스킬
registry/       직원·스킬·모델 binding
runtimes/       공통 runtime 지침
scripts/        launcher와 스킬 관리 도구
constitution/   운영 원칙
third_party/    외부 스킬 라이선스 사본
```

자세한 실행 구조는 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)를 참고하세요.

## 문서

- [아키텍처](docs/ARCHITECTURE.md)
- [기여 방법](CONTRIBUTING.md)
- [보안 정책](SECURITY.md)
- [외부 저작물 고지](NOTICE.md)
- [Corporate OS 명세](01-CORPORATE_OS_v6.2.md)
- [직원 Registry](02-EMPLOYEE_REGISTRY_v6.2.md)
- [스킬 출처·라이선스](07-SOURCE_LICENSE_MATRIX_v6.2.md)

## 라이선스

이 저장소 전체에 적용되는 라이선스는 아직 선언되지 않았습니다. 외부 스킬과 자산은 각 원저작자의 라이선스를 따릅니다. 배포·상업 이용 전 [NOTICE.md](NOTICE.md)와 [07-SOURCE_LICENSE_MATRIX_v6.2.md](07-SOURCE_LICENSE_MATRIX_v6.2.md)를 검토하세요.
