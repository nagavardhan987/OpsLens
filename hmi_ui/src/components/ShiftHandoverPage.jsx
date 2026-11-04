import React, { useEffect, useState } from 'react';
import { Check, Clock3, FileText, History, MessageSquare, RefreshCw } from 'lucide-react';
import { confirmHandover, getHandoverHistory, getHandoverRecord, respondToHandoverItem, submitHandover } from '../api/client';

const FIELD_CONFIG = [
  ['outgoing_confirmation', 'Outgoing operator confirms review'],
  ['shift_notes', 'Additional shift observations'],
  ['equipment_observations', 'Equipment observations not captured by sensors'],
  ['maintenance_updates', 'Maintenance updates not in OpsLens'],
  ['important_context', 'Important context or pending communication'],
];

function RecordList({ items, onOpen }) {
  if (!items?.length) return <p className="handover-muted">None recorded.</p>;
  return <ul className="handover-record-list">{items.map((item, index) => {
    const label = item.alarm_id || item.incident_id || item.action_type || item.tag || 'Stored record';
    return <li key={item.alarm_record_id || item.incident_id || item.action_id || item.tag || index}>
      <span><strong>{label}</strong>{item.equipment ? ` · ${item.equipment}` : ''}{item.status ? ` · ${item.status}` : ''}{item.timestamp ? ` · ${new Date(item.timestamp).toLocaleString()}` : ''}{item.operator ? ` · ${item.operator}` : ''}{item.notes ? ` — ${item.notes}` : ''}</span>
      {(item.incident_id || item.alarm_record_id) && onOpen && <button type="button" onClick={() => onOpen(item.incident_id || item.alarm_record_id)}>{item.incident_id ? 'Open incident' : 'Alarm record'}</button>}
    </li>;
  })}</ul>;
}

export default function ShiftHandoverPage({ summary, onSelectIncident, onOpenAlarmHistory, onRefresh }) {
  const [fields, setFields] = useState(Object.fromEntries(FIELD_CONFIG.map(([key]) => [key, ''])));
  const [outgoing, setOutgoing] = useState('');
  const [incoming, setIncoming] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [history, setHistory] = useState([]);
  const [historyError, setHistoryError] = useState('');
  const [active, setActive] = useState(null);
  const [historyFilters, setHistoryFilters] = useState({ date: '', shift: '', operator: '', equipment: '', incident: '' });
  const [responseDrafts, setResponseDrafts] = useState({});
  const [incomingName, setIncomingName] = useState('');
  const [signature, setSignature] = useState('');
  const [faceToFaceConfirmed, setFaceToFaceConfirmed] = useState(false);
  const [walkthroughConfirmed, setWalkthroughConfirmed] = useState(false);
  const [busyItem, setBusyItem] = useState('');

  const loadHistory = async (filters = historyFilters) => {
    setHistoryError('');
    try { setHistory(await getHandoverHistory(filters)); }
    catch (err) { setHistoryError(err.message || 'Saved handover history could not be loaded.'); }
  };
  useEffect(() => { loadHistory({}); onRefresh?.(); }, []);
  const openRecord = async (id) => {
    try { const record = await getHandoverRecord(id); setActive(record); setIncomingName(''); setSignature(''); setFaceToFaceConfirmed(false); setWalkthroughConfirmed(false); }
    catch (err) { setError(err.message || 'The selected handover could not be opened.'); }
  };
  const create = async () => {
    if (!summary?.current_shift?.configured) { setError('Shift timing is not configured. Configure OPSLENS_SHIFT_START and OPSLENS_SHIFT_END before submitting.'); return; }
    if (!outgoing.trim()) { setError('Enter the outgoing operator identity before submitting.'); return; }
    if (!fields.outgoing_confirmation.trim()) { setError('Confirm that you reviewed the generated shift handover.'); return; }
    setSubmitting(true); setError(''); setSuccess('');
    try {
      const result = await submitHandover({ shift_date: summary.current_shift.date, shift_name: summary.current_shift.name, shift_start: summary.current_shift.start, shift_end: summary.current_shift.end, outgoing_operator: outgoing.trim(), incoming_operator: incoming.trim() || null, fields });
      setSuccess('Handover submitted and saved. Alarm and incident states were not changed.');
      await Promise.all([loadHistory({}), openRecord(result.handover_id), onRefresh?.()]);
    } catch (err) { setError(err.message || 'Handover could not be saved. Check the service and configured shift details.'); }
    finally { setSubmitting(false); }
  };
  const answerItem = async (entry, acknowledged = true) => {
    if (!active || !incomingName.trim()) { setError('Enter your operator name before responding to a handover item.'); return; }
    setBusyItem(entry.item_id); setError('');
    try {
      await respondToHandoverItem(active.handover_id, entry.item_id, { operator: incomingName.trim(), comment: responseDrafts[entry.item_id] || null, acknowledged });
      await openRecord(active.handover_id);
    } catch (err) { setError(err.message || 'The handover item response could not be saved.'); }
    finally { setBusyItem(''); }
  };
  const accept = async () => {
    if (!active || !incomingName.trim() || !signature.trim() || !faceToFaceConfirmed || !walkthroughConfirmed) { setError('Enter the incoming operator and signature, and confirm the face-to-face handover and walk-through.'); return; }
    setError('');
    try { const updated = await confirmHandover(active.handover_id, { incoming_operator: incomingName.trim(), signature_name: signature.trim(), face_to_face_confirmed: faceToFaceConfirmed, walkthrough_confirmed: walkthroughConfirmed }); setActive(updated); setSuccess('Receipt confirmed and signature recorded. Alarm and incident states remain unchanged.'); await loadHistory({}); }
    catch (err) { setError(err.message || 'Handover receipt could not be confirmed.'); }
  };

  const shift = summary?.current_shift;
  const unavailable = ['equipment_out_of_service', 'active_permits', 'loto_status', 'process_changes', 'pending_maintenance', 'pending_laboratory_results', 'chemical_and_polymer_stock', 'outstanding_operator_actions']
    .filter((key) => summary?.[key]?.status === 'Unavailable');
  const allImportant = [...(summary?.open_alarms || []), ...(summary?.unresolved_incidents || [])];

  return <div className="handover-page-layout">
    <div className="handover-page-main">
      <header className="handover-page-heading"><div><span className="operator-eyebrow"><Clock3 size={14} /> Automatically generated shift record</span><h1>Shift Handover</h1>
        <p>{shift?.configured ? `${shift.name} · ${shift.date} · ${new Date(shift.start).toLocaleString()} to ${new Date(shift.end).toLocaleString()}` : 'Shift timing not configured'}</p>
        <small>Generated from OpsLens records · Last data refresh: {summary?.last_data_refresh ? new Date(summary.last_data_refresh).toLocaleString() : 'Not recorded'}</small>
      </div><button type="button" onClick={onRefresh} className="handover-refresh"><RefreshCw size={15} /> Refresh records</button></header>

      <section className="handover-narrative-panel"><div className="handover-section-heading"><div><span className="operator-eyebrow">{summary?.shift_narrative?.source || 'Deterministic record summary'}</span><h2>Shift summary</h2></div><span className="handover-source-badge">{summary?.shift_narrative?.status === 'fallback' ? 'Fallback summary' : 'Record grounded'}</span></div>
        <p>{summary?.shift_narrative?.text || 'A shift summary is not available yet. Refresh the page to retrieve stored records.'}</p>
        {summary?.shift_narrative?.notice && <small role="status">{summary.shift_narrative.notice}</small>}
      </section>

      <section className="handover-important-panel"><header><div><span className="operator-eyebrow">Review first</span><h2>Important items requiring handover</h2></div><strong>{allImportant.length}</strong></header>
        <h3>Open alarms</h3><RecordList items={summary?.open_alarms} onOpen={onOpenAlarmHistory} />
        <h3>Unacknowledged alarms</h3><RecordList items={summary?.unacknowledged_alarms} onOpen={onOpenAlarmHistory} />
        <h3>Acknowledged during shift</h3><RecordList items={summary?.alarms_acknowledged_in_shift} />
        <h3>Resolved during shift</h3><RecordList items={summary?.alarms_resolved_in_shift} />
        <h3>Unresolved incidents</h3><RecordList items={summary?.unresolved_incidents} onOpen={onSelectIncident} />
        <h3>Operator actions recorded this shift</h3><RecordList items={summary?.actions_in_shift} />
      </section>

      <details className="handover-source-details"><summary>AI or deterministic narrative and source records</summary>
        <h3>Latest sensor readings</h3><p className="handover-data-status">{summary?.latest_sensor_readings?.status || 'Unavailable'} · Source labels distinguish live PLC from simulated readings.</p>
        <RecordList items={(summary?.latest_sensor_readings?.items || []).map((item) => ({ ...item, action_type: `${item.value ?? 'Not recorded'} ${item.unit || ''} · ${item.record_type || 'recorded'} · ${item.data_quality || 'quality not recorded'}` }))} />
        <h3>Recorded abnormal evidence</h3><p>Evidence associations are possible contributors, not confirmed physical causes.</p><RecordList items={summary?.abnormal_sensor_readings?.items} />
        <h3>Event stories in shift</h3>{(summary?.event_story_records || []).map((story) => <section key={story.event_id}><strong>{story.causal_label || story.event_id}</strong><p>{(story.steps || []).map((step) => `${step.timestamp || 'Timestamp not recorded'} · ${step.tag || 'Tag not recorded'} · ${step.description || step.value || 'Details not recorded'}`).join(' → ') || 'No story steps recorded.'}</p>{onSelectIncident && <button type="button" onClick={() => onSelectIncident(story.event_id)}>Open incident</button>}</section>)}
        {summary?.event_story_records?.length === 0 && <p className="handover-muted">No event stories were recorded in this shift window.</p>}
        <p>{summary?.events_in_shift?.length ?? 'Unavailable'} event stories · {summary?.actions_in_shift?.length ?? 'Unavailable'} operator actions</p>
        {unavailable.length > 0 && <div className="handover-unavailable"><strong>Additional information not recorded</strong><p>{unavailable.map((key) => key.replaceAll('_', ' ')).join(' · ')}</p></div>}
      </details>

      <section className="handover-sop-notice"><strong>{summary?.sop_reference?.sop_id || 'SOP-GEN-003'} · {summary?.sop_reference?.title || 'Alarm Response and Shift Handover'}</strong><span>{summary?.sop_reference?.approval_status || 'Draft for review — not approved'} · Reference only</span><p>{summary?.sop_reference?.document_status || 'Approval status has not been verified.'}</p><ol>{(summary?.sop_reference?.requirements || []).map((item) => <li key={item}>{item}</li>)}</ol></section>

      <section className="handover-outgoing-form"><div className="handover-form-heading"><FileText size={17} /><div><h2>Operator review and confirmation</h2><p>Review the generated records, then add only context that OpsLens cannot collect.</p></div></div>
        <div className="handover-operator-fields"><label>Outgoing operator<input aria-label="Outgoing operator" placeholder={summary?.outgoing_operator_session?.status === 'available' ? summary.outgoing_operator_session.operator : 'Not recorded — enter identity'} value={outgoing} onChange={(event) => setOutgoing(event.target.value)} maxLength={120} /></label><label>Incoming operator (if known)<input placeholder="Not recorded" value={incoming} onChange={(event) => setIncoming(event.target.value)} maxLength={120} /></label></div>
        <div className="handover-fields-grid">{FIELD_CONFIG.map(([key, label]) => <label key={key}>{label}{key === 'outgoing_confirmation' ? <input type="checkbox" checked={fields[key] === 'Confirmed'} onChange={(event) => setFields((current) => ({ ...current, [key]: event.target.checked ? 'Confirmed' : '' }))} /> : <textarea rows={2} maxLength={3000} placeholder="Not recorded" value={fields[key]} onChange={(event) => setFields((current) => ({ ...current, [key]: event.target.value }))} />}</label>)}</div>
        {(error || success) && <p role={error ? 'alert' : 'status'} className={error ? 'operator-action-error' : 'operator-action-success'}>{error || success}</p>}
        <button type="button" className="handover-submit-button" disabled={submitting || !shift?.configured} onClick={create}>{submitting ? 'Submitting…' : 'Submit shift handover'}</button>
      </section>

      <section className="handover-history-panel"><header><History size={17} /><h2>Previous handovers</h2></header><div className="handover-history-filters"><input aria-label="Filter handovers by date" type="date" value={historyFilters.date} onChange={(event) => setHistoryFilters((current) => ({ ...current, date: event.target.value }))} /><input aria-label="Filter handovers by shift" placeholder="Shift" value={historyFilters.shift} onChange={(event) => setHistoryFilters((current) => ({ ...current, shift: event.target.value }))} /><input aria-label="Filter handovers by operator" placeholder="Operator" value={historyFilters.operator} onChange={(event) => setHistoryFilters((current) => ({ ...current, operator: event.target.value }))} /><input aria-label="Equipment" placeholder="Equipment" value={historyFilters.equipment} onChange={(event) => setHistoryFilters((current) => ({ ...current, equipment: event.target.value }))} /><input aria-label="Incident" placeholder="Incident ID" value={historyFilters.incident} onChange={(event) => setHistoryFilters((current) => ({ ...current, incident: event.target.value }))} /><button type="button" onClick={() => loadHistory()}>Filter</button></div>
        {historyError ? <p role="alert" className="operator-action-error">{historyError}</p> : history.length ? history.map((row) => <button type="button" className="handover-history-row" key={row.handover_id} onClick={() => openRecord(row.handover_id)}><span><strong>{row.shift_name} · {row.shift_date}</strong><small>{row.outgoing_operator} → {row.incoming_operator || 'Awaiting incoming operator'}</small></span><span>{row.status} · {new Date(row.submitted_at).toLocaleString()}</span></button>) : <p className="handover-history-empty">No previous handovers have been submitted.</p>}</section>
    </div>
    {active && <aside className="handover-incoming-panel"><header><div><span className="operator-eyebrow">Incoming shift review</span><h2>{active.shift_name} · {active.shift_date}</h2></div><button type="button" onClick={() => setActive(null)}>Close</button></header><p>Submitted by {active.outgoing_operator} at {new Date(active.submitted_at).toLocaleString()}. Review the stored summary and respond to items. This does not acknowledge alarms or resolve incidents.</p>
      <section className="handover-incoming-item"><strong>Original generated summary</strong><p>{active.summary?.shift_narrative?.text || 'Not recorded'}</p><small>{active.summary?.shift_narrative?.source || 'Source not recorded'} · Data refreshed {active.summary?.last_data_refresh || 'Not recorded'}</small></section>
      {(active.entries || []).map((entry) => { const responses = (active.item_responses || []).filter((item) => item.item_id === entry.item_id); const acknowledgement = responses.find((item) => item.acknowledged); return <section key={entry.item_id} className="handover-incoming-item"><strong>{entry.category.replaceAll('_', ' ')}</strong><p>{entry.item ? (entry.item.alarm_id || entry.item.incident_id || entry.item.action_type || JSON.stringify(entry.item)) : entry.value}</p>{entry.item?.incident_id && onSelectIncident && <button type="button" className="operator-text-button" onClick={() => onSelectIncident(entry.item.incident_id)}>Open incident</button>}{entry.item?.alarm_record_id && onOpenAlarmHistory && <button type="button" className="operator-text-button" onClick={onOpenAlarmHistory}>Open alarm history</button>}{acknowledgement && <small>Acknowledged by {acknowledgement.operator} at {new Date(acknowledgement.timestamp).toLocaleString()}</small>}{responses.filter((item) => item.comment).map((item) => <small key={item.response_id}>Comment from {item.operator}: {item.comment}</small>)}{!acknowledgement && <><textarea aria-label={`Comment on ${entry.item_id}`} placeholder="Question or comment" value={responseDrafts[entry.item_id] || ''} onChange={(event) => setResponseDrafts((current) => ({ ...current, [entry.item_id]: event.target.value }))} /><button type="button" disabled={busyItem === entry.item_id || !responseDrafts[entry.item_id]?.trim()} onClick={() => answerItem(entry, false)}><MessageSquare size={13} /> Add comment / question</button><button type="button" disabled={busyItem === entry.item_id} onClick={() => answerItem(entry, true)}><MessageSquare size={13} /> Acknowledge handover item</button></>}</section>; })}
      <label className="handover-confirm-check"><input type="checkbox" checked={faceToFaceConfirmed} onChange={(event) => setFaceToFaceConfirmed(event.target.checked)} /> Face-to-face handover held at control panel for at least 15 minutes.</label><label className="handover-confirm-check"><input type="checkbox" checked={walkthroughConfirmed} onChange={(event) => setWalkthroughConfirmed(event.target.checked)} /> I reviewed the log and completed the incoming walk-through.</label><label>Incoming operator<input value={incomingName} onChange={(event) => setIncomingName(event.target.value)} maxLength={120} /></label><label>Acceptance signature (type full name)<input value={signature} onChange={(event) => setSignature(event.target.value)} maxLength={120} /></label><button type="button" className="handover-submit-button" disabled={active.status === 'RECEIVED'} onClick={accept}><Check size={15} /> {active.status === 'RECEIVED' ? `Received by ${active.received_by}` : 'Confirm receipt and sign'}</button>
      {(error || success) && <p role={error ? 'alert' : 'status'} className={error ? 'operator-action-error' : 'operator-action-success'}>{error || success}</p>}
    </aside>}
  </div>;
}
