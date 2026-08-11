import { Dialog, InfoBlock } from '../shared';
import type { Task } from '../api';

export function ReflectionModal({ task, reflectionSummary, setReflectionSummary, reflectionCause, setReflectionCause, reflectionImprovement, setReflectionImprovement, lesson, setLesson, busy, submitReflection, onClose }: {
  task: Task | null; reflectionSummary: string; setReflectionSummary: (value: string) => void;
  reflectionCause: string; setReflectionCause: (value: string) => void;
  reflectionImprovement: string; setReflectionImprovement: (value: string) => void;
  lesson: string; setLesson: (value: string) => void; busy: string; submitReflection: () => void; onClose: () => void;
}) {
  return <Dialog title="회고와 회사 기억" onClose={onClose}>
    {!task ? <p className="dialog-copy">업무가 필요합니다.</p> : <><p className="dialog-copy">회고는 업무 기록에 남고, 레슨은 회사 기억으로 누적됩니다.</p><label>회고 요약</label><textarea className="request-editor compact-editor" value={reflectionSummary} onChange={event => setReflectionSummary(event.target.value)} placeholder="무엇이 잘 됐고 무엇을 바꿀지 기록합니다." /><label>원인 — 줄마다 하나</label><textarea className="request-editor compact-editor" value={reflectionCause} onChange={event => setReflectionCause(event.target.value)} /><label>개선 — 줄마다 하나</label><textarea className="request-editor compact-editor" value={reflectionImprovement} onChange={event => setReflectionImprovement(event.target.value)} /><label>회사 레슨</label><textarea className="request-editor compact-editor" value={lesson} onChange={event => setLesson(event.target.value)} placeholder="다음 업무에도 재사용할 한 문장 원칙" /><button className="solid-button wide" disabled={!reflectionSummary.trim() || Boolean(busy)} onClick={submitReflection}>{busy || '회고와 레슨 저장'}</button>{task.lessons.length ? <InfoBlock label="기록된 레슨" value={task.lessons.map(item => item.content).join('\n')} /> : null}</>}
  </Dialog>;
}
