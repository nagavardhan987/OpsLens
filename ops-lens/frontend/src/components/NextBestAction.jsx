import React from 'react';
import { Wrench, Eye, CheckSquare, Check, CheckCircle2, Zap } from 'lucide-react';

export default function NextBestAction({
  guidance,
  actions = [],
  equipmentId = 'Pump-02',
  primaryTag = 'Valve-04',
  recordedAction,
  onExecuteAction,
  onOpenSopModal,
  isIncident = false,
  isVisible = true
}) {
  if (!isIncident || !isVisible) {
    return (
      <div className="rounded-xl border border-[#1a2535] bg-[#0d1420] p-5 flex flex-col items-center justify-center min-h-[100px]">
        <Zap className="w-5 h-5 text-slate-600 mb-2" />
        <p className="text-xs text-slate-500">Action guidance pending</p>
      </div>
    );
  }

  const rawActions = guidance?.next_best_actions || actions || [];
  const citedSopId = guidance?.cited_sop_id || null;

  const actionList = rawActions.length > 0
    ? rawActions.map((item, i) => typeof item === 'string' ? { priority: i + 1, action: item } : item)
    : [
        { priority: 1, action: `Verify ${primaryTag} position` },
        { priority: 2, action: `Review ${equipmentId} operating status` },
        { priority: 3, action: 'Execute emergency procedure' },
      ];

  return (
    <div className="rounded-xl border border-[#00A344]/30 bg-[#0d1420] p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-widest text-[#00D65A]">AI Guidance · Human-in-the-Loop</div>
          <div className="text-sm font-bold text-white mt-0.5">Next-Best Actions</div>
        </div>
        {citedSopId && (
          <span className="text-[11px] font-mono px-2 py-1 rounded bg-[#00A344]/10 border border-[#00A344]/30 text-[#00D65A]">
            {citedSopId}
          </span>
        )}
      </div>

      {/* Recorded action banner */}
      {recordedAction && (
        <div className="mb-4 flex items-center gap-2.5 bg-emerald-950/50 border border-emerald-500/40 rounded-lg px-3 py-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
          <span className="text-xs text-emerald-300 font-semibold">
            [{recordedAction.action_type}] recorded → Shift Handover
          </span>
        </div>
      )}

      {/* 3 Recommended steps */}
      <div className="grid grid-cols-3 gap-2.5 mb-4">
        {actionList.map((item, idx) => (
          <div key={idx} className="rounded-lg border border-[#1a2535] bg-[#0a0e16] p-3 flex items-start gap-2.5">
            <div className="w-5 h-5 rounded-full bg-[#00A344]/20 border border-[#00A344]/40 text-[#00D65A] flex items-center justify-center text-[10px] font-black shrink-0 mt-0.5">
              {idx + 1}
            </div>
            <p className="text-[11px] text-slate-300 leading-snug">{item.action}</p>
          </div>
        ))}
      </div>

      {/* Action buttons */}
      <div className="grid grid-cols-4 gap-2">
        <button
          onClick={() => onExecuteAction('VERIFY', `Verified ${primaryTag || 'component'}`)}
          className="h-10 rounded-lg border border-[#1a2535] bg-[#0a0e16] hover:border-emerald-500/50 hover:bg-emerald-950/20 text-slate-300 text-[11px] font-bold uppercase tracking-wide flex flex-col items-center justify-center gap-1 transition-all cursor-pointer group"
        >
          <Wrench className="w-3.5 h-3.5 text-emerald-400" />
          <span>Verify</span>
        </button>

        <button
          onClick={() => onExecuteAction('INSPECT', `Inspected ${equipmentId}`)}
          className="h-10 rounded-lg border border-[#1a2535] bg-[#0a0e16] hover:border-blue-500/50 hover:bg-blue-950/20 text-slate-300 text-[11px] font-bold uppercase tracking-wide flex flex-col items-center justify-center gap-1 transition-all cursor-pointer group"
        >
          <Eye className="w-3.5 h-3.5 text-blue-400" />
          <span>Inspect</span>
        </button>

        <button
          onClick={onOpenSopModal}
          className="h-10 rounded-lg border border-[#1a2535] bg-[#0a0e16] hover:border-purple-500/50 hover:bg-purple-950/20 text-slate-300 text-[11px] font-bold uppercase tracking-wide flex flex-col items-center justify-center gap-1 transition-all cursor-pointer group"
        >
          <CheckSquare className="w-3.5 h-3.5 text-purple-400" />
          <span>View SOP</span>
        </button>

        <button
          onClick={() => onExecuteAction('RESOLVE', `Excursion resolved per ${citedSopId || 'SOP'}`)}
          className="h-10 rounded-lg bg-[#00A344] hover:bg-[#00D65A] text-black text-[11px] font-black uppercase tracking-wide flex flex-col items-center justify-center gap-1 transition-all cursor-pointer shadow-lg shadow-[#00A344]/20"
        >
          <Check className="w-3.5 h-3.5 stroke-[3]" />
          <span>Resolve</span>
        </button>
      </div>
    </div>
  );
}
