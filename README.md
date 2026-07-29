# AI Automation Office

AI 직원 24명과 업무 상태·권한·스킬·검증 흐름을 관리하는 로컬 자동화 오피스입니다. Corporate OS v6.2의 직원 레지스트리와 Embedded Skills를 기반으로 웹 화면, FastAPI API, 작업 실행 파이프라인을 제공합니다.

## 주요 기능

- NAVI 등 Lead/Worker AI 직원 라우팅
- 업무 계약(TaskContract), 상태 전이, 승인·검증·재시도
- 직원별 권한과 필수 스킬 검증
- 격리된 workspace 복사 또는 worktree 실행
- OpenRouter 모델 설정 및 MCP 연동
- SQLite 이벤트·체크포인트·작업 이력 저장

## 구조

| 경로 | 역할 |
| --- | --- |
| `apps/api/` | FastAPI API와 작업 워커 |
| `apps/web/` | Vite 기반 웹 클라이언트 |
| `registry/` | 직원·스킬·바인딩 레지스트리 |
| `employees/` | 직원 프로필, 권한, 스킬 |
| `runtimes/` | Planner, Builder, Reviewer 등 런타임 지침 |
| `scripts/` | 설치·검증·인덱스 생성 스크립트 |
| `data/` | 로컬 런타임 DB와 캐시; Git 제외 |

## 빠른 시작

### 스킬 설치·검증

```bash
python scripts/install_skills.py --employee ALL
python scripts/verify_skills.py --employee ALL
python scripts/render_skill_indexes.py
```

### API 실행

```bash
uvicorn apps.api.main:app --reload --port 5175
```

### 웹 실행

```bash
cd apps/web
npm ci
npm run dev
```

루트 정적 데모는 `npm test`로 Node 테스트를 실행할 수 있습니다. Windows에서는 `AI_Office_실행.cmd`를 사용할 수 있습니다.

## 설정

모델 API 키는 `OPENROUTER_API_KEY` 또는 `OPENAI_API_KEY` 환경 변수로 주입합니다. 키·토큰·로컬 DB는 커밋하지 않습니다. API는 기본적으로 `data/ai-office.sqlite3`에 상태를 저장합니다.

## 문서

- [`AI_AUTOMATION_OFFICE_V1_PLAN.md`](AI_AUTOMATION_OFFICE_V1_PLAN.md): 제품·구현 계획
- [`01-CORPORATE_OS_v6.2.md`](01-CORPORATE_OS_v6.2.md): 운영 원칙
- [`04-MVP_IMPLEMENTATION_v6.2.md`](04-MVP_IMPLEMENTATION_v6.2.md): MVP 구현 문서
- [`05-SKILL_BUNDLING_AND_INSTALLATION_v6.2.md`](05-SKILL_BUNDLING_AND_INSTALLATION_v6.2.md): 스킬 설치 정책
- [`CONTRIBUTING.md`](CONTRIBUTING.md): 기여·검증 절차
- [`SECURITY.md`](SECURITY.md): 보안 정책

## 상태

현재 버전은 초기 개발 단계(`0.1.0`)입니다. 운영 배포 전 인증, 비밀 관리, 백업, 외부 MCP 권한을 별도 점검해야 합니다.

