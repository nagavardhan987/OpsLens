const ACKNOWLEDGED = new Set(['ACKNOWLEDGED', 'ACKNOWLEDGE']);
const CLOSED = new Set(['CLEARED', 'RETURNED_TO_NORMAL', 'RESOLVED']);

export function getAlarmLifecycleState(alarm = {}) {
  return String(alarm.lifecycle_state || alarm.status || 'ACTIVE').trim().toUpperCase();
}

export function isAlarmAcknowledged(alarm = {}) {
  return ACKNOWLEDGED.has(getAlarmLifecycleState(alarm)) || Boolean(alarm.acknowledged_timestamp || alarm.acknowledged_at);
}

export function isAlarmActive(alarm = {}) {
  return !CLOSED.has(getAlarmLifecycleState(alarm));
}

// The operator acknowledges the alarm shown in the banner (the incident's
// primary alarm) first, then the remaining inputs one at a time.
export function getAcknowledgementTarget(incident = {}) {
  const alarms = Array.isArray(incident.individual_alarms) ? incident.individual_alarms : [];
  const pending = alarms.filter((alarm) => isAlarmActive(alarm) && !isAlarmAcknowledged(alarm));
  const primary = incident.primary_tag || incident.candidate?.primary_tag;
  return pending.find((alarm) => (alarm.tag || alarm.alarm_tag) === primary) || pending[0] || null;
}

export function summarizeAlarmStates(incidents = []) {
  const alarms = incidents.flatMap((incident) => {
    const rows = Array.isArray(incident.individual_alarms) ? incident.individual_alarms : [];
    return rows.length ? rows : [{ lifecycle_state: incident.lifecycle_state || incident.status }];
  });
  const active = alarms.filter(isAlarmActive);
  const acknowledged = active.filter(isAlarmAcknowledged).length;
  return { active: active.length, acknowledged, unacknowledged: active.length - acknowledged };
}
