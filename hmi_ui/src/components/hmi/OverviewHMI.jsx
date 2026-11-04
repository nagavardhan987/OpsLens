import React from 'react';
import { AlertTriangle, BookOpen, ChevronRight, FileWarning, GitCommitVertical, ListChecks, Loader2, Table2 } from 'lucide-react';
import TrendTile from './TrendTile';
import DiagnosisPanel from './DiagnosisPanel';
import { getAlarmLifecycleState, isAlarmAcknowledged, isAlarmActive, summarizeAlarmStates } from '../../lib/alarmState';
import { ALARM_LABELS } from '../../lib/plantTags.generated.js';

export function hhmmss(value) {
  const t = Date.parse(value || '');
  return Number.isFinite(t) ? new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '—';
}

function fmtVal(v) {
  if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE';
  if (typeof v !== 'number' || !Number.isFinite(v)) return v == null ? '—' : String(v);
  return Math.abs(v) >= 100 ? String(Math.round(v * 10) / 10) : String(Math.round(v * 100) / 100);
}

/** Severity class from the incident's priority / urgency band. */
export function severityOf(incident, brief) {
  if (brief?.escalation?.p1_reached) return { cls: 'p1', label: 'P1' };
  const s = String(brief?.scenario?.severity || '').toLowerCase();
  if (s === 'critical') return { cls: 'p1', label: 'CRITICAL' };
  if (s === 'high') return { cls: 'p2', label: 'HIGH' };
  if (s === 'medium') return { cls: 'p3', label: 'MEDIUM' };
  const band = incident?.urgency?.urgency_band;
  if (band === 'URGENT') return { cls: 'p1', label: 'URGENT' };
  if (band === 'ELEVATED') return { cls: 'p2', label: 'ELEVATED' };
  if (band === 'ROUTINE') return { cls: 'p4', label: 'ROUTINE' };
  return { cls: 'p4', label: '—' };
}

function alarmState(incident) {
  const a = incident?.individual_alarms?.[0] || {};
  if (incident?.status === 'RESOLVED') return 'RESOLVED';
  const st = getAlarmLifecycleState(a.lifecycle_state ? a : { lifecycle_state: incident?.lifecycle_state || incident?.status });
  if (!isAlarmActive({ lifecycle_state: st })) return st.replaceAll('_', ' ');
  return isAlarmAcknowledged(a) ? 'ACTIVE · ACK' : 'ACTIVE · UNACK';
}

export function AlarmBanner({ fullEvent, brief, incident }) {
  if (!fullEvent) {
    return <section className="ov-banner idle" aria-label="Selected alarm"><span>No alarm selected. Active alarms appear on the left as they are recorded.</span></section>;
  }
  const sev = severityOf(incident, brief);
  const problem = brief?.problem || {};
  const state = brief?.resolution?.state || alarmState(incident);
  return (
    <section className={`ov-banner ${sev.cls} ${/UNACK/.test(state) ? 'unack' : ''}`} aria-label="Selected alarm">
      <span className={`ov-sev ${sev.cls}`}>{sev.label}</span>
      <div className="ov-banner-main">
        <div className="ov-banner-title"><AlertTriangle size={15} /><strong>{problem.alarm_description || fullEvent.primary_tag}</strong><span className="mono">{problem.alarm_tag || fullEvent.primary_tag}</span><span>· {problem.equipment || '—'}</span>{brief?.scenario?.name && <span className="ov-banner-incident">“{brief.scenario.name}”</span>}</div>
        <div className="ov-banner-sub">{brief?.headline || 'Loading incident facts…'}</div>
      </div>
      <div className="ov-banner-meta">
        <span className={`ov-state ${/UNACK/.test(state) ? 'unack' : /ACK/.test(state) ? 'ack' : 'clear'}`}>{state}</span>
        <span className="mono">First {hhmmss(problem.first_triggered_at || fullEvent.trigger_timestamp)}</span>
        {brief?.escalation?.acknowledgement_deadline && <span className={brief.escalation.acknowledgement_deadline.overdue ? 'overdue' : ''}>Ack within {brief.escalation.acknowledgement_deadline.acknowledge_within}</span>}
      </div>
    </section>
  );
}

export function AlarmList({ incidents, selectedEventId, onSelect, loading }) {
  const open = incidents.filter((i) => i.is_open !== false && i.status !== 'RESOLVED');
  return (
    <section className="ov-panel ov-alarms" aria-label="Active alarms">
      <header className="ov-panel-head"><h2><AlertTriangle size={14} /> Active alarm groups</h2><span className="ov-count">{open.length}</span></header>
      <div className="ov-alarm-list">
        {loading && !incidents.length && <p className="ov-empty"><Loader2 size={13} className="spin" /> Loading…</p>}
        {!loading && !open.length && <p className="ov-empty">No active alarms.</p>}
        {open.map((inc) => {
          const primary = inc.primary_tag || inc.candidate?.primary_tag;
          const alarms = inc.individual_alarms || [];
          const a = alarms.find((x) => x.tag === primary) || alarms[0] || {};
          const counts = summarizeAlarmStates([inc]);
          const st = alarmState({ ...inc, individual_alarms: [a] });
          const band = inc.urgency?.urgency_band;
          const cls = band === 'URGENT' ? 'p1' : band === 'ELEVATED' ? 'p2' : 'p4';
          return (
            <button key={inc.event_id} type="button" data-event-id={inc.event_id} onClick={() => onSelect(inc.event_id)} aria-current={inc.event_id === selectedEventId ? 'true' : undefined}
              className={`ov-alarm-row ${cls} ${inc.event_id === selectedEventId ? 'selected' : ''} ${counts.unacknowledged ? 'unack' : ''}`}>
              <span className={`ov-alarm-bar ${cls}`} />
              <span className="ov-alarm-text">
                <strong>{ALARM_LABELS[primary] || a.description || primary}</strong>
                <small className="mono">{primary} · {a.equipment_id || inc.candidate?.equipment_id || ''}</small>
                <small>{counts.active} alarm input{counts.active === 1 ? '' : 's'} · {counts.unacknowledged} unack</small>
              </span>
              <span className="ov-alarm-meta"><span className={`ov-state sm ${/UNACK/.test(st) ? 'unack' : 'ack'}`}>{st.replace('ACTIVE · ', '')}</span><small className="mono">{hhmmss(inc.trigger_timestamp || a.last_seen_timestamp)}</small></span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function TrendsPanel({ trends, loading }) {
  const signals = trends?.signals || [];
  return (
    <section className="ov-panel ov-trends" aria-label="Key readings and trends">
      <header className="ov-panel-head"><h2>Readings &amp; trends</h2><span className="ov-sub">last {signals[0]?.points?.length ? '~6 min' : '—'}</span></header>
      <div className="ov-trend-grid">
        {loading && !signals.length && <p className="ov-empty"><Loader2 size={13} className="spin" /> Loading trends…</p>}
        {!loading && !signals.length && <p className="ov-empty">No recorded readings for this incident.</p>}
        {[...signals].sort((a, b) => Number(Boolean(b.beyond_limit)) - Number(Boolean(a.beyond_limit))).map((s) => <TrendTile key={s.tag} signal={s} />)}
      </div>
    </section>
  );
}

export function StoryPanel({ story, onOpen }) {
  const steps = story?.steps || [];
  return (
    <section className="ov-panel ov-story" aria-label="What changed">
      <header className="ov-panel-head"><h2><GitCommitVertical size={14} /> What changed · Event Story</h2><button type="button" className="ov-link" onClick={onOpen}>Full story <ChevronRight size={12} /></button></header>
      <ol className="ov-story-list">
        {!steps.length && <li className="ov-empty">No recorded sequence yet.</li>}
        {steps.map((s, i) => {
          const isAlarm = String(s.tag || '').startsWith('ALM-') || /FAULT|TRIP|FAIL/.test(s.tag || '');
          const label = String(s.description || s.tag).replace(/\s*\([A-Z0-9-]+\)\s*(reading recorded|annunciated)?.*$/, '').replace(/ reading recorded$/, '');
          return (
            <li key={`${s.tag}-${i}`} className={isAlarm && s.value_after === true ? 'alarm' : ''}>
              <span className="mono ov-story-time">{hhmmss(s.timestamp)}</span>
              <span className="ov-story-dot" />
              <span className="ov-story-text"><strong>{label}</strong> <span className="mono">{s.tag}</span></span>
              <span className="mono ov-story-change">{typeof s.value_after === 'boolean' ? (s.value_after ? 'ALARM' : 'normal') : `${fmtVal(s.value_before)} → ${fmtVal(s.value_after)} ${s.unit || ''}`}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function EvidencePanel({ brief, onOpen }) {
  const checks = brief?.supporting_evidence?.limit_checks || [];
  const rows = [...checks].sort((a, b) => Number(Boolean(b.exceeded_limits?.length)) - Number(Boolean(a.exceeded_limits?.length)));
  return (
    <section className="ov-panel ov-evidence" aria-label="Evidence against SOP limits">
      <header className="ov-panel-head"><h2><Table2 size={14} /> Evidence · readings vs SOP limits</h2><button type="button" className="ov-link" onClick={onOpen}>Evidence Engine <ChevronRight size={12} /></button></header>
      <div className="ov-table-wrap">
        <table className="ov-table">
          <thead><tr><th>Tag</th><th>Parameter</th><th className="r">Value</th><th>Normal</th><th>Limit reached</th></tr></thead>
          <tbody>
            {!rows.length && <tr><td colSpan={5} className="ov-empty">{brief ? 'No SOP limits apply to the recorded readings.' : 'Loading…'}</td></tr>}
            {rows.map((c) => {
              const hit = c.highest_exceeded;
              return (
                <tr key={c.tag} className={hit ? 'hit' : ''}>
                  <td className="mono">{c.tag}</td>
                  <td>{c.parameter}</td>
                  <td className="r mono"><b>{fmtVal(c.value)}</b> {c.unit}</td>
                  <td>{c.normal_text || '—'}</td>
                  <td>{hit ? <span title={`${hit.source_text || ''} (SOP p.${hit.source_page})`}><span className="ov-chip sm red">{hit.name}</span> {hit.action || ''}</span> : c.next_limit ? <span className="muted">{c.next_limit.margin_text}</span> : <span className="muted">within limits</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="ov-foot-note">Ranking scores are evidence weights, not probabilities. Values are recorded, not inferred.</p>
    </section>
  );
}

export function SopPanel({ brief, onOpenSop }) {
  const sop = brief?.sop;
  const steps = brief?.safe_inspection_steps?.steps || [];
  const gaps = (sop?.coverage_notes || []).filter((n) => /^gap/i.test(n));
  return (
    <section className="ov-panel ov-sop" aria-label="Procedure and guidance">
      <header className="ov-panel-head">
        <h2><BookOpen size={14} /> What to check · SOP</h2>
        <button type="button" className="ov-link" disabled={!sop?.sop_id} onClick={onOpenSop}>Open SOP <ChevronRight size={12} /></button>
      </header>
      {!brief && <p className="ov-empty">Select an alarm.</p>}
      {brief && !sop?.sop_id && <p className="ov-empty">No process-specific SOP matches this incident. Use the AI diagnosis as evidence-based guidance only and confirm with the shift supervisor.</p>}
      {sop?.sop_id && (
        <>
          <div className="ov-sop-id">
            <strong>{sop.sop_id}</strong><span>{sop.title}</span>
          </div>
          <div className="ov-sop-badges">
            <span className="ov-chip amber">DRAFT — NOT APPROVED</span>
            <span className={`ov-chip ${sop.coverage === 'full' ? 'green' : 'red'}`}>COVERAGE: {String(sop.coverage || 'unknown').toUpperCase()}</span>
            <span className="ov-sub">SOP-MAN-000 p.{(sop.source_pages || []).join(', ')}</span>
          </div>
          {gaps.map((g) => <p key={g} className="ov-gap" title={g}><FileWarning size={12} /> <span>{g.replace(/^Gap:\s*/i, '')}</span></p>)}
          <ol className="ov-steps">
            {steps.map((s) => <li key={s.number}><span className="ov-step-n">{s.number}</span><span>{s.text} <small className="muted">p.{s.page}</small></span></li>)}
          </ol>
          <p className="ov-foot-note"><ListChecks size={11} /> Steps copied verbatim from the draft SOP. OpsLens does not operate equipment.</p>
        </>
      )}
    </section>
  );
}

export default function OverviewHMI({
  fullEvent, brief, trends, trendsLoading, incidents, selectedEventId, onSelect, loading,
  onOpenStory, onOpenEvidence, onOpenSop, diagnosisKey,
}) {
  return (
    <div className="ov-grid">
      <div className="ov-col ov-col-a">
        <AlarmList incidents={incidents} selectedEventId={selectedEventId} onSelect={onSelect} loading={loading} />
        <TrendsPanel trends={trends} loading={trendsLoading} />
      </div>
      <div className="ov-col ov-col-b">
        <StoryPanel story={fullEvent?.story} onOpen={onOpenStory} />
        <EvidencePanel brief={brief} onOpen={onOpenEvidence} />
      </div>
      <div className="ov-col ov-col-c">
        <DiagnosisPanel eventId={fullEvent?.event_id} refreshKey={diagnosisKey} />
        <SopPanel brief={brief} onOpenSop={onOpenSop} />
      </div>
    </div>
  );
}
