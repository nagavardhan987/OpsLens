import test from 'node:test';
import assert from 'node:assert/strict';
import { getAcknowledgementTarget, isAlarmActive, isAlarmAcknowledged, summarizeAlarmStates } from './alarmState.js';

test('acknowledged alarm stays active and changes the unacknowledged count', () => {
  const alarm = { alarm_id: 'alarm-1', lifecycle_state: 'ACKNOWLEDGED', acknowledged_timestamp: '2026-11-03T10:00:00Z' };
  assert.equal(isAlarmActive(alarm), true);
  assert.equal(isAlarmAcknowledged(alarm), true);
  assert.deepEqual(summarizeAlarmStates([{ individual_alarms: [alarm] }]), { active: 1, acknowledged: 1, unacknowledged: 0 });
});

test('acknowledgement target skips acknowledged and cleared alarms', () => {
  const incident = { individual_alarms: [
    { alarm_id: 'ack', lifecycle_state: 'ACKNOWLEDGED' },
    { alarm_id: 'clear', lifecycle_state: 'CLEARED' },
    { alarm_id: 'active', lifecycle_state: 'ACTIVE' },
  ] };
  assert.equal(getAcknowledgementTarget(incident).alarm_id, 'active');
  assert.equal(summarizeAlarmStates([{ individual_alarms: incident.individual_alarms }]).active, 2);
});
