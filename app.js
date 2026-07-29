import { makeOfficeState, transition, locations, labels, taskStatus } from './office-state.js';

let office = makeOfficeState();
const rooms = [
  ['meeting','MEETING ROOM','협업 및 계획'], ['qa','QA ZONE','검증 중'], ['ceo','CEO OFFICE','승인·차단'],
  ['desk planning','PLANNING','NAVI · ROUTE · CLOCK'], ['desk product','PRODUCT','FRAME · FLOW · MOSS'], ['desk engineering','ENGINEERING','BUILD · FRONT · BACK'],
  ['desk ai-data','AI DATA','LINK · SIGNAL · EVAL'], ['desk platform','PLATFORM','SHIP · SRE · COST'], ['desk quality','QUALITY','GUARD · TRACE · SHIELD'], ['desk growth','GROWTH','GROW · VOICE · PULSE'], ['desk service','SERVICE','LENS · JOURNEY · DOCS']
];
let selected = ['NAVI','FRAME','FRONT','BACK','TRACE'];
const slug = (value) => value.toLowerCase().replaceAll(' ', '-');
function setupOffice() {
  const officeEl = document.querySelector('#office');
  officeEl.innerHTML = rooms.map(([id, name, note]) => `<div class="room ${id}" data-room="${id.split(' ')[0]}"><div class="room-title">${name}<small>${note}</small></div><div class="agents"></div></div>`).join('');
  office.employees.forEach(employee => {
    const node = document.createElement('button');
    node.dataset.employee = employee.id;
    node.className = 'agent idle'; node.title = `${employee.id}: ${labels.idle}`;
    node.innerHTML = `<span class="avatar">${employee.id.slice(0, 1)}</span><span>${employee.id}</span><i></i>`;
    document.querySelector(`.room.${slug(employee.team)} .agents`).append(node);
  });
}
function updateOffice(animate = true) {
  office.employees.forEach(employee => {
    const room = employee.status === 'idle' || employee.status === 'working' || employee.status === 'done' ? `.room.${slug(employee.team)}` : `.room.${locations[employee.status]}`;
    const node = document.querySelector(`[data-employee="${employee.id}"]`);
    const before = node.getBoundingClientRect();
    document.querySelector(room + ' .agents').append(node);
    node.className = `agent ${employee.status}`; node.title = `${employee.id}: ${labels[employee.status]}`;
    const after = node.getBoundingClientRect();
    if (animate && (before.x !== after.x || before.y !== after.y)) {
      node.style.transition = 'none'; node.style.transform = `translate(${before.x - after.x}px, ${before.y - after.y}px)`;
      requestAnimationFrame(() => { node.style.transition = 'transform .65s cubic-bezier(.2,.9,.2,1)'; node.style.transform = ''; });
    }
  });
  document.querySelector('#task-state').textContent = taskStatus[office.task.state];
  document.querySelector('#task-title').textContent = office.task.title;
  document.querySelector('#active-count').textContent = office.employees.filter(x => x.status !== 'idle').length;
  document.querySelector('#events').innerHTML = office.events.length ? office.events.map(event => `<li><time>${event.at}</time><b>${taskStatus[event.state]}</b><span>${event.action === 'assign' ? '직원 배정 및 작업 시작' : '상태 이벤트 처리'}</span></li>`).join('') : '<li class="empty">이벤트를 실행하면 기록됩니다.</li>';
  document.querySelector('#staff-list').innerHTML = office.employees.map(x => `<div class="staff"><span class="avatar">${x.id[0]}</span><b>${x.id}</b><small>${x.team}</small><em class="${x.status}">${labels[x.status]}</em></div>`).join('');
}
document.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', () => { office = transition(office, button.dataset.action, selected); updateOffice(); }));
document.querySelector('#run-command').addEventListener('click', () => {
  const words = document.querySelector('#command-input').value.trim().toUpperCase().split(/\s+/);
  const actions = { '회의':'meeting', 'MEETING':'meeting', '업무':'assign', '배정':'assign', '작업':'assign', 'WORK':'assign', '검증':'verify', 'QA':'verify', '승인':'approval', 'APPROVAL':'approval', '완료':'complete', 'DONE':'complete', '차단':'block', 'BLOCK':'block', '초기화':'reset', 'RESET':'reset' };
  const action = actions[words[0]];
  const input = document.querySelector('#command-input');
  if (!action) { input.setCustomValidity('명령은 회의, 업무, 검증, 승인, 완료, 차단, 초기화 중 하나로 시작해야 합니다.'); input.reportValidity(); return; }
  input.setCustomValidity('');
  const ids = words.filter(word => office.employees.some(employee => employee.id === word));
  if (ids.length) selected = ids;
  const title = document.querySelector('#task-input').value.trim();
  if (title) office.task.title = title;
  office = transition(office, action, selected); updateOffice();
});
setInterval(() => document.querySelector('#clock').textContent = new Date().toLocaleTimeString('ko-KR'), 1000);
setupOffice(); updateOffice(false);
