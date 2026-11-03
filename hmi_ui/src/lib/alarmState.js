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

export function getAcknowledgementTarget(incident = {}) {
  const alarms = Array.isArray(incident.individual_alarms) ? incident.individual_alarms : [];
  return alarms.find((alarm) => isAlarmActive(alarm) && !isAlarmAcknowledged(alarm)) || null;
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
