import React, { useEffect, useState } from 'react';
import { Play, Square, RotateCcw, ShieldCheck, AlertTriangle, RefreshCw, Loader2, CheckCircle2, Circle, XCircle } from 'lucide-react';
import { resolvePrimaryScenarioCatalog } from '../lib/scenarioCatalog';
import { getScenarioDetails } from '../api/client';

const STAGES = [
  { id: 'generating_telemetry', label: 'Generate simulated telemetry' },
  { id: 'processing_incident', label: 'Correlate · evidence · SOP retrieval' },
  { id: 'incident_published', label: 'Incident published to the HMI' },
];

function fmtTime(value) {
  if (!value) return '—';
  const t = Date.parse(value);
  return Number.isFinite(t) ? new Date(t).toLocaleTimeString() : value;
}

function stageState(stageId, status) {
  const order = STAGES.map((s) => s.id);
  const current = status.stage;
  if (status.status === 'error') return order.indexOf(stageId) <= Math.max(0, order.indexOf(current)) ? 'error' : 'todo';
  if (['awaiting_corrective_action', 'recovering', 'alarm_clear_observed'].includes(status.status)) return 'done';
  if (current === 'incident_published') return 'done';
  const ci = order.indexOf(current);
  const si = order.indexOf(stageId);
  if (ci < 0) return 'todo';
  if (si < ci) return 'done';
  if (si === ci) return status.status === 'running' ? 'active' : 'done';
  return 'todo';
}

function StageIcon({ state }) {
  if (state === 'done') return <CheckCircle2 className="h-4 w-4 text-[#009530]" />;
  if (state === 'active') return <Loader2 className="h-4 w-4 animate-spin text-[#155EEF]" />;
  if (state === 'error') return <XCircle className="h-4 w-4 text-[#D92D20]" />;
  return <Circle className="h-4 w-4 text-[#B8C4BC]" />;
}

export default function ScenarioLab({
  scenarios, selectedScenario, onSelectScenario, simulating, isIncident, onStart, onStop, onResetDemo,
  simulationStatus = {}, recoveryBusy = false, onSimulatedRecovery, repeatBusy = false, repeatError = '',
  onTriggerAlarmRepeat, startError = '',
}) {
  const { scenarios: choices } = resolvePrimaryScenarioCatalog(scenarios);
  const selected = choices.find((s) => s.scenario_id === selectedScenario) || choices[0];
  const [details, setDetails] = useState(null);
  const [detailsError, setDetailsError] = useState('');
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);

  useEffect(() => {
    let live = true;
    setDetails(null);
    setDetailsError('');
    if (!selected) return undefined;
    getScenarioDetails(selected.scenario_id).then((d) => live && setDetails(d))
      .catch((e) => live && setDetailsError(e.message));
    return () => { live = false; };
  }, [selected?.scenario_id]);

  const status = simulationStatus || {};
  const running = simulating || status.status === 'running';
  const progress = Math.round(100 * (status.progress ?? (running ? 0 : 0)));
  const runIsSelected = status.scenario_id === selected?.scenario_id;

  const start = async () => {
    setStarting(true);
    try { await onStart(); } finally { setStarting(false); }
  };
  const stop = async () => {
    setStopping(true);
    try { await onStop(); } finally { setStopping(false); }
  };

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 space-y-5 px-6 py-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-xs font-bold uppercase tracking-[0.22em] text-[#009530]">Simulation · not live plant data</p>
          <h1 className="mt-1 text-2xl font-bold text-[#26352C]">Scenario Lab</h1>
          <p className="mt-1 text-sm text-[#64736A]">Six incidents from the plant incident map. Each run creates its own incident record on the Operator HMI.</p>
        </div>
        <span className="rounded-md border border-[#155EEF]/30 bg-[#EFF8FF] px-3 py-1.5 font-mono text-xs font-bold text-[#155EEF]">SOURCE: SIMULATED</span>
      </header>

      <section className="grid gap-5 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        {/* Scenario list */}
        <div className="rounded-2xl border border-[#D8E2DA] bg-white p-3 shadow-sm" role="radiogroup" aria-label="Scenario">
          {choices.map((s) => {
            const active = s.scenario_id === selected?.scenario_id;
            return (
              <button key={s.scenario_id} type="button" role="radio" aria-checked={active} disabled={running}
                onClick={() => onSelectScenario(s.scenario_id)}
                className={`mb-1 flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors disabled:cursor-not-allowed ${active ? 'bg-[#E8F5EC] ring-1 ring-[#009530]/40' : 'hover:bg-[#F3F6F3]'} ${running && !active ? 'opacity-50' : ''}`}>
                <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full font-mono text-xs font-bold ${active ? 'bg-[#009530] text-white' : 'bg-[#E8ECE8] text-[#405647]'}`}>{s.number}</span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-[#26352C]">{s.name}</span>
                  <span className="block truncate font-mono text-[11px] text-[#64736A]">{s.equipment_id} · {s.sop_id}{s.sop_coverage === 'partial' ? ' · partial' : ''}</span>
                </span>
              </button>
            );
          })}
        </div>

        {/* Selected scenario + controls */}
        <div className="space-y-4">
          <div className="rounded-2xl border border-[#D8E2DA] bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="text-lg font-bold text-[#26352C]">{selected?.number}. {selected?.name}</h2>
                {details && <p className="mt-1 text-sm text-[#405647]">{details.summary}</p>}
                {details && <p className="mt-1 text-xs text-[#64736A]">Reported by {details.who} · Severity {details.severity} · {details.priority_note}</p>}
              </div>
              <div className="flex shrink-0 gap-2">
                {running ? (
                  <button type="button" onClick={stop} disabled={stopping} className="flex h-10 items-center gap-2 rounded-lg bg-[#D92D20] px-4 text-sm font-bold text-white shadow-sm hover:bg-[#B42318] disabled:opacity-60">
                    {stopping ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4 fill-current" />} Stop
                  </button>
                ) : (
                  <button type="button" onClick={start} disabled={starting || !selected} className="flex h-10 items-center gap-2 rounded-lg bg-[#009530] px-4 text-sm font-bold text-white shadow-sm hover:bg-[#006B35] disabled:opacity-60">
                    {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 fill-current" />} {isIncident ? 'Start another run' : 'Start scenario'}
                  </button>
                )}
              </div>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-[#D8E2DA] bg-[#F7FAF7] px-3 py-2 text-xs text-[#405647]">
                <div className="font-mono text-[10px] uppercase tracking-wider text-[#64736A]">Matching procedure</div>
                <div className="mt-0.5 font-semibold text-[#26352C]">{selected?.sop_id} · {selected?.sop_title}</div>
                <div className="mt-1 inline-block rounded bg-[#FEF0C7] px-1.5 py-0.5 font-mono text-[10px] font-bold text-[#B54708]">DRAFT FOR REVIEW — NOT APPROVED</div>
                <span className={`ml-2 inline-block rounded px-1.5 py-0.5 font-mono text-[10px] font-bold ${selected?.sop_coverage === 'partial' ? 'bg-[#FEF3F2] text-[#B42318]' : 'bg-[#E8F5EC] text-[#006B35]'}`}>COVERAGE: {String(selected?.sop_coverage || '').toUpperCase()}</span>
              </div>
              <div className="rounded-lg border border-[#D8E2DA] bg-[#F7FAF7] px-3 py-2 text-xs text-[#405647]">
                <div className="font-mono text-[10px] uppercase tracking-wider text-[#64736A]">Expected outcome</div>
                <div className="mt-0.5">{details?.expected_outcome || '—'}</div>
                <div className="mt-1 font-mono text-[11px]">Primary alarm {selected?.primary_alarm}</div>
              </div>
            </div>
            {details?.sop_coverage_notes?.filter((n) => n.startsWith('Gap')).map((note) => (
              <p key={note} className="mt-2 rounded-md border border-[#B7791F]/30 bg-[#FFFAEB] px-3 py-2 text-xs text-[#805400]"><AlertTriangle className="mr-1 inline h-3.5 w-3.5" />{note}</p>
            ))}
          </div>

          {/* Run status / pipeline */}
          <div className="rounded-2xl border border-[#D8E2DA] bg-white p-5 shadow-sm" aria-live="polite">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-bold text-[#26352C]">Run status</h3>
              <span className="font-mono text-xs text-[#64736A]">
                {status.scenario_id ? `${choices.find((c) => c.scenario_id === status.scenario_id)?.name || status.scenario_id} · ` : ''}
                <strong className="text-[#26352C]">{(status.status || 'idle').replaceAll('_', ' ')}</strong>
              </span>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-[#E8ECE8]">
              <div className={`h-full rounded-full transition-all ${status.status === 'error' ? 'bg-[#D92D20]' : 'bg-[#009530]'}`} style={{ width: `${status.status === 'idle' || !status.status ? 0 : progress}%` }} />
            </div>
            <div className="mt-1 flex justify-between font-mono text-[11px] text-[#64736A]">
              <span>{status.samples_emitted ? `${status.samples_emitted} samples · ${status.readings_emitted} readings` : 'No run yet'}</span>
              <span>{status.duration_seconds ? `${Math.round(status.simulated_elapsed_seconds || 0)} / ${status.duration_seconds} s simulated` : ''}</span>
            </div>
            <ol className="mt-3 grid gap-2 sm:grid-cols-3">
              {STAGES.map((stage) => {
                const state = status.status && status.status !== 'idle' ? stageState(stage.id, status) : 'todo';
                return <li key={stage.id} className="flex items-center gap-2 text-xs text-[#405647]"><StageIcon state={state} />{stage.label}</li>;
              })}
            </ol>
            {status.stage === 'incident_repeated' && <p className="mt-3 rounded-md border border-[#B7791F]/30 bg-[#FFFAEB] px-3 py-2 text-xs text-[#805400]">The same alarm re-annunciated while its earlier incident is still open, so it was added to that incident (repeat ×{status.repeat_count}). No duplicate incident was created. Close the earlier incident on the HMI to get a fresh one.</p>}
            {status.status === 'stopped' && <p className="mt-3 text-xs text-[#64736A]">Run stopped by user before completion.</p>}
            {status.stage === 'no_incident' && <p role="alert" className="mt-3 text-xs text-[#B42318]">The run finished but no incident was created. Check the backend log.</p>}
            {status.event_id && <p className="mt-3 font-mono text-[11px] text-[#64736A]">Incident {status.event_id.slice(0, 8)} · alarm {status.alarm_tag || '—'} · last seen {fmtTime(status.last_seen_timestamp)}</p>}
            {(startError || status.status === 'error') && (
              <p role="alert" className="mt-3 rounded-md border border-[#D92D20]/40 bg-[#FEF3F2] px-3 py-2 text-xs text-[#B42318]">
                {startError || status.message || status.error || 'The scenario failed. See the backend log.'}
              </p>
            )}

            {status.status === 'awaiting_corrective_action' && (
              <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-[#E8ECE8] pt-4">
                <span className="text-xs text-[#805400]">Alarm input {status.alarm_tag} is active (repeat ×{status.repeat_count || 1}). Fix it in simulation to see the after-fix values.</span>
                <button type="button" onClick={onTriggerAlarmRepeat} disabled={repeatBusy || recoveryBusy} className="flex h-9 items-center gap-2 rounded-lg border border-[#B7791F]/50 bg-white px-3 text-xs font-bold text-[#B7791F] disabled:opacity-50">
                  <RefreshCw className={`h-3.5 w-3.5 ${repeatBusy ? 'animate-spin' : ''}`} /> Re-annunciate alarm
                </button>
                <button type="button" onClick={onSimulatedRecovery} disabled={recoveryBusy || repeatBusy} className="flex h-9 items-center gap-2 rounded-lg bg-[#009530] px-3 text-xs font-bold text-white disabled:opacity-50">
                  {recoveryBusy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Simulate the fix (after-fix values)
                </button>
              </div>
            )}
            {status.status === 'recovering' && <p className="mt-3 flex items-center gap-2 text-xs text-[#006B35]"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Generating after-fix readings…</p>}
            {status.status === 'alarm_clear_observed' && <p role="status" className="mt-3 rounded-md border border-[#009530]/30 bg-[#E8F5EC] px-3 py-2 text-xs text-[#006B35]">After-fix values reached. Alarm input cleared at {fmtTime(status.timestamp)}. The operator still acknowledges and closes the incident on the HMI.</p>}
            {repeatError && <p role="alert" className="mt-2 text-xs text-[#B42318]">{repeatError}</p>}
          </div>
        </div>
      </section>

      {/* Incident map table */}
      <section className="rounded-2xl border border-[#D8E2DA] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-bold text-[#26352C]">Telemetry for “{selected?.name}”</h3>
          <span className="text-xs text-[#64736A]">{details?.source_document}{runIsSelected && status.status ? ` · current run: ${status.status.replaceAll('_', ' ')}` : ''}</span>
        </div>
        {detailsError && <p role="alert" className="mt-2 text-xs text-[#B42318]">Scenario details could not be loaded: {detailsError}</p>}
        {!details && !detailsError && <p className="mt-3 flex items-center gap-2 text-xs text-[#64736A]"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…</p>}
        {details && (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-xs">
              <thead className="border-b border-[#D8E2DA] font-mono text-[10px] uppercase tracking-wider text-[#64736A]">
                <tr><th className="py-2 pr-3">Tag</th><th className="pr-3">Signal</th><th className="pr-3">Normal</th><th className="pr-3">Alarm / limit</th><th className="pr-3">During incident</th><th className="pr-3">After fix</th></tr>
              </thead>
              <tbody>
                {details.table.map((row) => (
                  <tr key={row.tag} className="border-b border-[#EEF2EE] last:border-0">
                    <td className="py-1.5 pr-3 font-mono text-[11px] text-[#26352C]">{row.tag}{row.equipment_id !== details.equipment_id && <span className="ml-1 text-[10px] text-[#64736A]">({row.equipment_id})</span>}</td>
                    <td className="pr-3 text-[#405647]">{row.parameter}</td>
                    <td className="pr-3 text-[#405647]">{row.normal}</td>
                    <td className="pr-3 text-[#405647]">{row.limit}</td>
                    <td className={`pr-3 font-semibold ${row.status === 'Beyond limit' ? 'text-[#B42318]' : 'text-[#26352C]'}`}>{row.incident}</td>
                    <td className="pr-3 text-[#006B35]">{row.after_fix}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="flex flex-wrap items-center gap-4 rounded-xl border border-[#009530]/30 bg-[#E8F5EC] p-4 text-sm text-[#006B35]">
        <ShieldCheck className="h-5 w-5 shrink-0 text-[#009530]" />
        <p className="min-w-[240px] flex-1"><strong>Simulated values only.</strong> Nothing here writes to a PLC or operates equipment. Limits come from SOP-MAN-000, a draft that is not approved.</p>
        <button type="button" onClick={onResetDemo} disabled={running} className="flex h-9 items-center gap-2 rounded-lg border border-[#B7791F]/40 bg-white px-3 text-xs font-semibold text-[#B7791F] disabled:opacity-50"><RotateCcw className="h-3.5 w-3.5" /> Reset demo data</button>
      </section>
    </main>
  );
}
