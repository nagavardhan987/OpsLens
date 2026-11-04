import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Activity, BookOpen, Bot, ChevronLeft, ClipboardList, Factory, FileText, History, LayoutDashboard, Menu, Network } from 'lucide-react';
import OverviewHMI, { AlarmBanner } from './components/hmi/OverviewHMI';
import DiagnosisPanel from './components/hmi/DiagnosisPanel';
import PlantOverview from './components/hmi/PlantOverview';
import './hmi-overview.css';
import ProcessValues from './components/ProcessValues';
import EventStory from './components/EventStory';
import EvidenceSection from './components/EvidenceSection';
import RelevantSop from './components/RelevantSop';
import NextBestAction from './components/NextBestAction';
import OperatorBrief from './components/OperatorBrief';
import ShiftHandoverCard from './components/ShiftHandoverCard';
import AlarmHistory from './components/AlarmHistory';
import ShiftHandoverPage from './components/ShiftHandoverPage';
import IncidentOverview from './components/IncidentOverview';
import AlarmQueue from './components/AlarmQueue';
import IncidentAnalysis from './components/IncidentAnalysis';
import AskOpsLensDrawer from './components/AskOpsLensDrawer';
import SopModal from './components/SopModal';
import AlarmPopup from './components/AlarmPopup';
import SopLibrary from './components/SopLibrary';
import { resolveEventEquipment } from './lib/equipmentPresentation';
import { getAcknowledgementTarget, isAlarmAcknowledged, summarizeAlarmStates } from './lib/alarmState';
import { getWorkflowSubmission, hasSubsequentClearAlarmReading, workflowActionFailureMessage, workflowActionSuccessMessage } from './lib/operatorWorkflow';
import {
  subscribeToEventStream,
  getFullEvent,
  getRecentEvents,
  getAlarmHistory,
  getCurrentHandover,
  getHandoverHistory,
  getHandoverRecord,
  submitHandover,
  respondToHandoverItem,
  confirmHandover,
  getRankedIncidents,
  logOperatorAction,
  markIncidentUnresolved,
  getIntegrationStatus,
  getDataSource,
  getOllamaStatus,
  getOperatorBrief,
  getEventTrends,
} from './api/client';

export default function App() {
  const [fullEvent, setFullEvent] = useState(null);
  const [currentEventId, setCurrentEventId] = useState(null);
  const [handover, setHandover] = useState(null);
  const [recentEvents, setRecentEvents] = useState([]);
  const [alarmHistory, setAlarmHistory] = useState([]);
  const [handoverHistory, setHandoverHistory] = useState([]);
  const [selectedHandover, setSelectedHandover] = useState(null);
  const [handoverSubmitting, setHandoverSubmitting] = useState(false);
  const [handoverError, setHandoverError] = useState('');
  const [rankedIncidents, setRankedIncidents] = useState([]);
  const [integrationStatus, setIntegrationStatus] = useState(null);
  const [dataSource, setDataSource] = useState(null);
  const [aiStatus, setAiStatus] = useState(null);
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

  const [brief, setBrief] = useState(null);
  const [trends, setTrends] = useState(null);
  const [trendsLoading, setTrendsLoading] = useState(false);
  const [clock, setClock] = useState(() => new Date());

  const [isSopModalOpen, setIsSopModalOpen] = useState(false);
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
      try {
        const source = await getDataSource();
        if (active) setDataSource(source);
      } catch (_) {
        if (active) setDataSource(null);
      }
      try {
        const ai = await getOllamaStatus();
        if (active) setAiStatus(ai);
      } catch (_) {
        if (active) setAiStatus(null);
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
    try { const h = await getCurrentHandover(); setHandover(h); } catch (_) {}
  }, []);

  const refreshHandoverHistory = useCallback(async () => {
    try { setHandoverHistory(await getHandoverHistory()); } catch (_) {}
  }, []);

  const refreshAlarmHistory = useCallback(async () => {
    try { const result = await getAlarmHistory(); setAlarmHistory(result.alarms || []); setHistoryError(''); }
    catch (_) { setHistoryError('Alarm history is temporarily unavailable.'); }
    finally { setHistoryLoading(false); }
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

  const navigateAlarmHistory = useCallback(() => setActivePage('Alarm History'), []);

  // Brief (deterministic facts) and trends for the selected incident. The AI
  // diagnosis panel fetches its own stream; the older auto "why" question to
  // the assistant is no longer fired on every incident, so Ollama serves one
  // request at a time.
  const factsKey = `${fullEvent?.event_id}-${fullEvent?.status}-${(fullEvent?.actions || []).length}-${fullEvent?.story?.steps?.length || 0}`;
  useEffect(() => {
    const eventId = fullEvent?.event_id;
    if (!eventId) { setBrief(null); setTrends(null); return undefined; }
    let live = true;
    getOperatorBrief(eventId).then((b) => live && setBrief(b)).catch(() => live && setBrief(null));
    return () => { live = false; };
  }, [factsKey]);
  useEffect(() => {
    const eventId = fullEvent?.event_id;
    if (!eventId) return undefined;
    let live = true;
    setTrendsLoading(true);
    const load = () => getEventTrends(eventId).then((t) => live && setTrends(t)).catch(() => {}).finally(() => live && setTrendsLoading(false));
    load();
    const t = window.setInterval(load, 4000);
    return () => { live = false; window.clearInterval(t); };
  }, [fullEvent?.event_id]);
  useEffect(() => { const t = window.setInterval(() => setClock(new Date()), 1000); return () => window.clearInterval(t); }, []);

  useEffect(() => {
    // Subscribe synchronously before any API calls to avoid a startup race.
    const unsub = subscribeToEventStream(handleLiveEvent, () => {});
    refreshHandover();
    refreshRecentEvents();
    refreshAlarmHistory();
    refreshHandoverHistory();
    refreshActiveIncident();
    const poll = setInterval(refreshActiveIncident, 2500);
    const historyPoll = setInterval(refreshRecentEvents, 10000);
    const alarmHistoryPoll = setInterval(refreshAlarmHistory, 15000);
    const handoverPoll = setInterval(refreshHandover, 15000);
    return () => { clearAllTimers(); clearInterval(poll); clearInterval(historyPoll); clearInterval(alarmHistoryPoll); clearInterval(handoverPoll); unsub(); };
  }, [handleLiveEvent, refreshActiveIncident, refreshAlarmHistory, refreshHandover, refreshHandoverHistory, refreshRecentEvents]);

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
        const acknowledgementTarget = actionType === 'ACKNOWLEDGE' ? getAcknowledgementTarget(fullEvent || {}) : null;
        res = await logOperatorAction({ eventId: currentEventId, operator: 'J. Rivera (Shift 2)', actionType: submission.actionType, alarmId: acknowledgementTarget?.alarm_id, notes: safeNotes });
      }
      const savedAction = res.action || res;
      setRecordedAction(savedAction);
      await refreshHandover();
      await refreshRecentEvents();
      if (actionType === 'ACKNOWLEDGE') await refreshAlarmHistory();
      if (actionType === 'ACKNOWLEDGE') await refreshActiveIncident();
      const updated = await getFullEvent(currentEventId);
      if (updated) {
        setFullEvent(updated);
        setIsIncident(Boolean(updated.is_open));
        setRecordedAction([...(updated.actions || [])].reverse()[0] || savedAction);
      }
      setOperatorActionSuccess(workflowActionSuccessMessage(actionType));
      if (actionType === 'RESOLVE') {
        setTimeout(() => { refreshHandover(); setActivePage('Shift Handover'); }, 400);
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
  const alarmStateCounts = summarizeAlarmStates(openIncidentGroups);
  const activeAlarmCount = alarmStateCounts.active;
  const alarmGroups = new Set(openIncidentGroups.map((item) => item.group_id || item.alarm_group || item.equipment_id || item.correlated?.equipment_id || item.candidate?.equipment_id || item.individual_alarms?.[0]?.equipment_id || item.individual_alarms?.[0]?.equipment).filter(Boolean)).size;
  const topPriority = rankedIncidents[0]?.priority || rankedIncidents[0]?.urgency?.urgency_band || rankedIncidents[0]?.severity || '—';
  const sourceText = String(selectedDataSource || '').toLowerCase();
  const plcAdapter = integrationStatus?.adapters?.find((item) => item.type === 'opcua');
  const overviewSourceState = /simulat|synthetic/.test(sourceText) ? 'SIMULATED'
    : /stale/.test(sourceText) || plcAdapter?.source_label === 'STALE DATA' ? 'STALE'
      : /opc.?ua|plc|^live$/.test(sourceText) || plcAdapter?.source_label === 'LIVE PLC DATA' ? 'LIVE PLC'
        // Backend /api/datasource decides between SIMULATED, PLC DISCONNECTED
        // and NO DATA; a simulation is never shown as a disconnected PLC.
        : dataSource?.mode || (hasEvent ? 'RECORDED' : 'NO DATA');
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
  const incidentAlarms = fullEvent?.individual_alarms || [];
  const acknowledgementTarget = getAcknowledgementTarget(fullEvent || {});
  const hasAcknowledgedAlarm = incidentAlarms.some(isAlarmAcknowledged)
    || (fullEvent?.actions || []).some((action) => ['ACKNOWLEDGE', 'ACKNOWLEDGED'].includes(String(action.action_type || '').toUpperCase()));
  const canAcknowledge = incidentAlarms.length ? Boolean(acknowledgementTarget) : !hasAcknowledgedAlarm;
  const openWorkflowNote = (actionType) => {
    setOperatorActionError('');
    setOperatorActionSuccess('');
    setWorkflowDialog({ actionType, note: '' });
  };

  const NAV = [
    ['Overview', LayoutDashboard], ['Event Story', Activity], ['Evidence Engine', Network], ['Operator Brief', FileText],
    ['AI Diagnosis', Bot], ['Plant Overview', Factory], ['Incident History', History], ['Shift Handover', ClipboardList], ['SOP Library', BookOpen],
  ];
  const selectedIncident = rankedIncidents.find((item) => item.event_id === currentEventId);
  const p1Count = openIncidentGroups.filter((item) => item.urgency?.urgency_band === 'URGENT').length;
  const handoverPending = (handover?.unresolved_incidents || []).length;
  const aiClass = aiStatus?.ollama_selected ? (aiStatus.reachable && aiStatus.model_installed ? (aiStatus.verified_in_this_process ? 'verified' : 'ready') : 'down') : 'deterministic';
  const aiText = !aiStatus ? 'AI —'
    : aiStatus.ollama_selected
      ? `${aiStatus.model} · ${aiStatus.reachable && aiStatus.model_installed ? (aiStatus.verified_in_this_process ? 'verified' : 'ready') : aiStatus.reachable ? 'model missing' : 'offline → fallback'}`
      : 'AI off · deterministic';
  const pageTitle = (title) => <div className="ov-page-title"><h1>{title}</h1><span>{currentEventId ? `${brief?.problem?.alarm_tag || primaryTag} · ${equipmentId}` : 'Select an incident on the Overview'}</span></div>;

  return (
    <div className="hmi-app operator-shell ov-shell">
      <header className="ov-topbar" aria-label="Plant status">
        <span className="ov-brand"><i />OpsLens <small>Wastewater plant · operator HMI</small></span>
        <div className="ov-top-stats">
          <span className={`ov-top-stat ${activeAlarmCount ? 'p1' : ''}`} title="Active alarm inputs across all groups"><b>{activeAlarmCount}</b> active alarms</span>
          <span className="ov-top-stat"><b>{alarmStateCounts.unacknowledged}</b> unack</span>
          <span className="ov-top-stat"><b>{p1Count}</b> urgent</span>
          <span className="ov-top-stat"><b>{alarmGroups}</b> groups</span>
        </div>
        <span className="ov-top-spacer" />
        <span className={`ov-source ${overviewSourceState.toLowerCase().replaceAll(' ', '-')}`} title="Simulated (Scenario Lab) data is never presented as live PLC data">{overviewSourceState === 'SIMULATED' ? 'SIMULATED DATA' : overviewSourceState}</span>
        <span className={`ov-ai-pill ${aiClass}`} title={aiStatus?.error || (aiStatus?.last_diagnosis_call?.attempted ? `Last call ${aiStatus.last_diagnosis_call.succeeded ? 'succeeded' : 'failed'}${aiStatus.last_diagnosis_call.error ? `: ${aiStatus.last_diagnosis_call.error}` : ''}` : 'No AI call yet')}><i />{aiText}</span>
        <button type="button" className="ov-top-btn" onClick={() => setActivePage('Shift Handover')}><ClipboardList size={13} /> Handover {handoverPending ? <b>{handoverPending}</b> : null}</button>
        <span className="ov-clock">{clock.toLocaleTimeString([], { hour12: false })}</span>
      </header>
      <div className="operator-workspace">
        <nav className={`operator-sidebar ${sidebarExpanded ? 'expanded' : 'collapsed'}`} aria-label="Main navigation">
          <button className="operator-sidebar-toggle" type="button" aria-label={sidebarExpanded ? 'Collapse navigation' : 'Expand navigation'} onClick={() => setSidebarExpanded((value) => !value)}>{sidebarExpanded ? <ChevronLeft size={18}/> : <Menu size={18}/>}</button>
          {NAV.map(([label, Icon]) => <button key={label} type="button" title={label} aria-current={activePage === label ? 'page' : undefined} className={`operator-nav-item ${activePage === label ? 'active' : ''}`} onClick={() => { setActivePage(label); setSidebarExpanded(false); }}><Icon size={18}/>{sidebarExpanded && <span>{label}</span>}</button>)}
        </nav>
        {sidebarExpanded && <button className="operator-sidebar-backdrop" aria-label="Close navigation" onClick={() => setSidebarExpanded(false)} />}

        <main id="overview" className={`operator-main page-${activePage.toLowerCase().replaceAll(' ', '-')}`}>
          {activePage === 'Overview' && <>
            <AlarmBanner fullEvent={fullEvent} brief={brief} incident={selectedIncident} />
            <OverviewHMI
              fullEvent={fullEvent} brief={brief} trends={trends} trendsLoading={trendsLoading}
              incidents={rankedIncidents} selectedEventId={currentEventId} onSelect={selectHistoryEvent} loading={historyLoading}
              onOpenStory={() => setActivePage('Event Story')} onOpenEvidence={() => setActivePage('Evidence Engine')}
              onOpenSop={() => setIsSopModalOpen(true)} diagnosisKey={`${fullEvent?.status}`}
            />
            <section className="operator-workflow" aria-label="Resolution and operator workflow">
              <div className="operator-workflow-title"><span className="operator-eyebrow">Resolution</span><strong>{hasEvent ? isIncident ? 'Operator workflow' : 'Incident reported clear' : 'Select an incident'}</strong></div>
              <div className="operator-workflow-actions">
                <button type="button" className="acknowledge" disabled={!hasEvent || !isIncident || !canAcknowledge || operatorActionSubmitting} onClick={() => recordWorkflowAction('ACKNOWLEDGE', 'OpsLens acknowledgement recorded; source alarm remains active until cleared. No PLC write performed.')}>{canAcknowledge ? `Acknowledge${acknowledgementTarget?.tag ? ` ${acknowledgementTarget.tag}` : ''}` : 'ALL ACKNOWLEDGED'}</button>
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
          {serviceError && activePage !== 'Overview' && <div role="status" className="operator-service-state">{serviceError}</div>}
          {activePage === 'Event Story' && <section className="operator-panel operator-page-panel event-story-page">{pageTitle('Event Story')}<EventStory story={fullEvent?.story} isIncident={hasEvent} revealedCount={stepsLen} dataSource={selectedDataSource} relatedAlarm={relatedAlarm} /></section>}
          {activePage === 'Evidence Engine' && <section className="operator-panel operator-page-panel evidence-page">{pageTitle('Evidence Engine')}<EvidenceSection evidence={fullEvent?.evidence} evidenceAudit={fullEvent?.evidence_audit} event={fullEvent} isIncident={hasEvent} /></section>}
          {activePage === 'Operator Brief' && <section className="ov-page">{pageTitle('Operator brief')}{hasEvent ? <OperatorBrief eventId={currentEventId} refreshKey={factsKey} /> : <p className="ov-empty">Select an incident.</p>}</section>}
          {activePage === 'AI Diagnosis' && <section className="ov-page ov-page-diag">{pageTitle('AI diagnosis')}<DiagnosisPanel eventId={fullEvent?.event_id} refreshKey={`${fullEvent?.status}`} expanded /></section>}
          {activePage === 'Plant Overview' && <PlantOverview />}
          {activePage === 'SOP Library' && <SopLibrary />}
          {activePage === 'Incident History' && <section className="operator-page-panel"><div className="operator-section-heading"><h1>Alarm History</h1><span>{alarmHistory.length} alarm record(s) · linked incidents stay separate</span></div><AlarmHistory alarms={alarmHistory} loading={historyLoading} error={historyError} onSelectEvent={(id) => { selectHistoryEvent(id); setActivePage('Overview'); }} /></section>}
          {activePage === 'Shift Handover' && <section className="operator-page-panel"><ShiftHandoverPage summary={handover} onSelectIncident={(id) => { selectHistoryEvent(id); setActivePage('Overview'); }} onOpenAlarmHistory={navigateAlarmHistory} onRefresh={refreshHandover} /></section>}
        </main>
      </div>

      <SopModal isOpen={isSopModalOpen} onClose={() => setIsSopModalOpen(false)} sopData={fullEvent ? { ...(fullEvent.sop_match || {}), sop_resolution: fullEvent.sop_resolution, resolved_sop_sources: fullEvent.resolved_sop_sources } : null} />
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
      {/* On the overview the banner already announces the alarm; the popup is
          used on detail pages so a new alarm is never missed. */}
      {activePage !== 'Overview' && <AlarmPopup event={fullEvent} isActive={isIncident} onOpenCopilot={() => setIsAssistantOpen(true)} onDismiss={() => {}} />}
    </div>
  );
}
