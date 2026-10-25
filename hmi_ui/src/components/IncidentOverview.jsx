import React from 'react';
import { AlertTriangle, BookOpen, Clock3, MessageSquareText, RefreshCw, ShieldAlert, ShieldCheck, Zap } from 'lucide-react';

const URGENCY_STYLES = {
  URGENT:   { pill: 'bg-red-500/15 border border-red-500/40 text-red-300',   dot: 'bg-red-400 animate-pulse' },
  ELEVATED: { pill: 'bg-amber-500/15 border border-amber-500/40 text-amber-300', dot: 'bg-amber-400 animate-pulse' },
  ROUTINE:  { pill: 'bg-slate-700/40 border border-slate-600/40 text-slate-400', dot: 'bg-slate-500' },
  UNKNOWN:  { pill: 'bg-slate-800/40 border border-slate-700/40 text-slate-500', dot: 'bg-slate-600' },
};

function formatTimestamp(value) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Time unavailable';
  return new Intl.DateTimeFormat(undefined, {
    month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit', second: '2-digit', timeZoneName: 'short'
  }).format(new Date(value));
}

export default function IncidentOverview({ event, equipment, isActive, onOpenSop, onAskOpsLens }) {
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
  const rawSeverity = event?.source_priority || candidate.source_priority || candidate.alarm_severity || event?.priority_interpretation?.display_priority;
  const isConfiguredPriority = typeof rawSeverity === 'string'
    && !['', 'UNKNOWN', 'NOT SUPPLIED', 'NONE', 'UNCONFIGURED', 'NULL'].includes(rawSeverity.trim().toUpperCase());
  const configuredPriority = isConfiguredPriority ? rawSeverity.trim() : null;

  const evidence = event?.evidence || {};
  const sop = event?.sop_match || {};
  const hasSop = sop.sop_id && !['NONE', 'SOP-NONE', 'UNKNOWN-SOP'].includes(sop.sop_id);

  // Phase 2: Urgency assessment
  const urgency = event?.urgency || {};
  const urgencyBand = urgency.urgency_band || 'UNKNOWN';
  const urgencyScore = urgency.urgency_score;
  const urgencyStyle = URGENCY_STYLES[urgencyBand] || URGENCY_STYLES.UNKNOWN;
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
              {/* Separate Source Priority: honest representation, never inventing HIGH */}
              <span className={`severity-pill ${configuredPriority ? 'configured' : 'unknown'}`}>
                {configuredPriority ? `Source priority: ${configuredPriority}` : 'Source priority: Not supplied'}
              </span>
              {/* Distinct Provisional OpsLens Urgency Badge */}
              {urgencyBand !== 'UNKNOWN' ? (
                <span className={`inline-flex items-center gap-1.5 rounded px-2.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${urgencyStyle.pill}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${urgencyStyle.dot}`} />
                  OpsLens Urgency: {urgencyBand}
                  {urgencyScore != null && <span className="ml-0.5 font-mono opacity-80">{Math.round(urgencyScore)}/100</span>}
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 rounded px-2.5 py-0.5 text-[9px] font-bold uppercase tracking-wider bg-slate-800/40 border border-slate-700/40 text-slate-500">
                  OpsLens Urgency: Unavailable
                </span>
              )}
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
              <span className="inline-flex items-center gap-1 rounded bg-emerald-950/40 border border-emerald-600/30 px-2 py-0.5 text-[9px] font-mono text-emerald-400">
                <ShieldCheck size={11} />
                Advisory Only · No PLC Writes
              </span>
            </div>
            <h1 className="mt-1.5 truncate text-xl font-bold tracking-tight text-white sm:text-2xl">
              {alarmId}
            </h1>
            <p className="text-xs font-medium text-slate-400">
              Target equipment: <span className="text-slate-200">{equipment || 'Not specified'}</span>
            </p>
          </div>
        </div>

        {/* Time display */}
        <div className="incident-time text-right sm:text-left">
          <span className="section-kicker">Alarm trigger time</span>
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
            <strong>Time-to-limit estimate:</strong> ~{Math.round(ttl.time_to_limit_seconds)}s
            {' · '}{ttl.direction} toward {ttl.target_limit}
            {' · '}<span className="text-[10px] text-amber-400/70">{ttl.assumptions}</span>
          </span>
        </div>
      )}

      {/* Urgency details and scoring breakdown */}
      {(triggeredRules.length > 0 || Object.keys(scoringBreakdown).length > 0 || urgency.ttl_unavailable_reason) && (
        <details className="mt-2 rounded-lg border border-slate-700/50 bg-slate-900/40">
          <summary className="cursor-pointer px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            OpsLens Urgency Assessment Details {triggeredRules.length > 0 && `· Rules active: ${triggeredRules.length}`}
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
                <span className="font-semibold text-slate-300">Scoring Breakdown (Formula U = 0.35D + 0.25R + 0.20E + 0.10P + 0.10Q):</span>
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

      {/* Summary and Quick Actions */}
      <div className="incident-bottomline flex flex-wrap items-center justify-between gap-4 mt-3 pt-3 border-t border-slate-800">
        <div className="incident-explanation flex-1 min-w-[280px]">
          <span className="section-kicker">Operator summary</span>
          <p className="mt-0.5 text-xs leading-relaxed text-slate-200">
            {evidence.likely_contributor_tag ? (
              <>
                Evidence Engine ranks <strong className="font-mono text-amber-300">{evidence.likely_contributor_tag}</strong> as
                the primary contributor. Hypothesis based on temporal correlations — human verification required.
              </>
            ) : (
              'Incident sequence recorded. Check telemetry trends and confirm process condition.'
            )}
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {hasSop && (
            <button
              type="button"
              onClick={onOpenSop}
              className="hmi-secondary-button"
              aria-label="View matched standard operating procedure"
            >
              <BookOpen size={14} />
              <span>SOP: {sop.sop_id}</span>
            </button>
          )}
          {onAskOpsLens && (
            <button
              type="button"
              onClick={onAskOpsLens}
              className="hmi-primary-button"
              aria-label="Open Ask OpsLens Copilot for this incident"
            >
              <MessageSquareText size={14} />
              <span>Ask OpsLens</span>
            </button>
          )}
        </div>
      </div>

      {/* Streamlined runtime state indicator */}
      <div className={`runtime-state mt-2.5 pt-2 text-[11px] border-t border-slate-800/60 ${
        event?.runtime_alarm_state?.active === true || isActive ? 'danger' :
        event?.runtime_alarm_state?.active === false ? 'clear' : 'unknown'
      }`}>
        <span className="hmi-dot shrink-0" />
        <span>
          {event?.runtime_alarm_state?.active === true
            ? `Telemetry excursion confirmed active on ${equipment || 'unit'}`
            : event?.runtime_alarm_state?.active === false
            ? 'Alarm condition normalized in runtime · operator clear confirmation required'
            : isActive
            ? `Active excursion on ${equipment || 'unit'} · advisory guidance active`
            : 'Alarm state inactive in current record'}
        </span>
      </div>
    </section>
  );
}
