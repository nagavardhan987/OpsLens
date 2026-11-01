import React from 'react';
import { BookOpen, FileText, ShieldCheck, ShieldAlert } from 'lucide-react';

export default function RelevantSop({ sopData, onOpenSopModal, isIncident = false, isVisible = true }) {
  if (!isIncident || !isVisible) {
    return (
      <div className="flex min-h-[60px] items-center justify-center gap-2 rounded-lg border border-[#1a2535] bg-[#0d1420] px-4 py-3 text-xs text-slate-500">
        <BookOpen className="h-4 w-4 shrink-0 text-slate-600" />
        Select an incident to view its procedure reference
      </div>
    );
  }

  const sopId = sopData?.sop_id || sopData?.sop?.sop_id || '—';
  const title = sopData?.sop_title || sopData?.title || sopData?.sop?.title || 'Operating Procedure';
  const sources = sopData?.resolved_sop_sources || [];
  const resolution = sopData?.sop_resolution || {};
  const source = sources[0];
  const isNone = ['NONE', 'SOP-NONE', 'UNKNOWN-SOP', '—'].includes(sopId);

  if (isNone || !source?.verified) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-[#d8e3da] bg-white px-4 py-3">
        <BookOpen className="h-4 w-4 shrink-0 text-slate-500" />
        <span className="text-xs text-slate-600">{resolution.status === 'retrieval_unavailable' ? 'Procedure reference unavailable.' : 'No approved procedure found for this incident.'}</span>
      </div>
    );
  }

  const authorityVerified = source.approved === true;

  return (
      <div className="flex items-center gap-3 rounded-lg border border-[#d8e3da] bg-white px-4 py-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded border border-[#d7e2d9] bg-[#f3f7f3]">
        <BookOpen className="h-4 w-4 text-[#267546]" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[10px] font-mono uppercase tracking-wider text-[#386b48]">{sopId} · Rev {source.revision || 'unknown'}</div>
        <div className="mt-0.5 text-xs font-medium text-[#263b2d] leading-snug">{source.document_name || title}</div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-slate-600">
          {authorityVerified ? <ShieldCheck className="h-3 w-3 text-emerald-700" /> : <ShieldAlert className="h-3 w-3 text-amber-700" />}
          <span>{source.section || (source.page ? `Page ${source.page}` : 'Source passage resolved')}</span>
          <span>·</span>
          <span>{authorityVerified ? 'APPROVED GUIDANCE' : 'REFERENCE ONLY — NOT APPROVED'}</span>
        </div>
      </div>
      <button
        onClick={onOpenSopModal}
        className="hmi-secondary-button shrink-0"
      >
        <FileText className="h-3 w-3" /> View source
      </button>
    </div>
  );
}
