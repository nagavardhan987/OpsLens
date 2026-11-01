const UNKNOWN_VALUES = new Set(['', 'UNKNOWN', 'NOT SUPPLIED', 'NONE', 'UNCONFIGURED', 'NULL']);

/** Keep source severity distinct from advisory urgency used to rank alarms. */
export function getAlarmPopupPriority(event = {}) {
  const candidate = event.candidate || {};
  const raw = candidate.alarm_severity || event.alarm_severity || event.source_priority || candidate.source_priority;
  const sourceSeverity = typeof raw === 'string' ? raw.trim() : '';
  const configured = Boolean(sourceSeverity && !UNKNOWN_VALUES.has(sourceSeverity.toUpperCase()));
  const urgency = event.urgency?.urgency_band || 'ROUTINE';
  const label = configured ? `Severity: ${sourceSeverity}` : `Priority: ${urgency}`;
  const normalized = configured ? sourceSeverity.toUpperCase() : '';
  return {
    configured,
    label,
    tone: normalized === 'CRITICAL' ? 'critical' : normalized === 'WARNING' ? 'warning' : 'normal',
  };
}
