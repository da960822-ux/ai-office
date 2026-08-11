import { Dialog } from '../shared';
import { agentRole } from '../OfficeFloor';
import { personas } from '../personas';
import type { Task } from '../api';

export function LeadSelectionModal({ task, leadIds, selectedLeadIds, setSelectedLeadIds, busy, selectLeads, onClose }: {
  task: Task | null; leadIds: Set<string>; selectedLeadIds: string[]; setSelectedLeadIds: (updater: (current: string[]) => string[]) => void;
  busy: string; selectLeads: () => void; onClose: () => void;
}) {
  return <Dialog title="NAVI 판단 · 팀장 선택" onClose={onClose}>
    <p className="dialog-copy">NAVI가 필요한 부서 팀장 후보만 제시했습니다. 대표가 실제 회의 참석자를 확정합니다.</p>
    <div className="project-list">{task?.assigned_employees.map(id => <label key={id}><input type="checkbox" checked={selectedLeadIds.includes(id)} onChange={() => setSelectedLeadIds(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id])} /><b>{personas[id]?.name ?? id}</b><small>{agentRole(id, leadIds.has(id))}</small></label>)}</div>
    <button className="solid-button wide" disabled={!selectedLeadIds.length || Boolean(busy)} onClick={selectLeads}>{busy || '선택 팀장 회의 시작'}</button>
  </Dialog>;
}
