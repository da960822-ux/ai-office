import { useEffect, useMemo, useRef, useState } from 'react';
import { api, type Employee, type JobEvent, type Project, type RuntimeVersion, type Task, type UsageSummary, type Workspace } from './api';
import { personas } from './personas';
import { resolveMotion, type AgentAction } from './motion';
import { FloorAgent, Avatar, agentRole, compactText, teamStatus, teamForAgent, teamSignStyle } from './OfficeFloor';
import { InfoBlock } from './shared';
import { useOfficeCamera } from './hooks/useOfficeCamera';
import { useModelSettings } from './hooks/useModelSettings';
import { useTaskChat } from './hooks/useTaskChat';
import { ModelSettingsPanel } from './ModelSettingsPanel';
import { ProjectModal } from './modals/ProjectModal';
import { LeadSelectionModal } from './modals/LeadSelectionModal';
import { WorkerSelectionModal } from './modals/WorkerSelectionModal';
import { LeadCommandModal } from './modals/LeadCommandModal';
import { RequestModal } from './modals/RequestModal';
import { ChatModal } from './modals/ChatModal';
import { MeetingModal } from './modals/MeetingModal';
import { TaskModal } from './modals/TaskModal';
import { EvidenceModal } from './modals/EvidenceModal';
import { ApprovalModal } from './modals/ApprovalModal';
import { ReflectionModal } from './modals/ReflectionModal';

const initialAgents = ['NAVI', 'FRAME', 'BUILD', 'FRONT', 'BACK', 'TRACE', 'GUARD'];
const leadIds = new Set(['NAVI','FRAME','BUILD','LINK','SHIP','GUARD','GROW','LENS']);
const teamNames: Record<string, string> = {
  'operations-planning': '운영 기획', 'product-experience': '제품 경험', application: '애플리케이션',
  'ai-data': 'AI·데이터', 'platform-reliability': '플랫폼', 'quality-security': '품질·보안',
  'growth-marketing': '성장·마케팅', 'service-knowledge': '서비스·지식',
};
const deskPositions: Record<string, [number, number]> = {
  NAVI:[17,18], ROUTE:[16,39], CLOCK:[26,41], FRAME:[21,42], FLOW:[30,42], MOSS:[44,42],
  BUILD:[52,43], FRONT:[59,43], BACK:[76,42], LINK:[84,42], SIGNAL:[75,51], EVAL:[86,51],
  SHIP:[78,70], SRE:[86,70], COST:[78,80], GUARD:[88,80], TRACE:[86,20], SHIELD:[76,20],
  GROW:[16,70], VOICE:[26,70], PULSE:[17,80], LENS:[47,73], JOURNEY:[56,73], DOCS:[47,82],
};
const teamSigns = [
  ['product','제품·기획팀','PM · 리서치 · 로드맵'], ['design','디자인·프론트팀','UX · UI · 프론트엔드'],
  ['backend','백엔드·AI팀','API · 데이터 · AI'], ['growth','마케팅·성장팀','캠페인 · 지표'],
  ['lounge','공용 라운지','팀 허들 · 협업'], ['ops','운영·보안팀','신뢰성 · QA · 보안'],
] as const;

// Bounding box per department, derived from the real desk layout (deskPositions
// grouped by teamForAgent) so the floor tint always matches where agents
// actually stand — never a hand-tuned rectangle that can drift out of sync.
type ZoneRect = { left: number; top: number; width: number; height: number };
function computeDeptZoneRects(): Record<string, ZoneRect> {
  const groups: Record<string, [number, number][]> = {};
  for (const [id, position] of Object.entries(deskPositions)) {
    const team = teamForAgent(id);
    (groups[team] ??= []).push(position);
  }
  const pad = 7;
  return Object.fromEntries(Object.entries(groups).map(([team, points]) => {
    const xs = points.map(point => point[0]);
    const ys = points.map(point => point[1]);
    const left = Math.max(0, Math.min(...xs) - pad);
    const top = Math.max(0, Math.min(...ys) - pad);
    return [team, { left, top, width: Math.min(100, Math.max(...xs) + pad) - left, height: Math.min(100, Math.max(...ys) + pad) - top }];
  }));
}
const deptZoneRects = computeDeptZoneRects();

async function pingApi(): Promise<boolean> {
  try { const result = await api.health(); return Boolean(result.ok); } catch { return false; }
}

function friendlyError(error: unknown) {
  const text = error instanceof Error ? error.message : String(error);
  if (text.includes('Failed to fetch')) return '로컬 실행 엔진에 연결할 수 없습니다. 실행기를 다시 시작해 주세요.';
  if (text.includes('Project root must be')) return '존재하는 프로젝트 폴더 경로를 입력해 주세요.';
  if (text.includes('UNIQUE constraint')) return '이미 연결된 프로젝트입니다.';
  return text.replace(/^Error:\s*/, '');
}

export default function App() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [projectId, setProjectId] = useState('');
  const [task, setTask] = useState<Task | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [runtime, setRuntime] = useState<RuntimeVersion | null>(null);
  const [usage, setUsage] = useState<UsageSummary>({input_tokens:0,output_tokens:0,cost_usd:0,cost_known:false});
  const [requestText, setRequestText] = useState('');
  const [projectPath, setProjectPath] = useState('');
  const [brief, setBrief] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState<'project'|'request'|'settings'|'meeting'|'task'|'approval'|'evidence'|'reflection'|'leadSelection'|'workerSelection'|'leadCommand'|'chat'|null>(null);
  const [selectedLeadIds, setSelectedLeadIds] = useState<string[]>([]);
  const [selectedWorkerIds, setSelectedWorkerIds] = useState<string[]>([]);
  const [directLeadId, setDirectLeadId] = useState('NAVI');
  const [directCommandLeadId, setDirectCommandLeadId] = useState('');
  const [directCommandTitle, setDirectCommandTitle] = useState('');
  const [directCommandText, setDirectCommandText] = useState('');
  const [intakeMode, setIntakeMode] = useState<'blank'|'has_items'|''>('');
  const executionControl = useRef<'active'|'paused'|'cancelled'>('active');
  const [meetingObjective, setMeetingObjective] = useState('');
  const [meetingAgenda, setMeetingAgenda] = useState('');
  const [reflectionSummary, setReflectionSummary] = useState('');
  const [reflectionCause, setReflectionCause] = useState('');
  const [reflectionImprovement, setReflectionImprovement] = useState('');
  const [lesson, setLesson] = useState('');

  const cameraApi = useOfficeCamera(employees, deskPositions, teamForAgent, teamSigns.map(([id]) => id));
  const { camera, focusedId, focusedZone, focusZone, focusEmployee, locateZone, showAllOffice, moveTeam, zoomCamera, beginPan, panOffice, endPan, panByKeyboard } = cameraApi;
  const settings = useModelSettings(setError, friendlyError, setBusy);
  const { model, setModel, setProviderModels, setMcpConnections } = settings;
  const chat = useTaskChat(setError, friendlyError, setBusy);

  const load = async () => {
    try {
      const [roster, savedProjects, tasks, modelSettings, costs, connections, version] = await Promise.all([api.employees(), api.projects(), api.tasks(), api.modelSettings(), api.usageSummary(), api.mcpConnections(), api.runtime()]);
      setEmployees(roster); setProjects(savedProjects); setTasks(tasks); setProjectId(savedProjects[0]?.id ?? ''); setTask(tasks[0] ?? null); setModel(modelSettings); setUsage(costs); setMcpConnections(connections); setRuntime(version); setError('');
    } catch (cause) { setError(friendlyError(cause)); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); void api.providerModels().then(setProviderModels).catch(()=>setProviderModels([])); }, []);
  useEffect(() => {
    let cancelled = false;
    const check = () => { void pingApi().then(ok => { if (!cancelled) { settings.setConnectionOk(ok); settings.setConnectionCheckedAt(Date.now()); } }); };
    check();
    const interval = setInterval(check, 30_000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);
  useEffect(() => {
    if (!task) return;
    const stream = new EventSource(`/api/tasks/${task.id}/events/stream`);
    stream.addEventListener('job', () => { void api.task(task.id).then(updated=>{setTask(updated);setTasks(current=>current.map(item=>item.id===updated.id?updated:item));}).catch(cause=>setError(friendlyError(cause))); });
    stream.onerror = () => stream.close();
    return () => stream.close();
  }, [task?.id]);
  useEffect(() => { if (task?.state === 'awaiting_lead_selection') setSelectedLeadIds(task.assigned_employees); }, [task?.state, task?.assigned_employees.join(',')]);
  useEffect(() => { if (task?.id) void api.workspace(task.id).then(setWorkspace).catch(()=>setWorkspace(null)); }, [task?.id]);

  const selectedProject = projects.find(project => project.id === projectId);
  const currentMeeting = task?.meetings.find(meeting => meeting.status === 'active');
  const latestMeeting = task?.meetings.find(meeting => meeting.status === 'concluded' && task.agent_messages.some(message => message.kind === 'meeting'));
  const activeJobs = new Set(task?.jobs.filter(job=>['queued','running','pause_requested','cancel_requested'].includes(job.state)).map(job=>job.id) ?? []);
  const activeJob = task?.jobs.find(job=>activeJobs.has(job.id));
  const failedJob = task?.jobs.find(job=>['failed','interrupted'].includes(job.state));
  const liveAgentEvents = new Map<string, JobEvent>();
  for (const event of task?.job_events ?? []) if (event.agent_id && event.job_id && activeJobs.has(event.job_id) && !liveAgentEvents.has(event.agent_id)) liveAgentEvents.set(event.agent_id, event);
  const lastLocationEvents = new Map<string, JobEvent>();
  for (const event of task?.job_events ?? []) if (event.agent_id && ['agent.move','agent.at_location'].includes(event.type) && event.payload.zone && !lastLocationEvents.has(event.agent_id)) lastLocationEvents.set(event.agent_id, event);
  const activeIds = new Set(liveAgentEvents.keys());
  const workerProposalIds = new Set((task?.action_items ?? []).flatMap(item => {
    if (!leadIds.has(item.owner) || (task?.route === 'direct_lead' && item.owner === task.lead_id)) return [item.owner];
    const lead = employees.find(employee => employee.id === item.owner);
    return employees.filter(employee => employee.team === lead?.team && !leadIds.has(employee.id)).map(employee => employee.id);
  }));
  const bubbleByAgent = new Map<string, JobEvent>();
  for (const event of task?.job_events ?? []) {
    if (!event.agent_id || !event.summary || event.type === 'agent.move') continue;
    const age = Date.now() - new Date(event.created_at).getTime();
    const life = event.type === 'meeting.message' ? 15_000 : 8_000;
    if (age < life && !bubbleByAgent.has(event.agent_id)) bubbleByAgent.set(event.agent_id, event);
  }
  const runtimeReady = Boolean(runtime?.worker_build_id) && runtime?.api_build_id === runtime?.worker_build_id;
  const executionJobIds = new Set(task?.jobs.filter(job=>job.kind==='execute').map(job=>job.id) ?? []);
  const completedRunIds = new Set((task?.agent_runs ?? []).filter(run=>run.state==='succeeded'&&executionJobIds.has(run.job_id)).map(run=>run.employee_id));
  const failedModelUsage = task?.model_usage?.filter(item => item.error) ?? [];
  const latestExecutionResult = task?.agent_messages.find(message=>message.kind==='run');
  const latestReview = task?.reviews[0];
  const terminalTask = ['completed','cancelled'].includes(task?.state ?? '');
  const approvalCount = task?.state === 'awaiting_approval' ? 1 : 0;
  const pendingPermissions = task?.permission_requests.filter(item=>item.state==='pending') ?? [];
  const decisionCount = approvalCount + pendingPermissions.length;
  const activeTaskCount = tasks.filter(item=>item.jobs.some(job=>['queued','running','pause_requested','cancel_requested'].includes(job.state)) || ['awaiting_lead_selection','awaiting_approval'].includes(item.state)).length;
  const mainAction = !selectedProject ? {label:'프로젝트 연결', action:()=>setModal('project')} : decisionCount ? {label:'승인 패널 열기', action:()=>setModal('approval')} : !task || task.state === 'completed' ? {label:'새 업무 요청', action:()=>setModal('request')} : task.state==='planning' ? {label:activeJob ? 'NAVI 판단 진행 중' : 'NAVI 판단 다시 시작', action:()=>setModal('task')} : task.state==='awaiting_lead_selection' ? {label:'팀장 선택', action:()=>setModal('leadSelection')} : task.state==='awaiting_worker_selection' ? {label:'팀장 자동 배정 중', action:()=>setModal('task')} : {label:'현재 업무 열기', action:()=>setModal('task')};
  const focusedEmployee = employees.find(employee => employee.id === focusedId);
  const motions = useMemo(() => Object.fromEntries(employees.map(employee => {
    const taskAssignmentIndex=task?.assigned_employees.indexOf(employee.id) ?? -1;
    const assignedIndex=employee.id==='NAVI' ? 0 : Math.max(1, taskAssignmentIndex + 1);
    const live=liveAgentEvents.get(employee.id);
    const location=lastLocationEvents.get(employee.id);
    const active=activeIds.has(employee.id);
    const zone=(active ? live?.payload.zone ?? location?.payload.zone : undefined) as string | undefined;
    const action=active ? (live?.payload.action as AgentAction | undefined) ?? (location?.payload.action as AgentAction | undefined) : undefined;
    const motion=resolveMotion({employeeId:employee.id, taskState:zone === 'meeting' ? 'meeting' : zone === 'qa' ? 'team_review' : zone === 'ceo' ? 'awaiting_approval' : task?.state, active, isLead:leadIds.has(employee.id), assignmentIndex:assignedIndex});
    return [employee.id, {...motion, action:action ?? motion.action}];
  })), [employees, task, liveAgentEvents, lastLocationEvents, activeIds]);

  const registerProject = async () => {
    if (!projectPath.trim()) { setError('프로젝트 폴더 경로를 입력해 주세요.'); return; }
    setBusy('프로젝트 연결 중');
    try {
      const project = await api.createProject(projectPath.trim()); setProjects(current => [project, ...current]); setProjectId(project.id); setProjectPath(''); setModal(null); setError('');
    } catch (cause) {
      const existing = projects.find(project => project.root_path.toLowerCase() === projectPath.trim().toLowerCase());
      if (existing) { setProjectId(existing.id); setProjectPath(''); setModal(null); setError(''); } else setError(friendlyError(cause));
    } finally { setBusy(''); }
  };
  const pickProjectFolder = async () => {
    setBusy('폴더 선택 창을 여는 중');
    try { const selected = await api.pickProjectFolder(); if (selected.path) setProjectPath(selected.path); }
    catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(''); }
  };

  const startTask = async (mode:'plan'|'execute'='execute') => {
    if (!runtimeReady) { setError('API와 worker 버전이 맞지 않습니다. AI Office 실행기를 다시 시작해 주세요.'); return; }
    if (!selectedProject) { setError('먼저 헤더에서 작업 프로젝트를 연결해 주세요.'); setModal('project'); return; }
    if (!requestText.trim()) { setError('새 업무 요청을 입력해 주세요.'); return; }
    setBusy('NAVI가 업무를 준비하는 중'); setBrief('');
    try {
      const title = requestText.trim().split(/\r?\n/)[0].slice(0,80);
      const created = await api.create(title, requestText.trim(), initialAgents, directLeadId === 'NAVI' ? 'navi' : 'direct_lead', directLeadId === 'NAVI' ? undefined : directLeadId); setTasks(current=>[created,...current]);
      if (directLeadId !== 'NAVI') {
        await api.contract(created.id); setTask(created);
        const prepared = await api.createWorkspace(created.id, selectedProject.id, 'in_place'); setWorkspace(prepared);
        await api.queuePlan(created.id);
        setBrief(`${personas[directLeadId]?.name ?? directLeadId} 팀장 판단 Job을 대기열에 넣었습니다. worker 제안 뒤 대표가 실행자를 선택합니다.`);
        setRequestText(''); setModal('task'); return;
      }
      await api.contract(created.id); setTask(created); await api.queuePlan(created.id);
      if (mode === 'plan') {
        setBrief('NAVI 계획 Job을 대기열에 넣었습니다. 실행자 호출과 작업공간 생성은 하지 않습니다.');
        setRequestText(''); setModal('task'); return;
      }
      const prepared = await api.createWorkspace(created.id, selectedProject.id, 'in_place'); setWorkspace(prepared);
      setBrief('NAVI가 필요한 부서 팀장을 판단 중입니다. 완료되면 팀장 선택이 열립니다.');
      setRequestText(''); setModal('task');
    } catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(''); }
  };

  const createMeeting = async () => {
    if (!task || !meetingObjective.trim()) return;
    setBusy('회의를 준비하는 중');
    try { const updated=await api.createMeeting(task.id, meetingObjective.trim(), task.assigned_employees, meetingAgenda.split('\n').map(item=>item.trim()).filter(Boolean)); setTask(updated); setMeetingObjective(''); setMeetingAgenda(''); setError(''); }
    catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(''); }
  };
  const selectLeads = async () => { if (!task || !selectedLeadIds.length) return; setBusy('선택 팀장을 회의에 소집하는 중'); try { setTask(await api.selectLeads(task.id, selectedLeadIds)); setModal('task'); setBrief('팀장 선택 완료. 회의, 실행자 배정, 실행, 팀장 리뷰가 자동 진행됩니다.'); } catch (cause) { setError(friendlyError(cause)); } finally { setBusy(''); } };
  const selectWorkers = async () => { if (!task || !selectedWorkerIds.length || !workspace) return; setBusy('선택 실행자 Job을 대기열에 넣는 중'); try { const updated=await api.selectWorkers(task.id, selectedWorkerIds); setTask(updated); await api.queueExecution(task.id, workspace.id, selectedWorkerIds, task.request); setModal(null); setError(''); } catch (cause) { setError(friendlyError(cause)); } finally { setBusy(''); } };
  const controlTask = async (action:'pause'|'resume'|'cancel') => { if (!task) return; try { if (action==='cancel') { setTask(await api.cancel(task.id)); setBrief('업무를 취소했습니다. 대기 Job은 즉시 취소되고, 실행 중 호출은 안전 지점에서 중단됩니다.'); setError(''); return; } const job=task.jobs.find(item=>['queued','running','pause_requested','paused','interrupted','cancel_requested'].includes(item.state)); if (job) await api.controlJob(job.id, action); else setTask(action==='pause' ? await api.pause(task.id) : await api.resume(task.id)); setBrief(action==='pause'?'정지 요청됨. 현재 모델 호출 뒤 안전 지점에서 멈춥니다.':'재개 요청됨. worker가 다음 step부터 계속합니다.'); setError(''); } catch(cause) { setError(friendlyError(cause)); } };
  const retryFailedJob = async () => { if (!failedJob) return; setBusy('실패 단계 재시도 중'); try { await api.retryJob(failedJob.id); setTask(await api.task(failedJob.task_id)); setBrief('완료된 실행자는 유지하고 실패한 단계부터 다시 시작합니다.'); setError(''); } catch(cause) { setError(friendlyError(cause)); } finally { setBusy(''); } };
  const beginPlannedExecution = async () => { if (!task) return; setSelectedLeadIds(task.assigned_employees); setModal('leadSelection'); };
  const preparePlan = async () => { if (!task) return; setBusy('NAVI 계획 Job을 대기열에 넣는 중'); try { await api.queuePlan(task.id); setBrief('NAVI가 팀장 후보를 다시 판단 중입니다.'); setError(''); } catch(cause) { setError(friendlyError(cause)); } finally { setBusy(''); } };
  const submitLeadCommand = async (leadId=directCommandLeadId, title=directCommandTitle, prompt=directCommandText) => { if (!selectedProject || !leadId || !title.trim() || !prompt.trim()) return; setBusy('팀장 직접 업무를 등록하는 중'); try { const created=await api.create(title.trim(), prompt.trim(), [], 'direct_lead', leadId); setTasks(current=>[created,...current]); await api.contract(created.id); const prepared=await api.createWorkspace(created.id, selectedProject.id, 'in_place'); setWorkspace(prepared); await api.queuePlan(created.id); setTask(created); setModal('task'); setBrief(`${personas[leadId]?.name ?? leadId} 팀장이 실행자를 자동 배정하고 별도 리뷰합니다.`); } catch(cause) { setError(friendlyError(cause)); } finally { setBusy(''); } };
  const decideApproval = async (decision:'approve'|'rework'|'reject') => {
    if (!task) return;
    setBusy('대표 결정을 기록하는 중');
    try { setTask(await api.approval(task.id, decision, '대표 화면에서 기록한 결정')); setModal(null); setError(''); }
    catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(''); }
  };
  const decidePermission = async (requestId:string, decision:'approve'|'deny', reason:string) => {
    if (!task) return;
    setBusy(decision==='approve' ? '요청을 승인하는 중' : '요청을 거부하는 중');
    try { await api.decidePermission(task.id, requestId, decision, reason); setTask(await api.task(task.id)); setError(''); }
    catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(''); }
  };
  const submitReflection = async () => {
    if (!task || !reflectionSummary.trim()) return;
    setBusy('회고와 회사 기억을 기록하는 중');
    try { setTask(await api.reflection(task.id, reflectionSummary, reflectionCause.split('\n').filter(Boolean), reflectionImprovement.split('\n').filter(Boolean), lesson)); setReflectionSummary(''); setReflectionCause(''); setReflectionImprovement(''); setLesson(''); setModal(null); setError(''); }
    catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(''); }
  };

  if (loading) return <div className="boot-screen"><span>AI</span><b>오피스를 시작하는 중</b></div>;

  return <main className="product-shell">
    <header className="product-header">
      <button className="company-mark" onClick={() => focusEmployee('NAVI')}><span>A</span><b>AI OFFICE</b></button>
      <div className="header-actions">
        <select className="header-task-select" aria-label="현재 업무 선택" value={task?.id ?? ''} onChange={event=>void api.task(event.target.value).then(setTask).catch(cause=>setError(friendlyError(cause)))}><option value="">업무 선택</option>{tasks.map(item=><option key={item.id} value={item.id}>{item.id} · {item.title}</option>)}</select>
        <button className="header-project" onClick={() => setModal('project')}><small>현재 프로젝트</small><b>{selectedProject?.name ?? '프로젝트 연결'}</b></button>
        <button className="header-new" onClick={() => { setRequestText(''); setDirectLeadId('NAVI'); setModal('request'); }}>+ 새 업무</button>
        <button className="header-brief" onClick={() => setModal('task')}><small>CEO 브리핑</small><b>{task?.title ?? '대기 중'}</b></button>
        <span className="header-cost"><small>비용</small><b>{usage.cost_known ? `$${usage.cost_usd.toFixed(2)}` : 'unknown'}</b></span>
        <button className={`header-connection ${!model.configured ? 'is-unset' : settings.connectionOk ? 'is-ok' : 'is-down'}`} onClick={() => setModal('settings')} title={settings.connectionCheckedAt ? `마지막 확인 ${new Date(settings.connectionCheckedAt).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit'})}` : '아직 확인 전'}><i/><small>{settings.apiNickname || 'OpenRouter'}</small><b>{!model.configured ? '키 미등록' : settings.connectionOk ? '연결됨' : '연결 끊김'}</b></button>
        <button className="header-settings" onClick={() => setModal('settings')}>설정</button>
      </div>
    </header>

    {error && <div className="toast-error"><b>연결 또는 입력 오류</b><span>{error}</span><button onClick={() => setError('')}>×</button></div>}
    {!runtimeReady && <div className="toast-error"><b>실행기 버전 불일치</b><span>API와 worker 준비 상태를 확인할 수 없습니다. AI Office 실행기를 다시 시작하세요.</span></div>}

    <section className="execution-console" aria-label="실제 실행 현황">
      <div className="execution-heading"><span>LIVE EXECUTION</span><b>{activeJob ? '실행 중' : failedJob ? '실행 실패' : task?.state==='completed' ? '업무 완료' : task?.state==='cancelled' ? '업무 취소' : completedRunIds.size ? '최근 실행 완료' : '실행 대기'}</b></div>
      <div className="execution-metrics"><div><small>실행 중</small><b>{activeIds.size}</b></div><div><small>완료 실행</small><b>{completedRunIds.size}</b></div><div><small>검증 증거</small><b>{task?.evidence.length ?? 0}</b></div><div className={failedModelUsage.length ? 'metric-alert' : ''}><small>실패</small><b>{failedModelUsage.length}</b></div></div>
      <div className="execution-detail" aria-live="polite">
        <b>{task?.title ?? '선택된 업무 없음'}</b>
        <span>{activeJob ? `${activeJob.kind} · step ${activeJob.step} · ${activeJob.state}${activeJob.heartbeat_at ? ` · heartbeat ${new Date(activeJob.heartbeat_at).toLocaleTimeString()}` : ''}` : failedJob ? `${failedJob.kind} · step ${failedJob.step} · ${failedJob.error ?? '원인 미상'}` : latestReview ? `팀장 리뷰 ${latestReview.verdict} · ${compactText(latestReview.findings, 180)}` : latestExecutionResult ? `${personas[latestExecutionResult.employee_id]?.name ?? latestExecutionResult.employee_id} 실행 완료 · ${compactText(latestExecutionResult.content, 180)}` : '아직 실제 모델 실행·파일 변경·명령 결과가 없습니다.'}</span>
      </div>
      {failedJob && <section className="failure-card" role="alert"><span>EXECUTION NEEDS ACTION</span><b>{failedJob.kind} · step {failedJob.step}에서 멈췄습니다.</b><p><strong>영향</strong> 현재 업무 진행이 멈췄습니다. 완료된 실행과 증거는 유지됩니다.</p><p><strong>권장 행동</strong> 원인을 확인한 뒤 실패 단계만 재시도하세요.</p><details><summary>기술 세부</summary><code>{failedJob.error ?? '실행기가 오류 원인을 기록하지 않았습니다.'}</code></details></section>}
      {task && <div className="execution-controls">{task.state==='awaiting_lead_selection'&&<button className="solid-button" onClick={beginPlannedExecution}>팀장 선택</button>}{failedJob?<button className="solid-button" onClick={retryFailedJob} disabled={Boolean(busy)}>실패 단계 재시도</button>:task.jobs.some(job=>['paused','interrupted'].includes(job.state))?<button className="solid-button" onClick={()=>controlTask('resume')}>재개</button>:<button className="text-button" onClick={()=>controlTask('pause')} disabled={['completed','cancelled'].includes(task.state)}>일시 정지</button>}<button className="danger-button" onClick={()=>controlTask('cancel')} disabled={['completed','cancelled'].includes(task.state)}>취소</button></div>}
      {failedModelUsage[0] && <div className="execution-error"><b>마지막 실패</b><span>{failedModelUsage[0].error}</span></div>}
      <details className="execution-log"><summary>세부 실행 로그</summary><div className="execution-list">{task?.agent_messages?.slice(0, 4).map(message => <div key={message.id}><b>{personas[message.employee_id]?.name ?? message.employee_id}</b><span>{message.kind === 'run' ? '실행 결과' : message.kind === 'dispatch' ? '배정 판단' : message.kind === 'meeting' ? '회의 발언' : '브리핑'} · {new Date(message.created_at).toLocaleTimeString('ko-KR', {hour:'2-digit', minute:'2-digit'})}</span><p>{compactText(message.content, 260)}</p></div>) ?? <span>실행 기록 없음</span>}</div></details>
    </section>

    <section className="office-main">
      <div className={`office-stage product-office-stage ${cameraApi.dragging ? 'is-panning' : ''} ${focusedZone ? 'zone-focus' : ''} ${task?.state==='verifying'||task?.state==='team_review'||task?.state==='cross_review'?'qa-active':''} ${task?.state==='completed'?'office-complete':''}`} tabIndex={0} role="application" aria-label="AI 오피스 지도 · 화살표 키 또는 WASD로 이동, 버튼으로 확대·축소" onWheel={event => { event.preventDefault(); zoomCamera(event.deltaY < 0 ? .14 : -.14); }} onPointerDown={beginPan} onPointerMove={panOffice} onPointerUp={endPan} onPointerCancel={endPan} onKeyDown={panByKeyboard}>
        <div className="office-world" style={{transform:`translate(${camera.x}%, ${camera.y}%) scale(${camera.zoom})`}}>
        <img src="/assets/ai-office-zones-v2.png" alt="팀 구역이 구분된 탑다운 AI 자동화 오피스" />
        <div className="office-vignette" />
        <nav className="office-breadcrumb" aria-label="오피스 탐색"><span>전체 오피스</span>{focusedZone && <><i>›</i><b>{teamSigns.find(([id])=>id===focusedZone)?.[1]}</b></>}<div><button onClick={showAllOffice}>전체 보기</button><button onClick={()=>moveTeam(-1)}>이전 팀</button><button onClick={()=>moveTeam(1)}>다음 팀</button></div></nav>
        <div className="camera-controls"><button aria-label="확대" onClick={() => zoomCamera(.16)}>＋</button><button aria-label="축소" onClick={() => zoomCamera(-.16)}>－</button></div>
        <button className="room-marker marker-ceo" onClick={() => setModal('approval')}><span>CEO OFFICE</span><b>{task?.state==='completed' ? '업무 완료' : decisionCount ? `확인 필요 · ${decisionCount}` : '민감 업무만 대기'}</b></button>
        <button className="room-marker marker-meeting" onClick={() => setModal('meeting')}><span>MEETING HUB</span><b>{currentMeeting ? 'NAVI 회의 진행 중' : latestMeeting ? '실제 회의 완료' : '회의 없음'}</b></button>
        <button className="room-marker marker-qa" onClick={() => setModal('evidence')}><span>QA LAB</span><b>{task?.evidence.length ? `${task.evidence.length}건 검증` : '검증·보안'}</b></button>
        <div className="room-marker marker-work"><span>WORK FLOOR</span><b>{task?.title ?? '업무 대기'}</b></div>
        {Object.entries(deptZoneRects).map(([id, rect]) => <div key={id} aria-hidden="true" className={`dept-zone dept-zone-${id} ${focusedZone===id?'is-focused':''} ${(!terminalTask&&task?.assigned_employees.some(agentId=>teamForAgent(agentId)===id))?'active-zone':''}`} style={{left:`${rect.left}%`,top:`${rect.top}%`,width:`${rect.width}%`,height:`${rect.height}%`}} />)}
        {teamSigns.map(([id,title]) => <button key={id} className={`team-sign sign-${id} ${focusedZone===id?'selected':''} ${(!terminalTask&&task?.assigned_employees.some(agentId=>teamForAgent(agentId)===id))?'active-team':''}`} style={teamSignStyle(id)} onClick={() => focusZone(id)}><span>{title} · {employees.filter(employee=>teamForAgent(employee.id)===id).length}명 · {teamStatus(id,task)}</span></button>)}
        {employees.map(employee => {
          const motion=motions[employee.id];
          const position:[number,number]=[motion?.target.x ?? 50,motion?.target.y ?? 50];
          const activity=activeIds.has(employee.id) ? liveAgentEvents.get(employee.id)?.summary ?? task?.action_items.find(item=>item.owner===employee.id)?.description ?? '' : '';
          return <FloorAgent key={employee.id} employee={employee} active={activeIds.has(employee.id)} activity={activity} position={position} action={motion?.action ?? 'idle'} motion={motion} selected={focusedId===employee.id} bubble={bubbleByAgent.get(employee.id)} onFocus={focusEmployee} />;
        })}
        </div>
      </div>
    </section>

    <section className="event-timeline" aria-label="최근 회사 이벤트">
      <div className="timeline-heading"><span>RECENT TIMELINE</span><button className="text-button" onClick={()=>setModal('task')}>전체 보기</button></div>
      <ol aria-live="polite">{(task?.job_events ?? []).slice(0,5).map(event => <li key={event.id} className={event.type.includes('fail') ? 'timeline-alert' : ''}><button onClick={()=>event.agent_id && focusEmployee(event.agent_id)} disabled={!event.agent_id}><b>{personas[event.agent_id ?? '']?.name ?? event.agent_id ?? 'SYSTEM'}</b><span>{event.summary}</span><time>{new Date(event.created_at).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit'})}</time></button></li>)}{!task?.job_events.length&&<li className="timeline-empty">실제 실행 이벤트가 여기에 표시됩니다.</li>}</ol>
    </section>

    {selectedProject ? <footer className="primary-action-bar">
      <div className="company-state"><small>회사 전체 상태</small><b>{decisionCount ? '대표 결정 필요' : activeTaskCount ? '업무 진행 중' : selectedProject ? '진행 업무 없음' : '프로젝트 연결 필요'}</b></div>
      <button className="primary-task-button" onClick={task?.state==='awaiting_lead_selection'?beginPlannedExecution:task?.state==='planning'&&!activeJob?preparePlan:mainAction.action} disabled={!runtimeReady}>{mainAction.label}</button>
      <button className="bar-stat" onClick={()=>task&&setModal('task')}><small>진행 업무</small><b>{activeTaskCount}</b></button>
      <button className={`bar-stat ${decisionCount?'urgent':''}`} onClick={()=>setModal('approval')}><small>승인 필요</small><b>{decisionCount}</b></button>
    </footer> : <footer className="project-connect-cta"><span>프로젝트를 연결해야 업무를 시작할 수 있습니다.</span><button className="solid-button" onClick={()=>setModal('project')}>프로젝트 연결</button></footer>}

    {focusedEmployee && <ProfilePanel employee={focusedEmployee} active={activeIds.has(focusedEmployee.id)} activity={activeIds.has(focusedEmployee.id) ? liveAgentEvents.get(focusedEmployee.id)?.summary ?? task?.action_items.find(item=>item.owner===focusedEmployee.id)?.description ?? '' : ''} result={task?.agent_messages.find(message=>message.employee_id===focusedEmployee.id&&message.kind==='run')?.content ?? ''} evidenceCount={task?.evidence.length ?? 0} busy={Boolean(busy)} onSubmitCommand={(leadId,title,prompt)=>submitLeadCommand(leadId,title,prompt)} onClose={() => cameraApi.setFocusedId('')} />}
    {focusedZone && <TeamPanel teamId={focusedZone} members={employees.filter(employee=>teamForAgent(employee.id)===focusedZone)} lead={employees.find(employee=>teamForAgent(employee.id)===focusedZone&&leadIds.has(employee.id))} task={task} onClose={()=>cameraApi.setFocusedZone('')} onFocus={()=>locateZone(focusedZone)} />}

    {modal === 'project' && <ProjectModal projects={projects} projectId={projectId} setProjectId={setProjectId} projectPath={projectPath} setProjectPath={setProjectPath} busy={busy} pickProjectFolder={()=>void pickProjectFolder()} registerProject={()=>void registerProject()} onClose={() => setModal(null)} />}

    {modal === 'leadSelection' && <LeadSelectionModal task={task} leadIds={leadIds} selectedLeadIds={selectedLeadIds} setSelectedLeadIds={setSelectedLeadIds} busy={busy} selectLeads={()=>void selectLeads()} onClose={() => setModal(null)} />}

    {modal === 'workerSelection' && <WorkerSelectionModal task={task} employees={employees} workerProposalIds={workerProposalIds} selectedWorkerIds={selectedWorkerIds} setSelectedWorkerIds={setSelectedWorkerIds} busy={busy} selectWorkers={()=>void selectWorkers()} onClose={() => setModal(null)} />}

    {modal === 'leadCommand' && <LeadCommandModal directCommandLeadId={directCommandLeadId} directCommandTitle={directCommandTitle} setDirectCommandTitle={setDirectCommandTitle} directCommandText={directCommandText} setDirectCommandText={setDirectCommandText} busy={busy} submitLeadCommand={()=>void submitLeadCommand()} onClose={() => setModal(null)} />}

    {modal === 'request' && <RequestModal intakeMode={intakeMode} setIntakeMode={setIntakeMode} directLeadId={directLeadId} setDirectLeadId={setDirectLeadId} employees={employees} leadIds={leadIds} requestText={requestText} setRequestText={setRequestText} busy={busy} startChat={()=>void chat.startChat({requestText, directLeadId, intakeMode, initialAgents, setTasks, setTask, setModal, setRequestText})} startTask={(mode)=>void startTask(mode)} onClose={() => setModal(null)} />}

    {modal === 'chat' && <ChatModal task={task} chatDraft={chat.chatDraft} setChatDraft={chat.setChatDraft} chatBusy={chat.chatBusy} chatNeedsInfo={chat.chatNeedsInfo} busy={busy} sendChat={()=>void chat.sendChat(task, intakeMode, setTask)} beginExecutionFromChat={()=>void chat.beginExecutionFromChat({task, selectedProject, directLeadId, setModal, setWorkspace, setTask, setBrief})} onClose={() => setModal(null)} />}

    {modal === 'meeting' && <MeetingModal task={task} currentMeeting={currentMeeting} latestMeeting={latestMeeting} meetingObjective={meetingObjective} setMeetingObjective={setMeetingObjective} meetingAgenda={meetingAgenda} setMeetingAgenda={setMeetingAgenda} busy={busy} createMeeting={()=>void createMeeting()} onClose={() => setModal(null)} />}

    {modal === 'task' && <TaskModal task={task} brief={brief} completedRunIds={completedRunIds} mainAction={mainAction} busy={busy} controlTask={(action)=>void controlTask(action)} beginPlannedExecution={()=>void beginPlannedExecution()} workspace={workspace} onOpenRequest={()=>{setRequestText('');setDirectLeadId('NAVI');setIntakeMode('');setModal('request');}} onOpenChat={()=>task&&setModal('chat')} onOpenEvidence={()=>task&&setModal('evidence')} onOpenReflection={()=>setModal('reflection')} onClose={() => setModal(null)} />}

    {modal === 'evidence' && <EvidenceModal task={task} workspace={workspace} onClose={() => setModal(null)} />}

    {modal === 'approval' && <ApprovalModal task={task} approvalCount={approvalCount} pendingPermissions={pendingPermissions} busy={busy} decideApproval={(decision)=>void decideApproval(decision)} decidePermission={(requestId,decision)=>void decidePermission(requestId,decision,'')} onClose={() => setModal(null)} />}

    {modal === 'reflection' && <ReflectionModal task={task} reflectionSummary={reflectionSummary} setReflectionSummary={setReflectionSummary} reflectionCause={reflectionCause} setReflectionCause={setReflectionCause} reflectionImprovement={reflectionImprovement} setReflectionImprovement={setReflectionImprovement} lesson={lesson} setLesson={setLesson} busy={busy} submitReflection={()=>void submitReflection()} onClose={() => setModal(null)} />}

    {modal === 'settings' && <ModelSettingsPanel settings={settings} employees={employees} teamNames={teamNames} busy={busy} onClose={() => setModal(null)} />}
  </main>;
}

function ProfilePanel({employee,active,activity,result,evidenceCount,busy,onSubmitCommand,onClose}:{employee:Employee;active:boolean;activity:string;result:string;evidenceCount:number;busy:boolean;onSubmitCommand:(leadId:string,title:string,prompt:string)=>Promise<void>;onClose:()=>void}) {
  const persona = personas[employee.id] ?? personas.NAVI;
  const lead=leadIds.has(employee.id);
  const [title,setTitle]=useState('');
  const [prompt,setPrompt]=useState('');
  useEffect(()=>{setTitle('');setPrompt('');},[employee.id]);
  return <aside className="profile-panel"><button onClick={onClose}>×</button><Avatar id={employee.id}/><div><span>{teamNames[employee.team] ?? employee.team}</span><h2>{persona.name}</h2><p>{persona.bio}</p>{lead && employee.id !== 'NAVI' && <section className="lead-command"><b>팀장에게 직접 지시</b><input value={title} onChange={event=>setTitle(event.target.value)} placeholder="업무 제목"/><textarea value={prompt} onChange={event=>setPrompt(event.target.value)} placeholder="프롬프트: 목표, 범위, 산출물, 확인 기준"/><button className="solid-button" disabled={!title.trim()||!prompt.trim()||busy} onClick={()=>void onSubmitCommand(employee.id,title,prompt)}>판단 Job 시작</button></section>}</div><dl><div><dt>직책</dt><dd>{agentRole(employee.id,lead)}</dd></div><div><dt>역할</dt><dd>{lead?'업무 분담 · 리뷰 · 디버깅':'실제 구현 · 문서 · 테스트 수행'}</dd></div><div><dt>전문 분야</dt><dd>{persona.specialty}</dd></div><div><dt>현재 업무</dt><dd className={active?'active':''}>{active ? (activity || '실제 Job 처리 중') : '배정 대기'}</dd></div><div><dt>최근 결과</dt><dd>{result ? result.slice(0,600) : '아직 결과물 없음'}</dd></div><div><dt>검증 근거</dt><dd>{evidenceCount}건</dd></div></dl></aside>;
}

function TeamPanel({teamId,members,lead,task,onClose,onFocus}:{teamId:string;members:Employee[];lead:Employee|undefined;task:Task|null;onClose:()=>void;onFocus:()=>void}) {
  const title=teamSigns.find(item=>item[0]===teamId)?.[1] ?? teamId;
  const active=['completed','cancelled'].includes(task?.state??'') ? [] : task?.assigned_employees.filter(id=>teamForAgent(id)===teamId) ?? [];
  const recent=task?.events.find(event=>event.employee_ids.some(id=>teamForAgent(id)===teamId));
  const meeting=task?.meetings.find(item=>item.participants.some(id=>teamForAgent(id)===teamId));
  const skills=members.flatMap(member=>member.required_skills??[]).filter((value,index,array)=>array.indexOf(value)===index).slice(0,8);
  return <aside className="team-panel"><button className="panel-close" onClick={onClose}>×</button><span>DEPARTMENT</span><h2>{title}</h2><p className="team-panel-state">{teamStatus(teamId,task)}</p><InfoBlock label="팀장" value={lead ? personas[lead.id]?.name ?? lead.id : '배정 없음'} /><InfoBlock label="구성원" value={members.map(member=>personas[member.id]?.name ?? member.id).join(' · ')} /><InfoBlock label="현재 업무" value={active.length ? task?.title ?? '업무 진행 중' : '대기 중'} /><InfoBlock label="최근 활동" value={recent?.note ?? '최근 활동 없음'} /><InfoBlock label="활성 스킬" value={skills.join(' · ') || '준비 중'} /><InfoBlock label="관련 회의" value={meeting?.objective ?? '관련 회의 없음'} /><button className="solid-button wide" onClick={onFocus}>팀 포커스</button></aside>;
}
