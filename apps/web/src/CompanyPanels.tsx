import { Task } from './api';
import { personas } from './personas';

export function CompanyPanels({task,onAction}:{task:Task|null;onAction:(action:string)=>void}) {
  const latest=task?.events[0]; const meeting=task?.meetings[0]; const completed=task?.state==='completed';
  return <section className="company-panels">
    <article className="ceo-brief"><div className="brief-orbit">N</div><div><p className="label">CEO BRIEFING · NAVI</p><h2>{task ? `${task.state_label}: ${task.title}` : '새 업무를 기다리는 중'}</h2><p>{task ? `현재 ${task.assigned_employees.length}명 배정. ${latest ? `최근 결정: ${latest.note}` : '아직 실행 이벤트 없음.'}` : 'CEO 대리 NAVI가 요청을 계약으로 정리합니다.'}</p><div className="brief-tags">{(task?.assigned_employees ?? ['NAVI','FRAME','BUILD']).map(id=><span key={id}>{personas[id]?.name ?? id}</span>)}</div></div></article>
    <article><p className="label">STRUCTURED MEETING</p><h3>{meeting?.objective ?? 'Intake Meeting 준비'}</h3><div className="meeting-grid"><span><b>참석</b>{meeting?.participants.join(' · ') ?? 'NAVI · FRAME'}</span><span><b>안건</b>{meeting?.agenda.join(' · ') ?? '요청 분석 · 범위 설정'}</span><span><b>결정</b>{meeting?.decisions.join(' · ') ?? '계약 생성 후 팀 배정'}</span></div><ol className="action-items">{task?.action_items.map(item=><li key={item.id}><b>{item.sequence}. {item.owner}</b><span>{item.description}</span></li>) ?? <li>계획을 실행하면 action item이 생성됩니다.</li>}</ol></article>
    <article><p className="label">COMPANY MEMORY</p><h3>작업에서 학습한 신호</h3><div className="memory"><span><b>현재 패턴</b>{task?.request ?? '프로젝트 요청을 기다리는 중'}</span><span><b>검증 규칙</b>신선한 Evidence 없이는 완료 불가</span><span><b>최근 사건</b>{latest?.to_state ?? '대기'} · {latest?.actor ?? 'NAVI'}</span></div></article>
    <article><p className="label">USER DECISION</p><h3>대표 승인</h3><p>현재 상태를 확인한 뒤 승인, 재작업, 차단을 직접 결정합니다.</p><div className="decision-buttons"><button disabled={!task} onClick={()=>onAction('approval')}>승인 대기</button><button disabled={!task} onClick={()=>onAction('reflect')}>재작업 지시</button><button disabled={!task} onClick={()=>onAction('block')}>작업 차단</button></div></article>
    <article className={`completion ${completed?'celebrate':''}`}><p className="label">COMPLETION REPORT</p><h3>{completed ? '업무 완료 · 증거 확보' : '완료 보고 대기'}</h3><p>{task ? `상태 ${task.state_label} · evidence ${task.evidence.filter(x=>x.status==='pass'&&!x.stale).length}건 · event ${task.events.length}건` : '작업을 시작하면 결과, 근거, 학습 내용을 모읍니다.'}</p>{completed&&<div className="confetti">✦ ✦ ✦</div>}</article>
  </section>
}
