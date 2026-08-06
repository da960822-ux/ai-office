const API = '/api';

export type Employee = {
  id: string;
  team: string;
  title: string;
  runtime: string;
  state: string;
  label: string;
  zone: string;
  active: boolean;
  required_skills?: string[];
  agent_role?: {
    tier: 'lead' | 'worker';
    model_role: 'lead_model' | 'worker_model';
    responsibility: string;
  };
  model_assignment?: {
    role: string;
    model: string;
    source: 'role' | 'team' | 'employee' | 'failure_escalation';
  };
};

export type Event = {
  id: number;
  action: string;
  from_state: string | null;
  to_state: string;
  actor: string;
  note: string;
  employee_ids: string[];
  created_at: string;
};

export type Evidence = {
  id: string;
  type: string;
  status: string;
  stale: number;
  created_at: string;
};

export type Meeting = {
  id: string;
  type: string;
  objective: string;
  participants: string[];
  agenda: string[];
  decisions: string[];
  status: string;
};

export type ActionItem = {
  id: string;
  owner: string;
  description: string;
  sequence: number;
  status: string;
};

export type Review = { id:string; reviewer_id:string; verdict:'pass'|'changes_requested'|'blocked'; findings:string; created_at:string };
export type Approval = { id:string; decision:'approve'|'rework'|'reject'; reason:string; decided_by:string; created_at:string };
export type Reflection = { id:string; summary:string; root_causes:string[]; improvements:string[]; created_at:string };
export type Lesson = { id:string; task_id:string; content:string; source_reflection_id:string | null; created_at:string };
export type AgentMessage = { id:number; task_id:string; employee_id:string; kind:string; content:string; created_at:string };
export type ModelUsage = { id:number; task_id:string; model:string; input_tokens:number; output_tokens:number; cost_usd:number; error:string | null; created_at:string };
export type ResearchSource = { id:number; task_id:string; employee_id:string; query:string; title:string; url:string; snippet:string; created_at:string };
export type Job = { id:string; task_id:string; kind:string; payload:Record<string,unknown>; state:string; step:number; lease_owner?:string|null; heartbeat_at?:string|null; error?:string|null; created_at:string; updated_at:string };
export type JobEvent = { id:number; task_id:string; job_id:string|null; agent_id:string|null; type:string; summary:string; payload:Record<string,unknown>; created_at:string };
export type AgentRun = { id:string; task_id:string; job_id:string; employee_id:string; state:string; model:string|null; started_at:string; finished_at:string|null; summary:string|null };
export type ToolCall = { id:number; task_id:string; job_id:string; agent_id:string; tool_name:string; input_summary:string; output_summary:string; status:string; duration_ms:number|null; created_at:string };
export type Deliverable = { id:string; task_id:string; owner:string; kind:string; path:string; status:string; artifact_sha256:string; created_at:string; updated_at:string };
export type ExecutionPhase = { id:string; department:string; lead_id:string; objective:string; output:string; handoff_to:string|null; depends_on:string[] };
export type ExecutionPlan = { summary:string; artifact_kind:string; final_owner:string; workspace_context:'none'|'read'|'write'; requires_web_research:boolean; evidence_strategy:string; reason:string; phases:ExecutionPhase[] };
export type AgentScope = { task_id:string; employee_id:string; assignment:string; skill_ids:string[]; deliverable:string; handoff_to:string|null; dependencies:string[]; sequence:number };
export type RuntimeVersion = { api_build_id:string; worker_build_id:string|null; schema_version:number; running_jobs:number };

export type Task = {
  id: string;
  route?: 'navi' | 'direct_lead';
  lead_id?: string | null;
  title: string;
  request: string;
  state: string;
  state_label: string;
  assigned_employees: string[];
  events: Event[];
  evidence: Evidence[];
  deliverables: Deliverable[];
  execution_plan: { task_id:string; plan_json:string; summary:string; plan:ExecutionPlan; created_at:string; updated_at:string } | null;
  agent_scopes: AgentScope[];
  meetings: Meeting[];
  action_items: ActionItem[];
  reviews: Review[];
  approvals: Approval[];
  reflections: Reflection[];
  lessons: Lesson[];
  agent_messages: AgentMessage[];
  model_usage: ModelUsage[];
  research_sources: ResearchSource[];
  jobs: Job[];
  job_events: JobEvent[];
  agent_runs: AgentRun[];
  tool_calls: ToolCall[];
  checkpoints: { id:number; label:string; snapshot:{state:string;updated_at:string}; created_at:string }[];
  budget_spent: number;
  contract: {
    allowed_paths: string[];
    allowed_commands: string[];
    acceptance_criteria: string[];
    retry_limit: number;
    token_limit: number;
  } | null;
};

export type Project = {
  id: string;
  name: string;
  root_path: string;
  git_available: number;
  created_at: string;
};

export type Workspace = {
  id: string;
  task_id: string;
  path: string;
  strategy: 'copy' | 'worktree' | 'in_place';
  status: string;
};

export type ModelSettings = {
  provider: string;
  lead_model: string;
  worker_model: string;
  role_models: Record<string, string>;
  team_overrides: Record<string, string>;
  employee_overrides: Record<string, string>;
  configured: boolean;
};

export type ProviderModel = { id:string; name:string; context_length:number };
export type McpConnection = { id:string; provider:'github'|'google-drive'|'notion'|'custom'; name:string; transport:'streamable_http'|'sse'; server_url:string; configured:boolean; status:string; created_at:string };

export type UsageSummary = {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  cost_known: boolean;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!response.ok) {
    const raw = await response.text();
    let message = raw;
    try { const parsed=JSON.parse(raw); message=parsed.detail || parsed.message || raw; } catch {}
    throw new Error(message || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

export const api = {
  health: () => request<{ ok: boolean }>('/health'),
  runtime: () => request<RuntimeVersion>('/runtime/version'),
  usageSummary: () => request<UsageSummary>('/usage/summary'),
  modelSettings: () => request<ModelSettings>('/settings/model'),
  providerModels: () => request<ProviderModel[]>('/settings/models'),
  saveModelSettings: (roleModels:Record<string,string>, teamOverrides:Record<string,string>, employeeOverrides:Record<string,string>, apiKey: string) =>
    request<ModelSettings>('/settings/model', {
      method: 'POST',
      body: JSON.stringify({ provider:'openrouter', role_models:roleModels, team_overrides:teamOverrides, employee_overrides:employeeOverrides, api_key: apiKey || undefined }),
    }),
  mcpConnections: () => request<McpConnection[]>('/settings/mcp'),
  saveMcpConnection: (provider:McpConnection['provider'], name:string, transport:McpConnection['transport'], serverUrl:string, authToken:string) => request<McpConnection>('/settings/mcp',{method:'POST',body:JSON.stringify({provider,name,transport,server_url:serverUrl,auth_token:authToken||undefined})}),
  agentBrief: (id: string) =>
    request<{ content: string }>(`/tasks/${id}/agent/brief`, {
      method: 'POST',
      body: '{}',
    }),
  agentRun: (taskId: string, workspaceId: string, employeeId: string, instruction = '') =>
    request<{ employee_id: string; tier: 'lead' | 'worker'; model: string; summary: string; changed_files: string[]; commands: { command: string; exit_code: number }[] }>(`/tasks/${taskId}/agent/run`, {
      method: 'POST',
      body: JSON.stringify({ workspace_id: workspaceId, employee_id: employeeId, instruction }),
    }),
  employees: () => request<Employee[]>('/registry/employees'),
  projects: () => request<Project[]>('/projects'),
  createProject: (rootPath: string) =>
    request<Project>('/projects', {
      method: 'POST',
      body: JSON.stringify({ root_path: rootPath }),
    }),
  pickProjectFolder: () => request<{path:string}>('/projects/pick',{method:'POST',body:'{}'}),
  tasks: () => request<Task[]>('/tasks'),
  task: (id:string) => request<Task>(`/tasks/${id}`),
  create: (title: string, requestText: string, selected: string[], route:'navi'|'direct_lead'='navi', leadId?:string) =>
    request<Task>('/tasks', {
      method: 'POST',
      body: JSON.stringify({
        title,
        request: requestText,
        selected_employees: selected,
        route,
        lead_id: leadId,
      }),
    }),
  contract: (id: string) =>
    request<Task>(`/tasks/${id}/contract`, {
      method: 'POST',
      body: JSON.stringify({
        allowed_paths: ['.'],
        allowed_commands: ['npm test', 'npm run build', 'pytest', 'python -m pytest'],
        acceptance_criteria: [
          '요청 범위를 충족한다',
          '선택한 프로젝트 폴더에 실제 산출물 파일을 생성한다',
          '부서별 결과를 하나의 최종 산출물로 통합한다',
          '검증 결과와 근거를 기록한다',
        ],
      }),
    }),
  plan: (id: string) =>
    request<Task>(`/tasks/${id}/plan`, { method: 'POST', body: '{}' }),
  queuePlan: (id:string) => request<{id:string;task:Task}>(`/tasks/${id}/jobs/plan`, {method:'POST',body:'{}'}),
  queueMeeting: (id:string, meetingId:string) => request<{id:string;task:Task}>(`/tasks/${id}/jobs/meeting`, {method:'POST',body:JSON.stringify({meeting_id:meetingId})}),
  queueExecution: (id:string, workspaceId:string, employeeIds:string[], instruction='') => request<{id:string;task:Task}>(`/tasks/${id}/jobs/execute`, {method:'POST',body:JSON.stringify({workspace_id:workspaceId,employee_ids:employeeIds,instruction})}),
  queueReview: (id:string) => request<{id:string;task:Task}>(`/tasks/${id}/jobs/review`, {method:'POST',body:'{}'}),
  controlJob: (id:string, action:'pause'|'resume'|'cancel') => request<Job>(`/jobs/${id}/control`, {method:'POST',body:JSON.stringify({action})}),
  retryJob: (id:string) => request<Job>(`/jobs/${id}/retry`, {method:'POST',body:'{}'}),
  agentCapabilities: (id:string) => request<unknown>(`/agents/${id}/capabilities`),
  teamCapabilities: (id:string) => request<unknown>(`/teams/${id}/capabilities`),
  directDispatch: (id:string, leadId:string) => request<Task>(`/tasks/${id}/direct-dispatch`, {method:'POST',body:JSON.stringify({lead_id:leadId})}),
  pause: (id:string) => request<Task>(`/tasks/${id}/pause`, {method:'POST',body:'{}'}),
  resume: (id:string) => request<Task>(`/tasks/${id}/resume`, {method:'POST',body:'{}'}),
  cancel: (id:string) => request<Task>(`/tasks/${id}/cancel`, {method:'POST',body:'{}'}),
  selectLeads: (id:string, employeeIds:string[]) => request<Task>(`/tasks/${id}/select-leads`, {method:'POST',body:JSON.stringify({employee_ids:employeeIds})}),
  selectWorkers: (id:string, employeeIds:string[]) => request<Task>(`/tasks/${id}/select-workers`, {method:'POST',body:JSON.stringify({employee_ids:employeeIds})}),
  createMeeting: (id:string, objective:string, participantIds:string[], agenda:string[]) =>
    request<Task>(`/tasks/${id}/meetings`, {method:'POST',body:JSON.stringify({objective,participant_ids:participantIds,agenda})}),
  runMeeting: (taskId:string, meetingId:string) => request<Task>(`/tasks/${taskId}/meetings/${meetingId}/run`, {method:'POST',body:'{}'}),
  approval: (id:string, decision:'approve'|'rework'|'reject', reason:string) =>
    request<Task>(`/tasks/${id}/approval`, {method:'POST',body:JSON.stringify({decision,reason})}),
  reflection: (id:string, summary:string, rootCauses:string[], improvements:string[], lesson:string) =>
    request<Task>(`/tasks/${id}/reflection`, {method:'POST',body:JSON.stringify({summary,root_causes:rootCauses,improvements,lesson})}),
  lessons: () => request<Lesson[]>('/lessons'),
  createWorkspace: (
    taskId: string,
    projectId: string,
    strategy: 'copy' | 'worktree' | 'in_place' = 'copy',
  ) =>
    request<Workspace>(`/tasks/${taskId}/workspace`, {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, strategy }),
    }),
  workspace: (taskId:string) => request<Workspace>(`/tasks/${taskId}/workspace`),
  command: (
    id: string,
    action: string,
    selected: string[],
    note = '',
  ) =>
    request<Task>(`/tasks/${id}/command`, {
      method: 'POST',
      body: JSON.stringify({ action, employee_ids: selected, note }),
    }),
  office: (id: string) =>
    request<{ task: Task; employees: Employee[] }>(`/tasks/${id}/office`),
};
