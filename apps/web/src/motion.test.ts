import { describe, expect, it } from 'vitest';
import { deskTargets, directionForSegment, resolveMotion, routeBetween, routeDuration, taskStateKey, taskStateToAction, targetZone, type MotionPoint } from './motion';

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

  it('routes between rooms through corridor waypoints, not one direct jump', () => {
    const desk: MotionPoint = {x:17, y:18, zone:'desk'};
    const qa: MotionPoint = {x:90, y:18, zone:'qa'};
    const route = routeBetween(desk, qa);
    expect(route).toHaveLength(5);
    expect(route[1]).toMatchObject({x:31, y:35});
    expect(route.at(-2)).toMatchObject({x:77, y:28});
  });

  it('uses bounded distance-based timing', () => {
    expect(routeDuration([{x:17,y:18,zone:'desk'}, {x:18,y:18,zone:'desk'}])).toBeGreaterThanOrEqual(350);
    expect(routeDuration([{x:0,y:0,zone:'desk'}, {x:100,y:100,zone:'qa'}])).toBeLessThanOrEqual(3000);
  });

  it('exposes task state as a renderable visual state', () => {
    expect(taskStateKey('planning', true)).toBe('planning');
    expect(taskStateKey('awaiting_approval', true)).toBe('approval');
    expect(taskStateKey('failed', true)).toBe('blocked');
    expect(taskStateKey('completed', true)).toBe('done');
  });

  it('selects a sprite direction from route vector', () => {
    const point: MotionPoint = {x:50, y:50, zone:'desk'};
    expect(directionForSegment(point, {x:40,y:60,zone:'desk'})).toBe('front-left');
    expect(directionForSegment(point, {x:60,y:40,zone:'desk'})).toBe('back-right');
  });

  it('gives every registered office agent a unique default desk target', () => {
    const employeeIds = Object.keys(deskTargets);
    const seats = employeeIds.map((employeeId) => {
      const motion = resolveMotion({ employeeId, taskState:'executing', active:true, isLead:false });
      expect(motion.target.zone).toBe('desk');
      return `${motion.target.x}:${motion.target.y}`;
    });

    expect(employeeIds).toHaveLength(24);
    expect(new Set(seats)).toHaveLength(24);
  });
});
