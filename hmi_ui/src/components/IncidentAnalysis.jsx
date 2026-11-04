import React from 'react';
import { Activity, AlertCircle, BookOpen, CheckCircle2, LoaderCircle, MessageSquareText } from 'lucide-react';
import { calculateEvidenceSupport } from '../lib/evidenceSupport';
import { sopDisplayStatus } from '../lib/assistantPresentation';

export default function IncidentAnalysis({ incident = null, answer, draft = '', status = '', loading = false, error = '', sopData = null, onOpenSop, onAskOpsLens, onSelectHistorical }) {
  const response = answer?.operator_response || {};
  const support = calculateEvidenceSupport(answer);
  const responseKind = answer?.fallback_used ? 'Evidence-based guidance' : 'Incident guidance';
  const matches = answer?.similar_incidents || [];
  const resolvedSop = sopData?.resolved_sop_sources?.find((source) => source?.verified === true);
  const sopResolution = sopData?.sop_resolution || answer?.sop_resolution || {};
  const sopPassages = (sopData?.resolved_sop_sources || response.relevant_sop?.passages || [])
    .filter((source) => source?.verified === true && typeof source?.text === 'string' && source.text.trim().length >= 20);
  const sopApproved = sopResolution.approved === true && sopPassages.some((source) => source.approved === true);
  const sopStatusLabel = sopDisplayStatus(sopResolution);
  const observations = (response.evidence || []).slice(0, 3);
  const problem = answer?.problem || response.problem || {};
  const cause = answer?.cause || response.cause || {};
  const solution = answer?.solution || response.solution || {};
  const readings = Array.isArray(answer?.supporting_readings) ? answer.supporting_readings : [];
  const events = Array.isArray(answer?.supporting_events) ? answer.supporting_events : [];
  const incidentCandidate = incident?.candidate || {};
  const equipmentId = incident?.equipment_id || incidentCandidate.equipment_id || incidentCandidate.equipment || 'Affected equipment not recorded';
  const storedSteps = incident?.story?.steps || [];
  const storedDeltas = incident?.evidence?.supporting_deltas || [];
  const storedSopStatus = incident?.sop_match?.retrieval_status || 'not_retrieved';

  return (
    <section className="incident-analysis" aria-labelledby="incident-analysis-heading">
      <div className="analysis-heading">
        <div><span className="analysis-kicker">Incident assessment</span><h2 id="incident-analysis-heading">Root-cause analysis</h2></div>
        {answer && <span className={`analysis-source ${answer.llm_used && !answer.fallback_used ? 'ai' : ''}`}>
          {answer.llm_used && !answer.fallback_used ? <CheckCircle2 size={14} /> : <Activity size={14} />}{responseKind}
        </span>}
      </div>

      {loading && <div className="analysis-wait" role="status"><LoaderCircle size={16} className="animate-spin" />{draft || status || 'Building an incident explanation from recorded evidence…'}</div>}
      {!answer && incident && <>
        <section className="analysis-summary" aria-label="Recorded incident details">
          <h3>Incident details</h3>
          <p className="analysis-bottomline">{incidentCandidate.primary_alarm ? 'Alarm active' : 'Recorded incident'} · {incidentCandidate.primary_tag || incident.primary_tag || 'Equipment not identified'} · {incident.trigger_timestamp || incidentCandidate.trigger_timestamp || 'Time unavailable'}</p>
        </section>
        {storedSteps.length > 0 && <section className="analysis-observations" aria-label="Recorded event timeline">
          <h3>Recorded event timeline</h3>
          <ul>{storedSteps.slice(-4).map((step, index) => <li key={`${step.tag || 'step'}-${step.timestamp || index}`}><strong>{step.tag || 'Event'}</strong><span>{step.description || [step.value_after != null ? `recorded ${step.value_after}` : '', step.timestamp || ''].filter(Boolean).join(' · ')}</span></li>)}</ul>
        </section>}
        {storedDeltas.length > 0 && <section className="analysis-observations" aria-label="Available recorded evidence">
          <h3>Available recorded evidence</h3>
          <ul>{storedDeltas.slice(0, 3).map((item, index) => <li key={`${item.tag || 'evidence'}-${index}`}><strong>{item.tag || 'Evidence'}</strong><span>{item.description || item.summary || (item.value != null ? `Recorded ${item.value} ${item.unit || ''}` : 'Recorded supporting signal')}</span></li>)}</ul>
        </section>}
        <p className="analysis-sop-status">Procedure reference status: {storedSopStatus.replaceAll('_', ' ')}</p>
      </>}
      {error && !answer && <div className="analysis-error" role="alert"><AlertCircle size={15} />{error}</div>}
      {!loading && !error && !answer && <p className="analysis-empty">An incident explanation will appear here when a recorded alarm is selected.</p>}
      {answer && <>
        <section className="analysis-summary analysis-problem" aria-label="Problem: what happened">
          <div className="analysis-section-title"><span className="analysis-step-number">1</span><div><span className="analysis-kicker">Problem · What happened?</span><h3>{problem.equipment || equipmentId || 'Affected equipment not recorded'} · {problem.alarm || incidentCandidate.primary_tag || 'Alarm not recorded'}</h3></div></div>
          <p className="analysis-bottomline">{problem.summary || response.bottom_line || answer.answer || 'No incident summary is available from the recorded data.'}</p>
          {(problem.observations || observations).length > 0 && <ul className="analysis-problem-observations">{(problem.observations || observations).slice(0, 3).map((item, index) => <li key={`${item.tag || item.kind}-${index}`}><strong>{item.tag || item.kind}</strong><span>{item.summary || item.description}</span>{(item.data_sources || []).map((source) => <small key={source} className={`analysis-source-chip ${/plc/i.test(source) ? 'plc' : /simulat|synthetic/i.test(source) ? 'simulated' : ''}`}>{/plc/i.test(source) ? 'PLC' : /simulat|synthetic/i.test(source) ? 'SIMULATED' : source}</small>)}</li>)}</ul>}
          <span className="analysis-problem-state">Alarm: {problem.alarm_state || 'status unavailable'}</span>
        </section>

        <section className="analysis-cause" aria-label="Possible root cause">
          <div className="analysis-section-title"><span className="analysis-step-number">2</span><div><span className="analysis-kicker">Possible contributor</span><h3>{cause.contributor_tag || 'Not identified'}</h3></div></div>
          <p>{cause.explanation || response.likely_explanation || 'The available evidence does not confirm a physical cause.'}</p>
          {cause.additional_evidence?.length > 0 && <p className="analysis-confirmation"><strong>To confirm or reject:</strong> {cause.additional_evidence.slice(0, 2).join(' ')}</p>}
          <span className="analysis-cause-status">{cause.confirmed === true ? 'Confirmed' : 'Under investigation'}</span>
        </section>

        <section className="analysis-checks analysis-solution" aria-label="Solution: safe next steps">
          <div className="analysis-section-title"><span className="analysis-step-number">3</span><div><span className="analysis-kicker">Solution · What should the operator do?</span><h3>Safe next steps</h3></div></div>
          <ol>{(solution.steps || response.recommended_checks || []).slice(0, 3).map((item, index) => <li key={`check-${index}`}>{item}</li>)}</ol>
          {solution.approved_instructions?.length > 0 && <div className="analysis-approved-instructions"><strong>Verified approved instructions · {solution.sop_status?.sop_id}</strong>{solution.approved_instructions.slice(0, 2).map((item, index) => <p key={`${item.section || item.step_title || 'instruction'}-${index}`}>{item.text}</p>)}</div>}
          {!sopApproved && <p className="analysis-no-approved-guidance">No approved instructions are available. Follow the site procedure or contact the responsible person before operation.</p>}
          <p className="analysis-recovery"><strong>Verify recovery:</strong> {solution.recovery_verification || 'Confirm a subsequent recorded alarm input is clear and review fresh sensor readings against site-approved criteria. Operator confirmation remains required.'}</p>
          <span className={`analysis-sop-status ${sopApproved ? 'approved' : 'reference-only'}`}>Guidance: {sopApproved ? 'Approved' : sopStatusLabel}</span>
        </section>

        <div className="analysis-actions">
          <button type="button" className="analysis-action primary" onClick={onAskOpsLens}><MessageSquareText size={15} />Ask OpsLens</button>
          {resolvedSop && <button type="button" className="analysis-action secondary" onClick={onOpenSop}><BookOpen size={15} />Review source · {resolvedSop.sop_id}</button>}
        </div>

        <details className="analysis-details analysis-supporting-details">
          <summary>View Supporting Evidence</summary>
          <div className="analysis-supporting-content">
            {response.evidence?.length > 0 && <section className="analysis-evidence-list"><h3>Evidence Engine observations</h3><ul>{response.evidence.map((item, index) => <li key={`${item.tag || item.kind}-${index}`}><strong>{item.tag || item.kind}</strong><span>{item.summary || item.description}</span>{item.first_timestamp && <small>{item.first_timestamp} → {item.last_timestamp} · {item.reading_count ?? '—'} readings</small>}</li>)}</ul></section>}
            {readings.length > 0 && <section><h3>Supporting sensor readings ({readings.length})</h3><ul>{readings.map((item, index) => <li key={`${item.tag || 'reading'}-${item.timestamp || index}`}><strong>{item.tag || 'Sensor'}</strong> {item.value ?? item.reading ?? 'Value unavailable'} {item.unit || ''} · source time {item.timestamp || 'unavailable'}<small>{String(item.data_source || 'unknown').toUpperCase()} · quality {item.data_quality || 'unknown'} · connection {item.connection_status || 'unknown'} · received {item.received_timestamp || 'time unavailable'}</small></li>)}</ul></section>}
            {events.length > 0 && <section><h3>Correlated events ({events.length})</h3><ul>{events.map((item, index) => <li key={`${item.tag || 'event'}-${item.timestamp || index}`}><strong>{item.tag || 'Event'}</strong> {item.description || item.timestamp || 'Recorded event'}</li>)}</ul></section>}
            {(response.interpretation || []).length > 0 && <section><h3>Cause interpretation</h3><ul>{response.interpretation.map((item, index) => <li key={`interpretation-${index}`}>{item}</li>)}</ul><p>Correlated records do not confirm physical cause.</p></section>}
            <section className={`analysis-sop-reference ${sopApproved ? 'approved' : 'reference-only'}`} aria-label="Relevant SOP source">
              <div className="analysis-sop-heading"><div><span className="analysis-kicker">SOP source</span><strong>{sopResolution.sop_id || sopData?.sop_id || 'No applicable SOP passage'}</strong></div><span className="analysis-sop-status">{sopPassages.length ? (sopApproved ? 'APPROVED GUIDANCE' : 'REFERENCE ONLY — NOT APPROVED') : sopStatusLabel}</span></div>
              {sopPassages.length ? <div className="analysis-sop-passages">{sopPassages.slice(0, 5).map((source, index) => <article key={`${source.sop_id}-${source.section}-${index}`}><div><strong>{source.step_title || source.section || (source.page ? `Page ${source.page}` : 'Retrieved passage')}</strong><small>{source.document_name || sopResolution.document_name || ''}{source.revision ? ` · Rev ${source.revision}` : ''}{source.page ? ` · Page ${source.page}` : ''}</small></div><p>{source.text}</p></article>)}</div> : <p className="analysis-sop-empty">{sopStatusLabel}</p>}
              {!sopApproved && sopPassages.length > 0 && <p className="analysis-sop-warning">Reference Only – Not Approved. This source is not authorized operating guidance and must not be used to direct operation.</p>}
              <p className="analysis-resolution"><strong>Resolution criteria:</strong> {sopApproved ? (response.resolution_criteria || 'Not established by retrieved approved guidance.') : 'Unavailable from approved guidance.'}</p>
            </section>
            {support && <section className="analysis-coverage"><h3>Evidence coverage indicator: {support.score}/{support.maxScore} points</h3><p>{support.score} is the sum of present component points; denominator 75 is the fixed maximum expected by this implementation, not an incident-specific evidence inventory. Missing categories receive zero. Duplicate records within a category do not add points because each category is scored once. Weights are fixed at 30 readings, 20 event sequence, 10 comparable incident history, and 15 evidence-sufficiency status. This is a reproducible presence heuristic; it is not cause confidence. Mathematically the weighted sum is consistent with those rules, but conceptually it does not measure completeness against the evidence expected for a particular incident type, and its 15-point sufficiency category is a status flag rather than evidence availability. Treat it as a rough availability indicator, not a calibrated coverage measure.</p><div className="analysis-components">{support.components.map((item) => <span key={item.label}>{item.label}<strong>{item.points}/{item.max}</strong></span>)}</div></section>}
            {answer?.timings_ms && <section className="analysis-timings"><h3>Measured analysis timings</h3><ul>{Object.entries(answer.timings_ms).map(([name, value]) => <li key={name}><span>{name.replaceAll('_', ' ')}</span><strong>{value != null && Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)} ms` : 'not measured'}</strong></li>)}</ul></section>}
            {(response.data_limitations || []).length > 0 && <section><h3>Data coverage and guidance limits</h3><ul>{response.data_limitations.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></section>}
            {matches.length > 0 && <section><h3>Comparable recorded incidents ({matches.length})</h3><div className="analysis-history-matches">{matches.slice(0, 3).map((item, index) => { const id = item.event_id || item.incident_id; return <button type="button" key={id || index} disabled={!id} onClick={() => id && onSelectHistorical?.(id)}><span>{item.causal_label || item.primary_tag || item.alarm_id || 'Recorded incident'}</span><small>{item.status || item.lifecycle_state || 'Stored record'}{item.similarity_score != null ? ` · match ${Math.round(item.similarity_score * 100)}%` : ''}</small></button>; })}</div></section>}
          </div>
        </details>
      </>}
    </section>
  );
}
