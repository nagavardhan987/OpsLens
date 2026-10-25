import React, { useCallback, useEffect, useState } from 'react';
import { Activity, ExternalLink, FlaskConical, LibraryBig, RadioTower } from 'lucide-react';
import ScenarioLab from './components/ScenarioLab';
import SopLibrary from './components/SopLibrary';
import { API_ORIGIN, applySimulatedCorrectiveAction, getCopilotHealth, getOpenEvents, getScenarioStatus, listScenarios, resetDemo, runScenario, subscribeToEventStream, triggerAlarmRepeat } from './api/client';

function WorkbenchHeader({ page, setPage }) {
  return (
    <header className="sticky top-0 z-40 border-b border-[#1a2535] bg-[#0a0e16]/95 px-6 py-3 backdrop-blur">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-lg font-black tracking-tight text-white"><span className="text-emerald-400">◉</span> OpsLens <span className="ml-2 text-xs font-medium text-slate-500">ENGINEERING CONSOLE</span></div>
          <div className="mt-0.5 text-[10px] font-mono uppercase tracking-wider text-slate-600">Scenario and SOP administration · local edge services</div>
        </div>
        <nav className="flex flex-wrap items-center gap-2" aria-label="Engineering console navigation">
          <button onClick={() => setPage('scenarioLab')} className={`flex h-9 items-center gap-2 rounded-lg border px-3 text-xs font-semibold ${page === 'scenarioLab' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : 'border-[#1a2535] bg-[#111827] text-slate-400 hover:text-white'}`}><FlaskConical className="h-3.5 w-3.5" /> SCENARIO LAB</button>
          <button onClick={() => setPage('sopLibrary')} className={`flex h-9 items-center gap-2 rounded-lg border px-3 text-xs font-semibold ${page === 'sopLibrary' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : 'border-[#1a2535] bg-[#111827] text-slate-400 hover:text-white'}`}><LibraryBig className="h-3.5 w-3.5" /> SOP LIBRARY</button>
          <a href="http://localhost:5173" target="_blank" rel="noreferrer" className="flex h-9 items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 text-xs font-semibold text-blue-200 hover:bg-blue-500/20">OPEN OPERATOR HMI <ExternalLink className="h-3.5 w-3.5" /></a>
        </nav>
      </div>
    </header>
  );
}

export default function WorkbenchApp() {
  const [page, setPage] = useState('scenarioLab');
  const [scenarios, setScenarios] = useState([]);
  const [selectedScenario, setSelectedScenario] = useState('valve_restriction');
  const [simulating, setSimulating] = useState(false);
  const [isIncident, setIsIncident] = useState(false);
  const [latestEvent, setLatestEvent] = useState(null);
  const [simulationStatus, setSimulationStatus] = useState({ status: 'idle' });
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [repeatBusy, setRepeatBusy] = useState(false);
  const [repeatError, setRepeatError] = useState('');
  const [copilotHealth, setCopilotHealth] = useState(null);

  const refreshOpenIncidents = useCallback(async () => {
    try {
      const status = await getScenarioStatus();
      setSimulationStatus(status);
      setSimulating(status.status === 'running' || status.status === 'recovering');
      if (status.event_id) setLatestEvent((current) => current?.event_id === status.event_id ? current : { event_id: status.event_id });
      const open = await getOpenEvents();
      const hasOpenIncident = open.length > 0;
      setIsIncident(hasOpenIncident);
      if (hasOpenIncident) {
        // The event can be published before this page's SSE connection is
        // established. Recover its ID from the same open-event poll and stop
        // showing the scenario as still running.
        setSimulating(false);
        setLatestEvent((current) => current || { event_id: open[open.length - 1].event_id });
      } else {
        setLatestEvent(null);
      }
    } catch (_) { /* The visible API/health status remains available through backend diagnostics. */ }
  }, []);

  useEffect(() => {
    let active = true;
    listScenarios().then((items) => {
      if (active && items?.length) {
        setScenarios(items);
        setSelectedScenario(items[0].scenario_id);
      }
    }).catch(() => {});
    refreshOpenIncidents();
    getCopilotHealth().then(setCopilotHealth).catch(() => setCopilotHealth({ llm: { configured: false }, rag: { connected: false } }));
    const unsubscribe = subscribeToEventStream((event) => {
      setLatestEvent(event);
      setIsIncident(true);
      setSimulating(false);
    }, () => {});
    const poll = window.setInterval(refreshOpenIncidents, 4000);
    return () => {
      active = false;
      unsubscribe();
      window.clearInterval(poll);
    };
  }, [refreshOpenIncidents]);

  const startScenario = async () => {
    setSimulating(true);
    try {
      await runScenario(selectedScenario, 10.0);
      return true;
    } catch (error) {
      console.error(error);
      setSimulating(false);
      return false;
    }
  };

  const clearDemoData = async () => {
    if (!window.confirm('Reset the demo database and clear demo event history? This does not write to industrial controls.')) return;
    try {
      await resetDemo();
      setIsIncident(false);
      setSimulating(false);
      setLatestEvent(null);
      await refreshOpenIncidents();
    } catch (error) {
      window.alert(`Could not reset demo data: ${error.message}`);
    }
  };

  const performSimulatedRecovery = async () => {
    setRecoveryBusy(true);
    try {
      await applySimulatedCorrectiveAction();
      await refreshOpenIncidents();
    } catch (error) {
      window.alert(error.message || 'The simulated recovery could not be completed.');
    } finally { setRecoveryBusy(false); }
  };

  const performAlarmRepeat = async () => {
    setRepeatError('');
    setRepeatBusy(true);
    try {
      await triggerAlarmRepeat();
      await refreshOpenIncidents();
    } catch (error) {
      const msg = error.message === 'Failed to fetch'
        ? 'Cannot reach OpsLens backend at http://localhost:8001. Please verify that the backend server is running.'
        : (error.message || 'The repeat alarm notification could not be sent.');
      setRepeatError(msg);
    } finally { setRepeatBusy(false); }
  };

  return (
    <div className="min-h-screen bg-[#070B11] font-sans text-slate-100">
      <WorkbenchHeader page={page} setPage={setPage} />
      <section className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-6 pt-5 text-xs">
        <div className="flex items-center gap-2 text-slate-400"><RadioTower className="h-4 w-4 text-emerald-400" /> Control API <span className="font-mono text-emerald-300">{API_ORIGIN.replace(/^https?:\/\//, '')}</span></div>
        <div className={`flex items-center gap-2 ${isIncident ? 'text-amber-300' : 'text-emerald-300'}`}><Activity className="h-4 w-4" />{isIncident ? 'Open incident · visible on Operator HMI' : 'No open demo incident'}</div>
      </section>
      {latestEvent?.event_id && <div className="mx-auto mt-3 max-w-5xl px-6 text-xs text-slate-500">Latest event <span className="font-mono text-slate-300">{latestEvent.event_id}</span></div>}
      {copilotHealth && (
        <div className="mx-auto mt-3 max-w-5xl rounded-lg border border-[#1a2535] bg-[#0d1420] px-6 py-3 text-xs text-slate-400">
          <div className="font-semibold text-slate-200">Demo resilience</div>
          <p className="mt-1">LLM: {copilotHealth.llm?.configured ? `${copilotHealth.llm.provider} (${copilotHealth.llm.verified ? 'verified this process' : 'configured, not yet verified'})` : 'not configured · deterministic assistant active'}. RAG: {copilotHealth.rag?.connected ? 'vector store connected' : 'BM25/local fallback if retrieval is unavailable'}. Copilot is advisory only and does not write to the PLC. No live EOTE connection is claimed.</p>
          <p className="mt-1 text-slate-500">Impact framing for the pitch: operators receive a 30-minute assembled context, ranked evidence, and an approved SOP excerpt instead of paging a historian by hand. Treat MTTR reduction as a target to measure on site, not a completed plant statistic.</p>
        </div>
      )}
      {page === 'scenarioLab' ? (
        <ScenarioLab
          scenarios={scenarios}
          selectedScenario={selectedScenario}
          onSelectScenario={setSelectedScenario}
          simulating={simulating}
          isIncident={isIncident}
          onStart={startScenario}
          onResetDemo={clearDemoData}
          simulationStatus={simulationStatus}
          recoveryBusy={recoveryBusy}
          onSimulatedRecovery={performSimulatedRecovery}
          repeatBusy={repeatBusy}
          repeatError={repeatError}
          onTriggerAlarmRepeat={performAlarmRepeat}
        />
      ) : <SopLibrary />}
    </div>
  );
}
