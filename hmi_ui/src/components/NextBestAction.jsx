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
  actionError = '',
  actionSubmitting = false,
  referenceOnly = false,
}) {
  if (!isIncident || !isVisible) {
    return (
      <div className="flex min-h-[80px] items-center justify-center gap-2 rounded-xl border border-[#D8E2DA] bg-white p-4 text-xs text-[#64736A]">
        <Zap className="h-4 w-4 shrink-0 text-[#64736A]" />
        Guidance unavailable
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
    <div className="rounded-xl border border-[#D8E2DA] bg-white p-4 shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="text-[10px] font-mono uppercase tracking-widest text-[#009530] font-bold">
          Next-Best Actions
        </div>
        {citedSopId && (
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#E8F5EC] border border-[#009530]/30 text-[#006B35] font-semibold whitespace-nowrap">
            {citedSopId}
          </span>
        )}
      </div>

      {/* Recorded action banner */}
      {recordedAction && (
        <div className="mb-3 flex items-center gap-2 bg-[#E8F5EC] border border-[#009530]/40 rounded-lg px-3 py-2 text-[#006B35]">
          <CheckCircle2 className="h-4 w-4 text-[#009530] shrink-0" />
          <span className="text-xs font-semibold">
            {{ RESOLVE: 'Resolution recorded', MARK_UNRESOLVED: 'Incident marked unresolved', ANNOTATE: 'Event note recorded', VERIFY: 'Verification recorded', INSPECT: 'Inspection recorded' }[recordedAction.action_type] || 'Operator action recorded'}
          </span>
        </div>
      )}

      {/* Numbered action list — readable, no word-wrap issues */}
      {displayActions.length > 0 ? (
        <ol className="space-y-2 mb-3">
          {displayActions.map((item, idx) => (
            <li key={idx} className="flex items-start gap-2.5 text-sm">
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[#E8F5EC] border border-[#009530]/40 text-[#006B35] text-[10px] font-black">
                {idx + 1}
              </span>
              <span className="text-[#26352C] leading-snug">{item.action}</span>
            </li>
          ))}
        </ol>
      ) : (
        <div className="mb-3 rounded-lg border border-[#B7791F]/30 bg-[#FEF0C7] px-3 py-2.5 text-xs text-[#B7791F]">
          {referenceOnly
            ? 'REFERENCE ONLY — NOT APPROVED. The retrieved document is shown for review; its steps are not presented as authorized actions.'
            : 'No approved operating guidance is available.'}
        </div>
      )}

      {/* Operator action row */}
      <div className="flex flex-wrap gap-2 border-t border-[#D8E2DA] pt-3">
        <button
          disabled={isResolved || actionSubmitting}
          onClick={() => onExecuteAction('VERIFY', `Verified ${primaryTag || 'component'}`)}
          className="flex items-center gap-1.5 rounded-lg border border-[#D8E2DA] bg-[#F3F6F3] hover:bg-[#E8F5EC] hover:border-[#009530]/50 text-[#26352C] px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide transition-all disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
        >
          <Wrench className="h-3 w-3 text-[#009530]" />Verify
        </button>

        <button
          disabled={isResolved || actionSubmitting}
          onClick={() => onExecuteAction('INSPECT', `Inspected ${equipmentId}`)}
          className="flex items-center gap-1.5 rounded-lg border border-[#D8E2DA] bg-[#F3F6F3] hover:bg-[#EFF8FF] hover:border-[#155EEF]/50 text-[#26352C] px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide transition-all disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
        >
          <Eye className="h-3 w-3 text-[#155EEF]" />Inspect
        </button>

        <button
          onClick={onOpenSopModal}
          className="flex items-center gap-1.5 rounded-lg border border-[#D8E2DA] bg-[#F3F6F3] hover:bg-[#F9F5FF] hover:border-[#7F56D9]/50 text-[#26352C] px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide transition-all cursor-pointer"
        >
          <CheckSquare className="h-3 w-3 text-[#7F56D9]" />View SOP
        </button>

        {isResolved ? (
          <div role="status" className="ml-auto flex items-center gap-1.5 rounded-lg border border-[#009530]/30 bg-[#E8F5EC] px-4 py-1.5 text-[11px] font-bold uppercase tracking-wide text-[#006B35]">
            <Check className="h-3.5 w-3.5 stroke-[3]" />Resolution recorded
          </div>
        ) : alarmClearObserved ? (
          <button
            onClick={() => onExecuteAction('RESOLVE', 'Operator confirmed the alarm was clear in the runtime.')}
            disabled={actionSubmitting}
            className="ml-auto flex items-center gap-1.5 rounded-lg bg-[#009530] hover:bg-[#006B35] px-4 py-1.5 text-[11px] font-black uppercase tracking-wide text-white shadow-sm transition-all cursor-pointer disabled:opacity-50 disabled:cursor-wait"
          >
            <Check className="h-3.5 w-3.5 stroke-[3]" />Confirm runtime clear
          </button>
        ) : (
          <div role="status" aria-live="polite" className="ml-auto flex items-center gap-1.5 rounded-lg border border-[#B7791F]/30 bg-[#FEF0C7] px-4 py-1.5 text-[11px] font-bold uppercase tracking-wide text-[#B7791F]">
            <CheckCircle2 className="h-3.5 w-3.5" />Awaiting source clear
          </div>
        )}
      </div>

      {!isResolved && (
        <p className="mt-1.5 text-[10px] text-[#64736A]">
          {alarmClearObserved
            ? 'Confirm the clear alarm state to record resolution.'
            : 'Resolution requires a later source-clear reading and operator confirmation.'}
        </p>
      )}
      {actionError && <p role="alert" className="mt-2 rounded border border-[#D92D20]/30 bg-[#FEF3F2] px-3 py-2 text-xs text-[#D92D20]">{actionError}</p>}
    </div>
  );
}
