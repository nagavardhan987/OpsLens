import React from 'react';
import { Target, ChevronDown } from 'lucide-react';

export default function EvidenceSection({ evidence, evidenceAudit, isIncident = false, isVisible = true }) {
  if (!isIncident || !isVisible) {
    return (
      <div className="flex min-h-[80px] items-center justify-center gap-2 rounded-lg border border-[#1a2535] bg-[#0d1420] p-4 text-xs text-slate-500">
        <Target className="h-4 w-4 shrink-0 text-slate-600" />
        Root cause evidence will appear here
      </div>
    );
  }

  const contributor = evidence?.likely_contributor_tag || evidence?.likely_contributor || '—';
  const evidenceLabel = evidence?.confidence_label
    || (evidence?.confidence_score > 0.7 ? 'HIGH' : evidence?.confidence_score > 0.4 ? 'MEDIUM' : 'LOW');
  const evidenceScore = evidence?.confidence_score != null
    ? Math.round(evidence.confidence_score * 100) : null;
  const deltas = (evidence?.supporting_deltas || []).map((d, i) => ({
    id: i,
    tag: d.tag,
    pct: `${d.delta_pct >= 0 ? '+' : ''}${typeof d.delta_pct === 'number' ? d.delta_pct.toFixed(1) : d.delta_pct}%`,
    dir: d.direction,
  }));

  const scoreStyle = evidenceLabel === 'HIGH'
    ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
    : evidenceLabel === 'MEDIUM'
    ? 'bg-amber-500/10 border-amber-500/30 text-amber-400'
    : 'bg-rose-500/10 border-rose-500/30 text-rose-400';

  const scoring = evidenceAudit?.scoring_breakdown || {};
  const contributorScores = Object.entries(scoring.tag_scores || {});

  return (
    <div className="space-y-3">
      {/* Likely contributor — prominent */}
      <div className="rounded-lg border border-[#1a2535] bg-[#0d1420] px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-wider text-amber-500 mb-0.5">
              Likely contributor
            </div>
            <div className="text-lg font-black text-amber-300 font-mono tracking-tight leading-tight">
              {contributor}
            </div>
            <p className="mt-1 text-[10px] text-slate-500 leading-relaxed">
              Possible contributor — hypothesis requiring operator verification. Not a confirmed physical root cause.
            </p>
          </div>
          <span
            title="Evidence ranking heuristic; not an alarm severity or calibrated probability."
            className={`shrink-0 text-[10px] font-mono font-bold px-2 py-1 rounded border ${scoreStyle}`}
          >
            {evidenceLabel}{evidenceScore !== null ? ` · ${evidenceScore}%` : ''}
          </span>
        </div>

        {/* Supporting deltas — inline, compact */}
        {deltas.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {deltas.map(d => (
              <span key={d.id} className="inline-flex items-center gap-1 rounded border border-[#1a2535] bg-[#0a0e16] px-2 py-0.5 text-[10px] font-mono">
                <span className="text-slate-400">{d.tag}</span>
                <span className={`font-bold ${d.dir === 'DOWN' ? 'text-red-400' : 'text-amber-400'}`}>{d.pct}</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Calculation detail — collapsed by default */}
      <details className="rounded-lg border border-[#1a2535] bg-[#0d1420] overflow-hidden group">
        <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-2.5 text-[10px] font-mono uppercase tracking-wider text-slate-500 hover:text-slate-300 select-none">
          <span>Evidence score calculation</span>
          <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
        </summary>
        <div className="border-t border-[#1a2535] px-4 py-3 space-y-3 text-[10px] leading-relaxed text-slate-400">
          <p>
            The percentage is the leading contributor's raw score divided by the sum of candidate scores.
            It is a normalized ranking heuristic — not a calibrated probability and not the alarm's configured severity.
          </p>
          {scoring.formula && (
            <code className="block whitespace-normal break-words rounded bg-[#080d15] p-2 text-slate-300">
              {scoring.formula}
            </code>
          )}
          {contributorScores.length > 0 && (
            <div className="space-y-2">
              {contributorScores.map(([tag, item]) => (
                <div key={tag} className="rounded bg-[#080d15] p-2 space-y-0.5">
                  <div className="font-mono font-bold text-slate-200">{tag} · raw score {item.raw_score}</div>
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
          {!scoring.formula && contributorScores.length === 0 && (
            <p>Detailed calculation data is unavailable for this event.</p>
          )}
        </div>
      </details>
    </div>
  );
}
