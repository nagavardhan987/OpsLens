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

export default function EventStory({ story = null, isIncident = false, revealedCount = 5, compact = false, selectedStep = null, onSelectStep, dataSource = null, relatedAlarm = null }) {
  const rawSteps = story?.steps || [];
  const steps = compact ? rawSteps : [...rawSteps].sort((left, right) => {
    const leftTime = parseEventTimestamp(left.timestamp);
    const rightTime = parseEventTimestamp(right.timestamp);
    if (leftTime === null) return rightTime === null ? 0 : 1;
    if (rightTime === null) return -1;
    return leftTime - rightTime;
  });

  if (!isIncident || steps.length === 0) {
    return (
      <div className="flex min-h-[80px] items-center justify-center gap-2 rounded-xl border border-[#D8E2DA] bg-white p-4 text-xs text-[#64736A]">
        <Clock className="h-4 w-4 shrink-0 text-[#64736A]" />
        Awaiting incident — timeline will appear here
      </div>
    );
  }

  const timestamps = steps.map((s) => parseEventTimestamp(s.timestamp));
  const validTs = timestamps.filter((t) => t !== null);
  const totalDuration = validTs.length > 1
    ? formatRelativeTime(Math.max(...validTs) - Math.min(...validTs))
    : null;

  if (compact) {
    return (
      <div className="event-story-compact" aria-label="Recorded incident timeline">
        <div className="event-story-track">
          {steps.map((step, idx) => {
            const isAlarm = String(step.tag || '').startsWith('ALM-');
            const elapsed = idx === 0 ? 'Start' : timestamps[idx] !== null && timestamps[idx - 1] !== null
              ? `+${formatRelativeTime(timestamps[idx] - timestamps[idx - 1])}` : 'Time unavailable';
            return <button type="button" key={`${step.tag || 'step'}-${idx}`}
              className={`event-story-node ${isAlarm ? 'alarm' : ''} ${selectedStep === idx ? 'selected' : ''}`}
              onClick={() => onSelectStep?.(idx)} aria-pressed={selectedStep === idx}>
              <span className="event-story-node-time">{elapsed}</span>
              <strong>{step.tag || 'Event'}</strong>
              <span>{step.description || 'Recorded event description unavailable'}</span>
              {step.value_after != null && <small>{step.data_source === 'calculated_from_configured_baseline' ? 'Derived' : 'Recorded'} {step.value_after}{step.unit ? ` ${step.unit}` : ''}</small>}
            </button>;
          })}
        </div>
        {selectedStep != null && steps[selectedStep] && <div className="event-story-selection">
          <strong>{steps[selectedStep].tag || 'Selected event'}</strong>
          <span>{steps[selectedStep].description || 'Recorded event description unavailable'}</span>
          <small>{formatFullTimestamp(steps[selectedStep].timestamp)}{steps[selectedStep].value_after != null ? ` · ${steps[selectedStep].value_before ?? 'Previous value unavailable'} → ${steps[selectedStep].value_after}${steps[selectedStep].unit ? ` ${steps[selectedStep].unit}` : ''}` : ''}</small>
        </div>}
      </div>
    );
  }

  return (
    <div className="event-story rounded-xl border border-[#D8E2DA] bg-white overflow-hidden shadow-sm">
      {/* Compact header */}
      <div className="flex items-center justify-between border-b border-[#D8E2DA] bg-[#F3F6F3] px-4 py-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-5 w-5 items-center justify-center rounded bg-[#E8F5EC] border border-[#009530]/30">
            <Sparkles className="h-3 w-3 text-[#009530]" />
          </div>
          <span className="text-xs font-semibold text-[#26352C]">Incident timeline</span>
        </div>
        {totalDuration && (
          <span className="text-[10px] font-mono text-[#B7791F] bg-[#FEF0C7] border border-[#B7791F]/30 px-2 py-0.5 rounded whitespace-nowrap font-medium">
            {totalDuration} total
          </span>
        )}
      </div>

      <p className="border-b border-[#D8E2DA] bg-[#F8FAF8] px-4 py-2 text-[10px] text-[#53695A]">Events are shown in recorded time order. Timing or ranked association does not prove physical causation.</p>
      {/* Timeline as readable vertical list */}
      <ol className="divide-y divide-[#D8E2DA]">
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

          const hasNumericDeviation = Number.isFinite(step.value_before)
            && Number.isFinite(step.value_after)
            && step.value_before !== 0;
          const absoluteChange = hasNumericDeviation ? step.value_after - step.value_before : null;
          const relativeChange = hasNumericDeviation ? (absoluteChange / Math.abs(step.value_before)) * 100 : null;
          const isPercentageTag = step.unit === '%';
          const source = String(step.data_source || step.source || dataSource || 'unknown').toLowerCase();
          const sourceLabel = /simulat|synthetic/.test(source) ? 'SIMULATED'
            : /opc.?ua|plc/.test(source) ? 'LIVE PLC'
              : /stale/.test(String(step.data_quality || '').toLowerCase()) ? 'STALE'
                : /disconnect/.test(String(step.connection_status || '').toLowerCase()) ? 'DISCONNECTED'
                  : /calculated_from_configured_baseline/.test(source) ? 'DERIVED' : 'RECORDED';

          return (
            <li
              key={idx}
              className={`grid items-start gap-x-3 px-4 py-2.5 transition-opacity
                grid-cols-[28px_minmax(0,1fr)_56px]
                ${!isRevealed ? 'opacity-40' : ''}
                ${isAlarm ? 'bg-[#FEF3F2]' : isActive ? 'bg-[#F0FDF4]' : 'hover:bg-[#F8FAF8]'}
              `}
            >
              {/* Step badge */}
              <div className="flex flex-col items-center gap-1 pt-0.5">
                <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[9px] font-black
                  ${!isRevealed ? 'bg-[#E8ECE8] text-[#64736A]'
                    : isAlarm ? 'bg-[#D92D20] text-white'
                    : isActive ? 'bg-[#009530] text-white'
                    : 'bg-[#E8F5EC] text-[#006B35]'}`}>
                  {step.step_number || idx + 1}
                </span>
                {idx < steps.length - 1 && (
                  <div className={`w-px h-3 ${isRevealed ? 'bg-[#D8E2DA]' : 'bg-[#E8ECE8]'}`} />
                )}
              </div>

              {/* Main content */}
              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <span className={`font-mono text-[10px] font-bold whitespace-nowrap
                    ${isAlarm ? 'text-[#D92D20]' : 'text-[#B7791F]'}`}>
                    {step.tag}
                  </span>
                  <span className="text-xs text-[#26352C] leading-snug">
                    {step.description || 'Event description unavailable'}
                  </span>
                </div>

                {/* Engineering details — collapsed by default */}
                <details className="mt-1 group">
                  <summary className="cursor-pointer text-[9px] text-[#64736A] hover:text-[#26352C] list-none select-none flex items-center gap-1">
                    <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
                    Reading details
                  </summary>
                  <div className="mt-1 space-y-0.5 text-[9px] font-mono text-[#64736A]">
                    <div>Time: {formatFullTimestamp(step.timestamp)}</div>
                    <div>Source: {sourceLabel}</div>
                    <div>Event type: {isAlarm ? 'Alarm' : 'Process reading'}</div>
                    {relatedAlarm && <div>Related alarm: {relatedAlarm}</div>}
                    {step.value_after != null && <div>Previous → current: {step.value_before ?? 'Unavailable'} → {step.value_after}{step.unit ? ` ${step.unit}` : ''}</div>}
                    {absoluteChange !== null && (
                      <div>
                        Absolute change: {absoluteChange >= 0 ? '+' : ''}{absoluteChange.toFixed(2)} {isPercentageTag ? 'percentage points' : (step.unit || '')}
                        {relativeChange !== null && <span> · Relative change: {relativeChange >= 0 ? '+' : ''}{relativeChange.toFixed(1)}%</span>}
                      </div>
                    )}
                    <div>Data quality: {step.data_quality || 'not recorded'}</div>
                    {isAlarm && <div className="text-[#D92D20] font-bold">TRIP ACTIVE</div>}
                  </div>
                </details>
              </div>

              {/* Elapsed time badge */}
              <div className="text-right">
                <span className="text-[9px] font-mono text-[#64736A] whitespace-nowrap">{elapsed}</span>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
