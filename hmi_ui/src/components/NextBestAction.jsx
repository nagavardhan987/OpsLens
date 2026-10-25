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
  isVisible = true,
  isResolved = false,
  alarmClearObserved = false,
}) {
  if (!isIncident || !isVisible) {
    return (
      <div className="flex min-h-[80px] items-center justify-center gap-2 rounded-lg border border-[#1a2535] bg-[#0d1420] p-4 text-xs text-slate-500">
        <Zap className="h-4 w-4 shrink-0 text-slate-600" />
        Action guidance pending
      </div>
    );
  }

  const rawActions = guidance?.next_best_actions || actions || [];
  const actionList = rawActions
    .map((item, i) => typeof item === 'string' ? { priority: i + 1, action: item } : item)
    .filter((item) => item?.action && item.action !== 'Operator verification required.');
  // Show top 2, or top 3 if all three are short
  const displayActions = actionList.slice(0, 3);
  const citedSopId = guidance?.cited_sop_id && !['NONE', 'SOP-NONE', 'UNKNOWN-SOP'].includes(guidance.cited_sop_id)
    ? guidance.cited_sop_id : null;

  return (
    <div className="rounded-xl border border-[#1a2535] bg-[#0d1420] p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="text-[10px] font-mono uppercase tracking-widest text-[#00D65A]">
          Next-Best Actions
        </div>
        {citedSopId && (
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#00A344]/10 border border-[#00A344]/30 text-[#00D65A] whitespace-nowrap">
            {citedSopId}
          </span>
        )}
      </div>

      {/* Recorded action banner */}
      {recordedAction && (
        <div className="mb-3 flex items-center gap-2 bg-emerald-950/50 border border-emerald-500/30 rounded-lg px-3 py-2">
          <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
          <span className="text-xs text-emerald-300 font-semibold">
            {recordedAction.action_type === 'RESOLVE'
              ? 'Operator-confirmed runtime alarm state recorded.'
              : `[${recordedAction.action_type}] recorded → Shift Handover`}
          </span>
        </div>
      )}

      {/* Numbered action list — readable, no word-wrap issues */}
      {displayActions.length > 0 ? (
        <ol className="space-y-2 mb-3">
          {displayActions.map((item, idx) => (
            <li key={idx} className="flex items-start gap-2.5 text-sm">
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[#00A344]/20 border border-[#00A344]/40 text-[#00D65A] text-[10px] font-black">
                {idx + 1}
              </span>
              <span className="text-slate-200 leading-snug">{item.action}</span>
            </li>
          ))}
        </ol>
      ) : (
        <div className="mb-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2.5 text-xs text-amber-200">
          Operator verification required. No supported next step is available from the retrieved procedure.
        </div>
      )}

      {/* Operator action row */}
      <div className="flex flex-wrap gap-2 border-t border-[#1a2535] pt-3">
        <button
          disabled={isResolved}
          onClick={() => onExecuteAction('VERIFY', `Verified ${primaryTag || 'component'}`)}
          className="flex items-center gap-1.5 rounded-lg border border-[#1a2535] bg-[#0a0e16] px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide text-slate-300 hover:border-emerald-500/50 hover:bg-emerald-950/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Wrench className="h-3 w-3 text-emerald-400" />Verify
        </button>

        <button
          disabled={isResolved}
          onClick={() => onExecuteAction('INSPECT', `Inspected ${equipmentId}`)}
          className="flex items-center gap-1.5 rounded-lg border border-[#1a2535] bg-[#0a0e16] px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide text-slate-300 hover:border-blue-500/50 hover:bg-blue-950/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Eye className="h-3 w-3 text-blue-400" />Inspect
        </button>

        <button
          onClick={onOpenSopModal}
          className="flex items-center gap-1.5 rounded-lg border border-[#1a2535] bg-[#0a0e16] px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide text-slate-300 hover:border-purple-500/50 hover:bg-purple-950/20 transition-all"
        >
          <CheckSquare className="h-3 w-3 text-purple-400" />View SOP
        </button>

        <button
          disabled={isResolved || !alarmClearObserved}
          onClick={() => onExecuteAction('RESOLVE', 'Operator confirmed the alarm was clear in the runtime.')}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-[#00A344] hover:bg-[#00D65A] px-4 py-1.5 text-[11px] font-black uppercase tracking-wide text-black shadow-sm shadow-[#00A344]/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Check className="h-3.5 w-3.5 stroke-[3]" />
          {isResolved ? 'Clear recorded' : alarmClearObserved ? 'Confirm runtime clear' : 'Await alarm clear'}
        </button>
      </div>

      {!isResolved && (
        <p className="mt-1.5 text-[10px] text-slate-600">
          {alarmClearObserved
            ? 'A timestamped clear state has been observed. Operator confirmation is still required.'
            : 'Resolution is locked until a later source reading reports the alarm input clear.'}
        </p>
      )}
    </div>
  );
}
