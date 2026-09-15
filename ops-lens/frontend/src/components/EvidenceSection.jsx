import React from 'react';
import { Target, CheckCircle2 } from 'lucide-react';

export default function EvidenceSection({ evidence, isIncident = false, isVisible = true }) {
  if (!isIncident || !isVisible) {
    return (
      <div className="rounded-xl border border-[#1a2535] bg-[#0d1420] p-5 flex flex-col items-center justify-center min-h-[160px]">
        <Target className="w-5 h-5 text-slate-600 mb-2" />
        <p className="text-xs text-slate-500">Root cause evidence will appear here</p>
      </div>
    );
  }

  const contributor = evidence?.likely_contributor_tag || evidence?.likely_contributor || '—';
  const confLabel = evidence?.confidence_label || (evidence?.confidence_score > 0.7 ? 'HIGH' : evidence?.confidence_score > 0.4 ? 'MEDIUM' : 'LOW');
  const confScore = evidence?.confidence_score != null ? Math.round(evidence.confidence_score * 100) : null;
  const deltas = (evidence?.supporting_deltas || []).map((d, i) => ({
    id: i, tag: d.tag,
    pct: `${d.delta_pct >= 0 ? '+' : ''}${typeof d.delta_pct === 'number' ? d.delta_pct.toFixed(1) : d.delta_pct}%`,
    dir: d.direction,
  }));

  const confColor = confLabel === 'HIGH' ? 'emerald' : confLabel === 'MEDIUM' ? 'amber' : 'rose';

  return (
    <div className="rounded-xl border border-[#1a2535] bg-[#0d1420] p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-widest text-amber-500">Root Cause</div>
          <div className="text-sm font-bold text-white mt-0.5">Evidence Engine</div>
        </div>
        <span className={`text-[11px] font-mono font-bold px-2 py-1 rounded border bg-${confColor}-500/10 border-${confColor}-500/30 text-${confColor}-400`}>
          {confLabel}{confScore !== null ? ` · ${confScore}%` : ''}
        </span>
      </div>

      {/* Contributor */}
      <div className="bg-[#0a0e16] border-l-2 border-amber-400 rounded-r-lg px-4 py-3 mb-4">
        <div className="text-[10px] text-slate-500 font-mono uppercase tracking-wider mb-0.5">Likely contributor</div>
        <div className="text-xl font-black text-amber-300 tracking-tight">{contributor}</div>
      </div>

      {/* Deltas */}
      {deltas.length > 0 && (
        <div className="space-y-1.5">
          {deltas.map(d => (
            <div key={d.id} className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-1.5">
                <CheckCircle2 className="w-3 h-3 text-emerald-500 shrink-0" />
                <span className="font-mono text-slate-400">{d.tag}</span>
              </div>
              <span className={`font-mono font-bold text-[11px] ${d.dir === 'DOWN' ? 'text-red-400' : 'text-amber-400'}`}>{d.pct}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
