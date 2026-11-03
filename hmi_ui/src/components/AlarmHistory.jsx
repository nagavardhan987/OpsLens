import React, { useMemo, useState } from 'react';
import { AlertTriangle, ChevronDown, Clock3, ExternalLink, Search } from 'lucide-react';

const STATUS_OPTIONS = [
  ['All alarms', 'all'], ['Active', 'ACTIVE'], ['Unacknowledged', 'UNACKNOWLEDGED'],
  ['Acknowledged', 'ACKNOWLEDGED'], ['Returned to normal', 'RETURNED_TO_NORMAL'],
  ['Resolved', 'RESOLVED'], ['Unresolved', 'UNRESOLVED'],
];
const STATUS_LABEL = { ACTIVE: 'Active', ACKNOWLEDGED: 'Acknowledged', RETURNED_TO_NORMAL: 'Returned to normal', RESOLVED: 'Resolved', UNRESOLVED: 'Unresolved' };

function showTime(value) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Not recorded';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' }).format(new Date(value));
}

function Filter({ label, value, onChange, type = 'text', placeholder = '' }) {
  return <label className="alarm-history-filter"><span>{label}</span><input type={type} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

export default function AlarmHistory({ events = [], alarms = events, loading = false, error = '', onSelectEvent }) {
  const [status, setStatus] = useState('all');
  const [filters, setFilters] = useState({ q: '', start: '', end: '', alarm_id: '', equipment: '', process_area: '', severity: '', priority: '', operator: '', incident_id: '' });
  const [filtersOpen, setFiltersOpen] = useState(false);
  const set = (key) => (value) => setFilters((current) => ({ ...current, [key]: value }));
  const filtered = useMemo(() => alarms.filter((alarm) => {
    const isOpen = ['ACTIVE', 'ACKNOWLEDGED', 'UNRESOLVED'].includes(alarm.status);
    if (status === 'UNACKNOWLEDGED' ? Boolean(alarm.acknowledged_at) || !isOpen : status === 'ACTIVE' ? !isOpen : status !== 'all' && alarm.status !== status) return false;
    const search = Object.values(alarm).map((value) => typeof value === 'string' ? value : '').join(' ').toLowerCase();
    if (filters.q && !search.includes(filters.q.toLowerCase())) return false;
    const fields = [['alarm_id', alarm.alarm_id], ['equipment', alarm.equipment], ['process_area', alarm.process_area], ['severity', alarm.severity], ['priority', alarm.priority], ['incident_id', alarm.incident_id]];
    if (fields.some(([key, value]) => filters[key] && !String(value || '').toLowerCase().includes(filters[key].toLowerCase()))) return false;
    if (filters.operator && !(alarm.operator_actions || []).some((action) => String(action.operator || '').toLowerCase().includes(filters.operator.toLowerCase()))) return false;
    const time = Date.parse(alarm.first_triggered_at || '');
    if (filters.start && Number.isFinite(time) && time < Date.parse(filters.start)) return false;
    if (filters.end && Number.isFinite(time) && time > Date.parse(filters.end)) return false;
    return true;
  }), [alarms, filters, status]);

  return (
    <section className="alarm-history-panel" aria-label="Alarm history">
      <header className="alarm-history-header">
        <div><span className="operator-eyebrow">Persistent records</span><h2>Alarm history</h2><p>Alarm occurrences remain separate from linked incidents. Acknowledgement does not resolve an incident.</p></div>
        <strong>{loading ? 'Loading…' : `${filtered.length} of ${alarms.length} alarms`}</strong>
      </header>
      {error && <p className="alarm-history-error" role="alert">{error}</p>}
      <div className="alarm-history-tabs" role="tablist" aria-label="Filter alarm status">
        {STATUS_OPTIONS.map(([label, value]) => <button key={value} type="button" role="tab" aria-selected={status === value} className={status === value ? 'selected' : ''} onClick={() => setStatus(value)}>{label}</button>)}
      </div>
      <div className="alarm-history-search"><Search size={15} /><input aria-label="Search alarm history" value={filters.q} onChange={(event) => set('q')(event.target.value)} placeholder="Search alarm, equipment, operator, incident…" /><button type="button" onClick={() => setFiltersOpen((value) => !value)} aria-expanded={filtersOpen}><ChevronDown size={14} />Filters</button></div>
      {filtersOpen && <div className="alarm-history-filters">
        <Filter label="From" type="datetime-local" value={filters.start} onChange={set('start')} /><Filter label="To" type="datetime-local" value={filters.end} onChange={set('end')} />
        <Filter label="Alarm ID" value={filters.alarm_id} onChange={set('alarm_id')} /><Filter label="Equipment" value={filters.equipment} onChange={set('equipment')} />
        <Filter label="Process area" value={filters.process_area} onChange={set('process_area')} /><Filter label="Severity" value={filters.severity} onChange={set('severity')} />
        <Filter label="Priority" value={filters.priority} onChange={set('priority')} /><Filter label="Operator" value={filters.operator} onChange={set('operator')} />
        <Filter label="Incident ID" value={filters.incident_id} onChange={set('incident_id')} />
      </div>}
      {loading && !alarms.length && <p className="alarm-history-empty">Loading stored alarm records…</p>}
      {!loading && !error && filtered.length === 0 && <div className="alarm-history-empty"><Clock3 size={18} /><p>No alarm records match these filters.</p></div>}
      <div className="alarm-history-list">{filtered.map((alarm) => (
        <details key={alarm.alarm_record_id || `${alarm.incident_id}-${alarm.alarm_id}`} className="alarm-history-record">
          <summary>
            <AlertTriangle size={16} aria-hidden="true" />
            <span className="alarm-history-primary"><strong>{alarm.alarm_id || 'Alarm ID unavailable'}</strong><small>{alarm.alarm_description || 'Description not recorded'}</small></span>
            <span className={`alarm-history-status status-${String(alarm.status || 'ACTIVE').toLowerCase()}`}>{STATUS_LABEL[alarm.status] || alarm.status || 'Status unavailable'}</span>
            <span className="alarm-history-count">×{alarm.repeat_count || 1}</span>
            <span className="alarm-history-meta">{alarm.equipment || 'Equipment unavailable'}<time>{showTime(alarm.latest_triggered_at)}</time></span>
          </summary>
          <div className="alarm-history-detail">
            <dl><div><dt>Process area</dt><dd>{alarm.process_area || 'Not recorded'}</dd></div><div><dt>Severity</dt><dd>{alarm.severity || 'Not recorded'}</dd></div><div><dt>Priority</dt><dd>{alarm.priority || 'Not recorded'}</dd></div><div><dt>First triggered</dt><dd>{showTime(alarm.first_triggered_at)}</dd></div><div><dt>Latest triggered</dt><dd>{showTime(alarm.latest_triggered_at)}</dd></div><div><dt>Acknowledged</dt><dd>{alarm.acknowledged_at ? `${showTime(alarm.acknowledged_at)} · ${alarm.acknowledged_by || 'Operator not recorded'}` : 'Not acknowledged'}</dd></div><div><dt>Returned to normal</dt><dd>{showTime(alarm.returned_to_normal_at)}</dd></div><div><dt>Resolved</dt><dd>{alarm.resolved_at ? `${showTime(alarm.resolved_at)} · ${alarm.resolved_by || 'Operator not recorded'}` : 'Not resolved'}</dd></div><div><dt>Data source / quality</dt><dd>{alarm.data_source || 'unknown'} / {alarm.data_quality || 'UNKNOWN'}</dd></div></dl>
            {alarm.occurrences_not_individually_retained > 0 && <p className="alarm-history-limitation">{alarm.occurrences_not_individually_retained} earlier repeat(s) were stored only as an aggregate; their individual timestamps were not present in the existing database.</p>}
            <section><h3>Individual occurrences ({(alarm.occurrences || []).length})</h3>{alarm.occurrences?.length ? <ol>{alarm.occurrences.map((occurrence, index) => <li key={occurrence.occurrence_id || `${occurrence.occurred_at}-${index}`}><time>{showTime(occurrence.occurred_at)}</time><span>Recorded value: {occurrence.value ?? 'Not recorded'}</span><span>{occurrence.data_source || 'unknown'} · {occurrence.data_quality || 'UNKNOWN'}</span></li>)}</ol> : <p>No individually timestamped occurrence records available.</p>}</section>
            <section><h3>Linked records</h3><p>Incident: <code>{alarm.incident_id || 'Not linked'}</code></p>{alarm.related_alarms?.length > 0 && <p>Related alarms: {alarm.related_alarms.join(', ')}</p>}{onSelectEvent && alarm.incident_id && <button type="button" className="operator-text-button" onClick={() => onSelectEvent(alarm.incident_id)}>Open linked incident <ExternalLink size={13} /></button>}</section>
            <section><h3>Operator notes and actions</h3>{alarm.operator_actions?.length ? <ul>{alarm.operator_actions.map((action) => <li key={action.action_id}><time>{showTime(action.timestamp)}</time> · {action.operator || 'Operator not recorded'} · {action.action_type}{action.notes ? ` — ${action.notes}` : ''}</li>)}</ul> : <p>No operator actions recorded.</p>}</section>
            <section><h3>Alarm transitions</h3>{alarm.transitions?.length ? <ul>{alarm.transitions.map((transition) => <li key={transition.transition_id}><time>{showTime(transition.timestamp)}</time> · {transition.state} · {transition.operator || 'Operator not recorded'}{transition.notes ? ` — ${transition.notes}` : ''}</li>)}</ul> : <p>No separate alarm transition records available.</p>}</section>
          </div>
        </details>
      ))}</div>
    </section>
  );
}
