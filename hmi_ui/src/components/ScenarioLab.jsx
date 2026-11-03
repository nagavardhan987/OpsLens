import React, { useState } from 'react';
import { Play, RotateCcw, Zap, ShieldCheck, AlertTriangle, RefreshCw } from 'lucide-react';
import { resolvePrimaryScenarioCatalog } from '../lib/scenarioCatalog';

function formatTimestamp(value) {
  if (!value) return 'Just now';
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  return new Intl.DateTimeFormat(undefined, {
    hour: 'numeric', minute: '2-digit', second: '2-digit', timeZoneName: 'short',
  }).format(timestamp);
}

export default function ScenarioLab({
  scenarios,
  selectedScenario,
  onSelectScenario,
  simulating,
  isIncident,
  onStart,
  onResetDemo,
  simulationStatus = {},
  recoveryBusy = false,
  onSimulatedRecovery,
  repeatBusy = false,
  repeatError = '',
  onTriggerAlarmRepeat,
}) {
  const [error, setError] = useState('');
  const { scenarios: choices, withSop, withoutEquipmentSop } = resolvePrimaryScenarioCatalog(scenarios);
  const selectedDetails = choices.find((scenario) => scenario.scenario_id === selectedScenario);
  const recoverySupported = ['valve_restriction', 'valve_restriction_cascade', 'scenario_a'].includes(simulationStatus.scenario_id);

  const start = async () => {
    setError('');
    const started = await onStart();
    if (!started) setError('Scenario could not be started. Try again.');
  };

  return (
    <main className="flex-1 px-6 py-8 max-w-5xl w-full mx-auto space-y-6">
      <header>
        <p className="text-xs font-mono uppercase tracking-[0.22em] text-[#009530] font-bold">DEMO & SIMULATION</p>
        <h1 className="mt-2 text-3xl font-bold text-[#26352C]">Scenario Lab</h1>
        <p className="mt-2 text-[#64736A]">Ten primary simulated incident and monitoring cases. Each run is retained as a separate incident record.</p>
      </header>

      <section className="rounded-2xl border border-[#D8E2DA] bg-white p-6 space-y-5 shadow-sm">
        <label className="block text-sm font-semibold text-[#26352C]" htmlFor="scenario-select">Scenario</label>
        <select id="scenario-select" value={selectedScenario} onChange={(e) => onSelectScenario(e.target.value)} disabled={simulating} className="w-full h-12 px-4 rounded-lg bg-white border border-[#D8E2DA] text-[#26352C] focus:outline-none focus:border-[#009530] disabled:opacity-50">
          <optgroup label="WITH MATCHING SOP">
            {withSop.map((scenario) => <option key={scenario.scenario_id} value={scenario.scenario_id}>{scenario.name} · {scenario.sop_id} · Draft, not approved</option>)}
          </optgroup>
          <optgroup label="WITHOUT SPECIFIC EQUIPMENT-FAILURE SOP">
            {withoutEquipmentSop.map((scenario) => <option key={scenario.scenario_id} value={scenario.scenario_id}>{scenario.name} · No specific equipment-failure SOP</option>)}
          </optgroup>
        </select>

        <div className="rounded-lg border border-[#D8E2DA] bg-[#F7FAF7] px-4 py-3 text-xs text-[#405647]">
          <strong>{selectedDetails?.sop_id ? `${selectedDetails.sop_id} · ${selectedDetails.sop_title || ''}` : 'No directly applicable equipment-failure SOP retrieved'}</strong>
          <p className="mt-1">{selectedDetails?.sop_id ? `${selectedDetails.sop_approval_status || 'Draft for review — not approved'} · Reference only` : 'General safety and management procedures may still apply. No unrelated equipment procedure is presented as a match.'}</p>
          {selectedDetails && <p className="mt-1">Equipment: {selectedDetails.equipment_id || selectedDetails.target_equipment || 'not recorded'} · Alarm: {selectedDetails.alarm_id || 'monitoring event'}</p>}
          <span>All generated readings are SIMULATED; they are not live PLC telemetry.</span>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button onClick={start} disabled={simulating} className="ml-auto h-11 px-5 rounded-lg bg-[#009530] hover:bg-[#006B35] disabled:bg-[#E8ECE8] disabled:text-[#64736A] text-white font-bold text-sm flex items-center gap-2 cursor-pointer transition-colors shadow-sm">
            <Play className="w-4 h-4 fill-current" /> {simulating ? 'SCENARIO RUNNING' : isIncident ? 'START ANOTHER SCENARIO' : 'START SCENARIO'}
          </button>
        </div>
        {simulating && <div className="flex items-center gap-2 text-sm text-[#155EEF]"><Zap className="w-4 h-4 animate-pulse" /> Scenario accepted. Waiting for the event pipeline; the HMI dashboard will update when the incident is published. Earlier incidents remain in Incident History.</div>}
        {simulationStatus.status === 'awaiting_corrective_action' && (
          <div className="rounded-lg border border-[#B7791F]/30 bg-[#FEF0C7] p-5 text-sm text-[#26352C] space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#B7791F]/20 pb-3">
              <div>
                <p className="font-bold text-[#B7791F] text-base">
                  Synthetic alarm active · {simulationStatus.equipment_id || 'Equipment'}
                </p>
                <p className="text-xs text-[#805400] mt-0.5">
                  Alarm input ({simulationStatus.alarm_tag || 'active trip'}) is active.
                </p>
              </div>
              <div className="flex items-center gap-3 font-mono text-xs">
                <span className="rounded bg-white border border-[#B7791F]/40 px-2.5 py-1 text-[#B7791F] font-bold">
                  Repeat Count: ×{simulationStatus.repeat_count || 1}
                </span>
                <span className="text-[#805400] text-[11px]">
                  Last seen: {formatTimestamp(simulationStatus.last_seen_timestamp)}
                </span>
              </div>
            </div>

            <p className="text-xs text-[#805400] leading-relaxed">
              The simulated fault sequence has finished. You can resend the identical active alarm notification to verify deterministic deduplication. {recoverySupported ? 'A synthetic recovery trajectory is available for this scenario.' : 'No synthetic recovery trajectory is configured for this scenario; the source-clear interlock remains in place.'}
            </p>

            <div className="flex flex-wrap items-center gap-3 pt-1">
              <button
                type="button"
                onClick={onTriggerAlarmRepeat}
                disabled={repeatBusy || recoveryBusy}
                className="h-10 px-4 rounded-lg border border-[#B7791F]/50 bg-white hover:bg-[#FEF0C7] text-[#B7791F] text-xs font-bold flex items-center gap-2 transition-colors disabled:opacity-50 cursor-pointer"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${repeatBusy ? 'animate-spin' : ''}`} />
                {repeatBusy ? 'SENDING NOTIFICATION…' : 'TRIGGER SAME ALARM AGAIN'}
              </button>

              {recoverySupported ? <button
                type="button"
                onClick={onSimulatedRecovery}
                disabled={recoveryBusy || repeatBusy}
                className="h-10 px-4 rounded-lg bg-[#009530] hover:bg-[#006B35] text-white text-xs font-bold flex items-center gap-2 transition-colors disabled:opacity-50 cursor-pointer shadow-sm"
              >
                {recoveryBusy ? 'SIMULATING RECOVERY…' : 'RUN SIMULATED CORRECTIVE ACTION'}
              </button> : <span className="rounded-md border border-[#D8E2DA] bg-[#F3F6F3] px-3 py-2 text-xs text-[#64736A]">Recovery simulation unavailable for this scenario</span>}
            </div>

            {repeatError && <p role="alert" className="rounded-md border border-[#D92D20]/40 bg-[#FEF3F2] px-3 py-2 text-xs text-[#D92D20]">{repeatError}</p>}

            <p className="text-[11px] text-[#805400] font-mono">
              Deterministic deduplication: Resending will not create a new incident. Repeat count increments from stored fingerprint.
            </p>
          </div>
        )}
        {simulationStatus.status === 'alarm_clear_observed' && <div role="status" className="rounded-lg border border-[#009530]/30 bg-[#E8F5EC] p-3 text-sm text-[#006B35]">Simulated recovery complete. Alarm input cleared at {simulationStatus.timestamp || 'the recorded time'}. Open the HMI to review and confirm.</div>}
        {simulationStatus.status === 'recovering' && <div className="text-sm text-[#006B35]">Synthetic recovery readings are being generated…</div>}
        {simulationStatus.status === 'error' && <div role="alert" className="text-sm text-[#D92D20]">Scenario could not be completed. Try again.</div>}
        {error && <p role="alert" className="text-sm text-[#D92D20]">{error}</p>}
      </section>

      <section className="rounded-xl border border-[#009530]/30 bg-[#E8F5EC] p-4 flex gap-3 text-sm text-[#006B35]">
        <ShieldCheck className="w-5 h-5 shrink-0 text-[#009530]" />
        <p><strong>Synthetic demo values.</strong> Reference ranges use a notional 50 MLD plant and are not approved site alarm limits.</p>
      </section>

      <section className="rounded-xl border border-[#B7791F]/30 bg-[#FEF0C7] p-4 flex flex-wrap items-center gap-4">
        <AlertTriangle className="w-5 h-5 shrink-0 text-[#B7791F]" />
        <div className="flex-1 min-w-[240px]">
          <h2 className="text-sm font-semibold text-[#B7791F]">Clear demo data</h2>
          <p className="mt-1 text-xs text-[#805400]">This clears demo incident history. It does not change industrial controls.</p>
        </div>
        <button onClick={onResetDemo} className="h-9 px-3 rounded-lg border border-[#B7791F]/40 bg-white hover:bg-[#FEF0C7] text-[#B7791F] text-xs font-semibold flex items-center gap-2 cursor-pointer transition-colors"><RotateCcw className="w-3.5 h-3.5" /> RESET DEMO DATA</button>
      </section>
    </main>
  );
}
