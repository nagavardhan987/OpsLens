import React from 'react';
import { ShieldAlert, Layers } from 'lucide-react';

export default function AlarmPrioritization({
  isIncident,
  candidate = null,
  correlated = null,
  story = null,
  guidance = null,
  revealedStep = 5
}) {
  if (!isIncident || revealedStep < 4) {
    return (
      <div className="flex items-center justify-between px-4 py-2 rounded-lg border border-[#1a2535] bg-[#0d1420]">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          <span className="text-xs text-slate-400">
            <span className="text-emerald-400 font-semibold">0 Active Alarms</span> &nbsp;·&nbsp; Steady state monitoring
          </span>
        </div>
        <span className="text-[11px] text-slate-600 font-mono">OpsLens Edge · Passive</span>
      </div>
    );
  }

  const isAlarm = candidate?.primary_alarm;
  const primaryTag = candidate?.primary_tag || 'EXCURSION';
  const causalTitle = story?.causal_label || `${candidate?.equipment_id || 'Unit'} Incident`;
  const triggerTime = candidate?.trigger_timestamp
    ? new Date(candidate.trigger_timestamp).toLocaleTimeString()
    : 'LIVE';

  const correlatedList = correlated?.correlated_deviations?.length > 0
    ? correlated.correlated_deviations.map(d => `${d.tag} (${d.deviation_pct >= 0 ? '+' : ''}${d.deviation_pct.toFixed(0)}%)`)
    : (candidate?.clustered_tags || []).filter(t => t !== primaryTag);

  return (
    <div className={`flex items-center justify-between px-4 py-2.5 rounded-lg border-l-4 ${
      isAlarm ? 'border-l-red-500 bg-[#1a0e10] border border-red-500/20' : 'border-l-amber-500 bg-[#1a1608] border border-amber-500/20'
    }`}>
      <div className="flex items-center gap-3">
        <div className={`w-7 h-7 rounded flex items-center justify-center shrink-0 ${isAlarm ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'}`}>
          <ShieldAlert className="w-4 h-4" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${isAlarm ? 'bg-red-600 text-white' : 'bg-amber-600 text-white'}`}>
              {isAlarm ? 'CRITICAL' : 'INCIDENT'}
            </span>
            <span className="text-sm font-semibold text-white">{causalTitle}</span>
            <span className={`text-[11px] font-mono ${isAlarm ? 'text-red-400' : 'text-amber-400'}`}>
              {primaryTag} · {triggerTime}
            </span>
          </div>
        </div>
      </div>

      {correlatedList.length > 0 && (
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <Layers className="w-3.5 h-3.5 text-amber-500 shrink-0" />
          <span className="text-[11px] font-mono">
            {correlatedList.slice(0, 3).join(' · ')}
          </span>
        </div>
      )}
    </div>
  );
}
