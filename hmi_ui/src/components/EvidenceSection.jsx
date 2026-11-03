import React from 'react';
import { Target, ChevronDown } from 'lucide-react';

function formatValue(value, unit = '') {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return `${Number.isInteger(value) ? value : value.toFixed(2)}${unit ? ` ${unit}` : ''}`;
}

function sourceLabel(value) {
  const source = String(value || '').toLowerCase();
  if (/simulat|synthetic/.test(source)) return 'SIMULATED';
  if (/opc.?ua|plc/.test(source)) return 'LIVE PLC';
  return value ? 'RECORDED' : 'SOURCE UNKNOWN';
}

export default function EvidenceSection({ evidence, evidenceAudit, event, isIncident = false, isVisible = true }) {
  if (!isIncident || !isVisible) {
    return (
      <div className="flex min-h-[80px] items-center justify-center gap-2 rounded-xl border border-[#D8E2DA] bg-white p-4 text-xs text-[#64736A]">
        <Target className="h-4 w-4 shrink-0 text-[#64736A]" />
        Root cause evidence will appear here
      </div>
    );
  }

  const scoring = evidenceAudit?.scoring_breakdown || {};
  const tagScores = scoring.tag_scores || {};
  const deltas = evidence?.supporting_deltas || [];
  const storySteps = event?.story?.steps || [];
  const eventSource = event?.runtime_alarm_state?.data_source || event?.runtime_alarm_state?.source || event?.data_source || event?.source;
  const primaryTag = event?.candidate?.primary_tag || event?.primary_tag;
  const tags = [...new Set([...deltas.map((item) => item.tag), ...Object.keys(tagScores)])].filter((tag) => tag && tag !== primaryTag);
  const hasSupportingEvidence = tags.length >= 2;
  const contributor = hasSupportingEvidence ? (evidence?.likely_contributor_tag || evidence?.likely_contributor || '—') : 'No clear contributing factor identified.';
  const rows = tags.map((tag) => {
    const delta = deltas.find((item) => item.tag === tag) || {};
    const score = tagScores[tag] || {};
    const observed = score.observed_reading || {};
    const story = [...storySteps].reverse().find((item) => item.tag === tag && typeof item.value_after === 'number') || {};
    const current = typeof observed.value === 'number' ? observed.value : story.value_after;
    const previous = typeof story.value_before === 'number' ? story.value_before : delta.value_before;
    const abs = typeof current === 'number' && typeof previous === 'number' ? current - previous : null;
    const source = observed.data_source || observed.source || story.data_source || story.source || eventSource;
    const relevance = `${score.precedes_primary === true ? 'Preceded the alarm; ' : score.precedes_primary === false ? 'Followed the alarm; ' : ''}ranked using recorded deviation, configured weight and topology.`;
    return { tag, delta, score, observed, current, previous, abs, source, relevance };
  });
  const missingData = rows.filter((row) => row.current == null || row.previous == null || !row.source).length;

  return (
    <div className="evidence-section space-y-3">
      {/* Likely contributor — prominent */}
      {hasSupportingEvidence && <div className="rounded-xl border border-[#D8E2DA] bg-white px-4 py-3 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-[#B7791F] mb-0.5 font-bold">Possible contributor</div>
            <div className="text-lg font-black text-[#26352C] font-mono tracking-tight leading-tight">
              {contributor}
            </div>
            <p className="mt-1 text-[10px] text-[#64736A] leading-relaxed">
            This recorded signal changed near the alarm and may be relevant. A physical fault has not been confirmed.
            </p>
          </div>
          <span className="shrink-0 text-[10px] font-bold px-2 py-1 rounded border bg-[#FFF9EB] border-[#E8C879] text-[#795911]">Under investigation</span>
        </div>

        <p className="mt-2 text-[10px] text-[#64736A]">A temporal or ranked relationship is a possible contributor, not confirmation of physical causation.</p>
      </div>}

      {!hasSupportingEvidence && <div className="rounded-xl border border-[#D8E2DA] bg-white px-4 py-3 text-sm text-[#64736A]"><strong className="text-[#26352C]">No clear contributing factor identified.</strong> The recorded alarm is available, but supporting correlated readings are insufficient to rank a possible contributor.</div>}

      <section className="evidence-table-panel" aria-label="Ranked evidence readings">
        <div className="evidence-coverage" role="status">Evidence coverage: {rows.length ? `${rows.length} ranked signal${rows.length === 1 ? '' : 's'} listed` : 'No ranked signals available'} · {missingData} row{missingData === 1 ? '' : 's'} missing a prior value, current value, or source record. Coverage describes data availability, not probability of root cause.</div>
        {rows.length ? <div className="evidence-table-scroll"><table className="evidence-table">
          <thead><tr><th>Tag</th><th>Previous</th><th>Current</th><th>Absolute change</th><th>Relative change</th><th>Relevance</th><th>Source / quality</th><th>Status</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.tag}>
            <td><strong className="evidence-table-tag">{row.tag}</strong><details className="evidence-row-details"><summary><ChevronDown size={13} /> Details</summary><p>{row.relevance}</p><p>Observed range {row.observed.configured_range?.join('–') || 'not recorded'} · baseline {formatValue(row.observed.baseline_midpoint, row.observed.unit || '')}</p><p>Recorded at {row.observed.timestamp || storySteps.find((step) => step.tag === row.tag)?.timestamp || 'timestamp unavailable'} · quality {row.observed.quality || row.observed.quality_status || 'not recorded'}</p></details></td>
            <td>{formatValue(row.previous, row.observed.unit || '')}</td><td>{formatValue(row.current, row.observed.unit || '')}</td>
            <td>{row.abs == null ? '—' : `${row.abs > 0 ? '+' : ''}${formatValue(row.abs, row.observed.unit || '')}`}</td>
            <td>{typeof row.delta.delta_pct === 'number' ? `${row.delta.delta_pct > 0 ? '+' : ''}${row.delta.delta_pct.toFixed(1)}%` : '—'}</td>
            <td>{row.relevance}</td><td>{sourceLabel(row.source)} · {row.observed.quality || row.observed.quality_status || 'quality not recorded'}</td>
            <td><span className={hasSupportingEvidence ? 'evidence-possible' : 'evidence-observed'}>{hasSupportingEvidence ? 'Possible contributor' : 'Recorded signal'}</span></td>
          </tr>)}</tbody>
        </table></div> : <p className="evidence-empty">No ranked supporting readings are available for this incident. Check related tags and source timestamps in the event record.</p>}
      </section>

      {/* Calculation detail — collapsed by default */}
      <details className="rounded-xl border border-[#D8E2DA] bg-white overflow-hidden group shadow-sm">
        <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-2.5 text-[10px] font-mono uppercase tracking-wider text-[#64736A] hover:text-[#26352C] select-none bg-[#F3F6F3]">
          <span>How evidence was ranked</span>
          <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
        </summary>
        <div className="border-t border-[#D8E2DA] px-4 py-3 space-y-3 text-[10px] leading-relaxed text-[#64736A]">
          <p>
            The ranking compares candidate signals using recorded deviation, configured severity weight, topology distance, and whether a signal preceded the alarm.
            With one candidate this can be 100% by definition. It is a normalized ranking share — not a calibrated probability, physical-cause confidence, or alarm severity.
          </p>
          {scoring.formula && (
            <code className="block whitespace-normal break-words rounded bg-[#F3F6F3] border border-[#D8E2DA] p-2 text-[#26352C] font-mono">
              {scoring.formula}
            </code>
          )}
          {Object.keys(tagScores).length > 0 && (
            <div className="space-y-2">
            {Object.entries(tagScores).map(([tag, item]) => (
                <div key={tag} className="rounded bg-[#F3F6F3] border border-[#D8E2DA] p-2 space-y-0.5">
                  <div className="font-mono font-bold text-[#26352C]">{tag} · raw score {item.raw_score}</div>
                  <div>
                    Deviation {item.deviation_pct}% ·
                    registry weight {item.severity_weight} ·
                    topology distance {item.topology_distance} ·
                    {item.precedes_primary ? ' preceded' : ' followed'} the alarm
                  </div>
                  {item.observed_reading && (
                    <div>
                      Observed {item.observed_reading.value} {item.observed_reading.unit || ''} ·
                      range {item.observed_reading.configured_range?.join('–') ?? 'unavailable'} ·
                      baseline {item.observed_reading.baseline_midpoint ?? 'unavailable'}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          {!scoring.formula && Object.keys(tagScores).length === 0 && (
            <p>Detailed calculation data is unavailable for this event.</p>
          )}
        </div>
      </details>
    </div>
  );
}
