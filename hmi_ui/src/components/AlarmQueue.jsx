import React from 'react';
import { AlertTriangle, ArrowUpRight, Layers3 } from 'lucide-react';

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
  const tags = [...new Set(alarms.map((item) => item.alarm_id || item.tag).filter(Boolean))];
  if (!tags.length) {
    const storyAlarm = [...(event.story?.steps || [])].reverse().find((step) => String(step.tag || '').startsWith('ALM-'));
    tags.push(storyAlarm?.tag || event.candidate?.alarm_id || event.candidate?.primary_tag || event.primary_tag || 'Alarm ID unavailable');
  }
  return tags;
}

export default function AlarmQueue({ incidents = [], selectedEventId, onSelect, loading = false, error = '', compact = false }) {
  const activeAlarmCount = incidents.reduce((sum, incident) => sum + alarmTags(incident).length, 0);
  return (
    <section className={`alarm-queue${compact ? ' alarm-queue-compact' : ''}`} aria-label="Prioritized active alarms">
      <div className="alarm-queue-heading">
        <div>
          <span className="alarm-queue-kicker">Active alarm queue</span>
          <h2>{activeAlarmCount} active alarm{activeAlarmCount === 1 ? '' : 's'}</h2>
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
          const timestamp = incident.candidate?.trigger_timestamp || incident.trigger_timestamp || incident.story?.steps?.[0]?.timestamp;
          return (
            <button key={eventId} type="button" className={`alarm-queue-item ${selectedEventId === eventId ? 'selected' : ''}`} onClick={() => onSelect?.(eventId)}>
              <span className="alarm-queue-rank">{incident.ranking_position || index + 1}</span>
              <span className="alarm-queue-main">
                <span className="alarm-queue-title"><AlertTriangle size={15} />{alarmDescription}</span>
                <span className="alarm-queue-tags"><Layers3 size={12} />{tags.join(', ')} · severity {sourceSeverity}</span>
              </span>
              <span className={`alarm-priority ${BAND[band] || BAND.UNKNOWN}`}>{band}</span>
              <span className="alarm-queue-equipment"><strong>{equipment}</strong><time>{displayTime(timestamp)}</time></span>
              <ArrowUpRight size={15} className="alarm-queue-open" />
            </button>
          );
        })}
      </div>}
      <details className="alarm-queue-help"><summary>About priority</summary><p>Priority helps order the alarm list. Source alarm severity remains unchanged.</p></details>
    </section>
  );
}
