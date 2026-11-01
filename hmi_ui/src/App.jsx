import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Activity, ChevronLeft, ChevronRight, ClipboardList, History, LayoutDashboard, Lightbulb, ListChecks, Menu, Network } from 'lucide-react';
import ProcessValues from './components/ProcessValues';
import EventStory from './components/EventStory';
import EvidenceSection from './components/EvidenceSection';
import RelevantSop from './components/RelevantSop';
import NextBestAction from './components/NextBestAction';
import ShiftHandoverCard from './components/ShiftHandoverCard';
import AlarmHistory from './components/AlarmHistory';
import IncidentOverview from './components/IncidentOverview';
import AlarmQueue from './components/AlarmQueue';
import IncidentAnalysis from './components/IncidentAnalysis';
import AskOpsLensDrawer from './components/AskOpsLensDrawer';
import SopModal from './components/SopModal';
import AlarmPopup from './components/AlarmPopup';
import SopLibrary from './components/SopLibrary';
import HandoverModal from './components/HandoverModal';
import { resolveEventEquipment } from './lib/equipmentPresentation';
import { getWorkflowSubmission, hasSubsequentClearAlarmReading, workflowActionFailureMessage, workflowActionSuccessMessage } from './lib/operatorWorkflow';
import {
  subscribeToEventStream,
  getFullEvent,
  getRecentEvents,
  getRankedIncidents,
  askOpsLensStream,
  logOperatorAction,
  markIncidentUnresolved,
  compileHandover,
  getIntegrationStatus,
} from './api/client';

export default function App() {
  const [fullEvent, setFullEvent] = useState(null);
  const [currentEventId, setCurrentEventId] = useState(null);
  const [handover, setHandover] = useState(null);
  const [recentEvents, setRecentEvents] = useState([]);
  const [rankedIncidents, setRankedIncidents] = useState([]);
  const [integrationStatus, setIntegrationStatus] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState('');
  const [serviceError, setServiceError] = useState('');
  const [analysisAnswer, setAnalysisAnswer] = useState(null);
  const [analysisDraft, setAnalysisDraft] = useState('');
  const [analysisStatus, setAnalysisStatus] = useState('');
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState('');

  const [isIncident, setIsIncident] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [simStep, setSimStep] = useState(0);
  const [pacingMode, setPacingMode] = useState('animated');
  const [recordedAction, setRecordedAction] = useState(null);
  const [operatorActionError, setOperatorActionError] = useState('');
  const [operatorActionSuccess, setOperatorActionSuccess] = useState('');
  const [operatorActionSubmitting, setOperatorActionSubmitting] = useState(false);
  const [workflowDialog, setWorkflowDialog] = useState(null);
  const [selectedStoryStep, setSelectedStoryStep] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [activeAlarmsOpen, setActiveAlarmsOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [activePage, setActivePage] = useState('Overview');
  const [sidebarExpanded, setSidebarExpanded] = useState(false);

  const [isSopModalOpen, setIsSopModalOpen] = useState(false);
  const [isHandoverModalOpen, setIsHandoverModalOpen] = useState(false);
  const [isAssistantOpen, setIsAssistantOpen] = useState(false);

  const timersRef = useRef([]);
  const currentEventIdRef = useRef(null);
  const analysisEventRef = useRef(null);
  const analysisAbortRef = useRef(null);
  const actionSubmitRef = useRef(false);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const status = await getIntegrationStatus();
        if (active) setIntegrationStatus(status);
      } catch (_) {
        if (active) setIntegrationStatus(null);
      }
    };
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => { active = false; clearInterval(interval); };
  }, []);

  const clearAllTimers = () => {
    timersRef.current.forEach(t => { clearTimeout(t); clearInterval(t); });
    timersRef.current = [];
  };

  const refreshHandover = useCallback(async () => {
    try { const h = await compileHandover(); setHandover(h); } catch (_) {}
  }, []);

  const refreshRecentEvents = useCallback(async () => {
    try {
      setRecentEvents(await getRecentEvents(20));
      setHistoryError('');
    }
    catch (_) { setHistoryError('Alarm history is temporarily unavailable.'); }
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
    if (!eventId) return;
    try {
      const full = await getFullEvent(eventId);
      if (full) {
        if (eventId !== currentEventIdRef.current) {
          setAnalysisAnswer(null); setAnalysisDraft(''); setAnalysisError(''); setAnalysisStatus('Preparing assessment…');
        }
        setFullEvent(full);
        setIsIncident(true);
        setRecordedAction([...(full.actions || [])].reverse()[0] || null);
        setDetailsOpen(false);
        setSelectedStoryStep(null);
        if (eventId !== currentEventIdRef.current) {
          currentEventIdRef.current = eventId;
          setCurrentEventId(eventId);
          triggerCascade(full.story?.steps?.length || 5);
        }
        refreshHandover();
        refreshRecentEvents();
      }
    } catch (_) { setServiceError('The new alarm details are temporarily unavailable.'); }
  }, [triggerCascade, refreshHandover, refreshRecentEvents]);

  // Poll the active-event endpoint as a recovery path if a browser connects
  // after an SSE notification or briefly loses its EventSource connection.
  const refreshActiveIncident = useCallback(async () => {
    try {
      const ranking = await getRankedIncidents(20);
      if (!ranking || !Array.isArray(ranking.ranked_incidents)) throw new Error('Alarm list unavailable');
      const incidents = ranking.ranked_incidents;
      setRankedIncidents(incidents);
      setServiceError('');
      const eventId = currentEventIdRef.current || incidents[0]?.event_id;
      if (!eventId) {
        setIsIncident(false);
        return;
      }
      if (!currentEventIdRef.current && incidents[0]?.event_id) {
        setAnalysisAnswer(null); setAnalysisDraft(''); setAnalysisError(''); setAnalysisStatus('Preparing assessment…');
        currentEventIdRef.current = eventId;
        setCurrentEventId(eventId);
        triggerCascade(incidents[0].story?.steps?.length || 5);
        refreshHandover();
        refreshRecentEvents();
      }
      const full = await getFullEvent(eventId);
      if (full) {
        setFullEvent(full);
        setIsIncident(full.status !== 'RESOLVED');
      }
    } catch (_) { setServiceError('Active alarms are temporarily unavailable.'); }
  }, [triggerCascade, refreshHandover, refreshRecentEvents]);

  const selectHistoryEvent = useCallback(async (eventId) => {
    try {
      setAnalysisAnswer(null); setAnalysisDraft(''); setAnalysisError(''); setAnalysisStatus('Preparing assessment…');
      const full = await getFullEvent(eventId);
      if (!full) return;
      currentEventIdRef.current = eventId;
      setCurrentEventId(eventId);
      setFullEvent(full);
      setServiceError('');
      setIsIncident(full.status !== 'RESOLVED');
      setSimStep(full.story?.steps?.length || 0);
      setSimulating(false);
      setRecordedAction([...(full.actions || [])].reverse()[0] || null);
      setSelectedStoryStep(null);
      setDetailsOpen(false);
    } catch (_) { setServiceError('This incident could not be loaded. Try again.'); }
  }, []);

  useEffect(() => {
    const eventId = fullEvent?.event_id;
    if (!eventId || analysisEventRef.current === eventId) return undefined;
    analysisAbortRef.current?.abort();
    const controller = new AbortController();
    analysisAbortRef.current = controller;
    analysisEventRef.current = eventId;
    setAnalysisAnswer(null);
    setAnalysisDraft('');
    setAnalysisStatus('Preparing assessment…');
    setAnalysisError('');
    setAnalysisLoading(true);
    askOpsLensStream({
      eventId,
      question: 'Why did this alarm trigger? Give a concise explanation using recorded readings, event sequence, and retrieved SOP evidence where available.',
      signal: controller.signal,
      onStatus: () => setAnalysisStatus('Preparing assessment…'),
      onToken: (text) => { setAnalysisStatus(''); setAnalysisDraft((current) => current + text); },
      onError: () => setAnalysisError('Assessment is temporarily unavailable. Review the recorded observations below.'),
      onDone: (answer) => setAnalysisAnswer(answer),
    }).catch((error) => {
      if (error.name !== 'AbortError') setAnalysisError('Assessment is temporarily unavailable. Review the recorded observations below.');
    }).finally(() => {
      if (!controller.signal.aborted) setAnalysisLoading(false);
    });
    return () => controller.abort();
  }, [fullEvent?.event_id]);

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
    if (!currentEventId || actionSubmitRef.current) return false;
    if (actionType === 'LOG_EVENT' && !String(notes || '').trim()) return false;
    actionSubmitRef.current = true;
    setOperatorActionSubmitting(true);
    setOperatorActionError('');
    setOperatorActionSuccess('');
    if (actionType === 'RESOLVE' && !window.confirm('Have you checked the EcoStruxure/runtime and confirmed that this alarm is clear? This records your confirmation only; OpsLens will not write to the PLC or control equipment.')) {
      actionSubmitRef.current = false;
      setOperatorActionSubmitting(false);
      return false;
    }
    try {
      const submission = getWorkflowSubmission(actionType, notes || '');
      let res;
      if (submission.kind === 'status') {
        res = await markIncidentUnresolved({ eventId: currentEventId, operator: 'J. Rivera (Shift 2)', reason: submission.reason });
      } else {
        const safeNotes = actionType === 'RESOLVE'
          ? `Operator attests runtime alarm is clear. ${notes || ''}`.trim()
          : submission.notes || `Operator recorded ${actionType}`;
        res = await logOperatorAction({ eventId: currentEventId, operator: 'J. Rivera (Shift 2)', actionType: submission.actionType, notes: safeNotes });
      }
      const savedAction = res.action || res;
      setRecordedAction(savedAction);
      await refreshHandover();
      await refreshRecentEvents();
      const updated = await getFullEvent(currentEventId);
      if (updated) {
        setFullEvent(updated);
        setIsIncident(Boolean(updated.is_open));
        setRecordedAction([...(updated.actions || [])].reverse()[0] || savedAction);
      }
      setOperatorActionSuccess(workflowActionSuccessMessage(actionType));
      if (actionType === 'RESOLVE') {
        setTimeout(() => setIsHandoverModalOpen(true), 400);
      }
      return true;
    } catch (error) {
      setOperatorActionError(workflowActionFailureMessage(actionType, error));
      return false;
    } finally {
      actionSubmitRef.current = false;
      setOperatorActionSubmitting(false);
    }
  };

  const submitWorkflowDialog = async () => {
    if (!workflowDialog || actionSubmitRef.current) return;
    const success = await handleOperatorAction(workflowDialog.actionType, workflowDialog.note || '');
    if (success) setWorkflowDialog(null);
  };

  const equipmentId  = resolveEventEquipment(fullEvent);
  const hasEvent = Boolean(fullEvent);
  const primaryTag   = fullEvent?.candidate?.primary_tag || fullEvent?.primary_tag || fullEvent?.story?.steps?.find((step) => !String(step.tag || '').startsWith('ALM-'))?.tag || '';
  const relatedAlarm = fullEvent?.candidate?.alarm_id || fullEvent?.candidate?.primary_tag || primaryTag || null;
  const stepsLen     = fullEvent?.story?.steps?.length || 1;
  const panelsVisible = true;
  const possibleCauseTag = analysisAnswer?.cause?.contributor_tag || fullEvent?.evidence?.likely_contributor_tag;
  const selectedDataSource = fullEvent?.runtime_alarm_state?.data_source
    || analysisAnswer?.supporting_readings?.find((reading) => reading?.data_source || reading?.source)?.data_source
    || analysisAnswer?.supporting_readings?.find((reading) => reading?.data_source || reading?.source)?.source
    || null;
  const openIncidentGroups = rankedIncidents.filter((item) => item.is_open !== false && item.status !== 'RESOLVED');
  const activeAlarmCount = openIncidentGroups.reduce((count, item) => count + (Array.isArray(item.individual_alarms) && item.individual_alarms.length ? item.individual_alarms.length : 1), 0);
  const alarmGroups = new Set(openIncidentGroups.map((item) => item.group_id || item.alarm_group || item.equipment_id || item.correlated?.equipment_id || item.candidate?.equipment_id || item.individual_alarms?.[0]?.equipment_id || item.individual_alarms?.[0]?.equipment).filter(Boolean)).size;
  const topPriority = rankedIncidents[0]?.priority || rankedIncidents[0]?.urgency?.urgency_band || rankedIncidents[0]?.severity || '—';
  const sourceText = String(selectedDataSource || '').toLowerCase();
  const plcAdapter = integrationStatus?.adapters?.find((item) => item.type === 'opcua');
  const overviewSourceState = /simulat|synthetic/.test(sourceText) ? 'SIMULATED'
    : /stale/.test(sourceText) || plcAdapter?.source_label === 'STALE DATA' ? 'STALE'
      : /opc.?ua|plc|^live$/.test(sourceText) || plcAdapter?.source_label === 'LIVE PLC DATA' ? 'LIVE PLC'
        : hasEvent ? 'RECORDED' : 'DISCONNECTED';
  const possibleCauseText = analysisAnswer?.cause?.explanation
    || (possibleCauseTag ? `Recorded changes in ${possibleCauseTag} may be relevant to this alarm.` : 'No likely contributor is established from the recorded observations.');
  const safeActions = analysisAnswer?.solution?.steps?.length
    ? analysisAnswer.solution.steps
    : fullEvent?.sop_resolution?.approved === true && fullEvent?.guidance?.next_best_actions?.length
      ? fullEvent.guidance.next_best_actions
      : ['Confirm the alarm state and latest recorded timestamp on the operator runtime.', 'Compare current readings for the alarm and related tags; check data quality and time alignment.', 'No approved operating instructions are verified. Consult the plant procedure or responsible personnel before operating.'];
  const openIncidentDetails = () => {
    setDetailsOpen(true);
    window.setTimeout(() => document.getElementById('incident-details')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 40);
  };
  const openAlarmHistory = () => { setHistoryOpen(true); openIncidentDetails(); };
  const openAllActiveAlarms = () => { setActiveAlarmsOpen(true); openIncidentDetails(); };
  const recordWorkflowAction = (actionType, notes) => handleOperatorAction(actionType, notes);
  const openWorkflowNote = (actionType) => {
    setOperatorActionError('');
    setOperatorActionSuccess('');
    setWorkflowDialog({ actionType, note: '' });
  };

  return (
    <div className="hmi-app operator-shell min-h-screen flex flex-col font-sans">
      <div className="operator-workspace">
      <nav className={`operator-sidebar ${sidebarExpanded ? 'expanded' : 'collapsed'}`} aria-label="Main navigation">
        <button className="operator-sidebar-toggle" type="button" aria-label={sidebarExpanded ? 'Collapse navigation' : 'Expand navigation'} onClick={() => setSidebarExpanded((value) => !value)}>{sidebarExpanded ? <ChevronLeft size={19}/> : <Menu size={19}/>}</button>
        {[['Overview', LayoutDashboard], ['Event Story', Activity], ['Evidence Engine', Network], ['Incident History', History]].map(([label, Icon]) => <button key={label} type="button" title={label} aria-current={activePage === label ? 'page' : undefined} className={`operator-nav-item ${activePage === label ? 'active' : ''}`} onClick={() => { setActivePage(label); if (window.innerWidth < 760) setSidebarExpanded(false); }}><Icon size={19}/>{sidebarExpanded && <span>{label}</span>}</button>)}
      </nav>
      {sidebarExpanded && <button className="operator-sidebar-backdrop" aria-label="Close navigation" onClick={() => setSidebarExpanded(false)} />}

      <main id="overview" className={`operator-main flex w-full flex-1 flex-col gap-3 px-3 py-3 md:px-4 page-${activePage.toLowerCase().replaceAll(' ', '-')}`}>
        {serviceError && <div role="status" className="operator-service-state">{serviceError}</div>}
        {activePage === 'Overview' && <><section className="overview-status-strip" aria-label="Alarm and data-source status">
          <div className="overview-status-item"><span>Active alarms</span><strong>{activeAlarmCount}</strong></div>
          <div className="overview-status-item"><span>Alarm groups</span><strong>{alarmGroups}</strong></div>
          <div className="overview-status-item"><span>Priority</span><strong>{String(topPriority).toUpperCase()}</strong></div>
          <div className={`overview-status-item source ${overviewSourceState.toLowerCase().replace(' ', '-')}`}><span>Data source</span><strong>{overviewSourceState}</strong></div>
          <div className="overview-status-context">{primaryTag || currentEventId || 'No incident selected'}{equipmentId ? ` · ${equipmentId}` : ''}</div>
        </section><section className="operator-overview-grid" aria-label="Operator overview">
          <div className="operator-panel operator-alarms">
            <AlarmQueue incidents={rankedIncidents} selectedEventId={currentEventId} onSelect={selectHistoryEvent} loading={historyLoading} error={serviceError} compact />
            <div className="operator-panel-links"><button type="button" onClick={openAllActiveAlarms}>View all alarms</button><button type="button" onClick={openAlarmHistory}>Past related events</button></div>
          </div>
          <section className="operator-panel operator-cause" aria-label="Possible root cause">
            <div className="operator-panel-heading"><div><span className="operator-eyebrow">Possible contributor</span><h2>{possibleCauseTag || 'Not identified'}</h2></div><span className={`cause-state ${analysisAnswer?.cause?.confirmed === true ? 'confirmed' : 'possible'}`}>{analysisAnswer?.cause?.confirmed === true ? 'Confirmed' : 'Under investigation'}</span></div>
            <p>{possibleCauseText}</p>
            <button type="button" className="operator-text-button" onClick={openIncidentDetails}>View details</button>
          </section>
          <section className="operator-panel operator-next-action" aria-label="Next best actions">
            <div className="operator-panel-heading"><div><span className="operator-eyebrow">Next step</span><h2>Safe verification</h2></div></div>
            <ol>{safeActions.slice(0, 3).map((action, index) => <li key={`${index}-${action}`}><span>{index + 1}</span><p>{action}</p></li>)}</ol>
            <button type="button" className="operator-text-button" onClick={openIncidentDetails}>View action details</button>
          </section>
          <section className="operator-panel operator-quick-access" aria-label="Quick access">
            <span className="operator-eyebrow">Quick access</span>
            <button type="button" disabled={!hasEvent} onClick={() => setIsSopModalOpen(true)}>View SOP</button>
            <button type="button" disabled={!hasEvent} onClick={() => setIsAssistantOpen(true)}>Ask OpsLens</button>
            <button type="button" onClick={() => setActivePage('SOP Library')}>SOP Library</button>
          </section>
        </section>

        <section className="operator-panel operator-timeline" aria-labelledby="operator-timeline-heading">
          <div className="operator-section-heading"><div><h2 id="operator-timeline-heading">Event Story</h2></div><button type="button" className="operator-text-button" onClick={openIncidentDetails}>View details</button></div>
          <EventStory story={fullEvent?.story} isIncident={hasEvent} revealedCount={Math.min(simStep, stepsLen)} compact selectedStep={selectedStoryStep} onSelectStep={setSelectedStoryStep} dataSource={selectedDataSource} relatedAlarm={relatedAlarm} />
        </section>

        <section className="operator-panel operator-equipment" aria-label="Equipment status">
          <ProcessValues event={fullEvent} equipmentId={equipmentId} compact onOpenDetails={openIncidentDetails} supportingReadings={analysisAnswer?.supporting_readings || []} />
        </section>

        <section className="operator-workflow" aria-label="Resolution and operator workflow">
          <div className="operator-workflow-title"><span className="operator-eyebrow">Resolution</span><strong>{hasEvent ? isIncident ? 'Operator workflow' : 'Incident reported clear' : 'Select an incident to begin'}</strong></div>
          <div className="operator-workflow-actions">
            <button type="button" disabled={!hasEvent || operatorActionSubmitting} onClick={() => recordWorkflowAction('VERIFY', 'Operator independently verified the displayed incident details. Alarm state unchanged.')}>Verify</button>
            <button type="button" disabled={!hasEvent || operatorActionSubmitting} onClick={() => recordWorkflowAction('INSPECT', 'Operator recorded an inspection acknowledgement; no PLC write performed.')}>Inspect</button>
            <button type="button" disabled={!hasEvent} onClick={() => setIsAssistantOpen(true)}>AI Guidance</button>
            <button type="button" disabled={!hasEvent} onClick={() => setIsSopModalOpen(true)}>SOP</button>
            <button type="button" disabled={!hasEvent || operatorActionSubmitting} onClick={() => openWorkflowNote('LOG_EVENT')}>Log Event</button>
            <button type="button" className="unresolved" disabled={!hasEvent || operatorActionSubmitting} onClick={() => openWorkflowNote('MARK_UNRESOLVED')}>Mark Unresolved</button>
          </div>
          {operatorActionError && <p role="alert" className="operator-action-error">{operatorActionError}</p>}
          {operatorActionSuccess && <p role="status" aria-live="polite" className="operator-action-success">{operatorActionSuccess}</p>}
        </section>

        </>}
        {activePage === 'Event Story' && <section className="operator-panel operator-page-panel event-story-page"><div className="operator-section-heading"><div><h1>Event Story</h1><span className="event-page-identity">{currentEventId || 'Select an incident'}{equipmentId ? ` · ${equipmentId}` : ''}</span></div></div><EventStory story={fullEvent?.story} isIncident={hasEvent} revealedCount={stepsLen} dataSource={selectedDataSource} relatedAlarm={relatedAlarm} /></section>}
        {activePage === 'Evidence Engine' && <section className="operator-panel operator-page-panel evidence-page"><div className="operator-section-heading"><div><h1>Evidence Engine</h1><span className="event-page-identity">{currentEventId || 'Select an incident'}{equipmentId ? ` · ${equipmentId}` : ''}</span></div></div><EvidenceSection evidence={fullEvent?.evidence} evidenceAudit={fullEvent?.evidence_audit} event={fullEvent} isIncident={hasEvent} /></section>}
        {activePage === 'Root Cause Analysis' && <section className="operator-page-panel">{hasEvent ? <IncidentAnalysis incident={fullEvent} answer={analysisAnswer} draft={analysisDraft} status={analysisStatus} loading={analysisLoading} error={analysisError} sopData={{ ...(fullEvent?.sop_match || {}), sop_resolution: fullEvent?.sop_resolution, resolved_sop_sources: fullEvent?.resolved_sop_sources }} onOpenSop={() => setIsSopModalOpen(true)} onAskOpsLens={() => setIsAssistantOpen(true)} onSelectHistorical={selectHistoryEvent} /> : <p>Select an incident to view its assessment.</p>}</section>}
        {activePage === 'Recommended Actions' && <section className="operator-panel operator-page-panel"><div className="operator-section-heading"><h1>Recommended Actions</h1><span>{fullEvent?.sop_resolution?.approved === true ? 'Approved guidance available' : 'No approved guidance verified'}</span></div><NextBestAction guidance={fullEvent?.sop_resolution?.approved === true ? fullEvent?.guidance : null} actions={fullEvent?.sop_resolution?.approved === true ? (fullEvent?.guidance?.next_best_actions || []) : []} referenceOnly={Boolean(fullEvent?.resolved_sop_sources?.length) && fullEvent?.sop_resolution?.approved !== true} equipmentId={equipmentId} primaryTag={fullEvent?.evidence?.likely_contributor_tag || primaryTag} recordedAction={recordedAction} onExecuteAction={handleOperatorAction} onOpenSopModal={() => setIsSopModalOpen(true)} isIncident={hasEvent} isVisible={true} isResolved={!isIncident} alarmClearObserved={hasSubsequentClearAlarmReading(fullEvent?.runtime_alarm_state)} actionError={operatorActionError} actionSubmitting={operatorActionSubmitting} /></section>}
        {activePage === 'SOP Library' && <SopLibrary />}
        {activePage === 'Incident History' && <section className="operator-panel operator-page-panel"><div className="operator-section-heading"><h1>Incident History</h1><span>{recentEvents.length} recorded</span></div><AlarmHistory events={recentEvents} loading={historyLoading} error={historyError} onSelectEvent={selectHistoryEvent} /></section>}

        {activePage === 'Overview' && <details id="incident-details" className="operator-detail-drawer" open={detailsOpen} onToggle={(event) => setDetailsOpen(event.currentTarget.open)}>
          <summary><span>Incident details and supporting records</span>{equipmentId && <span>{equipmentId}</span>}</summary>
          <div className="operator-detail-content">
            <details className="dashboard-details" open={activeAlarmsOpen} onToggle={(event) => setActiveAlarmsOpen(event.currentTarget.open)}><summary>All active alarms · {rankedIncidents.length}</summary><div className="operator-detail-inner"><AlarmQueue incidents={rankedIncidents} selectedEventId={currentEventId} onSelect={selectHistoryEvent} loading={historyLoading} error={serviceError} /></div></details>
            {hasEvent && <IncidentOverview event={fullEvent} equipment={equipmentId} isActive={isIncident} onOpenSop={() => setIsSopModalOpen(true)} onAskOpsLens={() => setIsAssistantOpen(true)} />}
            {hasEvent && <IncidentAnalysis incident={fullEvent} answer={analysisAnswer} draft={analysisDraft} status={analysisStatus} loading={analysisLoading} error={analysisError} sopData={{ ...(fullEvent?.sop_match || {}), sop_resolution: fullEvent?.sop_resolution, resolved_sop_sources: fullEvent?.resolved_sop_sources }} onOpenSop={() => setIsSopModalOpen(true)} onAskOpsLens={() => setIsAssistantOpen(true)} onSelectHistorical={selectHistoryEvent} />}
            {hasEvent && <details className="dashboard-details"><summary>Full event timeline</summary><div className="operator-detail-inner"><EventStory story={fullEvent?.story} isIncident={hasEvent} revealedCount={Math.min(simStep, stepsLen)} dataSource={selectedDataSource} /></div></details>}
            {hasEvent && <details className="dashboard-details"><summary>Evidence details</summary><div className="operator-detail-inner"><EvidenceSection evidence={fullEvent?.evidence} evidenceAudit={fullEvent?.evidence_audit} isIncident={hasEvent} isVisible={panelsVisible} /></div></details>}
            {hasEvent && <details className="dashboard-details"><summary>Procedure and operator records</summary><div className="operator-detail-inner"><RelevantSop sopData={{ ...(fullEvent.sop_match || {}), sop_resolution: fullEvent.sop_resolution, resolved_sop_sources: fullEvent.resolved_sop_sources }} onOpenSopModal={() => setIsSopModalOpen(true)} isIncident={hasEvent} isVisible={panelsVisible} /><div className="operator-detail-grid"><NextBestAction guidance={fullEvent?.sop_resolution?.approved === true ? fullEvent?.guidance : null} actions={fullEvent?.sop_resolution?.approved === true ? (fullEvent?.guidance?.next_best_actions || []) : []} referenceOnly={Boolean(fullEvent?.resolved_sop_sources?.length) && fullEvent?.sop_resolution?.approved !== true} equipmentId={equipmentId} primaryTag={fullEvent?.evidence?.likely_contributor_tag || primaryTag} recordedAction={recordedAction} onExecuteAction={handleOperatorAction} onOpenSopModal={() => setIsSopModalOpen(true)} isIncident={hasEvent} isVisible={panelsVisible} isResolved={!isIncident} alarmClearObserved={hasSubsequentClearAlarmReading(fullEvent?.runtime_alarm_state)} actionError={operatorActionError} actionSubmitting={operatorActionSubmitting} /><ShiftHandoverCard handover={handover} unitName={equipmentId} onOpenModal={() => setIsHandoverModalOpen(true)} isIncident={hasEvent} fullEvent={fullEvent} /></div></div></details>}
            <details className="dashboard-details" open={historyOpen} onToggle={(event) => setHistoryOpen(event.currentTarget.open)}><summary>Alarm history · {historyLoading ? 'Loading…' : `${recentEvents.length} recorded events`}</summary><div className="operator-detail-inner"><AlarmHistory events={recentEvents} loading={historyLoading} error={historyError} onSelectEvent={selectHistoryEvent} /></div></details>
          </div>
        </details>}
      </main>
      </div>

      {/* Modals */}
      <SopModal isOpen={isSopModalOpen} onClose={() => setIsSopModalOpen(false)} sopData={fullEvent ? { ...(fullEvent.sop_match || {}), sop_resolution: fullEvent.sop_resolution, resolved_sop_sources: fullEvent.resolved_sop_sources } : null} />
      <HandoverModal isOpen={isHandoverModalOpen} onClose={() => setIsHandoverModalOpen(false)} handover={handover} unitName={equipmentId} isIncident={isIncident} />
      <AskOpsLensDrawer event={fullEvent} equipment={equipmentId} isOpen={isAssistantOpen} onClose={() => setIsAssistantOpen(false)} />
      {workflowDialog && <div className="workflow-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !operatorActionSubmitting) setWorkflowDialog(null); }}>
        <section className="workflow-dialog" role="dialog" aria-modal="true" aria-labelledby="workflow-dialog-title">
          <div className="workflow-dialog-heading"><div><span className="operator-eyebrow">{workflowDialog.actionType === 'LOG_EVENT' ? 'Incident audit entry' : 'Incident status transition'}</span><h2 id="workflow-dialog-title">{workflowDialog.actionType === 'LOG_EVENT' ? 'Log Event' : 'Mark Unresolved'}</h2></div><button type="button" disabled={operatorActionSubmitting} aria-label="Close dialog" onClick={() => setWorkflowDialog(null)}>×</button></div>
          <p>Incident <strong>{currentEventId}</strong> · Operator <strong>J. Rivera (Shift 2)</strong></p>
          <label htmlFor="workflow-action-note">{workflowDialog.actionType === 'LOG_EVENT' ? 'Event note (required)' : 'Reason or operator note (optional)'}</label>
          <textarea id="workflow-action-note" rows={4} maxLength={1000} required={workflowDialog.actionType === 'LOG_EVENT'} value={workflowDialog.note} onChange={(event) => setWorkflowDialog((current) => ({ ...current, note: event.target.value }))} placeholder={workflowDialog.actionType === 'LOG_EVENT' ? 'Describe the event or observation to add to the audit history.' : 'Why is the incident unresolved?'} />
          <small>Saved with your name and the current time.</small>
          {operatorActionError && <p role="alert" className="operator-action-error">{operatorActionError}</p>}
          <div className="workflow-dialog-actions"><button type="button" disabled={operatorActionSubmitting} onClick={() => setWorkflowDialog(null)}>Cancel</button><button type="button" disabled={operatorActionSubmitting || (workflowDialog.actionType === 'LOG_EVENT' && !workflowDialog.note.trim())} onClick={submitWorkflowDialog}>{operatorActionSubmitting ? 'Saving…' : workflowDialog.actionType === 'LOG_EVENT' ? 'Save event note' : 'Mark unresolved'}</button></div>
        </section>
      </div>}
      <AlarmPopup 
        event={fullEvent} 
        isActive={isIncident} 
        onOpenCopilot={() => setIsAssistantOpen(true)}
        onDismiss={() => {}}
      />
    </div>
  );
}
