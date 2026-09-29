import React from 'react';
import { ChevronRight, Sparkles, Clock } from 'lucide-react';

export default function EventStory({ story = null, isIncident = false, revealedCount = 5 }) {
  const steps = story?.steps || [];

  if (!isIncident || steps.length === 0) {
    return (
      <div className="rounded-xl border border-[#1a2535] bg-[#0d1420] p-5 flex flex-col items-center justify-center min-h-[120px]">
        <Clock className="w-5 h-5 text-slate-600 mb-2" />
        <p className="text-xs text-slate-500">Awaiting incident — timeline will appear here</p>
      </div>
    );
  }

  let leadTimeSec = null;
  if (steps.length > 1) {
    try {
      const t0 = new Date(steps[0].timestamp).getTime();
      const tEnd = new Date(steps[steps.length - 1].timestamp).getTime();
      const diff = Math.round((tEnd - t0) / 1000);
      if (diff > 0) leadTimeSec = diff;
    } catch (_) {}
  }

  const causalLabel = story?.causal_label || 'Causal Sequence';

  return (
    <div className="rounded-xl border border-[#00A344]/30 bg-[#0d1420] p-5 relative overflow-hidden">
      {/* Subtle glow */}
      <div className="absolute -top-12 -right-12 w-40 h-40 bg-[#00A344]/5 rounded-full blur-3xl pointer-events-none" />

      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-[#00A344]/15 border border-[#00A344]/40 flex items-center justify-center">
            <Sparkles className="w-3.5 h-3.5 text-[#00D65A]" />
          </div>
          <div>
            <div className="text-[10px] font-mono uppercase tracking-widest text-[#00D65A]">Causal Chain</div>
            <div className="text-sm font-bold text-white leading-tight">{causalLabel}</div>
          </div>
        </div>
        {leadTimeSec && (
          <span className="text-[11px] font-mono text-amber-400 bg-amber-500/10 border border-amber-500/20 px-2 py-1 rounded">
            {leadTimeSec}s lead time
          </span>
        )}
      </div>

      {/* Steps */}
      <div className={`grid gap-3`} style={{ gridTemplateColumns: `repeat(${steps.length}, 1fr)` }}>
        {steps.map((step, idx) => {
          const isRevealed = idx < revealedCount;
          const isAlarm = step.tag.startsWith('ALM-');
          const isActive = idx === revealedCount - 1;
          let deltaPct = 0;
          if (step.value_before && step.value_before !== 0 && step.value_after !== null)
            deltaPct = ((step.value_after - step.value_before) / step.value_before) * 100;

          return (
            <div key={idx} className="relative">
              {/* Connector arrow */}
              {idx < steps.length - 1 && isRevealed && (
                <ChevronRight className="absolute -right-1.5 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-600 z-10" />
              )}
              <div className={`rounded-lg p-3 border h-full flex flex-col gap-2 transition-all duration-500 ${
                !isRevealed
                  ? 'opacity-20 border-[#1a2535] bg-[#0a0e16]'
                  : isAlarm
                  ? 'border-red-500/60 bg-[#150e10] ring-1 ring-red-500/30'
                  : isActive
                  ? 'border-[#00A344]/60 bg-[#0d1a12] ring-1 ring-[#00A344]/20'
                  : 'border-[#1a2535] bg-[#0d1420]'
              }`}>
                {/* Step badge + tag */}
                <div className="flex items-center justify-between">
                  <span className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded uppercase ${
                    !isRevealed ? 'bg-slate-800 text-slate-600'
                    : isAlarm ? 'bg-red-600/80 text-white'
                    : 'bg-[#00A344]/20 text-[#00D65A]'
                  }`}>
                    S{step.step_number || idx + 1}
                  </span>
                  <span className={`text-[10px] font-mono font-bold ${isAlarm ? 'text-red-400' : 'text-amber-400'}`}>
                    {step.tag}
                  </span>
                </div>

                {/* Description */}
                <p className="text-[11px] text-slate-400 leading-snug flex-1">
                  {step.description?.split(' ').slice(0, 10).join(' ')}{step.description?.split(' ').length > 10 ? '…' : ''}
                </p>

                {/* Value */}
                <div className={`text-[10px] font-mono text-center rounded py-1 ${
                  !isRevealed ? 'bg-[#0a0e16] text-slate-700'
                  : isAlarm ? 'bg-red-950/50 text-red-300'
                  : 'bg-[#0a0e16] text-amber-300'
                }`}>
                  {isAlarm ? 'TRIP ACTIVE' : `${deltaPct >= 0 ? '+' : ''}${deltaPct.toFixed(1)}%`}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
