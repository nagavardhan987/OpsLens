import React, { useCallback, useEffect, useState } from 'react';
import { Activity, BarChart3, ExternalLink, FlaskConical, LibraryBig } from 'lucide-react';
import ScenarioLab from './components/ScenarioLab';
import SopLibrary from './components/SopLibrary';
import OperationalMetrics from './components/OperationalMetrics';
import { applySimulatedCorrectiveAction, getCopilotHealth, getOpenEvents, getScenarioStatus, listScenarios, resetDemo, runScenario, subscribeToEventStream, triggerAlarmRepeat } from './api/client';

function WorkbenchHeader({ page, setPage }) {
  return (
    <header className="sticky top-0 z-40 border-b border-[#D8E2DA] bg-white/95 px-6 py-3 backdrop-blur shadow-sm">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-lg font-black tracking-tight text-[#26352C]"><span className="text-[#009530]">◉</span> OpsLens</div>
        </div>
        <nav className="flex flex-wrap items-center gap-2" aria-label="Engineering console navigation">
          <button onClick={() => setPage('scenarioLab')} className={`flex h-9 items-center gap-2 rounded-lg border px-3 text-xs font-semibold cursor-pointer transition-colors ${page === 'scenarioLab' ? 'border-[#009530]/40 bg-[#E8F5EC] text-[#006B35]' : 'border-[#D8E2DA] bg-white text-[#64736A] hover:text-[#26352C] hover:bg-[#F3F6F3]'}`}><FlaskConical className="h-3.5 w-3.5 text-[#009530]" /> Scenario Lab</button>
          <button onClick={() => setPage('sopLibrary')} className={`flex h-9 items-center gap-2 rounded-lg border px-3 text-xs font-semibold cursor-pointer transition-colors ${page === 'sopLibrary' ? 'border-[#009530]/40 bg-[#E8F5EC] text-[#006B35]' : 'border-[#D8E2DA] bg-white text-[#64736A] hover:text-[#26352C] hover:bg-[#F3F6F3]'}`}><LibraryBig className="h-3.5 w-3.5 text-[#009530]" /> Procedures</button>
          <button onClick={() => setPage('operationalMetrics')} className={`flex h-9 items-center gap-2 rounded-lg border px-3 text-xs font-semibold cursor-pointer transition-colors ${page === 'operationalMetrics' ? 'border-[#009530]/40 bg-[#E8F5EC] text-[#006B35]' : 'border-[#D8E2DA] bg-white text-[#64736A] hover:text-[#26352C] hover:bg-[#F3F6F3]'}`}><BarChart3 className="h-3.5 w-3.5 text-[#009530]" /> Metrics</button>
          <a href="http://localhost:5173" target="_blank" rel="noreferrer" className="flex h-9 items-center gap-2 rounded-lg border border-[#155EEF]/30 bg-[#EFF8FF] px-3 text-xs font-semibold text-[#155EEF] hover:bg-[#E0F2FE] transition-colors">Operator HMI <ExternalLink className="h-3.5 w-3.5" /></a>
        </nav>
      </div>
    </header>
  );
}

export default function WorkbenchApp() {
  const [page, setPage] = useState('scenarioLab');
  const [scenarios, setScenarios] = useState([]);
  const [selectedScenario, setSelectedScenario] = useState('wet_well_high_level');
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
    } catch (_) {
      window.alert('The demo could not be reset. Try again.');
    }
  };

  const performSimulatedRecovery = async () => {
    setRecoveryBusy(true);
    try {
      await applySimulatedCorrectiveAction();
      await refreshOpenIncidents();
    } catch (_) {
      window.alert('Simulated recovery could not be completed. Try again.');
    } finally { setRecoveryBusy(false); }
  };

  const performAlarmRepeat = async () => {
    setRepeatError('');
    setRepeatBusy(true);
    try {
      await triggerAlarmRepeat();
      await refreshOpenIncidents();
    } catch (_) {
      setRepeatError('The alarm notification could not be sent. Try again.');
    } finally { setRepeatBusy(false); }
  };

  return (
    <div className="engineering-console min-h-screen bg-[#F3F6F3] font-sans text-[#26352C]">
      <WorkbenchHeader page={page} setPage={setPage} />
      <section className="mx-auto flex max-w-5xl items-center justify-end gap-3 px-6 pt-5 text-xs">
        <div className={`flex items-center gap-2 font-medium ${isIncident ? 'text-[#B7791F]' : 'text-[#006B35]'}`}><Activity className="h-4 w-4" />{isIncident ? 'Open incident · visible on Operator HMI' : 'No open demo incident'}</div>
      </section>
      {copilotHealth && (
        <details className="mx-auto mt-3 max-w-5xl rounded-xl border border-[#D8E2DA] bg-white px-5 py-3 text-xs text-[#64736A] shadow-sm">
          <summary className="cursor-pointer font-semibold text-[#26352C]">Service details</summary>
          <p className="mt-2">Assistant: {copilotHealth.llm?.configured ? `${copilotHealth.llm.provider} (${copilotHealth.llm.verified ? 'connected' : 'not verified'})` : 'Evidence-based responses available'}. Search: {copilotHealth.rag?.connected ? 'Connected' : 'Local search available'}.</p>
          <p className="mt-1">OpsLens is advisory and does not write to the PLC.</p>
        </details>
      )}
      {page === 'scenarioLab' && (
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
      )}
      {page === 'sopLibrary' && <SopLibrary />}
      {page === 'operationalMetrics' && <OperationalMetrics activeEventId={latestEvent?.event_id} />}
    </div>
  );
}
