import { Dialog } from '../shared';
import { personas } from '../personas';
import type { Task } from '../api';

export function ChatModal({ task, chatDraft, setChatDraft, chatBusy, chatNeedsInfo, busy, sendChat, beginExecutionFromChat, onClose }: {
  task: Task | null; chatDraft: string; setChatDraft: (value: string) => void; chatBusy: boolean; chatNeedsInfo: boolean;
  busy: string; sendChat: () => void; beginExecutionFromChat: () => void; onClose: () => void;
}) {
  return <Dialog title={`${personas[task?.route === 'direct_lead' && task?.lead_id ? task.lead_id : 'NAVI']?.name ?? 'NAVI'}와 대화`} onClose={onClose}>
    <p className="dialog-copy">{task?.title ?? '대화가 아직 시작되지 않았습니다.'}</p>
    <div className="chat-thread">{(task?.agent_messages ?? []).filter(message => ['user', 'chat'].includes(message.kind)).slice().sort((a, b) => a.created_at.localeCompare(b.created_at)).map(message => <article key={message.id} className={`chat-bubble ${message.kind === 'user' ? 'from-ceo' : 'from-agent'}`}><b>{message.kind === 'user' ? '대표' : (personas[message.employee_id]?.name ?? message.employee_id)}</b><p>{message.content}</p></article>)}{!task?.agent_messages.some(message => ['user', 'chat'].includes(message.kind)) && <p className="dialog-copy">아직 대화가 없습니다.</p>}{chatBusy && <p className="chat-typing">응답 작성 중…</p>}</div>
    {chatNeedsInfo && <div className="chat-needs-info"><b>답변이 필요합니다</b><span>정보가 부족해 아직 실행 계획을 시작할 수 없습니다. 위 질문에 답해 주세요.</span></div>}
    <div className="dialog-input-row"><input value={chatDraft} onChange={event => setChatDraft(event.target.value)} placeholder="답하거나 더 물어보세요" onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendChat(); } }} disabled={chatBusy} /><button className="solid-button" onClick={sendChat} disabled={chatBusy || !chatDraft.trim()}>전송</button></div>
    <button className="solid-button wide" onClick={beginExecutionFromChat} disabled={Boolean(busy) || chatBusy}>{busy || (chatNeedsInfo ? '그래도 지금 실행 계획 시작' : '이 내용으로 실행 계획 시작')}</button>
  </Dialog>;
}
