export const employees = [
  ['NAVI','Planning'],['ROUTE','Planning'],['CLOCK','Planning'],['FRAME','Product'],['FLOW','Product'],['MOSS','Product'],
  ['BUILD','Engineering'],['FRONT','Engineering'],['BACK','Engineering'],['LINK','AI Data'],['SIGNAL','AI Data'],['EVAL','AI Data'],
  ['SHIP','Platform'],['SRE','Platform'],['COST','Platform'],['GUARD','Quality'],['TRACE','Quality'],['SHIELD','Quality'],
  ['GROW','Growth'],['VOICE','Growth'],['PULSE','Growth'],['LENS','Service'],['JOURNEY','Service'],['DOCS','Service']
].map(([id, team]) => ({ id, team, status: 'idle', taskId: null }));

export const locations = { idle: 'desk', meeting: 'meeting', working: 'desk', verifying: 'qa', approval: 'ceo', blocked: 'ceo', done: 'desk' };
export const labels = { idle: '대기', meeting: '회의', working: '작업', verifying: '검증', approval: '승인 대기', blocked: '차단', done: '완료' };
export const taskStatus = { draft: '초안', idle: '초안', meeting: '회의 중', working: '진행 중', verifying: 'QA 검증', approval: '승인 대기', done: '완료', blocked: '차단' };

export function makeOfficeState() {
  return { employees: structuredClone(employees), task: { id: 'TASK-028', title: '온보딩 이탈 분석 및 개선안', state: 'draft', assignees: [] }, events: [] };
}

export function transition(office, action, selected = ['NAVI','FRAME','FRONT','BACK','TRACE']) {
  const map = { meeting: 'meeting', assign: 'working', verify: 'verifying', approval: 'approval', complete: 'done', block: 'blocked', reset: 'idle' };
  const state = map[action];
  if (!state) throw new Error(`Unknown action: ${action}`);
  office.task.state = action === 'assign' ? 'working' : state;
  office.task.assignees = action === 'reset' ? [] : selected;
  for (const employee of office.employees) {
    employee.status = selected.includes(employee.id) ? state : 'idle';
    employee.taskId = selected.includes(employee.id) && state !== 'idle' ? office.task.id : null;
  }
  office.events.unshift({ action, state: office.task.state, selected, at: new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }) });
  return office;
}
