import { Dialog, InfoBlock } from '../shared';
import { personas } from '../personas';

export function LeadCommandModal({ directCommandLeadId, directCommandTitle, setDirectCommandTitle, directCommandText, setDirectCommandText, busy, submitLeadCommand, onClose }: {
  directCommandLeadId: string; directCommandTitle: string; setDirectCommandTitle: (value: string) => void;
  directCommandText: string; setDirectCommandText: (value: string) => void; busy: string; submitLeadCommand: () => void; onClose: () => void;
}) {
  return <Dialog title="팀장에게 직접 지시" onClose={onClose}>
    <p className="dialog-copy">독립 소규모 업무입니다. NAVI 판단·팀장 회의는 생략하지만, worker 선택과 해당 팀장 실제 리뷰는 반드시 거칩니다.</p>
    <InfoBlock label="수신 팀장" value={personas[directCommandLeadId]?.name ?? directCommandLeadId} />
    <label>업무 제목</label><input value={directCommandTitle} onChange={event => setDirectCommandTitle(event.target.value)} placeholder="짧고 검증 가능한 제목" />
    <label>명령</label><textarea className="request-editor compact-editor" value={directCommandText} onChange={event => setDirectCommandText(event.target.value)} placeholder="목표, 범위, 산출물, 확인 기준" />
    <button className="solid-button wide" disabled={!directCommandTitle.trim() || !directCommandText.trim() || Boolean(busy)} onClick={submitLeadCommand}>{busy || '팀장 판단 시작'}</button>
  </Dialog>;
}
