import React, { useState } from 'react';
import { Play, RotateCcw, Zap, ShieldCheck, AlertTriangle } from 'lucide-react';

const defaultScenarios = [
  { scenario_id: 'valve_restriction', name: 'Pump-02 — Valve Restriction' },
  { scenario_id: 'bearing_wear', name: 'Compressor-01 — Bearing Wear' },
  { scenario_id: 'seal_leak', name: 'Pump-02 — Seal Leak' },
  { scenario_id: 'sensor_fault', name: 'Filter-01 — Sensor Fault' },
  { scenario_id: 'tank_overflow', name: 'Tank-01 — High Level' },
  { scenario_id: 'compressor_overspeed', name: 'Compressor-01 — Overspeed' },
  { scenario_id: 'pump_cavitation', name: 'Pump-02 — Cavitation' },
];

export default function ScenarioLab({ scenarios, selectedScenario, onSelectScenario, simulating, isIncident, onStart, onResetDemo }) {
  const [error, setError] = useState('');
  const choices = scenarios.length ? scenarios : defaultScenarios;

  const start = async () => {
    setError('');
    const started = await onStart();
    if (!started) setError('The scenario could not be started. Check that the OpsLens API is running, then try again.');
  };

  return (
    <main className="flex-1 px-6 py-8 max-w-5xl w-full mx-auto space-y-6">
      <header>
        <p className="text-xs font-mono uppercase tracking-[0.22em] text-emerald-400">DEMO & SIMULATION</p>
        <h1 className="mt-2 text-3xl font-bold text-white">Scenario Lab</h1>
        <p className="mt-2 text-slate-400">Run synthetic scenarios for demonstrations and observe the resulting alarm on the HMI dashboard.</p>
      </header>

      <section className="rounded-2xl border border-[#1a2535] bg-[#0d1420] p-6 space-y-5">
        <label className="block text-sm font-semibold text-slate-200" htmlFor="scenario-select">Scenario</label>
        <select id="scenario-select" value={selectedScenario} onChange={(e) => onSelectScenario(e.target.value)} disabled={simulating || isIncident} className="w-full h-12 px-4 rounded-lg bg-[#080d15] border border-[#29374a] text-slate-100 focus:outline-none focus:border-emerald-500 disabled:opacity-50">
          {choices.map((scenario) => <option key={scenario.scenario_id} value={scenario.scenario_id}>{scenario.name || scenario.scenario_id}</option>)}
        </select>

        <div className="flex flex-wrap items-center gap-3">
          <button onClick={start} disabled={simulating || isIncident} className="ml-auto h-11 px-5 rounded-lg bg-red-600 hover:bg-red-500 disabled:bg-slate-700 disabled:text-slate-400 text-white font-bold text-sm flex items-center gap-2">
            <Play className="w-4 h-4 fill-current" /> {simulating ? 'SCENARIO RUNNING' : isIncident ? 'OPEN INCIDENT ACTIVE' : 'START SCENARIO'}
          </button>
        </div>
        {simulating && <div className="flex items-center gap-2 text-sm text-blue-300"><Zap className="w-4 h-4 animate-pulse" /> Scenario accepted. Waiting for the event pipeline; the HMI dashboard will update when the incident is published.</div>}
        {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      </section>

      <section className="rounded-xl border border-emerald-900/60 bg-emerald-950/20 p-4 flex gap-3 text-sm text-emerald-100">
        <ShieldCheck className="w-5 h-5 shrink-0 text-emerald-400" />
        <p><strong>Read-only simulation.</strong> Starting a scenario generates synthetic telemetry and an event for the OpsLens demo pipeline. It does not write to a PLC, pump, valve, actuator, or setpoint.</p>
      </section>

      <section className="rounded-xl border border-amber-700/40 bg-amber-950/20 p-4 flex flex-wrap items-center gap-4">
        <AlertTriangle className="w-5 h-5 shrink-0 text-amber-400" />
        <div className="flex-1 min-w-[240px]">
          <h2 className="text-sm font-semibold text-amber-200">Clear demo data</h2>
          <p className="mt-1 text-xs text-amber-100/70">This calls the backend demo reset and clears demo incident state/history. Use it only when you want to reset the demonstration.</p>
        </div>
        <button onClick={onResetDemo} className="h-9 px-3 rounded-lg border border-amber-600/40 text-amber-200 hover:bg-amber-900/30 text-xs font-semibold flex items-center gap-2"><RotateCcw className="w-3.5 h-3.5" /> RESET DEMO DATA</button>
      </section>
    </main>
  );
}
