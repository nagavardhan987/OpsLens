import test from 'node:test';
import assert from 'node:assert/strict';
import { getWorkflowSubmission, hasSubsequentClearAlarmReading, workflowActionFailureMessage, workflowActionSuccessMessage } from './operatorWorkflow.js';

test('active alarm never unlocks operator resolution', () => {
  assert.equal(hasSubsequentClearAlarmReading({ observed: true, active: true, is_later_than_alarm: true, timestamp: '2026-10-01T10:00:02Z' }), false);
});

test('stale or non-later clear reading never unlocks resolution', () => {
  assert.equal(hasSubsequentClearAlarmReading({ observed: true, active: false, is_later_than_alarm: false, timestamp: '2026-10-01T09:59:00Z' }), false);
  assert.equal(hasSubsequentClearAlarmReading({ observed: true, active: false, timestamp: '2026-10-01T10:00:02Z' }), false);
});

test('valid later timestamped clear sample unlocks operator confirmation', () => {
  assert.equal(hasSubsequentClearAlarmReading({ observed: true, active: false, is_later_than_alarm: true, timestamp: '2026-10-01T10:00:02Z' }), true);
});

test('Log Event maps to a note-bearing ANNOTATE audit action', () => {
  assert.deepEqual(getWorkflowSubmission('LOG_EVENT', '  Checked the local indicator.  '), {
    kind: 'audit', actionType: 'ANNOTATE', notes: 'Checked the local indicator.',
  });
  assert.equal(workflowActionSuccessMessage('LOG_EVENT'), 'Event note saved to the incident audit history.');
});

test('Mark Unresolved uses a dedicated status operation and preserves an optional note', () => {
  assert.deepEqual(getWorkflowSubmission('MARK_UNRESOLVED', 'Investigating repeat alarm'), {
    kind: 'status', actionType: 'MARK_UNRESOLVED', reason: 'Investigating repeat alarm',
  });
  assert.deepEqual(getWorkflowSubmission('MARK_UNRESOLVED'), {
    kind: 'status', actionType: 'MARK_UNRESOLVED', reason: null,
  });
  assert.equal(workflowActionSuccessMessage('MARK_UNRESOLVED'), 'Incident marked unresolved and returned to the active alarm list.');
});

test('Verify and Inspect remain independent audit actions', () => {
  assert.deepEqual(getWorkflowSubmission('VERIFY', 'Reviewed current status.'), {
    kind: 'audit', actionType: 'VERIFY', notes: 'Reviewed current status.',
  });
  assert.deepEqual(getWorkflowSubmission('INSPECT', 'Checked panel indication.'), {
    kind: 'audit', actionType: 'INSPECT', notes: 'Checked panel indication.',
  });
  assert.equal(workflowActionSuccessMessage('VERIFY'), 'Operator verification recorded. Alarm state is unchanged.');
});

test('workflow errors never expose raw backend validation text', () => {
  const raw = new Error("Invalid action_type 'LOG_EVENT'. secret backend detail");
  assert.equal(workflowActionFailureMessage('LOG_EVENT', raw), 'The event note was not saved. Check the note and try again.');
  assert.equal(workflowActionFailureMessage('RESOLVE', { status: 400, message: 'internal detail' }), 'Resolution is still locked. A later source-clear reading and operator confirmation are required.');
});

test('acknowledgement uses the existing audited operator action type', () => {
  assert.deepEqual(getWorkflowSubmission('ACKNOWLEDGE', 'Reviewed alarm.'), {
    kind: 'audit', actionType: 'ACKNOWLEDGE', notes: 'Reviewed alarm.',
  });
});

test('acknowledgement feedback keeps alarm acknowledgement separate from resolution', () => {
  assert.match(workflowActionSuccessMessage('ACKNOWLEDGE'), /remains active/);
  assert.match(workflowActionFailureMessage('ACKNOWLEDGE', new Error()), /state is unchanged; try again/);
});
