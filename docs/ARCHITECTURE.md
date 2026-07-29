# Architecture

## 실행 구성

AI Office는 브라우저가 모델을 직접 순차 호출하지 않습니다.

```text
React/Vite UI
  │ REST + SSE
FastAPI
  │ Job enqueue / state query
SQLite (WAL)
  │ atomic lease
Single local worker
  ├─ OpenRouter model calls
  ├─ workspace file tools
  ├─ verification commands
  ├─ web search
  └─ configured MCP tools
```

`scripts/start-ai-office.ps1`가 API, worker, Vite를 실행합니다. `/api/runtime/version`의 API build, worker build, schema version이 일치해야 UI 실행 기능이 활성화됩니다.

## Job과 task 분리

Task state는 사용자가 이해할 업무 단계입니다.

- `awaiting_lead_selection`
- `meeting_running`
- `awaiting_worker_selection`
- `executing`
- `lead_review_running`
- `completed`, `blocked`, `paused`, `cancelled`

Job state는 실행기 상태입니다.

- `queued`, `running`
- `pause_requested`, `paused`
- `cancel_requested`, `cancelled`
- `succeeded`, `failed`, `interrupted`

worker는 각 모델·도구 호출 사이 안전 지점에서 pause/cancel을 처리합니다. 모델 HTTP 응답을 기다리는 동안에는 2초 간격으로 lease와 heartbeat를 갱신하며, 15초 간격으로 관측 이벤트를 남깁니다. 생성 응답에는 고정 read timeout을 두지 않고 connection timeout, heartbeat, 최대 도구 round를 사용합니다.

## 영속성과 복구

SQLite는 WAL과 busy timeout을 사용합니다. 주요 테이블:

- `tasks`, `task_contracts`, `task_assignments`
- `jobs`, `job_steps`, `job_leases`, `worker_heartbeats`
- `agent_runs`, `tool_calls`, `job_events`
- `meetings`, `action_items`, `reviews`
- `evidence`, `research_sources`, `model_usage`

worker가 재시작되면 다른 worker lease를 가진 실행 Job은 `interrupted`로 바뀝니다. 재시도 시 성공한 `agent_run`은 건너뛰고 실패한 실행자부터 계속합니다.

## 실행 진실성

- 실제 회의 발언 없이 회의 완료 불가
- 실제 실행 Evidence 없이 팀장 리뷰 시작 불가
- 팀장 리뷰 pass 없이 완료 불가
- 조사 업무는 저장된 웹 출처 없이 완료 불가
- UI 아바타·말풍선은 `job_events`를 기준으로 표시
- tool summary에는 경로·건수·exit code만 표시하고 파일 본문·인증 값은 표시하지 않음

## Workspace와 권한

사용자가 등록한 프로젝트는 task별 `data/workspaces/WS-*`에 복사되거나 Git worktree로 격리됩니다. 파일 경로와 검증 명령은 TaskContract의 `allowed_paths`, `allowed_commands`로 제한됩니다. API key는 OS keyring에 저장됩니다.
