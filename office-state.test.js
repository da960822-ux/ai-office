import test from 'node:test';
import assert from 'node:assert/strict';
import { makeOfficeState, transition, locations } from './office-state.js';

test('meeting event moves selected staff to meeting state', () => {
  const office = transition(makeOfficeState(), 'meeting', ['NAVI', 'FRAME']);
  assert.equal(office.task.state, 'meeting');
  assert.equal(office.employees.find(x => x.id === 'NAVI').status, 'meeting');
  assert.equal(locations.meeting, 'meeting');
});

test('verification event sends assignees to QA and preserves idle staff', () => {
  const office = transition(makeOfficeState(), 'verify', ['FRONT', 'TRACE']);
  assert.equal(office.employees.find(x => x.id === 'TRACE').status, 'verifying');
  assert.equal(office.employees.find(x => x.id === 'NAVI').status, 'idle');
});

test('reset returns every employee and task to initial state', () => {
  const office = makeOfficeState();
  transition(office, 'approval', ['NAVI', 'FRONT']);
  transition(office, 'reset');
  assert.equal(office.task.state, 'idle');
  assert.ok(office.employees.every(x => x.status === 'idle'));
});
