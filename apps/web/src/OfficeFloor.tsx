import { useEffect, useRef, useState, type CSSProperties } from 'react';
import type { Employee, JobEvent, Task } from './api';
import { personas } from './personas';
import { directionForSegment, resolveMotion, routeBetween, routeDuration, type AgentAction, type AgentStateKey, type AvatarDirection, type MotionPoint } from './motion';

const leadIds = new Set(['NAVI', 'FRAME', 'BUILD', 'LINK', 'SHIP', 'GUARD', 'GROW', 'LENS']);
const spriteIds = ['NAVI', 'ROUTE', 'CLOCK', 'FRAME', 'FLOW', 'MOSS', 'BUILD', 'FRONT', 'BACK', 'LINK', 'SIGNAL', 'EVAL', 'SHIP', 'SRE', 'COST', 'GUARD', 'TRACE', 'SHIELD', 'GROW', 'VOICE', 'PULSE', 'LENS', 'JOURNEY', 'DOCS'];
// Sprite sheet slots verified against apps/web/public/assets/agent-sprites-v3.png:
// only 7 of 24 painted characters wear glasses (indexes 1,5,8,15,18,20,22). Personas
// with accessory:'glasses' (NAVI/BUILD/LINK/GUARD/LENS/DOCS) must land on one of those
// slots or they render as a different-looking character than their profile describes.
const avatarIndexes: Record<string, number> = { NAVI: 1, ROUTE: 0, BUILD: 8, BACK: 6, LINK: 22, JOURNEY: 9, LENS: 20, PULSE: 21, DOCS: 18, GROW: 23 };

/**
 * Seam for a future game-feel layer: props are explicit (agent id, state,
 * position) rather than reaching into global app state, so per-agent visual
 * effects can hook in here without threading through App.tsx.
 */
export function FloorAgent({ employee, active, activity, position, action, motion, selected, bubble, onFocus }: { employee: Employee; active: boolean; activity: string; position: [number, number]; action: AgentAction; motion?: ReturnType<typeof resolveMotion>; selected: boolean; bubble?: JobEvent; onFocus: (id: string) => void }) {
  const elementRef = useRef<HTMLButtonElement>(null);
  const previousPosition = useRef<MotionPoint | null>(null);
  const [isMoving, setIsMoving] = useState(false);
  const [direction, setDirection] = useState<AvatarDirection>('front-right');
  const lead = leadIds.has(employee.id);
  const team = teamForAgent(employee.id);
  const state = motion?.stateKey ?? 'idle';
  const status = stateLabel(state);
  const icon = stateIcon(state);
  const pose = isMoving || action === 'walk' ? 'walk-a' : action === 'idle' ? 'sit' : action;
  const genericBubble = !bubble || ['모델 작업 시작', '작업 중 · 실제 Job 처리 중'].includes(bubble.summary);
  const bubbleText = active ? ((genericBubble ? activity : bubble?.summary)?.slice(0, 140) || `${status} · 실제 Job 처리 중`) : (bubble?.summary.slice(0, 140) ?? '');
  useEffect(() => {
    const element = elementRef.current;
    const next: MotionPoint = { x: position[0], y: position[1], zone: motion?.target.zone ?? 'desk' };
    const previous = previousPosition.current;
    previousPosition.current = next;
    if (!element || !previous || (previous.x === next.x && previous.y === next.y)) return;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) { element.animate([{ opacity: .45 }, { opacity: 1 }], { duration: 120, easing: 'ease-out' }); return; }
    const stage = element.closest('.office-world');
    if (!stage) return;
    const bounds = stage.getBoundingClientRect();
    const route = routeBetween(previous, next);
    const duration = routeDuration(route);
    setDirection(directionForSegment(route[0], route[1] ?? route[0]));
    const keyframes = route.map((point, index) => {
      const dx = (point.x - next.x) / 100 * bounds.width;
      const dy = (point.y - next.y) / 100 * bounds.height;
      return { transform: `translate3d(-50%, -60%, 0) translate3d(${dx}px, ${dy}px, 0)`, offset: index / (route.length - 1) };
    });
    setIsMoving(true);
    const animation = element.animate(keyframes, { duration, easing: 'cubic-bezier(.22,.8,.25,1)', fill: 'both' });
    animation.onfinish = () => setIsMoving(false);
    animation.oncancel = () => setIsMoving(false);
    return () => animation.cancel();
  }, [motion?.target.zone, position[0], position[1]]);
  const visualAction = isMoving ? 'walk' : action;
  return <button ref={elementRef} aria-label={`${personas[employee.id]?.name ?? employee.id}, ${status}`} aria-live={selected ? 'polite' : undefined} className={`floor-agent ${active ? 'working' : ''} ${lead ? 'team-lead' : 'sub-agent'} team-${team} ${selected ? 'selected' : ''} state-${state} action-${visualAction}`} style={{ '--x': `${position[0]}%`, '--y': `${position[1]}%`, '--agent-tone': personas[employee.id]?.palette ?? '#7d9271', '--motion-delay': `${motion?.delayMs ?? 0}ms`, '--motion-duration': `${motion?.durationMs ?? 1600}ms` } as CSSProperties} onClick={() => onFocus(employee.id)}><span className="agent-shadow" />{bubbleText && <span className="agent-bubble">{bubbleText}</span>}<Avatar id={employee.id} pose={pose} direction={direction} />{lead && <b className="lead-mark" aria-label="팀장">◆</b>}{icon && <span className="agent-state-icon" aria-hidden="true">{icon}</span>}<span className="agent-name"><i />{personas[employee.id]?.name ?? employee.id}<em>{status}</em></span></button>;
}

export function agentBehavior(state: string, active: boolean) { if (!active) return '자리 대기'; if (['contracting', 'planning'].includes(state)) return '계획 중'; if (state === 'meeting') return '회의 중'; if (['verifying', 'failed', 'team_review', 'cross_review'].includes(state)) return 'QA 검토'; if (['awaiting_approval', 'blocked', 'escalated'].includes(state)) return state === 'blocked' ? '차단' : 'CEO 보고'; if (state === 'completed') return '업무 완료'; return '팀 작업 중'; }
// `group` here is an AgentStateKey display group from motion.getStateGroup, not
// a raw backend task/job state string. Backend states are awaiting_approval,
// completed, verifying/team_review/cross_review, etc. (apps/api/main.py
// JOB_STATES/TASK_STATES) - grouping them into approval/done/reviewing for
// display happens once, in motion.ts, so this function never re-derives a
// display bucket from a raw state string itself.
export function stateLabel(group: AgentStateKey) { return group === 'planning' ? '계획 중' : group === 'meeting' ? '회의 중' : group === 'reviewing' ? 'QA 검토' : group === 'blocked' ? '차단' : group === 'approval' ? 'CEO 보고' : group === 'running' ? '작업 중' : group === 'done' ? '업무 완료' : '대기'; }
export function stateIcon(group: AgentStateKey) { return group === 'planning' ? '▤' : group === 'meeting' ? '◌' : group === 'reviewing' ? '⌕' : group === 'blocked' ? '!' : group === 'approval' || group === 'done' ? '✓' : group === 'running' ? '◔' : ''; }
export function agentRole(id: string, lead: boolean) { const roles: Record<string, string> = { NAVI: 'CEO', FRAME: 'PM', BUILD: 'TECH LEAD', LINK: 'AI LEAD', SHIP: 'OPS LEAD', GUARD: 'QA LEAD', GROW: 'GROWTH LEAD', LENS: 'REVIEW LEAD', MOSS: 'DESIGNER', FRONT: 'FRONTEND', BACK: 'BACKEND', SIGNAL: 'DATA', EVAL: 'AI EVAL', SRE: 'SRE', TRACE: 'QA', SHIELD: 'SECURITY', VOICE: 'BRAND', PULSE: 'ANALYST', DOCS: 'DOCS', JOURNEY: 'RESEARCH', ROUTE: 'PLANNER', CLOCK: 'OPS', FLOW: 'UX', COST: 'FINOPS' }; return roles[id] ?? (lead ? 'TEAM LEAD' : 'SPECIALIST'); }
export function compactText(value: string, limit: number) { const text = value.replace(/[#*_`|]+/g, ' ').replace(/\s+/g, ' ').trim(); return text.length > limit ? `${text.slice(0, limit - 1)}…` : text; }
export function teamStatus(id: string, task: Task | null) { const count = task?.assigned_employees.filter(agentId => teamForAgent(agentId) === id).length ?? 0; if (!count || ['completed', 'cancelled'].includes(task?.state ?? '')) return '대기'; if (['meeting', 'meeting_running'].includes(task?.state ?? '')) return '회의 중'; if (['contracting', 'planning', 'awaiting_lead_selection', 'awaiting_worker_selection'].includes(task?.state ?? '')) return `실행 대기 ${count}`; if (['verifying', 'failed', 'team_review', 'cross_review', 'lead_review_running'].includes(task?.state ?? '')) return '검토 중'; if (task?.state === 'awaiting_approval') return '승인 대기'; if (task?.state === 'blocked') return '차단'; if (['running', 'executing'].includes(task?.state ?? '')) return `작업 중 ${count}`; return `배정 ${count}`; }

export function teamForAgent(id: string) {
  if (['NAVI', 'ROUTE', 'CLOCK', 'FRAME', 'FLOW'].includes(id)) return 'product';
  if (['MOSS', 'BUILD', 'FRONT'].includes(id)) return 'design';
  if (['BACK', 'LINK', 'SIGNAL', 'EVAL'].includes(id)) return 'backend';
  if (['GROW', 'VOICE', 'PULSE'].includes(id)) return 'growth';
  if (['LENS', 'JOURNEY', 'DOCS'].includes(id)) return 'lounge';
  return 'ops';
}

export function teamSignStyle(id: string): CSSProperties {
  const coordinates: Record<string, [string, string]> = { product: ['8%', '29%'], design: ['42%', '31%'], backend: ['72%', '31%'], growth: ['8%', '61%'], lounge: ['42%', '66%'], ops: ['72%', '61%'] };
  const [left, top] = coordinates[id];
  return { position: 'absolute', zIndex: 8, left, top, minWidth: 112, padding: '6px 8px', border: '1px solid #ffffffaa', borderRadius: 'var(--radius-sm)', background: '#101811e8', color: '#f7fff3', textAlign: 'left', boxShadow: 'var(--shadow-sm)' };
}

const directionalAtlases: Partial<Record<string, string>> = { NAVI: '/assets/agent-navi-v3.png', BUILD: '/assets/agent-build-v3.png', GUARD: '/assets/agent-guard-v3.png' };
export function Avatar({ id, compact = false, pose = 'stand', direction = 'front-right' }: { id: string; compact?: boolean; pose?: string; direction?: AvatarDirection }) {
  const persona = personas[id] ?? personas.NAVI;
  const index = avatarIndexes[id] ?? Math.max(0, spriteIds.indexOf(id));
  const atlas = directionalAtlases[id];
  const [x, y] = direction === 'front-left' ? ['0%', '0%'] : direction === 'front-right' ? ['100%', '0%'] : direction === 'back-left' ? ['0%', '100%'] : ['100%', '100%'];
  return <div data-avatar={id} className={`avatar-art sprite-avatar ${atlas ? 'directional-avatar' : ''} pose-${pose} ${compact ? 'compact' : ''}`} style={{ '--sprite-x': `${(index % 8) * 100 / 7}%`, '--sprite-y': `${Math.floor(index / 8) * 50}%`, '--directional-atlas': atlas ? `url(${atlas})` : undefined, '--direction-x': x, '--direction-y': y, '--halo': persona.palette } as CSSProperties} />;
}
