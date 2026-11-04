import test from 'node:test';
import assert from 'node:assert/strict';
import { getAlarmPopupPriority } from './alarmPopupPresentation.js';

test('only configured source critical severity gets the critical popup accent', () => {
  assert.deepEqual(getAlarmPopupPriority({ candidate: { alarm_severity: 'CRITICAL' }, urgency: { urgency_band: 'ROUTINE' } }), {
    configured: true, label: 'Severity: CRITICAL', tone: 'critical',
  });
  assert.equal(getAlarmPopupPriority({ candidate: { alarm_severity: 'WARNING' } }).tone, 'warning');
  const advisoryCritical = getAlarmPopupPriority({ urgency: { urgency_band: 'CRITICAL' } });
  assert.equal(advisoryCritical.tone, 'normal');
  assert.match(advisoryCritical.label, /Priority: CRITICAL/);
  assert.equal(getAlarmPopupPriority({ candidate: { alarm_severity: 'NOT SUPPLIED' }, urgency: { urgency_band: 'ROUTINE' } }).tone, 'normal');
});
