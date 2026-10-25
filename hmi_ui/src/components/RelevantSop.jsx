import React from 'react';
import { BookOpen, FileText, ShieldCheck } from 'lucide-react';

export default function RelevantSop({ sopData, onOpenSopModal, isIncident = false, isVisible = true }) {
  if (!isIncident || !isVisible) {
    return (
      <div className="flex min-h-[60px] items-center justify-center gap-2 rounded-lg border border-[#1a2535] bg-[#0d1420] px-4 py-3 text-xs text-slate-500">
        <BookOpen className="h-4 w-4 shrink-0 text-slate-600" />
        SOP retrieval pending
      </div>
    );
  }

  const sopId = sopData?.sop_id || sopData?.sop?.sop_id || '—';
  const title = sopData?.sop_title || sopData?.title || sopData?.sop?.title || 'Operating Procedure';
  const steps = sopData?.steps || sopData?.sop?.steps || [];
  const isNone = ['NONE', 'SOP-NONE', 'UNKNOWN-SOP', '—'].includes(sopId);

  if (isNone) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-[#1a2535] bg-[#0d1420] px-4 py-3">
        <BookOpen className="h-4 w-4 shrink-0 text-slate-600" />
        <span className="text-xs text-slate-500">No matching procedure for this incident type.</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 rounded-lg border border-[#1a2535] bg-[#0d1420] px-4 py-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-blue-600/20 border border-blue-500/30">
        <BookOpen className="h-4 w-4 text-blue-400" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[10px] font-mono uppercase tracking-wider text-blue-400">{sopId}</div>
        <div className="mt-0.5 text-xs font-medium text-slate-200 leading-snug">{title}</div>
        <div className="mt-0.5 flex items-center gap-1 text-[10px] text-slate-500">
          <ShieldCheck className="h-3 w-3 text-emerald-500/70" />
          {steps.length > 0 ? `${steps.length} steps` : 'Multi-step protocol'} · Locally authored
        </div>
      </div>
      <button
        onClick={onOpenSopModal}
        className="shrink-0 flex items-center gap-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide text-white transition-colors"
      >
        <FileText className="h-3 w-3" />
        View
      </button>
    </div>
  );
}
