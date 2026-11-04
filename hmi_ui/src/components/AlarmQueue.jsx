import React from 'react';
import { AlertTriangle, ArrowUpRight, Layers3 } from 'lucide-react';
import { getAlarmLifecycleState, isAlarmAcknowledged, isAlarmActive, summarizeAlarmStates } from '../lib/alarmState';

const BAND = {
  URGENT: 'border-red-200 bg-red-50 text-red-700',
  ELEVATED: 'border-amber-200 bg-amber-50 text-amber-700',
  ROUTINE: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  UNKNOWN: 'border-slate-200 bg-slate-50 text-slate-600',
};

function displayTime(value) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Time unavailable';
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(new Date(value));
}

function alarmTags(event) {
  const alarms = Array.isArray(event.individual_alarms) ? event.individual_alarms : [];
  // `alarm_id` is the durable database UUID; `tag` is the operator-readable
  // instrument/alarm identifier and belongs in the queue row.
  const tags = [...new Set(alarms.map((item) => item.tag || item.alarm_tag || item.alarm_id).filter(Boolean))];
  if (!tags.length) {
    const storyAlarm = [...(event.story?.steps || [])].reverse().find((step) => String(step.tag || '').startsWith('ALM-'));
    tags.push(storyAlarm?.tag || event.candidate?.alarm_id || event.candidate?.primary_tag || event.primary_tag || 'Alarm ID unavailable');
  }
  return tags;
}

export default function AlarmQueue({ incidents = [], selectedEventId, onSelect, loading = false, error = '', compact = false }) {
  const alarmStateCounts = summarizeAlarmStates(incidents);
  const selected = incidents.find((incident) => incident.event_id === selectedEventId) || incidents[0];
  const urgency = selected?.urgency;
  return (
    <section className={`alarm-queue${compact ? ' alarm-queue-compact' : ''}`} aria-label="Prioritized active alarms">
      <div className="alarm-queue-heading">
        <div>
          <span className="alarm-queue-kicker">Active alarm queue</span>
          <h2>{alarmStateCounts.active} active alarm{alarmStateCounts.active === 1 ? '' : 's'}</h2>
          <small>{alarmStateCounts.unacknowledged} unacknowledged · {alarmStateCounts.acknowledged} acknowledged</small>
        </div>
      </div>
      {error ? <p className="alarm-queue-state" role="status">Alarms are temporarily unavailable.</p> : null}
      {!error && loading && incidents.length === 0 ? <p className="alarm-queue-state">Loading recorded alarm groups…</p> : null}
      {!error && !loading && incidents.length === 0 ? <p className="alarm-queue-state">No active alarm groups. New alarms will appear here when recorded.</p> : null}
      {incidents.length > 0 && <div className="alarm-queue-list">
        {incidents.slice(0, compact ? 3 : incidents.length).map((incident, index) => {
          const tags = alarmTags(incident);
          const firstAlarm = incident.individual_alarms?.[0] || {};
          const alarmDescription = firstAlarm.description || firstAlarm.alarm_description || incident.candidate?.alarm_description || tags.join(' · ');
          const band = incident.urgency?.urgency_band || 'UNKNOWN';
          const sourceSeverity = firstAlarm.source_priority || firstAlarm.alarm_severity || incident.candidate?.source_priority || incident.candidate?.alarm_severity || 'Not supplied';
          const eventId = incident.event_id;
          const equipment = firstAlarm.equipment_id || incident.candidate?.equipment_id || incident.equipment_id || 'Equipment unavailable';
          const timestamp = firstAlarm.last_seen_timestamp || incident.candidate?.trigger_timestamp || incident.trigger_timestamp || incident.story?.steps?.[0]?.timestamp;
          const firstState = getAlarmLifecycleState(firstAlarm.lifecycle_state ? firstAlarm : { lifecycle_state: incident.lifecycle_state || incident.status });
          const alarmState = incident.status === 'RESOLVED' ? 'RESOLVED'
            : !isAlarmActive(firstAlarm.lifecycle_state ? firstAlarm : { lifecycle_state: firstState }) ? firstState.replaceAll('_', ' ')
              : isAlarmAcknowledged(firstAlarm) ? 'ACTIVE — ACKNOWLEDGED' : 'ACTIVE — UNACKNOWLEDGED';
          return (
            <button key={eventId} type="button" className={`alarm-queue-item alarm-queue-${BAND[band] === BAND.URGENT ? 'urgent' : BAND[band] === BAND.ELEVATED ? 'elevated' : 'routine'} ${selectedEventId === eventId ? 'selected' : ''}`} onClick={() => onSelect?.(eventId)} aria-label={`Select ${equipment}: ${alarmDescription}`}>
              <span className="alarm-queue-rank">{incident.ranking_position || index + 1}</span>
              <span className="alarm-queue-main">
                <span className="alarm-queue-title"><AlertTriangle size={15} /><strong>{equipment}</strong><span aria-hidden="true">—</span><span>{alarmDescription}</span></span>
                <span className="alarm-queue-tags"><Layers3 size={12} />{tags.join(', ')} · {String(alarmState).replaceAll('_', ' ')}</span>
              </span>
              <span className={`alarm-priority ${BAND[band] || BAND.UNKNOWN}`} title={`Source severity: ${sourceSeverity}`}>{sourceSeverity === 'Not supplied' ? band : sourceSeverity}</span>
              <span className="alarm-queue-equipment"><span>{band} priority</span><time>{displayTime(timestamp)}</time></span>
              <ArrowUpRight size={15} className="alarm-queue-open" />
            </button>
          );
        })}
      </div>}
      <details className="alarm-queue-help"><summary>About priority</summary><div className="alarm-queue-help-content"><p>Priority is a rule-based ordering aid. Its score is not a probability and does not replace the source alarm severity or establish physical cause.</p><p>The configured ranking uses deviation, rate of change, correlated deviations, repeat persistence and telemetry quality. Hard rules can raise urgency for source criticality, a trip-limit breach, critical time-to-limit or combined deviations.</p>{urgency ? <><p><strong>Selected group:</strong> {urgency.urgency_band || 'Unknown'}{urgency.urgency_score != null ? ` · score ${urgency.urgency_score}` : ''}{urgency.data_quality ? ` · data quality ${urgency.data_quality}` : ''}</p>{urgency.scoring_breakdown && Object.keys(urgency.scoring_breakdown).length > 0 && <dl>{Object.entries(urgency.scoring_breakdown).filter(([key]) => key !== 'weighted_score').map(([key, value]) => <div key={key}><dt>{({ D_deviation: 'Deviation', R_rate: 'Rate of change', E_evidence: 'Correlated deviations', P_persistence: 'Repeat persistence', Q_quality: 'Data quality' })[key] || key}</dt><dd>{value}</dd></div>)}</dl>}{urgency.urgency_reasons?.length ? <ul>{urgency.urgency_reasons.map((reason, index) => <li key={`${index}-${reason}`}>{reason}</li>)}</ul> : <p>No recorded priority rationale is available for this group.</p>}</> : <p>No recorded priority details are available yet.</p>}</div></details>
    </section>
  );
}
