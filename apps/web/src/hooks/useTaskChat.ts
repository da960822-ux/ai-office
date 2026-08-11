import { useState } from 'react';
import { api, type Project, type Task } from '../api';
import { personas } from '../personas';

type ModalId = 'project' | 'request' | 'settings' | 'meeting' | 'task' | 'approval' | 'evidence' | 'reflection' | 'leadSelection' | 'workerSelection' | 'leadCommand' | 'chat' | null;

/**
 * Chat-intake state (chatDraft/chatBusy/chatNeedsInfo). The handlers still
 * need task/project/request-editor state that App.tsx owns, so those are
 * passed in per call instead of duplicated here — this hook is the seam for
 * the chat draft only, not a second source of truth for the task.
 */
export function useTaskChat(setError: (message: string) => void, friendlyError: (cause: unknown) => string, setBusy: (message: string) => void) {
  const [chatDraft, setChatDraft] = useState('');
  const [chatBusy, setChatBusy] = useState(false);
  const [chatNeedsInfo, setChatNeedsInfo] = useState(false);

  const startChat = async (opts: { requestText: string; directLeadId: string; intakeMode: 'blank' | 'has_items' | ''; initialAgents: string[]; setTasks: (updater: (current: Task[]) => Task[]) => void; setTask: (task: Task) => void; setModal: (modal: ModalId) => void; setRequestText: (value: string) => void }) => {
    const { requestText, directLeadId, intakeMode, initialAgents, setTasks, setTask, setModal, setRequestText } = opts;
    if (!requestText.trim()) { setError('메시지를 입력해 주세요.'); return; }
    setBusy('대화를 여는 중');
    try {
      const title = requestText.trim().split(/\r?\n/)[0].slice(0, 80);
      const created = await api.create(title, requestText.trim(), initialAgents, directLeadId === 'NAVI' ? 'navi' : 'direct_lead', directLeadId === 'NAVI' ? undefined : directLeadId);
      setTasks(current => [created, ...current]); setTask(created); setModal('chat'); setError('');
      const firstMessage = requestText.trim(); setRequestText('');
      setChatBusy(true);
      const reply = await api.chat(created.id, firstMessage, intakeMode || undefined);
      setChatNeedsInfo(reply.needs_info); setTask(await api.task(created.id));
    } catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(''); setChatBusy(false); }
  };

  const sendChat = async (task: Task | null, intakeMode: 'blank' | 'has_items' | '', setTask: (task: Task) => void) => {
    if (!task || !chatDraft.trim()) return;
    setChatBusy(true);
    try {
      const message = chatDraft.trim(); setChatDraft('');
      const reply = await api.chat(task.id, message, intakeMode || undefined);
      setChatNeedsInfo(reply.needs_info); setTask(await api.task(task.id)); setError('');
    } catch (cause) { setError(friendlyError(cause)); }
    finally { setChatBusy(false); }
  };

  const beginExecutionFromChat = async (opts: { task: Task | null; selectedProject: Project | undefined; directLeadId: string; setModal: (modal: ModalId) => void; setWorkspace: (workspace: Awaited<ReturnType<typeof api.createWorkspace>>) => void; setTask: (task: Task) => void; setBrief: (brief: string) => void }) => {
    const { task, selectedProject, directLeadId, setModal, setWorkspace, setTask, setBrief } = opts;
    if (!task) return;
    if (!selectedProject) { setError('먼저 헤더에서 작업 프로젝트를 연결해 주세요.'); setModal('project'); return; }
    setBusy('실행 계획을 시작하는 중');
    try {
      await api.contract(task.id); await api.queuePlan(task.id);
      const prepared = await api.createWorkspace(task.id, selectedProject.id, 'in_place'); setWorkspace(prepared);
      setBrief(directLeadId === 'NAVI' ? 'NAVI가 필요한 부서 팀장을 판단 중입니다. 완료되면 팀장 선택이 열립니다.' : `${personas[directLeadId]?.name ?? directLeadId} 팀장 판단 Job을 대기열에 넣었습니다.`);
      setTask(await api.task(task.id)); setModal('task'); setError('');
    } catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(''); }
  };

  return { chatDraft, setChatDraft, chatBusy, chatNeedsInfo, setChatNeedsInfo, startChat, sendChat, beginExecutionFromChat };
}
