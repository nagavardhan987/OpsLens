import React from 'react';
import { BookOpen, FileText } from 'lucide-react';

export default function RelevantSop({ sopData, onOpenSopModal, isIncident = false, isVisible = true }) {
  if (!isIncident || !isVisible) {
    return (
      <div className="rounded-xl border border-[#1a2535] bg-[#0d1420] p-5 flex flex-col items-center justify-center min-h-[160px]">
        <BookOpen className="w-5 h-5 text-slate-600 mb-2" />
        <p className="text-xs text-slate-500">SOP retrieval pending</p>
      </div>
    );
  }

  const sopId    = sopData?.sop_id || sopData?.sop?.sop_id || '—';
  const title    = sopData?.sop_title || sopData?.title || sopData?.sop?.title || 'Operating Procedure';
  const steps    = sopData?.steps || sopData?.sop?.steps || [];
  const match    = sopData?.match_score != null ? Math.round(sopData.match_score * 100) : null;

  return (
    <div className="rounded-xl border border-[#1a2535] bg-[#0d1420] p-5 flex flex-col justify-between">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-widest text-blue-400">Matched SOP</div>
          <div className="text-sm font-bold text-white mt-0.5">{sopId}</div>
        </div>
        {match !== null && (
          <span className="text-[11px] font-mono font-bold px-2 py-1 rounded border bg-blue-500/10 border-blue-500/30 text-blue-400">
            {match}% match
          </span>
        )}
      </div>

      {/* Title block */}
      <div className="bg-[#0a0e16] border-l-2 border-blue-400 rounded-r-lg px-4 py-3 mb-4 flex-1">
        <p className="text-xs font-medium text-slate-200 leading-relaxed">{title}</p>
        <div className="text-[10px] font-mono text-slate-500 mt-1.5">
          {steps.length > 0 ? `${steps.length} steps defined` : 'Multi-step protocol'}
        </div>
      </div>

      {/* CTA */}
      <button
        onClick={onOpenSopModal}
        className="w-full h-9 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold uppercase tracking-wider flex items-center justify-center gap-2 transition-all cursor-pointer"
      >
        <FileText className="w-3.5 h-3.5" />
        View Full Procedure
      </button>
    </div>
  );
}
