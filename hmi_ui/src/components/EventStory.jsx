import React from 'react';
import { Clock, Sparkles, ChevronDown } from 'lucide-react';

function parseEventTimestamp(timestamp) {
  if (typeof timestamp !== 'string' || timestamp.trim() === '') return null;
  const ms = Date.parse(timestamp);
  return Number.isFinite(ms) ? ms : null;
}

/** Short relative time for the main timeline row */
function formatRelativeTime(ms) {
  if (!Number.isFinite(ms) || ms < 0) return null;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

/** Full timestamp for engineering details */
function formatFullTimestamp(timestamp) {
  const ms = parseEventTimestamp(timestamp);
  if (ms === null) return 'Timestamp unavailable';
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit', second: '2-digit', timeZoneName: 'short',
  }).format(ms);
}

export default function EventStory({ story = null, isIncident = false, revealedCount = 5 }) {
  const steps = story?.steps || [];

  if (!isIncident || steps.length === 0) {
    return (
      <div className="flex min-h-[80px] items-center justify-center gap-2 rounded-lg border border-[#1a2535] bg-[#0d1420] p-4 text-xs text-slate-500">
        <Clock className="h-4 w-4 shrink-0 text-slate-600" />
        Awaiting incident — timeline will appear here
      </div>
    );
  }

  const timestamps = steps.map((s) => parseEventTimestamp(s.timestamp));
  const validTs = timestamps.filter((t) => t !== null);
  const causalLabel = story?.causal_label || 'Recorded incident sequence';
  const totalDuration = validTs.length > 1
    ? formatRelativeTime(Math.max(...validTs) - Math.min(...validTs))
    : null;

  return (
    <div className="rounded-lg border border-[#1a2535] bg-[#0d1420] overflow-hidden">
      {/* Compact header */}
      <div className="flex items-center justify-between border-b border-[#1a2535] px-4 py-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-5 w-5 items-center justify-center rounded bg-[#00A344]/15 border border-[#00A344]/30">
            <Sparkles className="h-3 w-3 text-[#00D65A]" />
          </div>
          <span className="text-xs font-semibold text-slate-200">{causalLabel}</span>
        </div>
        {totalDuration && (
          <span className="text-[10px] font-mono text-amber-400/80 bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 rounded whitespace-nowrap">
            {totalDuration} total
          </span>
        )}
      </div>

      {/* Timeline as readable vertical list */}
      <ol className="divide-y divide-[#1a2535]">
        {steps.map((step, idx) => {
          const isRevealed = idx < revealedCount;
          const isAlarm = String(step.tag || '').startsWith('ALM-');
          const isActive = idx === revealedCount - 1;
          const eventTime = timestamps[idx];
          const prevTime = idx > 0 ? timestamps[idx - 1] : null;
          const elapsed = idx === 0
            ? 'Start'
            : eventTime !== null && prevTime !== null
              ? `+${formatRelativeTime(eventTime - prevTime)}`
              : '—';

          const hasDeviation = !isAlarm
            && Number.isFinite(step.value_before)
            && Number.isFinite(step.value_after)
            && step.value_before !== 0;
          const deltaPct = hasDeviation
            ? ((step.value_after - step.value_before) / step.value_before) * 100
            : null;

          return (
            <li
              key={idx}
              className={`grid items-start gap-x-3 px-4 py-2.5 transition-opacity
                grid-cols-[28px_minmax(0,1fr)_56px]
                ${!isRevealed ? 'opacity-25' : ''}
                ${isAlarm ? 'bg-red-950/20' : isActive ? 'bg-[#0a1810]' : ''}
              `}
            >
              {/* Step badge */}
              <div className="flex flex-col items-center gap-1 pt-0.5">
                <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[9px] font-black
                  ${!isRevealed ? 'bg-slate-800 text-slate-600'
                    : isAlarm ? 'bg-red-600 text-white'
                    : isActive ? 'bg-[#00A344] text-black'
                    : 'bg-[#1a2535] text-slate-400'}`}>
                  {step.step_number || idx + 1}
                </span>
                {idx < steps.length - 1 && (
                  <div className={`w-px h-3 ${isRevealed ? 'bg-[#2a3848]' : 'bg-[#1a2535]'}`} />
                )}
              </div>

              {/* Main content */}
              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <span className={`font-mono text-[10px] font-bold whitespace-nowrap
                    ${isAlarm ? 'text-red-400' : 'text-amber-400'}`}>
                    {step.tag}
                  </span>
                  <span className="text-xs text-slate-300 leading-snug">
                    {step.description || 'Event description unavailable'}
                  </span>
                </div>

                {/* Engineering details — collapsed by default */}
                <details className="mt-1 group">
                  <summary className="cursor-pointer text-[9px] text-slate-600 hover:text-slate-400 list-none select-none flex items-center gap-1">
                    <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
                    Engineering detail
                  </summary>
                  <div className="mt-1 space-y-0.5 text-[9px] font-mono text-slate-500">
                    <div>Time: {formatFullTimestamp(step.timestamp)}</div>
                    {deltaPct !== null && (
                      <div>
                        Δ {deltaPct >= 0 ? '+' : ''}{deltaPct.toFixed(1)}%
                        {' '}({step.value_before} → {step.value_after})
                        <span className="ml-1 text-slate-600">percentage-point change relative to prior reading</span>
                      </div>
                    )}
                    {isAlarm && <div className="text-red-400">TRIP ACTIVE</div>}
                  </div>
                </details>
              </div>

              {/* Elapsed time badge */}
              <div className="text-right">
                <span className="text-[9px] font-mono text-slate-500 whitespace-nowrap">{elapsed}</span>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
