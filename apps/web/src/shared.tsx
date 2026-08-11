import type { CSSProperties, ReactNode } from 'react';
import { useState } from 'react';
import { personas } from './personas';
import type { AgentScope, Deliverable, Evidence, ResearchSource, Review, Task, Workspace } from './api';

/** Modal chrome shared by every dialog variant. */
export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return <div className="modal-backdrop" onMouseDown={onClose}><section className="detail-dialog" onMouseDown={event => event.stopPropagation()}><button className="modal-close" onClick={onClose}>×</button><span>AI OFFICE</span><h2>{title}</h2>{children}</section></div>;
}

export function InfoBlock({ label, value }: { label: string; value: string }) {
  return <div className="info-block"><b>{label}</b><p>{value}</p></div>;
}

export function deliverableStatusMeta(status: string) {
  if (['approved', 'final_candidate'].includes(status)) return { label: status === 'approved' ? '승인됨' : '최종 후보', tone: 'is-ok' };
  if (['rejected', 'fail'].includes(status)) return { label: '반려', tone: 'is-down' };
  return { label: status || '작성 중', tone: 'is-unset' };
}

export function DeliverableCards({ deliverables, workspace }: { deliverables: Deliverable[]; workspace: Workspace | null }) {
  const [copiedId, setCopiedId] = useState('');
  if (!deliverables.length) return <InfoBlock label="실제 산출물" value="아직 생성된 산출물 파일이 없습니다." />;
  const copyPath = (id: string, fullPath: string) => {
    void navigator.clipboard?.writeText(fullPath).then(() => { setCopiedId(id); setTimeout(() => setCopiedId(current => current === id ? '' : current), 1500); }).catch(() => {});
  };
  return <div className="deliverable-section">
    <b className="info-block-label">실제 산출물 · {deliverables.length}건</b>
    <div className="deliverable-grid">{deliverables.map(item => {
      const fullPath = workspace ? `${workspace.path}\\${item.path.replaceAll('/', '\\')}` : item.path;
      const status = deliverableStatusMeta(item.status);
      return <div key={item.id} className="deliverable-card">
        <div className="deliverable-card-head"><span className={`status-dot ${status.tone}`} aria-hidden="true" /><b>{status.label}</b><small>{personas[item.owner]?.name ?? item.owner}</small></div>
        <code className="deliverable-path" title={fullPath}>{item.path}</code>
        <div className="deliverable-card-foot"><small>{item.kind} · {new Date(item.updated_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}</small><button className="text-button" onClick={() => copyPath(item.id, fullPath)}>{copiedId === item.id ? '복사됨' : '경로 복사'}</button></div>
      </div>;
    })}</div>
  </div>;
}

// The one allowed "reward" moment: task reaching `completed` only happens
// server-side once evidence rows of type 'deliverable' (file hash), 'command'
// (verification exit code), and 'lead_review' (independent review) all read
// status:'pass' (see apps/api/task_routes.py's lead_review/pass gate check).
// This reads those same three real evidence rows back out and renders them
// resolving in sequence — no synthetic celebration, only the actual gate.
type GateCheck = { key: string; label: string; pass: boolean; present: boolean; detail: string };
export function evidenceGateChecks(task: Task): GateCheck[] {
  const fileHash = task.evidence.find(item => item.type === 'deliverable');
  const verifyExit = task.evidence.find(item => item.type === 'command');
  const reviewEvidence = task.evidence.find(item => item.type === 'lead_review');
  const reviewRecord = task.reviews[0];
  const primaryDeliverable = task.deliverables[0];
  return [
    { key: 'hash', label: '파일 해시', present: Boolean(fileHash), pass: fileHash?.status === 'pass',
      detail: fileHash ? `${primaryDeliverable?.artifact_sha256?.slice(0, 12) ?? fileHash.id} · ${fileHash.status}` : '아직 산출물 해시 없음' },
    { key: 'exit', label: '검증 명령 종료 코드', present: Boolean(verifyExit), pass: verifyExit?.status === 'pass',
      detail: verifyExit ? `${verifyExit.id} · ${verifyExit.status}` : '아직 검증 명령 실행 없음' },
    { key: 'review', label: '독립 리뷰', present: Boolean(reviewEvidence) || Boolean(reviewRecord), pass: reviewEvidence?.status === 'pass' || reviewRecord?.verdict === 'pass',
      detail: reviewRecord ? `${personas[reviewRecord.reviewer_id]?.name ?? reviewRecord.reviewer_id} · ${reviewRecord.verdict}` : reviewEvidence ? `${reviewEvidence.id} · ${reviewEvidence.status}` : '아직 리뷰 없음' },
  ];
}
export function EvidenceGateSequence({ task }: { task: Task }) {
  const checks = evidenceGateChecks(task);
  return <div className="evidence-gate">
    <b className="info-block-label">완료 조건 · 3중 증거 게이트</b>
    <ol className="evidence-gate-list">{checks.map((check, index) => <li key={check.key} className={check.pass ? 'gate-pass' : check.present ? 'gate-fail' : 'gate-missing'} style={{ '--gate-delay': `${index * 280}ms` } as CSSProperties}>
      <span className="gate-dot" aria-hidden="true">{check.pass ? '✓' : check.present ? '✕' : '·'}</span>
      <span className="gate-label">{check.label}</span>
      <code className="gate-detail">{check.detail}</code>
    </li>)}</ol>
  </div>;
}

export function CompletionSummary({ task, onDetails }: { task: Task; onDetails: () => void }) {
  const failed = task.evidence.some(item => item.status === 'fail') || task.jobs.some(job => job.state === 'failed');
  const report = task.agent_messages.find(message => message.employee_id === 'NAVI' && message.kind === 'final_report');
  return <section className="completion-summary"><h3>작업 결과</h3><EvidenceGateSequence task={task} /><InfoBlock label="작동 여부" value={failed ? '확인이 필요합니다. 상세 검토가 필요합니다.' : '검증을 통과했습니다.'} /><InfoBlock label="남은 작업" value={failed ? '검토 후 재작업 범위를 선택하세요.' : '현재 요청 기준 남은 작업이 없습니다.'} /><InfoBlock label="다음 행동" value="결과를 사용하거나, 새 요청으로 다음 개선을 시작하세요." />{report && <p className="completion-note">NAVI가 완료 조건과 위험을 확인했습니다.</p>}<button className="text-button" onClick={onDetails}>테스트 결과·기술 리포트 자세히 보기 →</button></section>;
}

/** Bordered report section with a heading — the scannable-card building block for
 *  ApprovalModal / MeetingModal / EvidenceModal, replacing stacked InfoBlock dumps. */
export function ReportSection({ title, meta, children, empty }: { title: string; meta?: string; children: ReactNode; empty?: boolean }) {
  return <section className={`report-section${empty ? ' is-empty' : ''}`}>
    <div className="report-section-head"><b>{title}</b>{meta && <small>{meta}</small>}</div>
    <div className="report-section-body">{children}</div>
  </section>;
}

/** Long-form AI output (final reports, review findings) rendered as real prose,
 *  not squeezed into an InfoBlock's small label:value box. */
export function ProseBlock({ text, placeholder }: { text: string; placeholder: string }) {
  if (!text.trim()) return <p className="prose-empty">{placeholder}</p>;
  return <p className="prose-block">{text}</p>;
}

export function PersonChips({ ids }: { ids: string[] }) {
  if (!ids.length) return <p className="prose-empty">아직 배정된 참여자가 없습니다.</p>;
  return <div className="chip-row">{ids.map(id => <span key={id} className="person-chip">{personas[id]?.name ?? id}</span>)}</div>;
}

const EVIDENCE_TYPE_LABEL: Record<string, string> = {
  deliverable: '산출물 파일 해시 확인',
  rendered_deliverable: '렌더링 문서 확인',
  command: '검증 명령 실행 결과',
  research_claim: '조사 근거 확인',
  verified_web_source: '원문 웹 근거 확인',
  web_source: '원문 웹 근거 확인',
  agent_run: '실행자 작업 기록',
  integration_review: '통합 검토 결과',
  lead_review: '독립 리뷰 결과',
};
const EVIDENCE_STATUS_LABEL: Record<string, { label: string; tone: string }> = {
  pass: { label: '통과', tone: 'is-ok' },
  fail: { label: '실패', tone: 'is-down' },
  pending: { label: '대기 중', tone: 'is-unset' },
  info: { label: '참고용 기록', tone: 'is-unset' },
};

/** Evidence rows as a real checklist of what was actually verified — same honest
 *  pass/fail/pending language as the completion-gate sequence, but covering every row. */
export function EvidenceChecklist({ evidence }: { evidence: Evidence[] }) {
  if (!evidence.length) return <p className="prose-empty">아직 검증 근거가 없습니다.</p>;
  return <ul className="checklist">{evidence.map(item => {
    const status = EVIDENCE_STATUS_LABEL[item.status] ?? { label: item.status || '대기 중', tone: 'is-unset' };
    return <li key={item.id} className="checklist-item">
      <span className={`status-dot ${status.tone}`} aria-hidden="true" />
      <span className="checklist-item-label">{EVIDENCE_TYPE_LABEL[item.type] ?? item.type}</span>
      <span className="checklist-item-status">{status.label}</span>
    </li>;
  })}</ul>;
}

/** Research sources as real link cards instead of a newline-joined string. */
export function SourceList({ sources }: { sources: ResearchSource[] }) {
  if (!sources.length) return <p className="prose-empty">확인된 원문 근거가 없습니다.</p>;
  return <ul className="source-list">{sources.slice(0, 5).map(source => <li key={source.id} className="source-item">
    <a href={source.url} target="_blank" rel="noreferrer">{source.title || source.url}</a>
    {source.snippet && <p>{source.snippet}</p>}
  </li>)}</ul>;
}

/** Per-employee execution scope as real cards instead of a newline-joined string. */
export function ScopeList({ scopes }: { scopes: AgentScope[] }) {
  if (!scopes.length) return <p className="prose-empty">아직 담당 범위가 정해지지 않았습니다.</p>;
  return <ul className="scope-list">{scopes.map(scope => <li key={scope.employee_id} className="scope-item">
    <b>{personas[scope.employee_id]?.name ?? scope.employee_id}</b>
    <p>{scope.assignment}</p>
    <small>산출물: {scope.deliverable || '미정'}</small>
  </li>)}</ul>;
}

const REVIEW_VERDICT_LABEL: Record<string, { label: string; tone: string }> = {
  pass: { label: '통과', tone: 'is-ok' },
  changes_requested: { label: '수정 요청', tone: 'is-unset' },
  blocked: { label: '차단됨', tone: 'is-down' },
};

/** Latest independent review as a verdict badge + real prose findings. */
export function ReviewCard({ review }: { review: Review | undefined }) {
  if (!review) return <p className="prose-empty">아직 리뷰가 없습니다.</p>;
  const verdict = REVIEW_VERDICT_LABEL[review.verdict] ?? { label: review.verdict, tone: 'is-unset' };
  return <div className="review-card">
    <div className="review-card-head"><span className={`status-dot ${verdict.tone}`} aria-hidden="true" /><b>{personas[review.reviewer_id]?.name ?? review.reviewer_id}</b><span className={`review-verdict ${verdict.tone}`}>{verdict.label}</span></div>
    <ProseBlock text={review.findings} placeholder="별도 의견이 남지 않았습니다." />
  </div>;
}
