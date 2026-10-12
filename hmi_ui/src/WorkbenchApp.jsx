import React, { useCallback, useEffect, useState } from 'react';
import { Activity, ExternalLink, FlaskConical, LibraryBig, RadioTower } from 'lucide-react';
import ScenarioLab from './components/ScenarioLab';
import SopLibrary from './components/SopLibrary';
import { getOpenEvents, listScenarios, resetDemo, runScenario, subscribeToEventStream } from './api/client';

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

  const refreshOpenIncidents = useCallback(async () => {
    try {
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

  return (
    <div className="min-h-screen bg-[#070B11] font-sans text-slate-100">
      <WorkbenchHeader page={page} setPage={setPage} />
      <section className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-6 pt-5 text-xs">
        <div className="flex items-center gap-2 text-slate-400"><RadioTower className="h-4 w-4 text-emerald-400" /> Control API <span className="font-mono text-emerald-300">localhost:8000</span></div>
        <div className={`flex items-center gap-2 ${isIncident ? 'text-amber-300' : 'text-emerald-300'}`}><Activity className="h-4 w-4" />{isIncident ? 'Open incident · visible on Operator HMI' : 'No open demo incident'}</div>
      </section>
      {latestEvent?.event_id && <div className="mx-auto mt-3 max-w-5xl px-6 text-xs text-slate-500">Latest event <span className="font-mono text-slate-300">{latestEvent.event_id}</span></div>}
      {page === 'scenarioLab' ? (
        <ScenarioLab
          scenarios={scenarios}
          selectedScenario={selectedScenario}
          onSelectScenario={setSelectedScenario}
          simulating={simulating}
          isIncident={isIncident}
          onStart={startScenario}
          onResetDemo={clearDemoData}
        />
      ) : <SopLibrary />}
    </div>
  );
}
