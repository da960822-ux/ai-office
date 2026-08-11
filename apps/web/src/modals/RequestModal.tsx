import { Dialog } from '../shared';
import { personas } from '../personas';
import type { Employee } from '../api';

export function RequestModal({ intakeMode, setIntakeMode, directLeadId, setDirectLeadId, employees, leadIds, requestText, setRequestText, busy, startChat, startTask, onClose }: {
  intakeMode: 'blank' | 'has_items' | ''; setIntakeMode: (mode: 'blank' | 'has_items' | '') => void;
  directLeadId: string; setDirectLeadId: (id: string) => void; employees: Employee[]; leadIds: Set<string>;
  requestText: string; setRequestText: (value: string) => void; busy: string;
  startChat: () => void; startTask: (mode: 'plan' | 'execute') => void; onClose: () => void;
}) {
  return <Dialog title="새 업무 요청" onClose={onClose}>
    <p className="dialog-copy">NAVI는 여러 부서가 필요한 업무용입니다. 작은 범위는 팀장을 직접 지정하면 NAVI 계획과 팀장 회의를 건너뜁니다.</p>
    <label>지금 얼마나 정해졌나요?</label>
    <div className="intake-mode-row">
      <button className={`intake-mode-button ${intakeMode === 'blank' ? 'selected' : ''}`} onClick={() => setIntakeMode('blank')}>아직 아이디어 없음<small>NAVI가 질문으로 방향을 좁혀 줍니다</small></button>
      <button className={`intake-mode-button ${intakeMode === 'has_items' ? 'selected' : ''}`} onClick={() => setIntakeMode('has_items')}>어느 정도 정해짐<small>빠진 부분만 빠르게 확인합니다</small></button>
    </div>
    <label>지시 대상</label><select value={directLeadId} onChange={event => setDirectLeadId(event.target.value)}><option value="NAVI">NAVI · 부서 판단 후 팀장 후보 제시</option>{employees.filter(employee => leadIds.has(employee.id) && employee.id !== 'NAVI').map(employee => <option key={employee.id} value={employee.id}>{personas[employee.id]?.name ?? employee.id} · {employee.title} 팀장에게 직접 지시</option>)}</select>
    <textarea className="request-editor" value={requestText} onChange={event => setRequestText(event.target.value)} placeholder="예: 로그인 오류를 찾아 수정하고 테스트까지 실행해." autoFocus />
    <div className="decision-row"><button className="solid-button" onClick={startChat} disabled={Boolean(busy) || !requestText.trim()}>{busy || '대화로 시작'}</button>{directLeadId === 'NAVI' && <button className="text-button" onClick={() => startTask('plan')} disabled={Boolean(busy)}>계획만 생성</button>}<button className="text-button" onClick={() => startTask('execute')} disabled={Boolean(busy)}>{directLeadId === 'NAVI' ? '대화 없이 바로 시작' : '팀장에게 직접 지시'}</button></div>
  </Dialog>;
}
