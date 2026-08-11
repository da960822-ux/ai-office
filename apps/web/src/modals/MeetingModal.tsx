import { Dialog, PersonChips } from '../shared';
import { personas } from '../personas';
import type { Meeting, Task } from '../api';

export function MeetingModal({ task, currentMeeting, latestMeeting, meetingObjective, setMeetingObjective, meetingAgenda, setMeetingAgenda, busy, createMeeting, onClose }: {
  task: Task | null; currentMeeting: Meeting | undefined; latestMeeting: Meeting | undefined;
  meetingObjective: string; setMeetingObjective: (value: string) => void; meetingAgenda: string; setMeetingAgenda: (value: string) => void;
  busy: string; createMeeting: () => void; onClose: () => void;
}) {
  const transcript = task?.agent_messages.filter(message => message.kind === 'meeting') ?? [];
  return <Dialog title="구조화된 회의" onClose={onClose}>
    <p className="dialog-copy">{currentMeeting?.objective ?? '현재 진행 중인 회의가 없습니다. 회의는 여러 담당자의 판단을 한 자리에서 맞춰 다음 결정을 확정하는 절차입니다.'}</p>

    {currentMeeting && <>
      <div className="meeting-summary">
        <div className="meeting-summary-row"><b>참석</b><PersonChips ids={currentMeeting.participants} /></div>
        <div className="meeting-summary-row"><b>안건 · {currentMeeting.agenda.length}건</b>
          {currentMeeting.agenda.length ? <ol className="scope-list">{currentMeeting.agenda.map((item, index) => <li key={index} className="scope-item"><p>{item}</p></li>)}</ol> : <p className="prose-empty">등록된 안건이 없습니다.</p>}
        </div>
        <div className="meeting-summary-row"><b>결정</b>
          {currentMeeting.decisions.length ? <ol className="scope-list">{currentMeeting.decisions.map((item, index) => <li key={index} className="scope-item"><p>{item}</p></li>)}</ol> : <p className="prose-empty">아직 결정된 사항이 없습니다 — 회의가 자동으로 진행 중입니다.</p>}
        </div>
      </div>

      <div className="chat-thread">
        {transcript.map(message => <article key={message.id} className="chat-bubble from-agent">
          <b>{personas[message.employee_id]?.name ?? message.employee_id}</b>
          <p>{message.content}</p>
        </article>)}
        {!transcript.length && <p className="dialog-copy">아직 발언 기록이 없습니다. 회의가 진행되면 여기에 표시됩니다.</p>}
      </div>
    </>}

    {latestMeeting && !currentMeeting && <p className="dialog-copy">가장 최근 회의는 실제 발언 기록이 남아 있습니다. 새 회의를 시작하면 그 위에 이어집니다.</p>}

    {task && <>
      <p className="meeting-form-hint">회의를 시작하면 관련 담당자들이 목표와 안건을 두고 판단을 맞추고, 그 결과가 다음 작업 방향을 결정합니다.</p>
      <label>회의 목표</label>
      <input value={meetingObjective} onChange={event => setMeetingObjective(event.target.value)} placeholder="예: API 오류 원인과 수정 담당 확정" />
      <label>안건 — 줄마다 하나</label>
      <textarea className="request-editor compact-editor" value={meetingAgenda} onChange={event => setMeetingAgenda(event.target.value)} placeholder="범위 확인&#10;위험 확인&#10;담당자 결정" />
      <button className="solid-button wide" onClick={createMeeting} disabled={Boolean(busy) || !meetingObjective.trim()}>{busy || '회의 시작'}</button>
    </>}
  </Dialog>;
}
