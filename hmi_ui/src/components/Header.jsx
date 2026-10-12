import React, { useState, useRef, useEffect } from 'react';
import { AlertTriangle, CheckCircle2, X, Clock, Tag, Layers } from 'lucide-react';

export default function Header({
  machineStatus,
  isIncident,
  simulating,
  simStep,
  totalSteps,
  pacingMode,
  setPacingMode,
  onStartIncident,
  onResetDemo,
  onResetScenario,
  operatorName,
  scenarios = [],
  selectedScenario = 'valve_restriction',
  onSelectScenario = () => {},
  equipmentId = 'Pump-02',
  primaryTag = null,
  causalLabel = null,
  fullEvent = null,
}) {
  const isAlarm = isIncident && (machineStatus?.status === 'CRITICAL_ALARM' || machineStatus?.primary_alarm);
  const [alarmOpen, setAlarmOpen] = useState(false);
  const popoverRef = useRef(null);

  // Close popover on outside click
  useEffect(() => {
    if (!alarmOpen) return;
    const handler = (e) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target)) setAlarmOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [alarmOpen]);

  // Build alarm detail data
  const candidate     = fullEvent?.candidate;
  const story         = fullEvent?.story;
  const evidence      = fullEvent?.evidence;
  const triggerTime   = candidate?.trigger_timestamp
    ? new Date(candidate.trigger_timestamp).toLocaleTimeString()
    : null;
  const correlatedTags = fullEvent?.correlated?.correlated_deviations?.map(d =>
    `${d.tag} (${d.deviation_pct >= 0 ? '+' : ''}${d.deviation_pct?.toFixed(0)}%)`
  ) || candidate?.clustered_tags || [];

  return (
    <header className="sticky top-0 z-40 bg-[#0A0E16]/98 backdrop-blur-md border-b border-[#1a2535] px-6 h-14 flex items-center shadow-xl">
      <div className="w-full flex items-center justify-between gap-4">

        {/* Left: Logo */}
        <div className="shrink-0">
          <img src="/opslens-logo.png" alt="OpsLens" className="h-7 w-auto object-contain" />
        </div>

        {/* Center: Status pill (clickable when incident active) */}
        <div className="flex-1 flex justify-center relative" ref={popoverRef}>
          <button
            onClick={() => isIncident && setAlarmOpen(v => !v)}
            className={`flex items-center gap-2.5 px-4 py-1.5 rounded-full border text-xs font-semibold tracking-wide transition-all duration-300 ${
              isIncident ? 'cursor-pointer hover:opacity-80' : 'cursor-default'
            } ${
              isAlarm
                ? 'bg-red-500/10 border-red-500/60 text-red-300'
                : isIncident
                ? 'bg-amber-500/10 border-amber-500/60 text-amber-300'
                : 'bg-emerald-500/10 border-emerald-500/40 text-emerald-400'
            }`}
          >
            <span className={`w-2 h-2 rounded-full shrink-0 ${
              isAlarm ? 'bg-red-500 animate-ping' : isIncident ? 'bg-amber-400' : 'bg-emerald-400'
            }`} />
            {isAlarm ? (
              <><AlertTriangle className="w-3.5 h-3.5" /> CRITICAL ALARM — {primaryTag}</>
            ) : isIncident ? (
              <><AlertTriangle className="w-3.5 h-3.5" /> {causalLabel || 'INCIDENT DETECTED'}</>
            ) : (
              <><CheckCircle2 className="w-3.5 h-3.5" /> SYSTEM RUNNING NOMINAL</>
            )}
          </button>

          {/* Alarm Detail Popover */}
          {alarmOpen && isIncident && (
            <div className="absolute top-full mt-2 left-1/2 -translate-x-1/2 w-[520px] z-50 rounded-xl border border-[#1a2535] bg-[#0d1420] shadow-2xl shadow-black/60 overflow-hidden">
              {/* Popover header */}
              <div className={`flex items-center justify-between px-4 py-3 border-b border-[#1a2535] ${isAlarm ? 'bg-red-500/10' : 'bg-amber-500/10'}`}>
                <div className="flex items-center gap-2">
                  <AlertTriangle className={`w-4 h-4 ${isAlarm ? 'text-red-400' : 'text-amber-400'}`} />
                  <span className={`text-xs font-bold uppercase tracking-wider ${isAlarm ? 'text-red-300' : 'text-amber-300'}`}>
                    {isAlarm ? 'Critical Alarm Detail' : 'Incident Detail'}
                  </span>
                </div>
                <button onClick={() => setAlarmOpen(false)} className="text-slate-500 hover:text-white transition-colors cursor-pointer">
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Content */}
              <div className="p-4 space-y-3 text-xs">
                {/* Causal label */}
                {causalLabel && (
                  <div>
                    <div className="text-[10px] font-mono uppercase tracking-widest text-slate-500 mb-0.5">Incident</div>
                    <div className="text-sm font-bold text-white">{causalLabel}</div>
                  </div>
                )}

                {/* Key facts grid */}
                <div className="grid grid-cols-2 gap-2">
                  {primaryTag && (
                    <div className="bg-[#0a0e16] rounded-lg px-3 py-2 border border-[#1a2535]">
                      <div className="flex items-center gap-1.5 text-[10px] text-slate-500 font-mono uppercase mb-1">
                        <Tag className="w-3 h-3" /> Primary Tag
                      </div>
                      <div className={`font-mono font-bold ${isAlarm ? 'text-red-400' : 'text-amber-400'}`}>{primaryTag}</div>
                    </div>
                  )}
                  {triggerTime && (
                    <div className="bg-[#0a0e16] rounded-lg px-3 py-2 border border-[#1a2535]">
                      <div className="flex items-center gap-1.5 text-[10px] text-slate-500 font-mono uppercase mb-1">
                        <Clock className="w-3 h-3" /> Triggered
                      </div>
                      <div className="font-mono font-bold text-slate-200">{triggerTime}</div>
                    </div>
                  )}
                  {evidence?.likely_contributor_tag && (
                    <div className="bg-[#0a0e16] rounded-lg px-3 py-2 border border-[#1a2535]">
                      <div className="text-[10px] text-slate-500 font-mono uppercase mb-1">Likely Cause</div>
                      <div className="font-mono font-bold text-amber-300">{evidence.likely_contributor_tag}</div>
                    </div>
                  )}
                  {equipmentId && (
                    <div className="bg-[#0a0e16] rounded-lg px-3 py-2 border border-[#1a2535]">
                      <div className="text-[10px] text-slate-500 font-mono uppercase mb-1">Equipment</div>
                      <div className="font-mono font-bold text-slate-200">{equipmentId}</div>
                    </div>
                  )}
                </div>

                {/* Correlated tags */}
                {correlatedTags.length > 0 && (
                  <div>
                    <div className="flex items-center gap-1.5 text-[10px] text-slate-500 font-mono uppercase mb-1.5">
                      <Layers className="w-3 h-3" /> Correlated Tags
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {correlatedTags.slice(0, 6).map((t, i) => (
                        <span key={i} className="px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-300 font-mono text-[11px]">
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Story steps */}
                {story?.steps?.length > 0 && (
                  <div>
                    <div className="text-[10px] text-slate-500 font-mono uppercase mb-1.5">Causal Chain</div>
                    <div className="flex items-center gap-1 flex-wrap">
                      {story.steps.map((s, i) => (
                        <React.Fragment key={i}>
                          <span className={`text-[10px] font-mono font-bold ${s.tag.startsWith('ALM-') ? 'text-red-400' : 'text-slate-300'}`}>
                            {s.tag}
                          </span>
                          {i < story.steps.length - 1 && <span className="text-slate-600 text-xs">→</span>}
                        </React.Fragment>
                      ))}
                    </div>
                  </div>
                )}

                {/* Operator name */}
                <div className="pt-1 border-t border-[#1a2535] text-[10px] text-slate-500 font-mono">
                  Operator on shift: <span className="text-slate-300">{operatorName}</span>
                </div>
              </div>
            </div>
          )}
        </div>

      </div>
    </header>
  );
}
