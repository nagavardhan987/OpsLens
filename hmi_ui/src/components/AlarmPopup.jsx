import React, { useEffect, useRef, useState } from 'react';
import { MessageSquareText, X, Zap } from 'lucide-react';

/**
 * Non-intrusive HMI alarm notification for NEWLY arriving alarms.
 * Suppresses itself when the operator has already seen the incident on the
 * main panel (tracked by dismissedEventId ref) to avoid duplicate banners
 * for an already-visible alarm.
 * Auto-dismisses after 20 s; operator can dismiss manually.
 */
export default function AlarmPopup({ event, isActive, onOpenCopilot, onDismiss }) {
  const [visible, setVisible] = useState(false);
  const [animateIn, setAnimateIn] = useState(false);
  const dismissedId = useRef(null);
  const isFirstMount = useRef(true);
  const timerRef = useRef(null);

  useEffect(() => {
    // Clear any pending timer when event changes
    clearTimeout(timerRef.current);

    const eventId = event?.event_id;

    // Suppress popup on first page load if an incident is already loaded
    // and shown prominently on the main dashboard overview card.
    if (isFirstMount.current) {
      isFirstMount.current = false;
      if (eventId) {
        dismissedId.current = eventId;
      }
      return;
    }

    // Don't show if:
    // - No event / not active
    // - Same event that was already dismissed or already loaded on mount
    if (!event || !isActive || !eventId || eventId === dismissedId.current) {
      setAnimateIn(false);
      setTimeout(() => setVisible(false), 280);
      return;
    }

    // A genuinely new event — show the popup
    setVisible(true);
    const showTimer = setTimeout(() => setAnimateIn(true), 10);

    // Auto-dismiss after 20 s
    timerRef.current = setTimeout(() => {
      dismissedId.current = eventId;
      setAnimateIn(false);
      setTimeout(() => setVisible(false), 280);
    }, 20000);

    return () => {
      clearTimeout(showTimer);
      clearTimeout(timerRef.current);
    };
  }, [event?.event_id, isActive]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDismiss = () => {
    dismissedId.current = event?.event_id;
    clearTimeout(timerRef.current);
    setAnimateIn(false);
    setTimeout(() => {
      setVisible(false);
      onDismiss?.();
    }, 280);
  };

  const handleOpenCopilot = () => {
    handleDismiss();
    onOpenCopilot?.();
  };

  if (!visible) return null;

  const candidate = event?.candidate || {};
  const story = event?.story || {};
  const evidence = event?.evidence || {};
  const guidance = event?.guidance || {};
  const steps = story.steps || [];
  const alarmStep = [...steps].reverse().find(s => String(s.tag || '').startsWith('ALM-'));
  const alarmId = alarmStep?.tag || candidate.primary_tag || candidate.alarm_id || 'Alarm';
  const equipment = (event?.correlated || {}).equipment_id || 'Equipment';
  const rawSeverity = event?.source_priority || candidate.source_priority || candidate.alarm_severity || event?.priority_interpretation?.display_priority;
  const isConfiguredPriority = typeof rawSeverity === 'string'
    && !['', 'UNKNOWN', 'NOT SUPPLIED', 'NONE', 'UNCONFIGURED', 'NULL'].includes(rawSeverity.trim().toUpperCase());
  const priorityLabel = isConfiguredPriority ? rawSeverity.trim() : (event?.urgency?.urgency_band || 'ROUTINE');

  const rootCause = evidence.likely_contributor_tag
    ? `Likely contributor: ${evidence.likely_contributor_tag}`
    : story.causal_label || 'Root cause under analysis';

  const nbaList = guidance.next_best_actions || [];
  const topAction = nbaList.slice(0, 1).map(a => typeof a === 'string' ? a : a.action || String(a))[0];

  const isHigh = priorityLabel?.toUpperCase().includes('HIGH') || priorityLabel?.toUpperCase().includes('CRITICAL') || priorityLabel?.toUpperCase().includes('URGENT');
  const borderColor = isHigh ? 'border-red-600/70' : 'border-amber-500/60';
  const dotColor = isHigh ? 'bg-red-400 animate-pulse' : 'bg-amber-400 animate-pulse';
  const labelColor = isHigh ? 'text-red-300' : 'text-amber-300';

  return (
    <div
      className={`fixed bottom-5 right-5 z-[100] w-[320px] rounded-xl border bg-slate-900/95 backdrop-blur-md shadow-2xl transition-all duration-280 ${borderColor} ${animateIn ? 'translate-y-0 opacity-100' : 'translate-y-6 opacity-0'}`}
      role="alertdialog"
      aria-label={`New alarm: ${alarmId}`}
      aria-live="assertive"
    >
      {/* Header row */}
      <div className="flex items-center justify-between px-3 pt-2.5 pb-1.5">
        <div className="flex items-center gap-1.5">
          <span className={`h-2 w-2 rounded-full ${dotColor}`} />
          <span className={`text-[10px] font-bold uppercase tracking-widest ${labelColor}`}>
            New Alarm · {isConfiguredPriority ? priorityLabel : `Urgency ${priorityLabel}`}
          </span>
        </div>
        <button
          onClick={handleDismiss}
          className="rounded p-0.5 text-slate-500 hover:text-white transition-colors"
          aria-label="Dismiss alarm notification"
        >
          <X size={13} />
        </button>
      </div>

      {/* Alarm ID & equipment */}
      <div className="px-3 pb-2">
        <div className="font-mono text-sm font-bold text-white">{alarmId}</div>
        <div className="text-[10px] text-slate-400">{equipment}</div>
      </div>

      {/* BLUF — one sentence root cause + top action */}
      <div className="border-t border-white/10 px-3 py-2 space-y-1.5">
        <div className="flex items-start gap-1.5 text-xs text-slate-200 leading-snug">
          <Zap size={11} className="mt-0.5 shrink-0 text-amber-400" />
          <span>{rootCause}</span>
        </div>
        {topAction && (
          <div className="text-[10px] text-slate-400 pl-4 leading-snug">
            Step 1: {topAction}
          </div>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex gap-2 border-t border-white/10 p-2.5">
        <button
          onClick={handleOpenCopilot}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500 transition-colors"
        >
          <MessageSquareText size={12} />
          Ask OpsLens
        </button>
        <button
          onClick={handleDismiss}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:text-white transition-colors"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
