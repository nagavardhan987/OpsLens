import React, { useEffect, useState } from 'react';
import { getOperatorBrief } from '../api/client';

/**
 * Deterministic eight-part operator brief. Every value comes from the backend
 * record or a Python calculation; the brief never depends on an LLM.
 * Labels distinguish OBSERVED readings, CALCULATED values and HYPOTHESES.
 */
const STATE_CLASS = {
  'ACTIVE / UNACKNOWLEDGED': 'danger',
  'ACTIVE / ACKNOWLEDGED — acknowledgement does not clear the alarm': 'warn',
};

function Kind({ kind }) {
  return <span className={`brief-kind ${String(kind || '').toLowerCase()}`}>{kind}</span>;
}

function LimitBar({ check }) {
  if (!check?.applied) return null;
  const limits = (check.comparisons || []).filter((row) => row.direction === 'high');
  if (!limits.length) return null;
  const max = Math.max(check.value, ...limits.map((row) => row.limit)) * 1.08;
  const pct = (value) => `${Math.max(0, Math.min(100, (value / max) * 100))}%`;
  return (
    <div className="brief-limitbar" aria-hidden="true">
      <div className="brief-limitbar-fill" style={{ width: pct(check.value) }} />
      {limits.map((row) => <span key={row.name} className={`brief-limitbar-mark ${row.exceeded ? 'hit' : ''}`} style={{ left: pct(row.limit) }} title={`${row.name} ${row.limit}`} />)}
    </div>
  );
}

export default function OperatorBrief({ eventId, refreshKey }) {
  const [brief, setBrief] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!eventId) { setBrief(null); return undefined; }
    let active = true;
    setLoading(true);
    getOperatorBrief(eventId)
      .then((data) => { if (active) { setBrief(data); setError(''); } })
      .catch(() => { if (active) setError('Operator brief is temporarily unavailable. The recorded event story below is unaffected.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [eventId, refreshKey]);

  if (!eventId) return null;
  if (error) return <section className="operator-panel operator-brief"><p role="status" className="brief-muted">{error}</p></section>;
  if (!brief) return <section className="operator-panel operator-brief"><p className="brief-muted">{loading ? 'Building operator brief…' : 'No brief available.'}</p></section>;

  const limitChecks = (brief.supporting_evidence?.limit_checks || []).filter((c) => c.applied);
  const deadline = brief.escalation?.acknowledgement_deadline;
  const steps = brief.safe_inspection_steps?.steps || [];

  return (
    <section className="operator-panel operator-brief" aria-labelledby="operator-brief-heading">
      <div className="operator-section-heading">
        <div>
          <span className="operator-eyebrow">Operator brief · deterministic · no AI required</span>
          <h2 id="operator-brief-heading">{brief.headline}</h2>
        </div>
        <span className={`brief-state ${STATE_CLASS[brief.resolution?.state] || 'neutral'}`}>{brief.resolution?.state}</span>
      </div>

      {brief.escalation?.p1_reached && <p role="alert" className="brief-p1">P1 escalation threshold reached: {brief.escalation.p1_details?.[0]?.source_text} (SOP-MAN-000 p.{brief.escalation.p1_details?.[0]?.source_page})</p>}
      {!brief.escalation?.p1_reached && brief.escalation?.p1_conditional?.length ? <p role="alert" className="brief-p1 conditional">Conditional P1 — verify on site: {brief.escalation.p1_conditional[0].condition}</p> : null}
      {deadline && <p className={`brief-deadline ${deadline.overdue ? 'overdue' : ''}`}>{deadline.priority}: acknowledge within {deadline.acknowledge_within}, operator on location within {deadline.operator_on_location_within} — {deadline.overdue ? 'OVERDUE' : `due ${new Date(deadline.due_at).toLocaleTimeString()}`} <small>({deadline.source})</small></p>}

      <div className="brief-grid">
        <div className="brief-block">
          <h3>1 · Observed alarm</h3>
          <p><strong>{brief.problem?.alarm_tag}</strong> — {brief.problem?.alarm_description}</p>
          <p className="brief-muted">Source: <b>{brief.problem?.data_source}</b> · Priority from source: {brief.problem?.priority_from_source}</p>
          {brief.problem?.status_tags_are_not_alarms?.length ? <p className="brief-muted">Status tags treated as evidence, not alarms: {brief.problem.status_tags_are_not_alarms.join(', ')}</p> : null}
        </div>

        <div className="brief-block">
          <h3>2 · Possible causes <small>hypotheses — not confirmed</small></h3>
          <ul>{(brief.possible_causes || []).map((h, i) => <li key={i}><Kind kind={h.kind} /> {h.statement}{h.ranking_score != null ? <small> Ranking {Number(h.ranking_score).toFixed(2)} — {h.ranking_note}</small> : null}</li>)}</ul>
        </div>

        <div className="brief-block brief-wide">
          <h3>3 · Supporting evidence — SOP limit check <small>calculated in the backend, cited to SOP-MAN-000</small></h3>
          {limitChecks.length ? <table className="brief-table"><thead><tr><th>Parameter</th><th>Value</th><th>Normal</th><th>Status vs SOP limits</th><th>Source</th></tr></thead><tbody>
            {limitChecks.map((c) => <tr key={c.tag} className={c.highest_exceeded ? 'exceeded' : ''}><td><b>{c.label}</b><br /><code>{c.tag}</code></td><td>{c.value} {c.unit}<LimitBar check={c} /></td><td>{c.normal_text}</td><td>{c.highest_exceeded ? <><b>{c.highest_exceeded.name}</b> {c.highest_exceeded.limit} {c.unit} reached</> : c.normal_state.replaceAll('_', ' ')}{c.next_limit ? <><br /><small>Next: {c.next_limit.name} {c.next_limit.limit} {c.unit} ({c.next_limit.margin_text})</small></> : null}{c.mapping === 'assumed' ? <><br /><small className="brief-warn">Mapping assumed: {c.mapping_note}</small></> : null}</td><td>{c.sop_id} p.{c.highest_exceeded?.source_page || c.source_page}</td></tr>)}
          </tbody></table> : <p className="brief-muted">No SOP-mapped measurements for this equipment.</p>}
          <details><summary>Observed event sequence ({brief.supporting_evidence?.observed?.length || 0}) and calculated changes ({brief.supporting_evidence?.calculated?.length || 0})</summary>
            <ul>{(brief.supporting_evidence?.observed || []).map((o, i) => <li key={`o${i}`}><Kind kind={o.kind} /> {o.timestamp ? new Date(o.timestamp).toLocaleTimeString() : ''} {o.label}: {o.description} <small>[{o.data_source}]</small></li>)}
            {(brief.supporting_evidence?.calculated || []).map((c, i) => <li key={`c${i}`}><Kind kind={c.kind} /> {c.label}: {c.change_percent_vs_baseline_midpoint > 0 ? '+' : ''}{c.change_percent_vs_baseline_midpoint}% vs baseline midpoint</li>)}</ul>
          </details>
        </div>

        <div className="brief-block">
          <h3>4 · Missing evidence &amp; limitations</h3>
          <ul>{[...(brief.missing_evidence || []), ...(brief.limitations || [])].slice(0, 8).map((m, i) => <li key={i}>{m}</li>)}</ul>
        </div>

        <div className="brief-block">
          <h3>5 · Safe inspection steps <small>verbatim from SOP</small></h3>
          <ol>{steps.slice(0, 5).map((s) => <li key={s.number}>{s.text} <small>{s.page ? `(p.${s.page})` : s.source}</small></li>)}</ol>
          {steps.length > 5 ? <small className="brief-muted">+{steps.length - 5} more steps in {brief.sop?.sop_id}</small> : null}
        </div>

        <div className="brief-block">
          <h3>6 · SOP</h3>
          <p><b>{brief.sop?.sop_id}</b> {brief.sop?.title}</p>
          <p className={brief.sop?.approved ? 'brief-ok' : 'brief-warn'}>{brief.sop?.approval_label}</p>
          <p className="brief-muted">Retrieved via {brief.sop?.retrieval_method || '—'}</p>
        </div>

        <div className="brief-block">
          <h3>7 · Verification criteria</h3>
          <ul>{(brief.verification_criteria || []).map((v, i) => <li key={i}>{v}</li>)}</ul>
        </div>

        <div className="brief-block">
          <h3>8 · Resolution status</h3>
          <p>{brief.resolution?.state}</p>
          <p className="brief-muted">{brief.resolution?.note}</p>
        </div>
      </div>
    </section>
  );
}
