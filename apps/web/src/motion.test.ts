import { describe, expect, it } from 'vitest';
import { resolveMotion, taskStateToAction, targetZone } from './motion';

describe('office motion follows backend execution state', () => {
  it('keeps a worker seated at the desk while executing', () => {
    const motion = resolveMotion({ employeeId:'PULSE', taskState:'executing', active:true, isLead:false });
    expect(motion.action).toBe('work');
    expect(motion.target.zone).toBe('desk');
  });

  it('seats selected leads in the meeting room', () => {
    const motion = resolveMotion({ employeeId:'GROW', taskState:'meeting', active:true, isLead:true, assignmentIndex:1 });
    expect(motion.action).toBe('meeting');
    expect(motion.target.zone).toBe('meeting');
  });

  it('does not animate an inactive or completed agent', () => {
    expect(taskStateToAction('completed', true, false)).toBe('idle');
    expect(targetZone('executing', false, false)).toBe('desk');
  });

  it('moves only a reviewing lead to QA', () => {
    expect(targetZone('team_review', true, true)).toBe('qa');
    expect(targetZone('team_review', true, false)).toBe('desk');
  });
});
