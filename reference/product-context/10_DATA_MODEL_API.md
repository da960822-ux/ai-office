# 10. Data Model and API Draft

> 현재 코드베이스의 스택과 패턴을 우선한다. 아래는 제품 개념을 맞추기 위한 논리 모델이다.

## 핵심 엔터티

### Project

```ts
type Project = {
  id: string;
  name: string;
  status: "draft" | "active" | "ready_for_export" | "archived"; // 거친 rollup. 05_AGENT_ORCHESTRATION.md의 세부 task/exception state(약 17종)는 이 필드에 담지 않고 별도로 추적한다.
  mode: "quick" | "guided" | "existing" | "review";
  skillLevel: "beginner" | "intermediate";
  teamSize?: number;
  deadline?: string;
  createdAt: string;
  updatedAt: string;
};
```

### InferredValue

```ts
type InferredValue = {
  value: unknown;
  confidence: number;
  status: "confirmed" | "recommended" | "unknown";
  source: "user" | "inferred" | "template";
};
```

### Artifact

```ts
type Artifact = {
  id: string;
  projectId: string;
  type: "product_brief" | "scope" | "requirements" | "user_flow" |
        "screen_spec" | "design" | "architecture" | "api_contract" |
        "data_model" | "tasks" | "test_plan" | "decision_log" | "agents_md";
  status: "draft" | "reviewed" | "approved" | "stale";
  currentVersionId: string;
  dependsOn: string[];
  createdAt: string;
  updatedAt: string;
};
```

### ArtifactVersion

```ts
type ArtifactVersion = {
  id: string;
  artifactId: string;
  version: number;
  contentMarkdown?: string;
  contentJson?: unknown;
  sourceBlueprintVersion: number;
  createdBy: "user" | AgentRole | "system";
  createdAt: string;
};
```

### Task

```ts
type Task = {
  id: string;
  projectId: string;
  title: string;
  userValue: string;
  status: "backlog" | "ready" | "in_progress" | "review" | "blocked" | "done";
  ownerRole: AgentRole;
  dependencies: string[];
  requirementIds: string[];
  acceptanceCriteria: string[];
  verificationCommands: string[];
  risk: "low" | "medium" | "high";
};
```

### AgentRun

```ts
type AgentRun = {
  id: string;
  projectId: string;
  role: AgentRole;
  taskId: string;
  status: "queued" | "running" | "waiting_approval" | "failed" | "completed";
  inputArtifactVersions: string[];
  outputArtifactVersions: string[];
  modelRoute: "fast" | "balanced" | "deep" | "code";
  failure?: { code: string; message: string; retryable: boolean };
};
```

### ReviewFinding

```ts
type ReviewFinding = {
  id: string;
  severity: "blocker" | "high" | "medium" | "note";
  category: "scope" | "ux" | "consistency" | "technical" | "security" | "handoff";
  title: string;
  explanation: string;
  impact: string;
  recommendation: string;
  artifactRefs: string[];
  autoFixable: boolean;
  status: "open" | "accepted" | "fixed" | "ignored";
};
```

### Decision / Checkpoint / ExportPackage

```ts
type Decision = {
  id: string;
  title: string;
  choice: string;
  rationale: string;
  alternatives: string[];
  affectedArtifacts: string[];
  reversibleWhen?: string;
};

type Checkpoint = {
  id: string;
  label: string;
  blueprintVersion: number;
  artifactVersionIds: string[];
  codeRef?: string;
  createdAt: string;
};

type ExportPackage = {
  id: string;
  target: "codex" | "claude_code" | "generic" | "github" | "zip";
  status: "generating" | "ready" | "failed";
  createdAt: string;
};
```

## 역할 타입

```ts
type AgentRole =
  | "orchestrator"
  | "product_guide"
  | "ux_designer"
  | "technical_planner"
  | "prototype_builder"
  | "reviewer";
```

## API 초안

```http
POST   /api/projects
GET    /api/projects/:projectId
PATCH  /api/projects/:projectId

POST /api/projects/:projectId/intake
GET  /api/projects/:projectId/intake/questions
POST /api/projects/:projectId/intake/answers

POST  /api/projects/:projectId/blueprints/generate
GET   /api/projects/:projectId/blueprints/current
PATCH /api/projects/:projectId/blueprints/current
POST  /api/projects/:projectId/blueprints/current/approve

POST /api/projects/:projectId/artifacts/generate
GET  /api/projects/:projectId/artifacts
GET  /api/projects/:projectId/artifacts/:type
POST /api/projects/:projectId/artifacts/:type/approve
POST /api/projects/:projectId/artifacts/:type/regenerate

POST /api/projects/:projectId/prototype/generate
GET  /api/projects/:projectId/prototype
POST /api/projects/:projectId/prototype/edits
POST /api/projects/:projectId/prototype/approve

POST /api/projects/:projectId/reviews
GET  /api/projects/:projectId/reviews
POST /api/projects/:projectId/reviews/:findingId/fix

GET   /api/projects/:projectId/tasks
PATCH /api/projects/:projectId/tasks/:taskId

POST /api/projects/:projectId/checkpoints
GET  /api/projects/:projectId/checkpoints
POST /api/projects/:projectId/checkpoints/:checkpointId/restore

POST /api/projects/:projectId/exports
GET  /api/projects/:projectId/exports/:exportId
```

## 이벤트

```text
project.created
intake.normalized
question.required
blueprint.generated
blueprint.approved
artifact.generated
artifact.stale
prototype.generated
review.finding_created
checkpoint.created
agent_run.failed
export.ready
```

## MVP 저장 전략

- 단일 DB에 프로젝트 메타데이터와 JSON
- Markdown 산출물은 DB 또는 object storage
- 코드 생성 시 프로젝트별 workspace
- 체크포인트는 artifact version + Git ref

## 보안 기본

- 모델 입력 전 비밀값 제거
- 파일 유형·크기 제한
- 코드 실행 sandbox
- 외부 네트워크 allowlist
- 위험 도구 승인
- 프로젝트 workspace 격리
- 내보내기 secret scan
- 커뮤니티 스킬 기본 비활성
