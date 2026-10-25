import React, { useEffect, useRef, useState } from 'react';
import { Activity, AlertCircle, ArrowLeft, BookOpen, CheckCircle2, ChevronDown, Clock3, LoaderCircle, MessageSquareText, PlusCircle, Send, ShieldCheck, X, Zap } from 'lucide-react';
import { askOpsLens, askOpsLensStream } from '../api/client';
import { assistantDisplayStatus, formatTimestamp } from '../lib/assistantPresentation';

const SUGGESTIONS = [
  'Why did this alarm trigger?',
  'What changed before this alarm?',
  'Were any operator actions recorded?',
  'Show the relevant SOP section.',
];

function sanitizeErrorMessage(msg) {
  if (!msg) return 'OpsLens could not retrieve guidance for this incident. Please consult runtime controls.';
  const str = String(msg);
  if (str.includes('Traceback') || str.includes('HTTP 500') || str.includes('Internal Server Error')) {
    return 'The advisory service experienced a temporary delay. Stored telemetry remains valid.';
  }
  return str;
}

function EvidenceLine({ item }) {
  if (item.kind === 'trend') {
    return <li className="copilot-evidence-row">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="copilot-tag">{item.tag}</span>
          <span className="text-slate-200">{item.summary}</span>
        </div>
        <div className="mt-2 grid gap-1 text-xs text-slate-400 sm:grid-cols-2">
          <span>First recorded · {formatTimestamp(item.first_timestamp)}</span>
          <span>Last recorded · {formatTimestamp(item.last_timestamp)}</span>
        </div>
      </div>
      <span className="shrink-0 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] text-slate-300">
        {item.reading_count ?? '—'} samples
      </span>
    </li>;
  }
  return <li className="copilot-evidence-row">
    <div><div className="text-sm text-slate-200">{item.summary || item.description || 'Recorded event'}</div>
      <div className="mt-1 text-xs text-slate-400">{formatTimestamp(item.timestamp)}</div>
    </div>
    {item.tag && <span className="copilot-tag">{item.tag}</span>}
  </li>;
}

export default function AskOpsLensDrawer({ event, equipment, isOpen, onClose }) {
  const [question, setQuestion] = useState('');
  const [askedQuestion, setAskedQuestion] = useState(''); // track the displayed question label
  const [answer, setAnswer] = useState(null);
  const [draft, setDraft] = useState('');
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const conversationRef = useRef('');
  const abortRef = useRef(null);

  useEffect(() => {
    setQuestion(''); setAnswer(null); setDraft(''); setError(''); setStatus('');
    setAskedQuestion('');
    conversationRef.current = '';
    abortRef.current?.abort();
  }, [event?.event_id]);

  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    if (!isOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previousOverflow; };
  }, [isOpen]);

  if (!isOpen) return null;

  const ask = async (value = question) => {
    const trimmed = value.trim();
    if (!trimmed || !event?.event_id || loading) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setAskedQuestion(trimmed);
    setQuestion(''); setAnswer(null); setDraft(''); setError('');
    setStatus('Assembling incident evidence…'); setLoading(true);
    const handleDone = (data) => {
      if (data?.conversation_id) conversationRef.current = data.conversation_id;
      setAnswer(data); setDraft(''); setStatus('');
    };
    try {
      await askOpsLensStream({
        eventId: event.event_id, question: trimmed,
        conversationId: conversationRef.current || undefined,
        signal: controller.signal,
        onStatus: (payload) => {
          if (payload?.stage === 'assembling_context') setStatus('Assembling incident evidence…');
          if (payload?.stage === 'generating') setStatus('Preparing a grounded response…');
        },
        onToken: (text) => setDraft((current) => current + text),
        onError: (payload) => setError(sanitizeErrorMessage(payload?.detail)),
        onDone: handleDone,
      });
    } catch (err) {
      if (err.name === 'AbortError') return;
      try { handleDone(await askOpsLens(event.event_id, trimmed, conversationRef.current || undefined)); }
      catch (fallbackErr) { setError(sanitizeErrorMessage(fallbackErr.message)); }
    } finally { setLoading(false); }
  };

  const response = answer?.operator_response || {};
  const statusLabel = assistantDisplayStatus(answer);
  const evidence = response.evidence || [];
  const fallback = answer?.fallback_used === true;
  const alarmId = event?.candidate?.alarm_id || event?.candidate?.primary_tag || 'Selected incident';
  const sourceItems = answer?.sources || [];

  return <div className="fixed inset-0 z-50 flex justify-end bg-black/45" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <aside className="copilot-drawer" role="dialog" aria-modal="true" aria-label="Ask OpsLens about this incident">
      <header className="copilot-drawer-header">
        <div className="flex min-w-0 items-center gap-3">
          <div className="copilot-icon"><MessageSquareText size={18} /></div>
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-slate-50">Ask OpsLens</h2>
            <p className="mt-0.5 text-xs text-slate-400">Support for the selected incident</p>
          </div>
        </div>
        <button onClick={onClose} aria-label="Close assistant" className="copilot-icon-button"><X size={18} /></button>
      </header>

      <div className="copilot-context-bar">
        <div className="min-w-0"><div className="text-[10px] font-semibold uppercase tracking-[.16em] text-slate-500">Selected incident</div>
          <div className="mt-1 truncate font-mono text-sm text-slate-100">{alarmId}</div>
        </div>
        <div className="text-right"><div className="text-[10px] font-semibold uppercase tracking-[.16em] text-slate-500">Equipment</div>
          <div className="mt-1 text-sm text-slate-200">{equipment || 'Not recorded'}</div>
        </div>
      </div>

      <div className="copilot-scroll-area">
        {!answer && !loading && !error && <section className="copilot-welcome">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-100"><Activity size={16} className="text-emerald-400" />Contextual incident support</div>
          <p className="mt-2 text-sm leading-6 text-slate-400">Ask about recorded alarm events, sensor trends, operator actions, or retrieved procedure evidence.</p>
          <div className="mt-5 grid gap-2 sm:grid-cols-2">
            {SUGGESTIONS.map((item) => <button key={item} disabled={loading} onClick={() => ask(item)} className="copilot-suggestion">{item}</button>)}
          </div>
        </section>}

        {loading && <div className="copilot-state" role="status"><LoaderCircle size={17} className="animate-spin text-emerald-400" />{status || 'Reviewing stored incident evidence…'}</div>}
        {error && <div role="alert" className="copilot-error"><AlertCircle size={17} />{error}</div>}

        {(answer || draft) && <article className="copilot-response-card">
          {answer && <div className={`copilot-response-status ${statusLabel.tone}`}>
            {fallback ? <AlertCircle size={14} /> : answer.llm_used ? <CheckCircle2 size={14} /> : <ShieldCheck size={14} />}
            <span>{statusLabel.text}</span>
            {answer.cache_hit && <span className="ml-auto text-[10px] text-slate-500">Same context · cached</span>}
          </div>}

          {/* Consistent 5-part Schneider Copilot Structure */}
          <section className="copilot-answer-section bg-slate-900/40 p-4 border-b border-slate-800 space-y-3">
            {/* 1. Bottom Line */}
            <div>
              <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-amber-400">
                <Zap size={12} className="text-amber-400" />
                <span>1. Bottom Line</span>
              </div>
              <p className="mt-1 text-sm font-medium leading-relaxed text-slate-100">
                {response.bottom_line || answer?.answer || draft}
              </p>
            </div>

            {/* 2. Top Two Recommended Checks */}
            {((response.recommended_checks && response.recommended_checks.length > 0) || (answer?.immediate_checks && answer?.immediate_checks.length > 0)) && (
              <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
                <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-emerald-400">
                  <CheckCircle2 size={12} className="text-emerald-400" />
                  <span>2. Top Two Recommended Checks</span>
                </div>
                <ol className="mt-2 space-y-1.5">
                  {(response.recommended_checks || answer.immediate_checks).slice(0, 2).map((item, index) => (
                    <li key={index} className="flex items-start gap-2 text-xs text-slate-200">
                      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 font-mono text-[10px] font-bold text-emerald-400">
                        {index + 1}
                      </span>
                      <span className="leading-snug">{item}</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}

            {/* 3. Supporting Evidence Summary */}
            <div className="rounded border border-slate-800/80 bg-slate-900/30 px-3 py-2 text-xs text-slate-300">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1 flex items-center gap-1.5">
                <Activity size={11} className="text-blue-400" />
                <span>3. Supporting Evidence</span>
              </div>
              <p className="text-[11px] leading-relaxed text-slate-300">
                {evidence.length > 0
                  ? `Recorded ${evidence.length} contributing sensor excursion(s) in context window.`
                  : answer?.similar_incidents?.length > 0
                  ? `${answer.similar_incidents.length} similar event(s) recorded in daily operational window.`
                  : 'Correlated telemetry trends and recorded event sequence anchored to alarm trigger.'}
              </p>
            </div>

            {/* 4. Relevant SOP Reference */}
            {sourceItems.length > 0 && (
              <div className="rounded border border-slate-800/80 bg-slate-900/30 px-3 py-2 text-xs">
                <div className="text-[10px] font-bold uppercase tracking-wider text-blue-400 mb-1 flex items-center gap-1.5">
                  <BookOpen size={11} className="text-blue-400" />
                  <span>4. Relevant SOP Reference</span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[11px] text-slate-200 truncate">
                    {sourceItems[0].sop_id || 'Approved Site SOP'} · {sourceItems[0].section || 'Standard Procedure'}
                  </span>
                  <span className="text-[10px] font-mono text-emerald-400 shrink-0">
                    Verified Reference
                  </span>
                </div>
              </div>
            )}

            {/* 5. Data Limitations (when material) */}
            {(response.data_limitations || []).length > 0 && (
              <div className="rounded border border-amber-900/30 bg-amber-950/20 px-3 py-2 text-xs">
                <div className="text-[10px] font-bold uppercase tracking-wider text-amber-400 mb-1 flex items-center gap-1.5">
                  <AlertCircle size={11} className="text-amber-400" />
                  <span>5. Material Data Limitations</span>
                </div>
                <ul className="space-y-1 text-[11px] text-slate-300">
                  {response.data_limitations.slice(0, 2).map((item, idx) => (
                    <li key={idx} className="flex items-start gap-1.5">
                      <span className="text-amber-400">•</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          {/* Collapsible Telemetry & Supporting Sensor Readings */}
          {evidence.length > 0 && (
            <details className="copilot-technical-details border-b border-slate-800">
              <summary className="flex cursor-pointer items-center justify-between p-3 text-xs font-semibold text-slate-300 hover:text-white">
                <span className="flex items-center gap-1.5">
                  <Activity size={13} className="text-emerald-400" />
                  Supporting Sensor Trends ({evidence.length} signals)
                </span>
                <span className="text-[10px] text-slate-500">Tap to inspect raw values</span>
              </summary>
              <ul className="divide-y divide-slate-800 px-3 pb-3">
                {evidence.map((item, index) => (
                  <EvidenceLine key={`${item.kind}-${item.tag || index}-${item.timestamp || ''}`} item={item} />
                ))}
              </ul>
            </details>
          )}

          {/* Collapsible Data Quality & Audit Limitations */}
          {(response.data_limitations || []).length > 0 && (
            <details className="copilot-technical-details border-b border-slate-800">
              <summary className="flex cursor-pointer items-center justify-between p-3 text-xs font-semibold text-slate-400 hover:text-slate-200">
                <span className="flex items-center gap-1.5">
                  <AlertCircle size={13} className="text-amber-400" />
                  Data Quality & Limitations ({(response.data_limitations || []).length} items)
                </span>
                <span className="text-[10px] text-slate-500">Engineering notes</span>
              </summary>
              <ul className="space-y-1.5 px-4 pb-3">
                {(response.data_limitations || []).map((item, index) => (
                  <li key={index} className="flex gap-2 text-xs text-slate-400 leading-snug">
                    <span className="text-amber-500">•</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}

          <details className="copilot-technical-details">
            <summary><span>Technical evidence and sources</span><ChevronDown size={15} /></summary>
            <div className="space-y-4 px-4 pb-4">
              {answer?.supporting_readings?.length > 0 && <div><h3 className="copilot-detail-heading">Recorded readings · local display time</h3><div className="mt-2 space-y-2">{answer.supporting_readings.map((item, index) => <div key={`${item.tag}-${item.timestamp}-${index}`} className="copilot-detail-row"><span className="copilot-tag">{item.tag}</span><span>{item.value} {item.unit || ''}</span><time>{formatTimestamp(item.timestamp || item.timestamp_utc)}</time></div>)}</div></div>}
              {answer?.supporting_events?.length > 0 && <div><h3 className="copilot-detail-heading">Recorded event sequence</h3><div className="mt-2 space-y-2">{answer.supporting_events.map((item, index) => <div key={`${item.tag}-${index}`} className="copilot-detail-row"><span>{item.description || item.tag}</span><time>{formatTimestamp(item.timestamp)}</time></div>)}</div></div>}
              {sourceItems.length > 0 && <div><h3 className="copilot-detail-heading">Retrieved procedure references</h3><div className="mt-2 space-y-3">{sourceItems.map((source, index) => <div key={`${source.sop_id}-${source.section}-${index}`} className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
                <div className="flex items-center gap-2 text-sm font-medium text-slate-100"><BookOpen size={15} className="text-emerald-400" />{source.document_name || source.sop_id || 'Retrieved source'}</div>
                <p className="mt-1 text-xs text-slate-400">{source.sop_id} · {source.section}{source.page != null ? ` · page ${source.page}` : ''}</p>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-5 text-slate-300">{source.text}</p>
                <p className="mt-2 flex items-center gap-1.5 text-xs text-amber-300"><ShieldCheck size={13} />{source.document_status || 'Approval status not verified'}</p>
              </div>)}</div></div>}
              {answer?.incident_context?.context_window && <div className="text-xs text-slate-400"><h3 className="copilot-detail-heading">Context window · source timestamps</h3><div className="mt-2 flex flex-wrap items-center gap-2"><Clock3 size={14} />{formatTimestamp(answer.incident_context.context_window.start)} → {formatTimestamp(answer.incident_context.context_window.end)}</div></div>}
              {answer?.incident_context?.evidence_score != null && <p className="text-xs text-slate-400">Evidence Engine score: {(answer.incident_context.evidence_score * 100).toFixed(0)}% normalized contributor ranking heuristic; not a probability.</p>}
              <details className="rounded border border-slate-800 px-3 py-2">
                <summary className="cursor-pointer text-xs text-slate-500">Developer diagnostics</summary>
                <dl className="mt-2 grid grid-cols-2 gap-2 font-mono text-[11px] text-slate-400">
                  <dt>fallback_reason</dt><dd>{answer?.fallback_reason || 'none'}</dd>
                  <dt>correction_failure_reason</dt><dd>{answer?.correction_failure_reason || 'none'}</dd>
                  <dt>selected_provider</dt><dd>{answer?.selected_provider || answer?.provider_metadata?.selected_provider || 'none'}</dd>
                  <dt>used_provider</dt><dd>{answer?.used_provider || answer?.provider_metadata?.used_provider || 'deterministic'}</dd>
                </dl>
              </details>
            </div>
          </details>
          {answer && (
            <div className="px-4 pb-3 space-y-1">
              {answer.incident_context?.evidence_score != null && (
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-slate-500">Confidence score:</span>
                  <div className="flex-1 h-1.5 rounded-full bg-slate-800">
                    <div
                      className={`h-1.5 rounded-full transition-all ${
                        answer.incident_context.evidence_score > 0.7 ? 'bg-emerald-500' :
                        answer.incident_context.evidence_score > 0.4 ? 'bg-amber-500' : 'bg-red-500'
                      }`}
                      style={{ width: `${Math.min(100, Math.round(answer.incident_context.evidence_score * 100))}%` }}
                    />
                  </div>
                  <span className={`text-[10px] font-mono ${
                    answer.incident_context.evidence_score > 0.7 ? 'text-emerald-400' :
                    answer.incident_context.evidence_score > 0.4 ? 'text-amber-400' : 'text-red-400'
                  }`}>
                    {Math.round(answer.incident_context.evidence_score * 100)}%
                  </span>
                  <span className="text-[10px] text-slate-600">(heuristic, not probability)</span>
                </div>
              )}
              <div className="flex items-center gap-3 text-[10px] text-slate-500">
                {answer.assembly_latency_ms != null && (
                  <span className={answer.assembly_latency_ms < 2000 ? 'text-emerald-600' : 'text-amber-600'}>
                    Context: {answer.assembly_latency_ms.toFixed(0)}ms {answer.assembly_latency_ms < 2000 ? '✓' : '⚠'}
                  </span>
                )}
                {answer.total_latency_ms != null && <span>Total: {answer.total_latency_ms}ms</span>}
                {answer.cache_hit && <span className="text-blue-500">• Cached response</span>}
                {answer.llm_used && <span className="text-purple-400">• LLM enhanced</span>}
              </div>
            </div>
          )}
        </article>}
      </div>

      {/* New Question button — shown below the answer so the operator can reset */}
      {answer && !loading && (
        <div className="px-4 pb-2 border-t border-slate-800 pt-3">
          <button
            type="button"
            onClick={() => { setAnswer(null); setAskedQuestion(''); setError(''); setQuestion(''); }}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-700 bg-slate-800/60 py-2 text-xs font-semibold text-slate-300 hover:border-emerald-600 hover:text-emerald-400 transition-colors"
          >
            <ArrowLeft size={13} />
            Ask a new question
            <PlusCircle size={13} className="ml-auto" />
          </button>
        </div>
      )}

      <form className="copilot-composer" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <label htmlFor="opslens-question" className="sr-only">Ask about the selected incident</label>
        {askedQuestion && !loading && (
          <p className="mb-2 px-1 text-[10px] text-slate-500 truncate">
            <span className="text-slate-600">Last question:</span> {askedQuestion}
          </p>
        )}
        <div className="flex gap-2">
          <input id="opslens-question" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={answer ? "Ask another question…" : "Ask about this incident…"} maxLength={1000} className="copilot-input" />
          {loading && <button type="button" onClick={() => abortRef.current?.abort()} className="copilot-stop">Stop</button>}
          <button disabled={loading || !question.trim()} aria-label="Send question" className="copilot-send"><Send size={17} /></button>
        </div>
      </form>
    </aside>
  </div>;
}
