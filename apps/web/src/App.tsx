import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { api, type Employee, type JobEvent, type McpConnection, type ModelSettings, type Project, type ProviderModel, type RuntimeVersion, type Task, type UsageSummary, type Workspace } from './api';
import { personas, type Persona } from './personas';
import { resolveMotion, type AgentAction } from './motion';

const initialAgents = ['NAVI', 'FRAME', 'BUILD', 'FRONT', 'BACK', 'TRACE', 'GUARD'];
const leadIds = new Set(['NAVI','FRAME','BUILD','LINK','SHIP','GUARD','GROW','LENS']);
const spriteIds = ['NAVI','ROUTE','CLOCK','FRAME','FLOW','MOSS','BUILD','FRONT','BACK','LINK','SIGNAL','EVAL','SHIP','SRE','COST','GUARD','TRACE','SHIELD','GROW','VOICE','PULSE','LENS','JOURNEY','DOCS'];
const avatarIndexes: Record<string, number> = { NAVI:1, ROUTE:0 };
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
const roomPositions: Record<'meeting'|'qa'|'ceo', [number,number][]> = {
  meeting:[[50,25],[57,23],[64,26],[67,33],[62,39],[54,39],[48,34]],
  qa:[[83,17],[90,18],[87,25],[92,30],[83,32],[88,37],[94,22]],
  ceo:[[15,13],[21,14],[24,21],[18,25],[12,22],[26,15],[14,28]],
};
const teamSigns = [
  ['product','제품·기획팀','PM · 리서치 · 로드맵'], ['design','디자인·프론트팀','UX · UI · 프론트엔드'],
  ['backend','백엔드·AI팀','API · 데이터 · AI'], ['growth','마케팅·성장팀','캠페인 · 지표'],
  ['lounge','공용 라운지','팀 허들 · 협업'], ['ops','운영·보안팀','신뢰성 · QA · 보안'],
] as const;

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
  const [model, setModel] = useState<ModelSettings>({provider:'openrouter',lead_model:'openai/gpt-5',worker_model:'openai/gpt-5-mini',configured:false});
  const [providerModels, setProviderModels] = useState<ProviderModel[]>([]);
  const [mcpConnections, setMcpConnections] = useState<McpConnection[]>([]);
  const [usage, setUsage] = useState<UsageSummary>({input_tokens:0,output_tokens:0,cost_usd:0});
  const [requestText, setRequestText] = useState('');
  const [projectPath, setProjectPath] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [brief, setBrief] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState<'project'|'request'|'settings'|'meeting'|'task'|'approval'|'evidence'|'review'|'reflection'|'leadSelection'|'workerSelection'|'leadCommand'|null>(null);
  const [focusedId, setFocusedId] = useState('');
  const [focusedZone, setFocusedZone] = useState('');
  const [camera, setCamera] = useState({ zoom: 1, x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const [isWalkingTransition, setIsWalkingTransition] = useState(false);
  const [walkFrame, setWalkFrame] = useState(false);
  const [runningAgentIds, setRunningAgentIds] = useState<string[]>([]);
  const [selectedLeadIds, setSelectedLeadIds] = useState<string[]>([]);
  const [selectedWorkerIds, setSelectedWorkerIds] = useState<string[]>([]);
  const [directLeadId, setDirectLeadId] = useState('NAVI');
  const [directCommandLeadId, setDirectCommandLeadId] = useState('');
  const [directCommandTitle, setDirectCommandTitle] = useState('');
  const [directCommandText, setDirectCommandText] = useState('');
  const executionControl = useRef<'active'|'paused'|'cancelled'>('active');
  const dragOrigin = useRef<{ pointerX:number; pointerY:number; x:number; y:number } | null>(null);
  const [meetingObjective, setMeetingObjective] = useState('');
  const [meetingAgenda, setMeetingAgenda] = useState('');
  const [reviewerId, setReviewerId] = useState('');
  const [reviewFindings, setReviewFindings] = useState('');
  const [reflectionSummary, setReflectionSummary] = useState('');
  const [reflectionCause, setReflectionCause] = useState('');
  const [reflectionImprovement, setReflectionImprovement] = useState('');
  const [lesson, setLesson] = useState('');
  const [mcpProvider, setMcpProvider] = useState<McpConnection['provider']>('github');
  const [mcpName, setMcpName] = useState('GitHub MCP');
  const [mcpUrl, setMcpUrl] = useState('');
  const [mcpToken, setMcpToken] = useState('');

  const load = async () => {
    try {
      const [roster, savedProjects, tasks, settings, costs, connections, version] = await Promise.all([api.employees(), api.projects(), api.tasks(), api.modelSettings(), api.usageSummary(), api.mcpConnections(), api.runtime()]);
      setEmployees(roster); setProjects(savedProjects); setTasks(tasks); setProjectId(savedProjects[0]?.id ?? ''); setTask(tasks[0] ?? null); setModel(settings); setUsage(costs); setMcpConnections(connections); setRuntime(version); setError('');
    } catch (cause) { setError(friendlyError(cause)); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); void api.providerModels().then(setProviderModels).catch(()=>setProviderModels([])); }, []);
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
  const runtimeReady = runtime?.api_build_id === runtime?.worker_build_id && runtime?.schema_version === 2;
  const completedRunIds = new Set(task?.events.filter(event => event.action === 'agent_run').flatMap(event => event.employee_ids) ?? []);
  const failedModelUsage = task?.model_usage?.filter(item => item.error) ?? [];
  const latestExecution = task?.events.find(event => event.action === 'agent_run');
  const directTaskLead = task?.events.find(event => event.action === 'direct_dispatch')?.employee_ids[0];
  const approvalCount = task?.state === 'awaiting_approval' ? 1 : 0;
  const activeTaskCount = tasks.filter(item=>item.jobs.some(job=>['queued','running','pause_requested','cancel_requested'].includes(job.state)) || ['awaiting_lead_selection','awaiting_approval'].includes(item.state)).length;
  const mainAction = !selectedProject ? {label:'프로젝트 연결', action:()=>setModal('project')} : approvalCount ? {label:'승인 패널 열기', action:()=>setModal('approval')} : !task || task.state === 'completed' ? {label:'새 업무 요청', action:()=>setModal('request')} : task.state==='planning' ? {label:activeJob ? 'NAVI 판단 진행 중' : 'NAVI 판단 다시 시작', action:()=>setModal('task')} : task.state==='awaiting_lead_selection' ? {label:'팀장 선택', action:()=>setModal('leadSelection')} : task.state==='awaiting_worker_selection' ? {label:'팀장 자동 배정 중', action:()=>setModal('task')} : {label:'현재 업무 열기', action:()=>setModal('task')};
  const focusedEmployee = employees.find(employee => employee.id === focusedId);
  const motions = useMemo(() => Object.fromEntries(employees.map(employee => {
    const taskAssignmentIndex=task?.assigned_employees.indexOf(employee.id) ?? -1;
    const assignedIndex=employee.id==='NAVI' ? 0 : Math.max(1, taskAssignmentIndex + 1);
    const live=liveAgentEvents.get(employee.id);
    const location=lastLocationEvents.get(employee.id);
    const active=activeIds.has(employee.id);
    const zone=(active ? live?.payload.zone ?? location?.payload.zone : undefined) as string | undefined;
    const action=active ? (live?.payload.action as AgentAction | undefined) ?? (location?.payload.action as AgentAction | undefined) ?? (isWalkingTransition ? 'walk' as AgentAction : undefined) : undefined;
    const motion=resolveMotion({employeeId:employee.id, taskState:zone === 'meeting' ? 'meeting' : zone === 'qa' ? 'team_review' : zone === 'ceo' ? 'awaiting_approval' : task?.state, active, isLead:leadIds.has(employee.id), assignmentIndex:assignedIndex});
    return [employee.id, {...motion, action:action ?? motion.action}];
  })), [employees, task, isWalkingTransition, runningAgentIds]);
  const previousTaskState=useRef<string | null>(null);
  useEffect(() => {
    if (!task?.state || previousTaskState.current === null) { previousTaskState.current=task?.state ?? null; return; }
    if (previousTaskState.current !== task.state) { previousTaskState.current=task.state; setIsWalkingTransition(true); const timeout=window.setTimeout(()=>setIsWalkingTransition(false), 1300); return ()=>window.clearTimeout(timeout); }
  }, [task?.state]);
  useEffect(() => { const interval=window.setInterval(()=>setWalkFrame(current=>!current), 180); return ()=>window.clearInterval(interval); }, []);
  const focusZone = (zone: string) => {
    setFocusedZone(zone);
  };
  const locateZone = (zone: string) => {
    const members = employees.filter(employee => teamForAgent(employee.id) === zone);
    const points = members.map(employee => deskPositions[employee.id]).filter(Boolean);
    if (!points.length) return;
    const x = points.reduce((sum, point) => sum + point[0], 0) / points.length;
    const y = points.reduce((sum, point) => sum + point[1], 0) / points.length;
    setCamera({zoom:1.55, x:(50-x)*.55, y:(50-y)*.55});
  };
  const showAllOffice = () => { setCamera({zoom:1,x:0,y:0}); setFocusedZone(''); setFocusedId(''); };
  const moveTeam = (direction:number) => {
    const ids:string[]=teamSigns.map(([id])=>id);
    const current=Math.max(0,ids.indexOf(focusedZone));
    focusZone(ids[(current+direction+ids.length)%ids.length]);
  };
  const focusEmployee = (id: string) => {
    setFocusedId(id);
  };
  const zoomCamera = (delta:number) => setCamera(current => ({...current, zoom: Math.max(1, Math.min(2.35, current.zoom + delta))}));
  const beginPan = (event: React.PointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest('button')) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragOrigin.current = { pointerX:event.clientX, pointerY:event.clientY, x:camera.x, y:camera.y };
    setDragging(true);
  };
  const panOffice = (event: React.PointerEvent<HTMLDivElement>) => {
    const origin = dragOrigin.current;
    if (!origin) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const limit = Math.max(0, (camera.zoom - 1) * 42);
    setCamera(current => ({...current, x:Math.max(-limit, Math.min(limit, origin.x + (event.clientX-origin.pointerX)/bounds.width*100)), y:Math.max(-limit, Math.min(limit, origin.y + (event.clientY-origin.pointerY)/bounds.height*100))}));
  };
  const endPan = () => { dragOrigin.current = null; setDragging(false); };

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
        const prepared = await api.createWorkspace(created.id, selectedProject.id, selectedProject.git_available ? 'worktree' : 'copy'); setWorkspace(prepared);
        await api.queuePlan(created.id);
        setBrief(`${personas[directLeadId]?.name ?? directLeadId} 팀장 판단 Job을 대기열에 넣었습니다. worker 제안 뒤 대표가 실행자를 선택합니다.`);
        setRequestText(''); setModal('task'); return;
      }
      await api.contract(created.id); setTask(created); await api.queuePlan(created.id);
      if (mode === 'plan') {
        setBrief('NAVI 계획 Job을 대기열에 넣었습니다. 실행자 호출과 작업공간 생성은 하지 않습니다.');
        setRequestText(''); setModal('task'); return;
      }
      const prepared = await api.createWorkspace(created.id, selectedProject.id, selectedProject.git_available ? 'worktree' : 'copy'); setWorkspace(prepared);
      setBrief('NAVI가 필요한 부서 팀장을 판단 중입니다. 완료되면 팀장 선택이 열립니다.');
      setRequestText(''); setModal('task');
    } catch (cause) { setError(friendlyError(cause)); }
    finally { setRunningAgentIds([]); setBusy(''); }
  };

  const saveModel = async () => {
    setBusy('모델 연결 저장 중');
    try { const saved = await api.saveModelSettings(model.lead_model, model.worker_model, apiKey); setModel(saved); setApiKey(''); setModal(null); setError(''); }
    catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(''); }
  };
  const saveMcp = async () => {
    if (!mcpUrl.trim()) { setError('MCP 서버 URL을 입력해 주세요.'); return; }
    setBusy('MCP 연결을 저장하는 중');
    try { const saved=await api.saveMcpConnection(mcpProvider,mcpName.trim()||mcpProvider,'streamable_http',mcpUrl.trim(),mcpToken); setMcpConnections(current=>[saved,...current]); setMcpUrl(''); setMcpToken(''); setError(''); }
    catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(''); }
  };

  const createMeeting = async () => {
    if (!task || !meetingObjective.trim()) return;
    setBusy('회의를 준비하는 중');
    try { const updated=await api.createMeeting(task.id, meetingObjective.trim(), task.assigned_employees, meetingAgenda.split('\n').map(item=>item.trim()).filter(Boolean)); setTask(updated); setMeetingObjective(''); setMeetingAgenda(''); setError(''); }
    catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(''); }
  };
  const runMeeting = async () => {
    if (!task || !currentMeeting) return;
    setBusy('실제 팀장 회의 Job을 시작하는 중');
    try { await api.queueMeeting(task.id, currentMeeting.id); setModal(null); setError(''); }
    catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(''); }
  };
  const selectLeads = async () => { if (!task || !selectedLeadIds.length) return; setBusy('선택 팀장을 회의에 소집하는 중'); try { setTask(await api.selectLeads(task.id, selectedLeadIds)); setModal('task'); setBrief('팀장 선택 완료. 회의, 실행자 배정, 실행, 팀장 리뷰가 자동 진행됩니다.'); } catch (cause) { setError(friendlyError(cause)); } finally { setBusy(''); } };
  const selectWorkers = async () => { if (!task || !selectedWorkerIds.length || !workspace) return; setBusy('선택 실행자 Job을 대기열에 넣는 중'); try { const updated=await api.selectWorkers(task.id, selectedWorkerIds); setTask(updated); await api.queueExecution(task.id, workspace.id, selectedWorkerIds, task.request); setModal(null); setError(''); } catch (cause) { setError(friendlyError(cause)); } finally { setBusy(''); } };
  const controlTask = async (action:'pause'|'resume'|'cancel') => { if (!task) return; try { if (action==='cancel') { setTask(await api.cancel(task.id)); setBrief('업무를 취소했습니다. 대기 Job은 즉시 취소되고, 실행 중 호출은 안전 지점에서 중단됩니다.'); setError(''); return; } const job=task.jobs.find(item=>['queued','running','pause_requested','paused','interrupted','cancel_requested'].includes(item.state)); if (job) await api.controlJob(job.id, action); else setTask(action==='pause' ? await api.pause(task.id) : await api.resume(task.id)); setBrief(action==='pause'?'정지 요청됨. 현재 모델 호출 뒤 안전 지점에서 멈춥니다.':'재개 요청됨. worker가 다음 step부터 계속합니다.'); setError(''); } catch(cause) { setError(friendlyError(cause)); } };
  const retryFailedJob = async () => { if (!failedJob) return; setBusy('실패 단계 재시도 중'); try { await api.retryJob(failedJob.id); setTask(await api.task(failedJob.task_id)); setBrief('완료된 실행자는 유지하고 실패한 단계부터 다시 시작합니다.'); setError(''); } catch(cause) { setError(friendlyError(cause)); } finally { setBusy(''); } };
  const beginPlannedExecution = async () => { if (!task) return; setSelectedLeadIds(task.assigned_employees); setModal('leadSelection'); };
  const preparePlan = async () => { if (!task) return; setBusy('NAVI 계획 Job을 대기열에 넣는 중'); try { await api.queuePlan(task.id); setBrief('NAVI가 팀장 후보를 다시 판단 중입니다.'); setError(''); } catch(cause) { setError(friendlyError(cause)); } finally { setBusy(''); } };
  const startLeadReview = async () => { if (!task) return; try { await api.queueReview(task.id); setBrief('팀장 실제 리뷰 Job을 시작했습니다.'); setError(''); } catch(cause) { setError(friendlyError(cause)); } };
  const openLeadCommand = (leadId:string) => { setDirectCommandLeadId(leadId); setDirectCommandTitle(''); setDirectCommandText(''); setModal('leadCommand'); };
  const submitLeadCommand = async (leadId=directCommandLeadId, title=directCommandTitle, prompt=directCommandText) => { if (!selectedProject || !leadId || !title.trim() || !prompt.trim()) return; setBusy('팀장 직접 업무를 등록하는 중'); try { const created=await api.create(title.trim(), prompt.trim(), [], 'direct_lead', leadId); setTasks(current=>[created,...current]); await api.contract(created.id); const prepared=await api.createWorkspace(created.id, selectedProject.id, selectedProject.git_available ? 'worktree' : 'copy'); setWorkspace(prepared); await api.queuePlan(created.id); setTask(created); setModal('task'); setBrief(`${personas[leadId]?.name ?? leadId} 팀장이 실행자를 자동 배정하고 별도 리뷰합니다.`); } catch(cause) { setError(friendlyError(cause)); } finally { setBusy(''); } };
  const submitReview = async (verdict:'pass'|'changes_requested'|'blocked') => {
    if (!task || !reviewerId) return;
    setBusy('리뷰를 기록하는 중');
    try { setTask(await api.review(task.id, reviewerId, verdict, reviewFindings)); setReviewFindings(''); setModal(null); setError(''); }
    catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(''); }
  };
  const decideApproval = async (decision:'approve'|'rework'|'reject') => {
    if (!task) return;
    setBusy('대표 결정을 기록하는 중');
    try { setTask(await api.approval(task.id, decision, '대표 화면에서 기록한 결정')); setModal(null); setError(''); }
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
      <button className="company-mark" onClick={() => setFocusedId('NAVI')}><span>A</span><b>AI OFFICE</b></button>
      <div className="header-actions">
        <select className="header-task-select" aria-label="현재 업무 선택" value={task?.id ?? ''} onChange={event=>void api.task(event.target.value).then(setTask).catch(cause=>setError(friendlyError(cause)))}><option value="">업무 선택</option>{tasks.map(item=><option key={item.id} value={item.id}>{item.id} · {item.title}</option>)}</select>
        <button className="header-project" onClick={() => setModal('project')}><small>현재 프로젝트</small><b>{selectedProject?.name ?? '프로젝트 연결'}</b></button>
        <button className="header-new" onClick={() => { setRequestText(''); setDirectLeadId('NAVI'); setModal('request'); }}>+ 새 업무</button>
        <button className="header-brief" onClick={() => setModal('task')}><small>CEO 브리핑</small><b>{task?.title ?? '대기 중'}</b></button>
        <span className="header-cost"><small>비용</small><b>${usage.cost_usd.toFixed(2)}</b></span>
        <button className="header-settings" onClick={() => setModal('settings')}>설정</button>
      </div>
    </header>

    {error && <div className="toast-error"><b>연결 또는 입력 오류</b><span>{error}</span><button onClick={() => setError('')}>×</button></div>}
    {!runtimeReady && <div className="toast-error"><b>실행기 버전 불일치</b><span>API와 worker 준비 상태를 확인할 수 없습니다. AI Office 실행기를 다시 시작하세요.</span></div>}

    <section className="execution-console" aria-label="실제 실행 현황">
      <div className="execution-heading"><span>LIVE EXECUTION</span><b>{activeJob ? '실행 중' : failedJob ? '실행 실패' : latestExecution ? '최근 실행 완료' : '실행 대기'}</b></div>
      <div className="execution-metrics"><div><small>실행 중</small><b>{activeIds.size}</b></div><div><small>완료 실행</small><b>{completedRunIds.size}</b></div><div><small>검증 증거</small><b>{task?.evidence.length ?? 0}</b></div><div className={failedModelUsage.length ? 'metric-alert' : ''}><small>실패</small><b>{failedModelUsage.length}</b></div></div>
      <div className="execution-detail">
        <b>{task?.title ?? '선택된 업무 없음'}</b>
        <span>{activeJob ? `${activeJob.kind} · step ${activeJob.step} · ${activeJob.state}${activeJob.heartbeat_at ? ` · heartbeat ${new Date(activeJob.heartbeat_at).toLocaleTimeString()}` : ''}` : failedJob ? `${failedJob.kind} · step ${failedJob.step} · ${failedJob.error ?? '원인 미상'}` : latestExecution ? `${latestExecution.actor} · ${latestExecution.note}` : '아직 실제 모델 실행·파일 변경·명령 결과가 없습니다.'}</span>
      </div>
      {task && <div className="execution-controls">{task.state==='awaiting_lead_selection'&&<button className="solid-button" onClick={beginPlannedExecution}>팀장 선택</button>}{failedJob?<button className="solid-button" onClick={retryFailedJob} disabled={Boolean(busy)}>실패 단계 재시도</button>:task.jobs.some(job=>['paused','interrupted'].includes(job.state))?<button className="solid-button" onClick={()=>controlTask('resume')}>재개</button>:<button className="text-button" onClick={()=>controlTask('pause')} disabled={['completed','cancelled'].includes(task.state)}>일시 정지</button>}<button className="danger-button" onClick={()=>controlTask('cancel')} disabled={['completed','cancelled'].includes(task.state)}>취소</button></div>}
      {failedModelUsage[0] && <div className="execution-error"><b>마지막 실패</b><span>{failedModelUsage[0].error}</span></div>}
      <div className="execution-list">{task?.agent_messages?.slice(0, 3).map(message => <div key={message.id}><b>{personas[message.employee_id]?.name ?? message.employee_id}</b><span>{message.kind === 'run' ? '실행 결과' : message.kind === 'dispatch' ? '배정 판단' : message.kind === 'meeting' ? '회의 발언' : '브리핑'} · {new Date(message.created_at).toLocaleTimeString('ko-KR', {hour:'2-digit', minute:'2-digit'})}</span><p>{message.content}</p></div>) ?? <span>실행 기록 없음</span>}</div>
    </section>

    <section className="office-main">
      <div className={`office-stage product-office-stage ${dragging ? 'is-panning' : ''} ${focusedZone ? 'zone-focus' : ''} ${task?.state==='verifying'||task?.state==='team_review'||task?.state==='cross_review'?'qa-active':''} ${task?.state==='completed'?'office-complete':''}`} onWheel={event => { event.preventDefault(); zoomCamera(event.deltaY < 0 ? .14 : -.14); }} onPointerDown={beginPan} onPointerMove={panOffice} onPointerUp={endPan} onPointerCancel={endPan}>
        <div className="office-world" style={{transform:`translate(${camera.x}%, ${camera.y}%) scale(${camera.zoom})`}}>
        <img src="/assets/ai-office-zones-v2.png" alt="팀 구역이 구분된 탑다운 AI 자동화 오피스" />
        <div className="office-vignette" />
        <nav className="office-breadcrumb" aria-label="오피스 탐색"><span>전체 오피스</span>{focusedZone && <><i>›</i><b>{teamSigns.find(([id])=>id===focusedZone)?.[1]}</b></>}<div><button onClick={showAllOffice}>전체 보기</button><button onClick={()=>moveTeam(-1)}>이전 팀</button><button onClick={()=>moveTeam(1)}>다음 팀</button></div></nav>
        <div className="camera-controls"><button aria-label="확대" style={cameraButton} onClick={() => zoomCamera(.16)}>＋</button><button aria-label="축소" style={cameraButton} onClick={() => zoomCamera(-.16)}>－</button></div>
        <button className="room-marker marker-ceo" onClick={() => setModal('approval')}><span>CEO OFFICE</span><b>대표 승인 {approvalCount ? `· ${approvalCount}` : ''}</b></button>
        <button className="room-marker marker-meeting" onClick={() => setModal('meeting')}><span>MEETING HUB</span><b>{currentMeeting ? 'NAVI 회의 진행 중' : latestMeeting ? '실제 회의 완료' : '회의 없음'}</b></button>
        <button className="room-marker marker-qa" onClick={() => setModal('evidence')}><span>QA LAB</span><b>{task?.evidence.length ? `${task.evidence.length}건 검증` : '검증·보안'}</b></button>
        <div className="room-marker marker-work"><span>WORK FLOOR</span><b>{task?.title ?? '업무 대기'}</b></div>
        {teamSigns.map(([id,title]) => <button key={id} className={`team-sign sign-${id} ${focusedZone===id?'selected':''} ${(task?.assigned_employees.some(agentId=>teamForAgent(agentId)===id))?'active-team':''}`} style={teamSignStyle(id)} onClick={() => focusZone(id)}><span>{title} · {employees.filter(employee=>teamForAgent(employee.id)===id).length}명 · {teamStatus(id,task)}</span></button>)}
        {employees.map(employee => {
          const motion=motions[employee.id];
          const position:[number,number]=[motion?.target.x ?? 50,motion?.target.y ?? 50];
          const activity=task?.action_items.find(item=>item.owner===employee.id)?.description ?? liveAgentEvents.get(employee.id)?.summary ?? '';
          return <FloorAgent key={employee.id} employee={employee} active={activeIds.has(employee.id)} activity={activity} position={position} action={motion?.action ?? 'idle'} walkFrame={walkFrame} selected={focusedId===employee.id} bubble={bubbleByAgent.get(employee.id)} onFocus={focusEmployee} />;
        })}
        </div>
      </div>
    </section>

    {selectedProject ? <footer className="primary-action-bar">
      <div className="company-state"><small>회사 전체 상태</small><b>{approvalCount ? '대표 결정 필요' : activeTaskCount ? '업무 진행 중' : selectedProject ? '진행 업무 없음' : '프로젝트 연결 필요'}</b></div>
      <button className="primary-task-button" onClick={task?.state==='awaiting_lead_selection'?beginPlannedExecution:task?.state==='planning'&&!activeJob?preparePlan:mainAction.action} disabled={!runtimeReady}>{mainAction.label}</button>
      <button className="bar-stat" onClick={()=>task&&setModal('task')}><small>진행 업무</small><b>{activeTaskCount}</b></button>
      <button className={`bar-stat ${approvalCount?'urgent':''}`} onClick={()=>setModal('approval')}><small>승인 필요</small><b>{approvalCount}</b></button>
    </footer> : <footer className="project-connect-cta"><span>프로젝트를 연결해야 업무를 시작할 수 있습니다.</span><button className="solid-button" onClick={()=>setModal('project')}>프로젝트 연결</button></footer>}

    {focusedEmployee && <ProfilePanel employee={focusedEmployee} active={activeIds.has(focusedEmployee.id)} activity={task?.action_items.find(item=>item.owner===focusedEmployee.id)?.description ?? liveAgentEvents.get(focusedEmployee.id)?.summary ?? ''} result={task?.agent_messages.find(message=>message.employee_id===focusedEmployee.id&&message.kind==='run')?.content ?? ''} evidenceCount={task?.evidence.length ?? 0} busy={Boolean(busy)} onSubmitCommand={submitLeadCommand} onClose={() => setFocusedId('')} />}
    {focusedZone && <TeamPanel teamId={focusedZone} members={employees.filter(employee=>teamForAgent(employee.id)===focusedZone)} lead={employees.find(employee=>teamForAgent(employee.id)===focusedZone&&leadIds.has(employee.id))} task={task} onClose={()=>setFocusedZone('')} onFocus={()=>locateZone(focusedZone)} />}

    {modal === 'project' && <Dialog title="작업 프로젝트" onClose={() => setModal(null)}>
      <p className="dialog-copy">프로젝트를 연결하면 에이전트가 원본과 분리된 작업공간에서 작업합니다.</p>
      {projects.length > 0 && <div className="project-list">{projects.map(project => <button key={project.id} className={project.id === projectId ? 'selected' : ''} onClick={() => { setProjectId(project.id); setModal(null); }}><b>{project.name}</b><small>{project.root_path}</small></button>)}</div>}
      <label>새 프로젝트 폴더</label><div className="dialog-input-row"><input value={projectPath} onChange={event => setProjectPath(event.target.value)} placeholder="C:\\Projects\\my-app"/><button className="text-button picker-button" onClick={pickProjectFolder} disabled={Boolean(busy)}>폴더 선택</button><button className="solid-button" onClick={registerProject} disabled={Boolean(busy)}>{busy || '연결'}</button></div>
    </Dialog>}

    {modal === 'leadSelection' && <Dialog title="NAVI 판단 · 팀장 선택" onClose={() => setModal(null)}>
      <p className="dialog-copy">NAVI가 필요한 부서 팀장 후보만 제시했습니다. 대표가 실제 회의 참석자를 확정합니다.</p>
      <div className="project-list">{task?.assigned_employees.map(id => <label key={id}><input type="checkbox" checked={selectedLeadIds.includes(id)} onChange={()=>setSelectedLeadIds(current=>current.includes(id)?current.filter(value=>value!==id):[...current,id])}/><b>{personas[id]?.name ?? id}</b><small>{agentRole(id, leadIds.has(id))}</small></label>)}</div>
      <button className="solid-button wide" disabled={!selectedLeadIds.length||Boolean(busy)} onClick={selectLeads}>{busy || '선택 팀장 회의 시작'}</button>
    </Dialog>}

    {modal === 'workerSelection' && <Dialog title="팀장 회의 완료 · 실행자 선택" onClose={() => setModal(null)}>
      <p className="dialog-copy">대표가 실제 실행자를 지정합니다. 선택된 실행자만 하위 모델로 호출됩니다.</p>
      <div className="project-list">{employees.filter(employee=>workerProposalIds.has(employee.id)).map(employee => <label key={employee.id}><input type="checkbox" checked={selectedWorkerIds.includes(employee.id)} onChange={()=>setSelectedWorkerIds(current=>current.includes(employee.id)?current.filter(value=>value!==employee.id):[...current,employee.id])}/><b>{personas[employee.id]?.name ?? employee.id}</b><small>{task?.action_items.find(item=>item.owner===employee.id)?.description ?? employee.title}</small></label>)}</div>
      <button className="solid-button wide" disabled={!selectedWorkerIds.length||Boolean(busy)} onClick={selectWorkers}>{busy || '선택 실행자 배정·실행'}</button>
    </Dialog>}

    {modal === 'leadCommand' && <Dialog title="팀장에게 직접 지시" onClose={() => setModal(null)}>
      <p className="dialog-copy">독립 소규모 업무입니다. NAVI 판단·팀장 회의는 생략하지만, worker 선택과 해당 팀장 실제 리뷰는 반드시 거칩니다.</p>
      <InfoBlock label="수신 팀장" value={personas[directCommandLeadId]?.name ?? directCommandLeadId} />
      <label>업무 제목</label><input value={directCommandTitle} onChange={event=>setDirectCommandTitle(event.target.value)} placeholder="짧고 검증 가능한 제목" />
      <label>명령</label><textarea className="request-editor compact-editor" value={directCommandText} onChange={event=>setDirectCommandText(event.target.value)} placeholder="목표, 범위, 산출물, 확인 기준" />
      <button className="solid-button wide" disabled={!directCommandTitle.trim()||!directCommandText.trim()||Boolean(busy)} onClick={()=>void submitLeadCommand()}>{busy || '팀장 판단 시작'}</button>
    </Dialog>}

    {modal === 'request' && <Dialog title="새 업무 요청" onClose={() => setModal(null)}>
      <p className="dialog-copy">NAVI는 여러 부서가 필요한 업무용입니다. 작은 범위는 팀장을 직접 지정하면 NAVI 계획과 팀장 회의를 건너뜁니다.</p>
      <label>지시 대상</label><select value={directLeadId} onChange={event=>setDirectLeadId(event.target.value)}><option value="NAVI">NAVI · 부서 판단 후 팀장 후보 제시</option>{employees.filter(employee=>leadIds.has(employee.id)&&employee.id!=='NAVI').map(employee=><option key={employee.id} value={employee.id}>{personas[employee.id]?.name ?? employee.id} · {employee.title} 팀장에게 직접 지시</option>)}</select>
      <textarea className="request-editor" value={requestText} onChange={event => setRequestText(event.target.value)} placeholder="예: 로그인 오류를 찾아 수정하고 테스트까지 실행해." autoFocus />
      <div className="decision-row">{directLeadId==='NAVI'&&<button className="text-button" onClick={()=>startTask('plan')} disabled={Boolean(busy)}>{busy || '계획만 생성'}</button>}<button className="solid-button" onClick={()=>startTask('execute')} disabled={Boolean(busy)}>{busy || (directLeadId==='NAVI'?'업무 시작':'팀장에게 직접 지시')}</button></div>
    </Dialog>}

    {modal === 'meeting' && <Dialog title="구조화된 회의" onClose={() => setModal(null)}>
      <p className="dialog-copy">{currentMeeting?.objective ?? '현재 진행 중인 회의가 없습니다.'}</p>
      {currentMeeting && <><InfoBlock label="참석" value={currentMeeting.participants.map(id => personas[id]?.name ?? id).join(' · ')} /><InfoBlock label="안건" value={currentMeeting.agenda.join(' · ')} /><InfoBlock label="결정" value={currentMeeting.decisions.join(' · ') || '회의 Job 자동 진행 중'} /><div className="meeting-transcript">{task?.agent_messages.filter(message => message.kind === 'meeting').map(message => <article key={message.id}><b>{personas[message.employee_id]?.name ?? message.employee_id}</b><p>{message.content}</p></article>)}</div></>}
      {latestMeeting && !currentMeeting && <InfoBlock label="마지막 회의 상태" value="실제 발언 기록이 남은 회의입니다." />}
      {task && <><label>회의 목표</label><input value={meetingObjective} onChange={event=>setMeetingObjective(event.target.value)} placeholder="예: API 오류 원인과 수정 담당 확정"/><label>안건 — 줄마다 하나</label><textarea className="request-editor compact-editor" value={meetingAgenda} onChange={event=>setMeetingAgenda(event.target.value)} placeholder="범위 확인&#10;위험 확인&#10;담당자 결정"/><button className="solid-button wide" onClick={createMeeting} disabled={Boolean(busy)||!meetingObjective.trim()}>{busy||'회의 시작'}</button></>}
    </Dialog>}

    {modal === 'task' && <Dialog title="CEO 브리핑" onClose={() => setModal(null)}>
      <p className="dialog-copy">{brief || (task ? `${task.title} · ${task.state_label} · 실제 실행 ${completedRunIds.size}건` : 'NAVI가 새 업무를 기다리고 있습니다.')}</p>
      <div className="brief-primary-actions"><button className="solid-button" onClick={()=>{setRequestText('');setDirectLeadId('NAVI');setModal('request')}}>+ 새 업무 / 대화</button><button className="text-button" onClick={()=>task&&setModal('evidence')} disabled={!task}>실행 근거 보기</button></div>
      {task && <section className="brief-live"><div><small>현재 Job</small><b>{task.jobs.find(job=>['running','queued','pause_requested','cancel_requested'].includes(job.state)) ? `${task.jobs.find(job=>['running','queued','pause_requested','cancel_requested'].includes(job.state))?.kind} · ${task.jobs.find(job=>['running','queued','pause_requested','cancel_requested'].includes(job.state))?.state}` : '없음'}</b></div><div><small>다음 행동</small><b>{mainAction.label}</b></div><div><small>최근 실제 이벤트</small><b>{task.job_events[0] ? `${task.job_events[0].type} · ${task.job_events[0].summary}` : '아직 실제 이벤트 없음'}</b></div></section>}
      {task && <><InfoBlock label="현재 업무" value={task.title} /><InfoBlock label="담당 팀" value={task.assigned_employees.map(id => personas[id]?.name ?? id).join(' · ')} /><InfoBlock label="모델 예산" value={`${task.budget_spent.toLocaleString()} / ${(task.contract?.token_limit ?? 0).toLocaleString()} tokens`} /><div className="decision-row">{task.state==='paused'?<button className="solid-button" onClick={()=>controlTask('resume')} disabled={Boolean(busy)}>재개</button>:<button className="text-button" onClick={()=>controlTask('pause')} disabled={Boolean(busy)||['completed','cancelled'].includes(task.state)}>일시 정지</button>}<button className="danger-button" onClick={()=>controlTask('cancel')} disabled={Boolean(busy)||['completed','cancelled'].includes(task.state)}>업무 취소</button></div>{task.state==='planning'&&!workspace&&<button className="solid-button wide" onClick={beginPlannedExecution} disabled={Boolean(busy)}>계획을 실행 단계로 전환</button>}<button className="text-button" onClick={() => setModal('evidence')}>TaskContract와 Evidence 보기 →</button><button className="text-button" onClick={() => setModal('review')}>리뷰 기록 →</button><button className="text-button" onClick={() => setModal('reflection')}>회고와 회사 기억 →</button></>}
    </Dialog>}

    {modal === 'evidence' && <Dialog title="업무 근거와 검증" onClose={() => setModal(null)}>
      {!task ? <p className="dialog-copy">업무가 시작되면 TaskContract와 검증 근거가 표시됩니다.</p> : <><InfoBlock label="TaskContract" value={task.contract?.acceptance_criteria.join(' · ') || '계약 준비 중'} /><InfoBlock label="Evidence" value={task.evidence.length ? task.evidence.map(item => `${item.id} · ${item.status}`).join('\n') : '아직 검증 근거가 없습니다.'} /><InfoBlock label="웹 조사 근거" value={task.research_sources.length ? task.research_sources.slice(0, 8).map(source => `${source.title}\n${source.url}`).join('\n\n') : '아직 웹 조사 근거가 없습니다.'} /><InfoBlock label="작업 항목" value={task.action_items.map(item => `${item.owner}: ${item.description}`).join('\n') || '작업 항목 준비 중'} /><InfoBlock label="리뷰" value={task.reviews.length ? task.reviews.map(item=>`${item.reviewer_id} · ${item.verdict} · ${item.findings||'의견 없음'}`).join('\n') : '아직 리뷰가 없습니다.'} />{workspace && <InfoBlock label="격리 작업공간" value={workspace.path} />}</>}
    </Dialog>}

    {modal === 'approval' && <Dialog title="대표 의사결정" onClose={() => setModal(null)}>
      {approvalCount ? <><p className="dialog-copy">현재 업무가 대표 승인을 기다리고 있습니다.</p><InfoBlock label="대상" value={task?.title ?? ''} /><div className="decision-row"><button className="solid-button" onClick={()=>decideApproval('approve')} disabled={Boolean(busy)}>승인</button><button className="text-button" onClick={()=>decideApproval('rework')} disabled={Boolean(busy)}>재작업</button><button className="danger-button" onClick={()=>decideApproval('reject')} disabled={Boolean(busy)}>반려</button></div></> : <><p className="dialog-copy">현재 대표 승인이 필요한 업무가 없습니다.</p>{task?.approvals.length ? <InfoBlock label="마지막 결정" value={`${task.approvals[0].decision} · ${task.approvals[0].reason || '사유 없음'}`} /> : null}</>}
    </Dialog>}

    {modal === 'review' && <Dialog title="팀 리뷰와 교차 리뷰" onClose={()=>setModal(null)}>
      {!task ? <p className="dialog-copy">업무가 필요합니다.</p> : <><p className="dialog-copy">팀장 또는 REVIEWER가 결과를 판정합니다. 통과하면 대표 승인으로, 수정 요청이면 계획으로 되돌아갑니다.</p><label>리뷰어</label><select value={reviewerId} onChange={event=>setReviewerId(event.target.value)}><option value="">리뷰어 선택</option>{task.assigned_employees.filter(id=>leadIds.has(id)||employees.find(employee=>employee.id===id)?.runtime==='REVIEWER').map(id=><option key={id} value={id}>{personas[id]?.name ?? id}</option>)}</select><label>발견 사항</label><textarea className="request-editor compact-editor" value={reviewFindings} onChange={event=>setReviewFindings(event.target.value)} placeholder="검증 결과, 위험, 수정 요청을 기록합니다."/><div className="decision-row"><button className="solid-button" disabled={!reviewerId||Boolean(busy)} onClick={()=>submitReview('pass')}>통과</button><button className="text-button" disabled={!reviewerId||Boolean(busy)} onClick={()=>submitReview('changes_requested')}>수정 요청</button><button className="danger-button" disabled={!reviewerId||Boolean(busy)} onClick={()=>submitReview('blocked')}>차단</button></div></>}
    </Dialog>}

    {modal === 'reflection' && <Dialog title="회고와 회사 기억" onClose={()=>setModal(null)}>
      {!task ? <p className="dialog-copy">업무가 필요합니다.</p> : <><p className="dialog-copy">회고는 업무 기록에 남고, 레슨은 회사 기억으로 누적됩니다.</p><label>회고 요약</label><textarea className="request-editor compact-editor" value={reflectionSummary} onChange={event=>setReflectionSummary(event.target.value)} placeholder="무엇이 잘 됐고 무엇을 바꿀지 기록합니다."/><label>원인 — 줄마다 하나</label><textarea className="request-editor compact-editor" value={reflectionCause} onChange={event=>setReflectionCause(event.target.value)} /><label>개선 — 줄마다 하나</label><textarea className="request-editor compact-editor" value={reflectionImprovement} onChange={event=>setReflectionImprovement(event.target.value)} /><label>회사 레슨</label><textarea className="request-editor compact-editor" value={lesson} onChange={event=>setLesson(event.target.value)} placeholder="다음 업무에도 재사용할 한 문장 원칙"/><button className="solid-button wide" disabled={!reflectionSummary.trim()||Boolean(busy)} onClick={submitReflection}>{busy||'회고와 레슨 저장'}</button>{task.lessons.length ? <InfoBlock label="기록된 레슨" value={task.lessons.map(item=>item.content).join('\n')} /> : null}</>}
    </Dialog>}

    {modal === 'settings' && <Dialog title="AI 및 연결 설정" onClose={() => setModal(null)}>
      <p className="dialog-copy">OpenRouter의 모델 목록을 그대로 사용합니다. 팀장은 큰 모델, 팀원은 저렴한 모델을 각각 선택할 수 있습니다. 키와 MCP 토큰은 Windows Credential Manager에만 저장됩니다.</p><label>팀장 모델 · OpenRouter</label><ModelSelect listId="lead-models" value={model.lead_model} models={providerModels} onChange={value=>setModel({...model,lead_model:value})}/><label>팀원 모델 · OpenRouter</label><ModelSelect listId="worker-models" value={model.worker_model} models={providerModels} onChange={value=>setModel({...model,worker_model:value})}/><label>OpenRouter API 키</label><input type="password" value={apiKey} onChange={event => setApiKey(event.target.value)} placeholder={model.configured ? '새 키 입력 시 교체' : 'sk-or-…'} /><button className="solid-button wide" onClick={saveModel} disabled={Boolean(busy)}>{busy || 'OpenRouter 연결 저장'}</button><div className="settings-divider"/><h3>MCP 연결</h3><p className="dialog-copy">GitHub, Google Drive, Notion의 MCP 서버 URL과 토큰을 등록합니다. 연결 서버가 제공하는 범위만 에이전트에 노출됩니다.</p><select value={mcpProvider} onChange={event=>{const provider=event.target.value as McpConnection['provider'];setMcpProvider(provider);setMcpName(provider==='github'?'GitHub MCP':provider==='google-drive'?'Google Drive MCP':provider==='notion'?'Notion MCP':'Custom MCP')}}><option value="github">GitHub</option><option value="google-drive">Google Drive</option><option value="notion">Notion</option><option value="custom">Custom</option></select><label>연결 이름</label><input value={mcpName} onChange={event=>setMcpName(event.target.value)}/><label>MCP 서버 URL</label><input value={mcpUrl} onChange={event=>setMcpUrl(event.target.value)} placeholder="https://…/mcp"/><label>토큰</label><input type="password" value={mcpToken} onChange={event=>setMcpToken(event.target.value)} placeholder="등록 시 보안 저장"/><button className="solid-button wide" onClick={saveMcp} disabled={Boolean(busy)}>{busy || 'MCP 연결 저장'}</button>{mcpConnections.length ? <InfoBlock label="등록된 MCP" value={mcpConnections.map(item=>`${item.name} · ${item.status}`).join('\n')} /> : null}
    </Dialog>}
  </main>;
}

function FloorAgent({employee, active, activity, position, action, walkFrame, selected, bubble, onFocus}:{employee:Employee;active:boolean;activity:string;position:[number,number];action:AgentAction;walkFrame:boolean;selected:boolean;bubble?:JobEvent;onFocus:(id:string)=>void}) {
  const lead=leadIds.has(employee.id);
  const behavior=actionLabel(action);
  const icon=stateIcon(behavior);
  const team=teamForAgent(employee.id);
  const pose=action==='walk' ? (walkFrame?'walk-b':'walk-a') : action==='idle'?'sit':action;
  const genericBubble=!bubble || ['모델 작업 시작','작업 중 · 실제 Job 처리 중'].includes(bubble.summary);
  const bubbleText=(genericBubble ? activity : bubble?.summary)?.slice(0, 140) ?? (active ? `${behavior} · 실제 Job 처리 중` : '');
  return <button aria-label={`${personas[employee.id]?.name ?? employee.id}, ${behavior}`} className={`floor-agent ${active ? 'working' : ''} ${lead ? 'team-lead' : 'sub-agent'} team-${team} ${selected ? 'selected' : ''} action-${action}`} style={{'--x':`${position[0]}%`,'--y':`${position[1]}%`,'--agent-tone':personas[employee.id]?.palette ?? '#7d9271'} as CSSProperties} onClick={() => onFocus(employee.id)}><span className="agent-shadow"/>{bubbleText && <span className="agent-bubble">{bubbleText}</span>}<Avatar id={employee.id} pose={pose}/>{lead&&<b className="lead-mark" aria-label="팀장">◆</b>}{icon&&<span className="agent-state-icon" aria-hidden="true">{icon}</span>}<span className="agent-name"><i/>{personas[employee.id]?.name ?? employee.id}<em>{behavior}</em></span></button>;
}

const cameraButton:CSSProperties={border:'1px solid #d5efaf',borderRadius:5,background:'#182319dd',color:'#efffe7',padding:'4px 6px',fontSize:8};
function agentBehavior(state:string, active:boolean){if(!active)return '자리 대기';if(['contracting','planning'].includes(state))return '계획 중';if(state==='meeting')return '회의 중';if(['verifying','failed','team_review','cross_review'].includes(state))return 'QA 검토';if(['awaiting_approval','blocked','escalated'].includes(state))return state==='blocked'?'차단':'CEO 보고';if(state==='completed')return '업무 완료';return '팀 작업 중';}
function actionLabel(action:AgentAction){return action==='idle'?'대기':action==='walk'?'이동 중':action==='work'?'작업 중':action==='review'?'리뷰 중':'회의 중';}
function agentStateKey(behavior:string){return behavior==='계획 중'?'planning':behavior==='회의 중'?'meeting':behavior==='QA 검토'?'reviewing':behavior==='차단'?'blocked':behavior==='CEO 보고'?'approval':behavior==='팀 작업 중'?'running':behavior==='업무 완료'?'done':'idle';}
function stateIcon(behavior:string){return behavior==='계획 중'?'▤':behavior==='회의 중'?'◌':behavior==='QA 검토'?'⌕':behavior==='차단'?'!':behavior==='CEO 보고'?'✓':behavior==='팀 작업 중'?'◔':behavior==='업무 완료'?'✓':'';}
function agentRole(id:string,lead:boolean){const roles:Record<string,string>={NAVI:'CEO',FRAME:'PM',BUILD:'TECH LEAD',LINK:'AI LEAD',SHIP:'OPS LEAD',GUARD:'QA LEAD',GROW:'GROWTH LEAD',LENS:'REVIEW LEAD',MOSS:'DESIGNER',FRONT:'FRONTEND',BACK:'BACKEND',SIGNAL:'DATA',EVAL:'AI EVAL',SRE:'SRE',TRACE:'QA',SHIELD:'SECURITY',VOICE:'BRAND',PULSE:'ANALYST',DOCS:'DOCS',JOURNEY:'RESEARCH',ROUTE:'PLANNER',CLOCK:'OPS',FLOW:'UX',COST:'FINOPS'};return roles[id] ?? (lead?'TEAM LEAD':'SPECIALIST');}
function teamStatus(id:string, task:Task|null){const count=task?.assigned_employees.filter(agentId=>teamForAgent(agentId)===id).length??0;if(!count)return '대기';if(task?.state==='meeting')return '회의 중';if(['contracting','planning'].includes(task?.state??''))return `실행 대기 ${count}`;if(['verifying','failed','team_review','cross_review'].includes(task?.state??''))return '검토 중';if(task?.state==='awaiting_approval')return '승인 대기';if(task?.state==='blocked')return '차단';if(task?.state==='running')return `작업 중 ${count}`;return `배정 ${count}`;}

function teamForAgent(id:string) {
  if (['NAVI','ROUTE','CLOCK','FRAME','FLOW'].includes(id)) return 'product';
  if (['MOSS','BUILD','FRONT'].includes(id)) return 'design';
  if (['BACK','LINK','SIGNAL','EVAL'].includes(id)) return 'backend';
  if (['GROW','VOICE','PULSE'].includes(id)) return 'growth';
  if (['LENS','JOURNEY','DOCS'].includes(id)) return 'lounge';
  return 'ops';
}

function teamSignStyle(id:string):CSSProperties {
  const coordinates:Record<string,[string,string]>={product:['8%','29%'],design:['42%','31%'],backend:['72%','31%'],growth:['8%','61%'],lounge:['42%','66%'],ops:['72%','61%']};
  const [left,top]=coordinates[id];
  return {position:'absolute',zIndex:8,left,top,minWidth:112,padding:'6px 8px',border:'1px solid #ffffffaa',borderRadius:7,background:'#101811e8',color:'#f7fff3',textAlign:'left',boxShadow:'0 5px 12px #0008'};
}

function Avatar({id,compact=false,pose='stand'}:{id:string;compact?:boolean;pose?:string}) {
  const persona=personas[id] ?? personas.NAVI;
  const index=avatarIndexes[id] ?? Math.max(0,spriteIds.indexOf(id));
  return <div data-avatar={id} className={`avatar-art sprite-avatar pose-${pose} ${compact?'compact':''}`} style={{'--sprite-x':`${(index%8)*100/7}%`,'--sprite-y':`${Math.floor(index/8)*50}%`,'--halo':persona.palette} as CSSProperties}/>;
}

function ProfilePanel({employee,active,activity,result,evidenceCount,busy,onSubmitCommand,onClose}:{employee:Employee;active:boolean;activity:string;result:string;evidenceCount:number;busy:boolean;onSubmitCommand:(leadId:string,title:string,prompt:string)=>Promise<void>;onClose:()=>void}) {
  const persona:Persona=personas[employee.id] ?? personas.NAVI;
  const lead=leadIds.has(employee.id);
  const [title,setTitle]=useState('');
  const [prompt,setPrompt]=useState('');
  useEffect(()=>{setTitle('');setPrompt('');},[employee.id]);
  return <aside className="profile-panel"><button onClick={onClose}>×</button><Avatar id={employee.id}/><div><span>{teamNames[employee.team] ?? employee.team}</span><h2>{persona.name}</h2><p>{persona.bio}</p>{lead && employee.id !== 'NAVI' && <section className="lead-command"><b>팀장에게 직접 지시</b><input value={title} onChange={event=>setTitle(event.target.value)} placeholder="업무 제목"/><textarea value={prompt} onChange={event=>setPrompt(event.target.value)} placeholder="프롬프트: 목표, 범위, 산출물, 확인 기준"/><button className="solid-button" disabled={!title.trim()||!prompt.trim()||busy} onClick={()=>void onSubmitCommand(employee.id,title,prompt)}>판단 Job 시작</button></section>}</div><dl><div><dt>직책</dt><dd>{agentRole(employee.id,lead)}</dd></div><div><dt>역할</dt><dd>{lead?'업무 분담 · 리뷰 · 디버깅':'실제 구현 · 문서 · 테스트 수행'}</dd></div><div><dt>전문 분야</dt><dd>{persona.specialty}</dd></div><div><dt>현재 업무</dt><dd className={active?'active':''}>{active ? (activity || '실제 Job 처리 중') : '배정 대기'}</dd></div><div><dt>최근 결과</dt><dd>{result ? result.slice(0,600) : '아직 결과물 없음'}</dd></div><div><dt>검증 근거</dt><dd>{evidenceCount}건</dd></div></dl></aside>;
}

const featuredModels: ProviderModel[] = [
  {id:'openai/gpt-5.6-sol',name:'OpenAI GPT-5.6 Sol',context_length:1050000},
  {id:'deepseek/deepseek-v4-pro',name:'DeepSeek V4 Pro',context_length:1048576},
  {id:'z-ai/glm-5.2',name:'Z.ai GLM 5.2',context_length:1048576},
];
function ModelSelect({listId,value,models,onChange}:{listId:string;value:string;models:ProviderModel[];onChange:(value:string)=>void}) {
  const options=[...featuredModels,...models.filter(model=>!featuredModels.some(featured=>featured.id===model.id)&&(!model.id.startsWith('openai/')||model.id.startsWith('openai/gpt-5.6')))];
  const featuredIds=new Set(featuredModels.map(model=>model.id));
  return <div className="model-picker"><select aria-label={`${listId} 모델 선택`} value={value} onChange={event=>onChange(event.target.value)}><option value={value}>{options.find(model=>model.id===value)?.name ?? value}</option><optgroup label="추천 · GPT-5.6 / DeepSeek 최신 / GLM 최신">{options.filter(model=>featuredIds.has(model.id)&&model.id!==value).map(model=><option key={model.id} value={model.id}>{model.name}</option>)}</optgroup><optgroup label="OpenRouter 전체 모델">{options.filter(model=>!featuredIds.has(model.id)&&model.id!==value).map(model=><option key={model.id} value={model.id}>{model.name}</option>)}</optgroup></select><input value={value} onChange={event=>onChange(event.target.value)} placeholder="직접 모델 ID 입력"/><small>목록 선택 또는 OpenRouter 모델 ID 직접 입력</small></div>;
}

function TeamPanel({teamId,members,lead,task,onClose,onFocus}:{teamId:string;members:Employee[];lead:Employee|undefined;task:Task|null;onClose:()=>void;onFocus:()=>void}) {
  const title=teamSigns.find(item=>item[0]===teamId)?.[1] ?? teamId;
  const active=task?.assigned_employees.filter(id=>teamForAgent(id)===teamId) ?? [];
  const recent=task?.events.find(event=>event.employee_ids.some(id=>teamForAgent(id)===teamId));
  const meeting=task?.meetings.find(item=>item.participants.some(id=>teamForAgent(id)===teamId));
  const skills=members.flatMap(member=>member.required_skills??[]).filter((value,index,array)=>array.indexOf(value)===index).slice(0,8);
  return <aside className="team-panel"><button className="panel-close" onClick={onClose}>×</button><span>DEPARTMENT</span><h2>{title}</h2><p className="team-panel-state">{teamStatus(teamId,task)}</p><InfoBlock label="팀장" value={lead ? personas[lead.id]?.name ?? lead.id : '배정 없음'} /><InfoBlock label="구성원" value={members.map(member=>personas[member.id]?.name ?? member.id).join(' · ')} /><InfoBlock label="현재 업무" value={active.length ? task?.title ?? '업무 진행 중' : '대기 중'} /><InfoBlock label="최근 활동" value={recent?.note ?? '최근 활동 없음'} /><InfoBlock label="활성 스킬" value={skills.join(' · ') || '준비 중'} /><InfoBlock label="관련 회의" value={meeting?.objective ?? '관련 회의 없음'} /><button className="solid-button wide" onClick={onFocus}>팀 포커스</button></aside>;
}

function Dialog({title,onClose,children}:{title:string;onClose:()=>void;children:ReactNode}) { return <div className="modal-backdrop" onMouseDown={onClose}><section className="detail-dialog" onMouseDown={event=>event.stopPropagation()}><button className="modal-close" onClick={onClose}>×</button><span>AI OFFICE</span><h2>{title}</h2>{children}</section></div>; }
function InfoBlock({label,value}:{label:string;value:string}) { return <div className="info-block"><b>{label}</b><p>{value}</p></div>; }
