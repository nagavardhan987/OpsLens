import React, { useState, useEffect, useRef, useCallback } from 'react';
import Header from './components/Header';
import ProcessValues from './components/ProcessValues';
import AlarmPrioritization from './components/AlarmPrioritization';
import EventStory from './components/EventStory';
import EvidenceSection from './components/EvidenceSection';
import RelevantSop from './components/RelevantSop';
import NextBestAction from './components/NextBestAction';
import ShiftHandoverCard from './components/ShiftHandoverCard';
import SopModal from './components/SopModal';
import HandoverModal from './components/HandoverModal';
import {
  subscribeToEventStream,
  getFullEvent,
  getOpenEvents,
  logOperatorAction,
  compileHandover,
  listScenarios,
  runScenario,
  resetDemo,
  getSystemStatus
} from './api/client';

export default function App() {
  const [fullEvent, setFullEvent] = useState(null);
  const [currentEventId, setCurrentEventId] = useState(null);
  const [handover, setHandover] = useState(null);
  const [scenarios, setScenarios] = useState([]);
  const [selectedScenario, setSelectedScenario] = useState('valve_restriction');

  const [isIncident, setIsIncident] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [simStep, setSimStep] = useState(0);
  const [pacingMode, setPacingMode] = useState('animated');
  const [recordedAction, setRecordedAction] = useState(null);

  const [isSopModalOpen, setIsSopModalOpen] = useState(false);
  const [isHandoverModalOpen, setIsHandoverModalOpen] = useState(false);

  const timersRef = useRef([]);

  const clearAllTimers = () => {
    timersRef.current.forEach(t => { clearTimeout(t); clearInterval(t); });
    timersRef.current = [];
  };

  const refreshHandover = useCallback(async () => {
    try { const h = await compileHandover(); setHandover(h); } catch (_) {}
  }, []);

  const triggerCascade = useCallback((stepsCount = 5) => {
    clearAllTimers();
    const total = Math.max(1, stepsCount);
    if (pacingMode === 'instant') { setSimStep(total); setSimulating(false); return; }
    setSimulating(true);
    setSimStep(1);
    if (total <= 1) { setSimulating(false); return; }
    for (let s = 2; s <= total; s++) {
      const tId = setTimeout(() => {
        setSimStep(s);
        if (s === total) setSimulating(false);
      }, (s - 1) * 1200);
      timersRef.current.push(tId);
    }
  }, [pacingMode]);

  const handleLiveEvent = useCallback(async (payload) => {
    const eventId = payload.event_id || (payload.data && payload.data.event_id);
    if (!eventId) return;
    try {
      const full = await getFullEvent(eventId);
      if (full) {
        setCurrentEventId(eventId);
        setFullEvent(full);
        setIsIncident(true);
        triggerCascade(full.story?.steps?.length || 5);
        refreshHandover();
      }
    } catch (_) {}
  }, [triggerCascade, refreshHandover]);

  useEffect(() => {
    let unsub = () => {};
    const init = async () => {
      try { const sc = await listScenarios(); if (sc?.length) { setScenarios(sc); setSelectedScenario(sc[0].scenario_id); } } catch (_) {}
      await refreshHandover();
      try {
        const open = await getOpenEvents();
        if (open?.length) {
          const full = await getFullEvent(open[open.length - 1].event_id);
          if (full) { setCurrentEventId(open[open.length - 1].event_id); setFullEvent(full); setIsIncident(true); setSimStep(7); }
        }
      } catch (_) {}
      unsub = subscribeToEventStream(handleLiveEvent, () => {});
    };
    init();
    return () => { clearAllTimers(); unsub(); };
  }, [handleLiveEvent, refreshHandover]);

  const handleStartIncident = async () => {
    clearAllTimers();
    setSimulating(true);
    setRecordedAction(null);
    try {
      const poll = setInterval(async () => {
        try {
          const open = await getOpenEvents();
          if (open?.length) {
            const full = await getFullEvent(open[open.length - 1].event_id);
            if (full) { setCurrentEventId(open[open.length - 1].event_id); setFullEvent(full); setIsIncident(true); refreshHandover(); }
          }
        } catch (_) {}
      }, 1000);
      timersRef.current.push(poll);
      await runScenario(selectedScenario, 10.0);
      clearInterval(poll);
      const open = await getOpenEvents();
      if (open?.length) {
        const full = await getFullEvent(open[open.length - 1].event_id);
        if (full) { setCurrentEventId(open[open.length - 1].event_id); setFullEvent(full); setIsIncident(true); triggerCascade(full.story?.steps?.length || 5); await refreshHandover(); }
      }
    } catch (err) { console.error(err); setSimulating(false); }
  };

  const handleResetDemo = async () => {
    clearAllTimers();
    setSimulating(false); setSimStep(0); setIsIncident(false);
    setCurrentEventId(null); setFullEvent(null); setRecordedAction(null);
    setIsSopModalOpen(false); setIsHandoverModalOpen(false);
    try { await resetDemo(); await refreshHandover(); } catch (_) {}
  };

  // Reset just the current scenario state — clears incident but keeps demo session
  const handleResetScenario = async () => {
    clearAllTimers();
    setSimulating(false); setSimStep(0); setIsIncident(false);
    setCurrentEventId(null); setFullEvent(null); setRecordedAction(null);
    try { await resetDemo(); await refreshHandover(); } catch (_) {}
  };

  const handleOperatorAction = async (actionType, notes) => {
    if (!currentEventId) return;
    try {
      const res = await logOperatorAction({ eventId: currentEventId, operator: 'J. Rivera (Shift 2)', actionType, notes: notes || `Operator executed ${actionType}` });
      setRecordedAction(res);
      await refreshHandover();
      if (actionType === 'RESOLVE') setTimeout(() => setIsHandoverModalOpen(true), 400);
    } catch (_) {}
  };

  const getEquipmentId = () => {
    if (selectedScenario === 'bearing_wear' || selectedScenario === 'compressor_overspeed') return 'Compressor-01';
    if (selectedScenario === 'sensor_fault') return 'Filter-01';
    if (selectedScenario === 'tank_overflow') return 'Tank-01';
    const pt = fullEvent?.candidate?.primary_tag || '';
    if (pt.includes('CMP')) return 'Compressor-01';
    if (pt.includes('TNK')) return 'Tank-01';
    if (pt.includes('FLT')) return 'Filter-01';
    return 'Pump-02';
  };

  const equipmentId  = getEquipmentId();
  const primaryTag   = fullEvent?.candidate?.primary_tag || (selectedScenario === 'bearing_wear' ? 'CMP-01-VIB' : 'VLV-04-POS');
  const causalLabel  = fullEvent?.story?.causal_label || null;
  const stepsLen     = fullEvent?.story?.steps?.length || 1;
  const panelsVisible = pacingMode === 'instant' || !simulating || simStep >= stepsLen;

  return (
    <div className="min-h-screen bg-[#070B11] text-slate-100 flex flex-col font-sans">

      {/* Sticky Header */}
      <Header
        machineStatus={{ status: isIncident ? 'CRITICAL_ALARM' : 'NOMINAL', primary_alarm: isIncident && Boolean(fullEvent?.candidate?.primary_alarm) }}
        isIncident={isIncident}
        simulating={simulating}
        simStep={simStep}
        totalSteps={(fullEvent?.story?.steps?.length || 5) + 2}
        pacingMode={pacingMode}
        setPacingMode={setPacingMode}
        onStartIncident={handleStartIncident}
        onResetDemo={handleResetDemo}
        onResetScenario={handleResetScenario}
        operatorName="J. Rivera (Shift 2)"
        scenarios={scenarios}
        selectedScenario={selectedScenario}
        onSelectScenario={setSelectedScenario}
        equipmentId={equipmentId}
        primaryTag={primaryTag}
        causalLabel={causalLabel}
        fullEvent={fullEvent}
      />

      {/* Dashboard body — optimised for 1920×1080 */}
      <main className="flex-1 px-6 py-5 space-y-4">

        {/* Row 1: Alarm banner */}
        <AlarmPrioritization
          isIncident={isIncident}
          revealedStep={simStep}
          candidate={fullEvent?.candidate}
          correlated={fullEvent?.correlated}
          story={fullEvent?.story}
          guidance={fullEvent?.guidance}
        />

        {/* Row 2: Sensor tiles */}
        <ProcessValues
          revealedStep={simStep}
          isIncident={isIncident}
          storySteps={fullEvent?.story?.steps || []}
          equipmentId={equipmentId}
          primaryTag={primaryTag}
        />

        {/* Row 3: Event story (full width) */}
        <EventStory
          story={fullEvent?.story}
          isIncident={isIncident}
          revealedCount={Math.min(simStep, stepsLen)}
        />

        {/* Row 4: Three-column — Evidence | SOP | Handover */}
        <div className="grid grid-cols-12 gap-4">
          {/* Evidence — 5 cols */}
          <div className="col-span-5">
            <EvidenceSection
              evidence={fullEvent?.evidence}
              isIncident={isIncident}
              isVisible={panelsVisible}
            />
          </div>

          {/* SOP — 3 cols */}
          <div className="col-span-3">
            <RelevantSop
              sopData={fullEvent?.sop_match}
              onOpenSopModal={() => setIsSopModalOpen(true)}
              isIncident={isIncident}
              isVisible={panelsVisible}
            />
          </div>

          {/* Handover — 4 cols */}
          <div className="col-span-4">
            <ShiftHandoverCard
              handover={handover}
              unitName={equipmentId}
              onOpenModal={() => setIsHandoverModalOpen(true)}
              isIncident={isIncident}
              fullEvent={fullEvent}
            />
          </div>
        </div>

        {/* Row 5: Next-best actions (full width) */}
        <NextBestAction
          guidance={fullEvent?.guidance}
          actions={fullEvent?.guidance?.next_best_actions || []}
          equipmentId={equipmentId}
          primaryTag={fullEvent?.evidence?.likely_contributor_tag || primaryTag}
          recordedAction={recordedAction}
          onExecuteAction={handleOperatorAction}
          onOpenSopModal={() => setIsSopModalOpen(true)}
          isIncident={isIncident}
          isVisible={panelsVisible}
        />

      </main>

      {/* Modals */}
      <SopModal isOpen={isSopModalOpen} onClose={() => setIsSopModalOpen(false)} sopData={fullEvent?.sop_match} />
      <HandoverModal isOpen={isHandoverModalOpen} onClose={() => setIsHandoverModalOpen(false)} handover={handover} unitName={equipmentId} isIncident={isIncident} />
    </div>
  );
}
