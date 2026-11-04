import React from 'react';
import { AlertTriangle, Clock3, RefreshCw, ShieldAlert, ShieldCheck, Zap } from 'lucide-react';

function formatTimestamp(value) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Time unavailable';
  return new Intl.DateTimeFormat(undefined, {
    month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit', second: '2-digit', timeZoneName: 'short'
  }).format(new Date(value));
}

export default function IncidentOverview({ event, equipment, isActive }) {
  const candidate = event?.candidate || {};
  const steps = event?.story?.steps || [];
  const contextEvent = event?.context?.selected_event || {};
  const alarmId = contextEvent.alarm_id 
    || candidate.alarm_id 
    || candidate.primary_tag 
    || event?.primary_tag 
    || [...steps].reverse().find((step) => String(step.tag || '').startsWith('ALM-'))?.tag 
    || steps[0]?.tag 
    || 'Active Incident';

  const triggerTimestamp = contextEvent.timestamp || candidate.trigger_timestamp;
  const storyTimestamp = contextEvent.event_story_alarm_timestamp || [...steps].reverse().find((step) => String(step.tag || '').startsWith('ALM-'))?.timestamp;
  const timestampDiffers = triggerTimestamp && storyTimestamp && Date.parse(triggerTimestamp) !== Date.parse(storyTimestamp);
  
  // Phase 1 & 2: Source priority must NEVER default to 'HIGH'.
  // Only valid plant-configured priorities are displayed as configured.
  const rawSeverity = event?.source_priority || candidate.source_priority || candidate.alarm_severity;
  const isConfiguredPriority = typeof rawSeverity === 'string'
    && !['', 'UNKNOWN', 'NOT SUPPLIED', 'NONE', 'UNCONFIGURED', 'NULL'].includes(rawSeverity.trim().toUpperCase());
  const configuredPriority = isConfiguredPriority ? rawSeverity.trim() : null;

  // Phase 2: Urgency assessment
  const urgency = event?.urgency || {};
  const ttl = urgency.time_to_limit;
  const repeatCount = event?.repeat_count || 1;
  const lifecycleState = event?.lifecycle_state || 'ACTIVE';
  const triggeredRules = urgency.triggered_rules || [];
  const scoringBreakdown = urgency.scoring_breakdown || {};

  return (
    <section id="incident" className={`incident-panel ${isActive ? 'active' : 'history'}`}>
      {/* Topline: Alarm ID, Severity, Advisory pill, and Timestamp */}
      <div className="incident-topline flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <div className={`incident-icon ${isActive ? 'active' : ''}`}>
            <ShieldAlert size={20} />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`state-pill ${isActive ? 'danger' : 'neutral'}`}>
                {isActive ? 'Active alarm' : event?.status === 'RESOLVED' ? 'Operator reported clear' : 'Incident history'}
              </span>
              <span className={`severity-pill ${configuredPriority ? 'configured' : 'unknown'}`}>
                Severity · {configuredPriority || 'Not supplied'}
              </span>
              {repeatCount > 1 && (
                <span className="inline-flex items-center gap-1 rounded bg-orange-900/30 border border-orange-700/30 px-2 py-0.5 text-[9px] font-bold text-orange-400">
                  <RefreshCw size={9} />
                  ×{repeatCount}
                </span>
              )}
              {lifecycleState === 'RECURRING' && (
                <span className="inline-flex items-center gap-1 rounded bg-red-900/30 border border-red-700/30 px-2 py-0.5 text-[9px] font-bold text-red-400">
                  RECURRING
                </span>
              )}
            </div>
            <h1 className="mt-1.5 truncate text-xl font-bold tracking-tight text-white sm:text-2xl">
              {alarmId}
            </h1>
            <p className="text-xs font-medium text-slate-400">
              Equipment: <span className="text-slate-200">{equipment || 'Not specified'}</span>
            </p>
          </div>
        </div>

        {/* Time display */}
        <div className="incident-time text-right sm:text-left">
          <span className="section-kicker">Alarm time</span>
          <div className="mt-1 flex items-center gap-1.5 text-xs font-mono font-medium text-slate-200">
            <Clock3 size={13} className="text-slate-400 shrink-0" />
            {formatTimestamp(triggerTimestamp)}
          </div>
          {timestampDiffers && (
            <details className="timestamp-details mt-1 text-left">
              <summary className="text-[10px] text-amber-400 cursor-pointer flex items-center gap-1">
                <AlertTriangle size={11} />
                Sequence timing note
              </summary>
              <p className="text-[10px] text-slate-400 mt-1">
                Alarm trigger: {formatTimestamp(triggerTimestamp)}<br />
                Sequence start: {formatTimestamp(storyTimestamp)}
              </p>
            </details>
          )}
        </div>
      </div>

      {/* Time-to-limit banner — only when TTL is estimated and critical */}
      {ttl && ttl.time_to_limit_seconds != null && ttl.time_to_limit_seconds <= 120 && (
        <div className="mt-2 flex items-center gap-2 rounded-lg border border-amber-600/40 bg-amber-900/20 px-3 py-2">
          <Zap size={13} className="text-amber-400 shrink-0" />
          <span className="text-xs text-amber-200">
            <strong>Estimated time to threshold:</strong> ~{Math.round(ttl.time_to_limit_seconds)}s
            {' · '}{ttl.direction} toward {ttl.target_limit}
          </span>
        </div>
      )}

      {/* Urgency details and scoring breakdown */}
      {(triggeredRules.length > 0 || Object.keys(scoringBreakdown).length > 0 || urgency.ttl_unavailable_reason) && (
        <details className="mt-2 rounded-lg border border-slate-700/50 bg-slate-900/40">
          <summary className="cursor-pointer px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            Priority details {triggeredRules.length > 0 && `· ${triggeredRules.length} rules`}
          </summary>
          <div className="px-3 pb-2 space-y-1.5 text-[10px]">
            {triggeredRules.length > 0 && (
              <div>
                <span className="font-semibold text-amber-300">Triggered Rules:</span>
                <ul className="mt-0.5 space-y-0.5 font-mono text-amber-400">
                  {triggeredRules.map(r => (
                    <li key={r}>• {r}</li>
                  ))}
                </ul>
              </div>
            )}
            {Object.keys(scoringBreakdown).length > 0 && (
              <div className="pt-1 border-t border-slate-800">
                <span className="font-semibold text-slate-300">Priority calculation:</span>
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-slate-300">
                  <span>D (Dev 35%): {scoringBreakdown.D_deviation}</span>
                  <span>R (Rate 25%): {scoringBreakdown.R_rate}</span>
                  <span>E (Evidence 20%): {scoringBreakdown.E_evidence}</span>
                  <span>P (Persistence 10%): {scoringBreakdown.P_persistence}</span>
                  <span>Q (Quality 10%): {scoringBreakdown.Q_quality}</span>
                </div>
              </div>
            )}
            {urgency.ttl_unavailable_reason && (
              <div className="pt-1 border-t border-slate-800 text-slate-400 italic">
                Time-to-limit note: {urgency.ttl_unavailable_reason}
              </div>
            )}
            {ttl?.assumptions && <div className="pt-1 border-t border-slate-800 text-slate-400">Threshold estimate basis: {ttl.assumptions}</div>}
            {(urgency.urgency_reasons || []).length > 0 && (
              <ul className="pt-1 border-t border-slate-800 space-y-0.5 text-slate-400">
                {(urgency.urgency_reasons || []).map((reason, i) => (
                  <li key={i}>{reason}</li>
                ))}
              </ul>
            )}
          </div>
        </details>
      )}

      {/* Streamlined runtime state indicator */}
      <div className={`runtime-state mt-2.5 pt-2 text-[11px] border-t border-slate-800/60 ${
        event?.runtime_alarm_state?.active === true || isActive ? 'danger' :
        event?.runtime_alarm_state?.active === false ? 'clear' : 'unknown'
      }`}>
        <span className="hmi-dot shrink-0" />
        <span>
          {event?.runtime_alarm_state?.active === true
            ? `Alarm input active · ${equipment || 'unit'}`
            : event?.runtime_alarm_state?.active === false
            ? 'Alarm input clear · operator confirmation required'
            : isActive
            ? `Active alarm · ${equipment || 'unit'}`
            : 'Alarm inactive in this record'}
        </span>
      </div>
    </section>
  );
}
