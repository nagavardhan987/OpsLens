import React, { useState, useEffect, useRef, useCallback } from 'react';
import Header from './components/Header';
import ProcessValues from './components/ProcessValues';
import EventStory from './components/EventStory';
import EvidenceSection from './components/EvidenceSection';
import RelevantSop from './components/RelevantSop';
import NextBestAction from './components/NextBestAction';
import ShiftHandoverCard from './components/ShiftHandoverCard';
import AlarmHistory from './components/AlarmHistory';
import IncidentOverview from './components/IncidentOverview';
import AskOpsLensDrawer from './components/AskOpsLensDrawer';
import SopModal from './components/SopModal';
import AlarmPopup from './components/AlarmPopup';
import ImpactMetricsPanel from './components/ImpactMetricsPanel';
import HandoverModal from './components/HandoverModal';
import { resolveEventEquipment } from './lib/equipmentPresentation';
import {
  subscribeToEventStream,
  getFullEvent,
  getOpenEvents,
  getRecentEvents,
  logOperatorAction,
  compileHandover,
} from './api/client';

export default function App() {
  const [fullEvent, setFullEvent] = useState(null);
  const [currentEventId, setCurrentEventId] = useState(null);
  const [handover, setHandover] = useState(null);
  const [recentEvents, setRecentEvents] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(true);

  const [isIncident, setIsIncident] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [simStep, setSimStep] = useState(0);
  const [pacingMode, setPacingMode] = useState('animated');
  const [recordedAction, setRecordedAction] = useState(null);

  const [isSopModalOpen, setIsSopModalOpen] = useState(false);
  const [isHandoverModalOpen, setIsHandoverModalOpen] = useState(false);
  const [isAssistantOpen, setIsAssistantOpen] = useState(false);

  const timersRef = useRef([]);
  const currentEventIdRef = useRef(null);

  const clearAllTimers = () => {
    timersRef.current.forEach(t => { clearTimeout(t); clearInterval(t); });
    timersRef.current = [];
  };

  const refreshHandover = useCallback(async () => {
    try { const h = await compileHandover(); setHandover(h); } catch (_) {}
  }, []);

  const refreshRecentEvents = useCallback(async () => {
    try { setRecentEvents(await getRecentEvents(10)); }
    catch (_) { /* Keep the last successfully loaded history visible. */ }
    finally { setHistoryLoading(false); }
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
    if (!eventId || eventId === currentEventIdRef.current) return;
    try {
      const full = await getFullEvent(eventId);
      if (full) {
        currentEventIdRef.current = eventId;
        setCurrentEventId(eventId);
        setFullEvent(full);
        setIsIncident(true);
        triggerCascade(full.story?.steps?.length || 5);
        refreshHandover();
        refreshRecentEvents();
      }
    } catch (_) {}
  }, [triggerCascade, refreshHandover, refreshRecentEvents]);

  // Poll the active-event endpoint as a recovery path if a browser connects
  // after an SSE notification or briefly loses its EventSource connection.
  const refreshActiveIncident = useCallback(async () => {
    try {
      const open = await getOpenEvents();
      if (!open.length) {
        setIsIncident((active) => active ? false : active);
        return;
      }
      const eventId = open[open.length - 1].event_id;
      if (!eventId) return;
      const full = await getFullEvent(eventId);
      if (full) {
        setFullEvent(full);
        setIsIncident(true);
        if (eventId !== currentEventIdRef.current) {
          currentEventIdRef.current = eventId;
          setCurrentEventId(eventId);
          triggerCascade(full.story?.steps?.length || 5);
          refreshHandover();
          refreshRecentEvents();
        }
      }
    } catch (_) { /* The data panels retain their last recorded state when unavailable. */ }
  }, [triggerCascade, refreshHandover, refreshRecentEvents]);

  const selectHistoryEvent = useCallback(async (eventId) => {
    try {
      const full = await getFullEvent(eventId);
      if (!full) return;
      currentEventIdRef.current = eventId;
      setCurrentEventId(eventId);
      setFullEvent(full);
      setIsIncident(full.status !== 'RESOLVED');
      setSimStep(full.story?.steps?.length || 0);
      setSimulating(false);
      setRecordedAction([...(full.actions || [])].reverse().find((action) => action.action_type === 'RESOLVE') || null);
    } catch (error) { window.alert(error.message || 'Could not record operator action.'); }
  }, []);

  useEffect(() => {
    // Subscribe synchronously before any API calls to avoid a startup race.
    const unsub = subscribeToEventStream(handleLiveEvent, () => {});
    refreshHandover();
    refreshRecentEvents();
    refreshActiveIncident();
    const poll = setInterval(refreshActiveIncident, 2500);
    const historyPoll = setInterval(refreshRecentEvents, 10000);
    return () => { clearAllTimers(); clearInterval(poll); clearInterval(historyPoll); unsub(); };
  }, [handleLiveEvent, refreshActiveIncident, refreshHandover, refreshRecentEvents]);

  const handleOperatorAction = async (actionType, notes) => {
    if (!currentEventId) return;
    if (actionType === 'RESOLVE' && !window.confirm('Have you checked the EcoStruxure/runtime and confirmed that this alarm is clear? This records your confirmation only; OpsLens will not write to the PLC or control equipment.')) return;
    try {
      const safeNotes = actionType === 'RESOLVE'
        ? `Operator attests runtime alarm is clear. ${notes || ''}`.trim()
        : notes || `Operator recorded ${actionType}`;
      const res = await logOperatorAction({ eventId: currentEventId, operator: 'J. Rivera (Shift 2)', actionType, notes: safeNotes });
      setRecordedAction(res);
      await refreshHandover();
      await refreshRecentEvents();
      if (actionType === 'RESOLVE') {
        const updated = await getFullEvent(currentEventId);
        if (updated) setFullEvent(updated);
        setIsIncident(false);
        setTimeout(() => setIsHandoverModalOpen(true), 400);
      }
    } catch (_) {}
  };

  const equipmentId  = resolveEventEquipment(fullEvent);
  const hasEvent = Boolean(fullEvent);
  const primaryTag   = fullEvent?.candidate?.primary_tag || fullEvent?.primary_tag || fullEvent?.story?.steps?.find((step) => !String(step.tag || '').startsWith('ALM-'))?.tag || '';
  const stepsLen     = fullEvent?.story?.steps?.length || 1;
  const panelsVisible = true;

  return (
    <div className="hmi-app min-h-screen flex flex-col font-sans">
      <Header onAskOpsLens={() => setIsAssistantOpen(true)} />

      <main id="overview" className="hmi-main mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-5 px-4 py-5 md:px-7 md:py-7">
        {hasEvent
          ? <IncidentOverview event={fullEvent} equipment={equipmentId} isActive={isIncident} onOpenSop={() => setIsSopModalOpen(true)} onAskOpsLens={() => setIsAssistantOpen(true)} />
          : <section className="incident-panel history"><h1 className="text-xl font-semibold text-white">No incident selected</h1><p className="mt-2 text-sm leading-6 text-slate-400">Open Scenario Lab to run a synthetic event, or select a recorded incident from alarm history.</p></section>}

        {hasEvent && <ProcessValues event={fullEvent} equipmentId={equipmentId} />}

        {hasEvent && <details className="dashboard-details" open>
          <summary><span>Incident timeline</span><span className="details-hint">{fullEvent?.story?.causal_label || 'Event sequence'}</span></summary>
          <div className="border-t border-slate-800 p-4">
            <EventStory story={fullEvent?.story} isIncident={hasEvent} revealedCount={Math.min(simStep, stepsLen)} />
          </div>
        </details>}

        {hasEvent && <details className="dashboard-details">
          <summary><span>Evidence and analysis</span><span className="details-hint">Contributor ranking · supporting records</span></summary>
          <div className="border-t border-slate-800 p-4">
            <EvidenceSection evidence={fullEvent?.evidence} evidenceAudit={fullEvent?.evidence_audit} isIncident={hasEvent} isVisible={panelsVisible} />
          </div>
        </details>}

        {hasEvent && <details className="dashboard-details">
          <summary><span>Procedure and operator record</span><span className="details-hint">SOP · next-best actions · shift handover</span></summary>
          <div className="border-t border-slate-800 p-4 space-y-3">
            {/* SOP match — compact single row above actions */}
            <RelevantSop sopData={fullEvent?.sop_match} onOpenSopModal={() => setIsSopModalOpen(true)} isIncident={hasEvent} isVisible={panelsVisible} />
            {/* 2-column: actions (wider) + handover (sidebar) */}
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
              <NextBestAction guidance={fullEvent?.guidance} actions={fullEvent?.guidance?.next_best_actions || []} equipmentId={equipmentId} primaryTag={fullEvent?.evidence?.likely_contributor_tag || primaryTag} recordedAction={recordedAction} onExecuteAction={handleOperatorAction} onOpenSopModal={() => setIsSopModalOpen(true)} isIncident={hasEvent} isVisible={panelsVisible} isResolved={!isIncident} alarmClearObserved={fullEvent?.runtime_alarm_state?.observed && fullEvent?.runtime_alarm_state?.active === false} />
              <ShiftHandoverCard handover={handover} unitName={equipmentId} onOpenModal={() => setIsHandoverModalOpen(true)} isIncident={hasEvent} fullEvent={fullEvent} />
            </div>
          </div>
        </details>}

        <ImpactMetricsPanel />

        <details className="dashboard-details">
          <summary><span>Alarm history</span><span className="details-hint">{historyLoading ? 'Loading records…' : `${recentEvents.length} recorded events`}</span></summary>
          <div className="border-t border-slate-800 p-4"><AlarmHistory events={recentEvents} loading={historyLoading} onSelectEvent={selectHistoryEvent} /></div>
        </details>
      </main>

      {/* Modals */}
      <SopModal isOpen={isSopModalOpen} onClose={() => setIsSopModalOpen(false)} sopData={fullEvent?.sop_match} />
      <HandoverModal isOpen={isHandoverModalOpen} onClose={() => setIsHandoverModalOpen(false)} handover={handover} unitName={equipmentId} isIncident={isIncident} />
      <AskOpsLensDrawer event={fullEvent} equipment={equipmentId} isOpen={isAssistantOpen} onClose={() => setIsAssistantOpen(false)} />
      <AlarmPopup 
        event={fullEvent} 
        isActive={isIncident} 
        onOpenCopilot={() => setIsAssistantOpen(true)}
        onDismiss={() => {}}
      />
    </div>
  );
}
