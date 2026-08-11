import { Dialog } from '../shared';
import { personas } from '../personas';
import type { Employee, Task } from '../api';

export function WorkerSelectionModal({ task, employees, workerProposalIds, selectedWorkerIds, setSelectedWorkerIds, busy, selectWorkers, onClose }: {
  task: Task | null; employees: Employee[]; workerProposalIds: Set<string>; selectedWorkerIds: string[];
  setSelectedWorkerIds: (updater: (current: string[]) => string[]) => void; busy: string; selectWorkers: () => void; onClose: () => void;
}) {
  return <Dialog title="팀장 회의 완료 · 실행자 선택" onClose={onClose}>
    <p className="dialog-copy">대표가 실제 실행자를 지정합니다. 선택된 실행자만 하위 모델로 호출됩니다.</p>
    <div className="project-list">{employees.filter(employee => workerProposalIds.has(employee.id)).map(employee => <label key={employee.id}><input type="checkbox" checked={selectedWorkerIds.includes(employee.id)} onChange={() => setSelectedWorkerIds(current => current.includes(employee.id) ? current.filter(value => value !== employee.id) : [...current, employee.id])} /><b>{personas[employee.id]?.name ?? employee.id}</b><small>{task?.action_items.find(item => item.owner === employee.id)?.description ?? employee.title}</small></label>)}</div>
    <button className="solid-button wide" disabled={!selectedWorkerIds.length || Boolean(busy)} onClick={selectWorkers}>{busy || '선택 실행자 배정·실행'}</button>
  </Dialog>;
}
