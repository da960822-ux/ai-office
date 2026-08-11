import { Dialog, DeliverableCards, EvidenceChecklist, InfoBlock, ProseBlock, ReportSection, ReviewCard, ScopeList, SourceList } from '../shared';
import type { Task, Workspace } from '../api';

export function EvidenceModal({ task, workspace, onClose }: { task: Task | null; workspace: Workspace | null; onClose: () => void }) {
  if (!task) return <Dialog title="QA Lab · 상세 보기" onClose={onClose}><p className="dialog-copy">업무가 시작되면 산출물과 검증 근거가 표시됩니다.</p></Dialog>;

  const naviReport = task.agent_messages.find(message => message.employee_id === 'NAVI' && message.kind === 'final_report');
  const originalSources = task.research_sources.filter(source => source.query === 'verified-original');
  const latestReview = task.reviews[0];

  return <Dialog title="QA Lab · 상세 보기" onClose={onClose}>
    <p className="dialog-copy">이 업무가 실제로 검증된 방식과 근거입니다. 통과·실패·대기 표시는 실제 검증 결과 그대로 보여줍니다.</p>

    {task.execution_plan && <ReportSection title="판단 요약">
      <ProseBlock text={task.execution_plan.plan.summary} placeholder="요약이 아직 없습니다." />
      {task.execution_plan.plan.evidence_strategy && <p className="prose-block">근거 전략: {task.execution_plan.plan.evidence_strategy}</p>}
    </ReportSection>}

    <ReportSection title="실제 산출물" empty={!task.deliverables.length}>
      <DeliverableCards deliverables={task.deliverables} workspace={workspace} />
    </ReportSection>

    <ReportSection title="검증 체크리스트" meta={`${task.evidence.length}건`} empty={!task.evidence.length}>
      <EvidenceChecklist evidence={task.evidence} />
    </ReportSection>

    <ReportSection title="NAVI 기술 리포트" empty={!naviReport}>
      <ProseBlock text={naviReport?.content ?? ''} placeholder="아직 최종 리포트가 없습니다." />
    </ReportSection>

    <ReportSection title="원문 확인 웹 근거" meta={originalSources.length ? `${originalSources.length}건` : undefined} empty={!originalSources.length}>
      <SourceList sources={originalSources} />
    </ReportSection>

    <ReportSection title="실행 범위" meta={task.agent_scopes.length ? `${task.agent_scopes.length}명` : undefined} empty={!task.agent_scopes.length}>
      <ScopeList scopes={task.agent_scopes} />
    </ReportSection>

    <ReportSection title="최종 리뷰" empty={!latestReview}>
      <ReviewCard review={latestReview} />
    </ReportSection>

    {workspace && <InfoBlock label="작업 프로젝트" value={workspace.path} />}
  </Dialog>;
}
