import { Dialog, EvidenceGateSequence, InfoBlock, ReportSection, ScopeList } from '../shared';
import { personas } from '../personas';
import type { PermissionRequest, Task } from '../api';

const DECISION_LABEL: Record<string, string> = { approve: '승인', rework: '재작업', reject: '반려' };

export function ApprovalModal({ task, approvalCount, pendingPermissions, busy, decideApproval, decidePermission, onClose }: {
  task: Task | null; approvalCount: number; pendingPermissions: PermissionRequest[]; busy: string;
  decideApproval: (decision: 'approve' | 'rework' | 'reject') => void;
  decidePermission: (requestId: string, decision: 'approve' | 'deny') => void;
  onClose: () => void;
}) {
  const lastDecision = task?.approvals[0];
  return <Dialog title="대표 의사결정" onClose={onClose}>
    {pendingPermissions.length > 0 && <ReportSection title="지금 실행이 멈춰서 기다리는 요청" meta={`${pendingPermissions.length}건`}>
      <div className="permission-request-list">{pendingPermissions.map(request => <div key={request.id} className="permission-request-card">
        <div className="permission-request-head">
          <b>{personas[request.employee_id]?.name ?? request.employee_id}</b>
          <span>실행 중 계약 범위 밖 작업이라 승인을 기다리고 있습니다.</span>
        </div>
        <code className="permission-request-detail">{request.action} · {request.target}</code>
        <div className="permission-request-actions">
          <button className="text-button" onClick={() => decidePermission(request.id, 'approve')} disabled={Boolean(busy)}>승인하고 계속 진행</button>
          <button className="text-button" onClick={() => decidePermission(request.id, 'deny')} disabled={Boolean(busy)}>거부하고 건너뛰기</button>
        </div>
      </div>)}</div>
    </ReportSection>}

    {approvalCount ? <>
      <div className="approval-context">
        <b>{task?.title}</b>
        <span>현재 상태: {task?.state_label} — 다음 단계로 넘어가려면 대표 승인이 필요합니다.</span>
      </div>

      <ReportSection title="지금까지 진행된 작업" empty={!task?.agent_scopes.length}>
        <ScopeList scopes={task?.agent_scopes ?? []} />
      </ReportSection>

      <ReportSection title="검증 근거">
        {task && <EvidenceGateSequence task={task} />}
      </ReportSection>

      <div className="decision-choices">
        <button className="decision-choice choice-approve" onClick={() => decideApproval('approve')} disabled={Boolean(busy)}>
          <b>승인</b>
          <span>지금까지 결과를 확정하고, 업무를 완료 처리합니다.</span>
        </button>
        <button className="decision-choice" onClick={() => decideApproval('rework')} disabled={Boolean(busy)}>
          <b>재작업</b>
          <span>담당 부서가 같은 목표로 다시 작업하도록 되돌립니다.</span>
        </button>
        <button className="decision-choice choice-reject" onClick={() => decideApproval('reject')} disabled={Boolean(busy)}>
          <b>반려</b>
          <span>이 방향으로는 진행하지 않고, 업무를 중단합니다.</span>
        </button>
      </div>
    </> : <>
      <p className="dialog-copy">현재 업무 완료 승인이 필요한 업무가 없습니다. 개인정보·법무·계약·영업·고객대응처럼 민감한 업무만 팀장 리뷰 통과 후 여기서 최종 확인을 거칩니다. 그 외 일반 업무는 팀장 리뷰만 통과하면 자동으로 완료됩니다.</p>
      {lastDecision ? <div className="decision-status">
        <span className={`status-dot ${lastDecision.decision === 'approve' ? 'is-ok' : lastDecision.decision === 'reject' ? 'is-down' : 'is-unset'}`} aria-hidden="true" />
        <div>
          <b>마지막 결정: {DECISION_LABEL[lastDecision.decision] ?? lastDecision.decision}</b>
          <span>{lastDecision.reason || '사유가 기록되지 않았습니다.'} · {new Date(lastDecision.created_at).toLocaleString('ko-KR')}</span>
        </div>
      </div> : <InfoBlock label="마지막 결정" value="아직 대표가 내린 결정이 없습니다." />}
    </>}
  </Dialog>;
}
