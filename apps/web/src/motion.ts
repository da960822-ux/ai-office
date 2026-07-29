/**
 * Pure motion policy for office agents. UI renders these values; it does not
 * decide who should move or which pose to show.
 */
export type AgentAction = 'idle' | 'walk' | 'work' | 'review' | 'meeting';
export type OfficeZone = 'desk' | 'meeting' | 'qa' | 'ceo';
export type MotionPoint = { x: number; y: number; zone: OfficeZone };

export type MotionInput = {
  employeeId: string;
  taskState?: string | null;
  active: boolean;
  isLead: boolean;
  assignmentIndex?: number;
};

export const deskTargets: Record<string, MotionPoint> = {
  NAVI:{x:17,y:18,zone:'desk'}, ROUTE:{x:16,y:39,zone:'desk'}, CLOCK:{x:26,y:41,zone:'desk'},
  FRAME:{x:21,y:42,zone:'desk'}, FLOW:{x:30,y:42,zone:'desk'}, MOSS:{x:44,y:42,zone:'desk'},
  BUILD:{x:52,y:43,zone:'desk'}, FRONT:{x:59,y:43,zone:'desk'}, BACK:{x:76,y:42,zone:'desk'},
  LINK:{x:84,y:42,zone:'desk'}, SIGNAL:{x:75,y:51,zone:'desk'}, EVAL:{x:86,y:51,zone:'desk'},
  SHIP:{x:78,y:70,zone:'desk'}, SRE:{x:86,y:70,zone:'desk'}, COST:{x:78,y:80,zone:'desk'},
  GUARD:{x:88,y:80,zone:'desk'}, TRACE:{x:86,y:20,zone:'desk'}, SHIELD:{x:76,y:20,zone:'desk'},
  GROW:{x:16,y:70,zone:'desk'}, VOICE:{x:26,y:70,zone:'desk'}, PULSE:{x:17,y:80,zone:'desk'},
  LENS:{x:47,y:73,zone:'desk'}, JOURNEY:{x:56,y:73,zone:'desk'}, DOCS:{x:47,y:82,zone:'desk'},
};

const roomTargets: Record<Exclude<OfficeZone, 'desk'>, MotionPoint[]> = {
  meeting:[{x:50,y:25,zone:'meeting'},{x:57,y:23,zone:'meeting'},{x:64,y:26,zone:'meeting'},{x:67,y:33,zone:'meeting'},{x:62,y:39,zone:'meeting'},{x:54,y:39,zone:'meeting'},{x:48,y:34,zone:'meeting'}],
  qa:[{x:83,y:17,zone:'qa'},{x:90,y:18,zone:'qa'},{x:87,y:25,zone:'qa'},{x:92,y:30,zone:'qa'},{x:83,y:32,zone:'qa'},{x:88,y:37,zone:'qa'},{x:94,y:22,zone:'qa'}],
  ceo:[{x:15,y:13,zone:'ceo'},{x:21,y:14,zone:'ceo'},{x:24,y:21,zone:'ceo'},{x:18,y:25,zone:'ceo'},{x:12,y:22,zone:'ceo'},{x:26,y:15,zone:'ceo'},{x:14,y:28,zone:'ceo'}],
};

const reviewStates = new Set(['verifying', 'failed', 'team_review', 'cross_review']);
const approvalStates = new Set(['awaiting_approval', 'blocked', 'escalated']);
const planningStates = new Set(['contracting', 'planning']);

/** Team members use only idle, walk, work. Team leads additionally review/meet. */
export function taskStateToAction(taskState: string | null | undefined, active: boolean, isLead: boolean): AgentAction {
  if (!active || !taskState || ['draft', 'completed', 'cancelled'].includes(taskState)) return 'idle';
  if (taskState === 'meeting') return 'meeting';
  if (reviewStates.has(taskState) || planningStates.has(taskState)) return isLead ? 'review' : 'work';
  if (approvalStates.has(taskState)) return isLead ? 'walk' : 'idle';
  return 'work';
}

export function targetZone(taskState: string | null | undefined, active: boolean, isLead: boolean): OfficeZone {
  if (!active) return 'desk';
  if (taskState === 'meeting') return 'meeting';
  if (reviewStates.has(taskState ?? '') && isLead) return 'qa';
  if (approvalStates.has(taskState ?? '') && isLead) return 'ceo';
  return 'desk';
}

export function targetLocation(input: MotionInput): MotionPoint {
  const zone = targetZone(input.taskState, input.active, input.isLead);
  if (zone === 'desk') return deskTargets[input.employeeId] ?? {x:50, y:50, zone:'desk'};
  const options = roomTargets[zone];
  return options[(input.assignmentIndex ?? deterministicIndex(input.employeeId)) % options.length];
}

/** Stable 0..1 seed. Same employee always gets same cadence. */
export function motionSeed(employeeId: string): number {
  let hash = 2166136261;
  for (const char of employeeId) { hash ^= char.charCodeAt(0); hash = Math.imul(hash, 16777619); }
  return (hash >>> 0) / 4294967295;
}

export function deterministicIndex(employeeId: string, count = 7): number {
  return Math.floor(motionSeed(employeeId) * count) % Math.max(1, count);
}

/** Start time offset prevents every agent posing on same frame. */
export function motionStagger(employeeId: string, spreadMs = 640): number {
  return Math.round(motionSeed(employeeId) * Math.max(0, spreadMs));
}

/** Per-agent stable duration. CSS can consume this as `animationDuration`. */
export function motionDuration(action: AgentAction, employeeId: string): number {
  const base: Record<AgentAction, number> = {idle: 3600, walk: 820, work: 1550, review: 2050, meeting: 2350};
  const variance: Record<AgentAction, number> = {idle: 1200, walk: 260, work: 520, review: 560, meeting: 700};
  return Math.round(base[action] + motionSeed(employeeId) * variance[action]);
}

export function resolveMotion(input: MotionInput) {
  const action = taskStateToAction(input.taskState, input.active, input.isLead);
  return {
    action,
    target: targetLocation(input),
    delayMs: motionStagger(input.employeeId),
    durationMs: motionDuration(action, input.employeeId),
  };
}
