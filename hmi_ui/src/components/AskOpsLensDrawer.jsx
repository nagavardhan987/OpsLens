import React, { useEffect, useRef, useState } from 'react';
import { Activity, AlertCircle, LoaderCircle, MessageSquareText, Send, X } from 'lucide-react';
import { askOpsLens, askOpsLensStream } from '../api/client';
import { assistantDisplayStatus } from '../lib/assistantPresentation';

const SUGGESTIONS = ['Why did this alarm trigger?', 'What changed before this alarm?', 'Were any operator actions recorded?', 'Show the relevant SOP section.'];
const NO_EVIDENCE = 'The selected incident has no relevant evidence for that question yet. Which sensor, alarm, or procedure would you like me to check?';
const SAFE_ASSISTANT_ERROR = 'I could not retrieve an answer because the incident assistant service did not respond. Check the data-source status and try again.';

export default function AskOpsLensDrawer({ event, equipment, isOpen, onClose }) {
  const [question, setQuestion] = useState('');
  const [askedQuestion, setAskedQuestion] = useState('');
  const [conversation, setConversation] = useState([]);
  const [answer, setAnswer] = useState(null);
  const [draft, setDraft] = useState('');
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const conversationRef = useRef('');
  const abortRef = useRef(null);

  useEffect(() => {
    setQuestion(''); setAnswer(null); setDraft(''); setError(''); setStatus('');
    setAskedQuestion(''); setConversation([]); conversationRef.current = '';
    abortRef.current?.abort();
  }, [event?.event_id]);
  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => {
    if (!isOpen) return undefined;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previous; };
  }, [isOpen]);
  if (!isOpen) return null;

  const archiveCurrent = () => {
    if (!answer || !askedQuestion) return;
    setConversation((items) => [...items, { question: askedQuestion, answer: answer.question_answer || answer.answer || NO_EVIDENCE }]);
  };
  const ask = async (value = question) => {
    const trimmed = value.trim();
    if (!trimmed || !event?.event_id || loading) return;
    archiveCurrent();
    abortRef.current?.abort();
    const controller = new AbortController(); abortRef.current = controller;
    setAskedQuestion(trimmed); setQuestion(''); setAnswer(null); setDraft(''); setError('');
    setStatus('Preparing response…'); setLoading(true);
    const handleDone = (data) => {
      if (data?.conversation_id) conversationRef.current = data.conversation_id;
      setAnswer(data); setDraft(''); setStatus(''); setError('');
    };
    try {
      await askOpsLensStream({
        eventId: event.event_id, question: trimmed, conversationId: conversationRef.current || undefined,
        signal: controller.signal,
        onStatus: (payload) => { if (payload?.stage === 'assembling_context' || payload?.stage === 'generating') setStatus('Preparing response…'); },
        onToken: (text) => setDraft((current) => current + text),
        onError: () => setError(SAFE_ASSISTANT_ERROR), onDone: handleDone,
      });
    } catch (err) {
      if (err.name === 'AbortError') return;
      try { handleDone(await askOpsLens(event.event_id, trimmed, conversationRef.current || undefined)); }
      catch (_) { setError(SAFE_ASSISTANT_ERROR); }
    } finally { setLoading(false); }
  };

  return <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <aside className="copilot-drawer" role="dialog" aria-modal="true" aria-label="Ask OpsLens about this incident">
      <header className="copilot-drawer-header bg-white"><div className="flex min-w-0 items-center gap-3"><div className="copilot-icon"><MessageSquareText size={18} /></div><div><h2 className="text-base font-semibold text-slate-800">Ask OpsLens</h2><p className="mt-0.5 text-xs text-slate-500">{equipment || 'Incident support'}</p></div></div><button onClick={onClose} aria-label="Close assistant" className="copilot-icon-button"><X size={18} /></button></header>
      <div className="copilot-context-bar bg-[#F4F7F4]"><div className="font-mono text-sm text-slate-800">{event?.candidate?.alarm_id || event?.candidate?.primary_tag || 'Alarm'}</div><div className="text-sm text-slate-600">{equipment || 'Not recorded'}</div></div>
      <div className="copilot-scroll-area">
        {!answer && !loading && !error && <section className="copilot-welcome"><div className="flex items-center gap-2 text-sm font-medium text-slate-800"><Activity size={16} className="text-emerald-700" />Contextual incident support</div><p className="mt-2 text-sm leading-6 text-slate-600">Ask about recorded alarm events, sensor trends, operator actions, or retrieved procedure evidence.</p><div className="mt-5 grid gap-2 sm:grid-cols-2">{SUGGESTIONS.map((item) => <button key={item} disabled={loading} onClick={() => ask(item)} className="copilot-suggestion">{item}</button>)}</div></section>}
        {conversation.length > 0 && <section aria-label="Conversation history" className="px-4 pt-3"><h3 className="text-xs font-semibold text-slate-300">Earlier questions</h3><ol className="mt-2 space-y-3">{conversation.map((turn, i) => <li key={`${i}-${turn.question}`} className="rounded-lg border border-slate-200 bg-white p-3 text-slate-800"><p className="text-xs font-semibold">Operator · {turn.question}</p><p className="mt-2 whitespace-pre-wrap text-sm leading-5">{turn.answer}</p></li>)}</ol></section>}
        {loading && <div className="copilot-state text-slate-700" role="status"><LoaderCircle size={17} className="animate-spin text-emerald-700" />{status || 'Reviewing stored incident evidence…'}</div>}
        {error && <div role="alert" className="copilot-error"><AlertCircle size={17} />{error}</div>}
        {(answer || draft) && <article className="copilot-response-card">
          {answer && <p role="status" className="mx-4 mt-3 text-[11px] text-slate-500">{assistantDisplayStatus(answer).text}</p>}
          {answer && <section className="mx-4 mt-3 rounded-lg border border-[#D8E2DA] bg-white p-4 text-[#26352C]" aria-label="Answer to operator question"><h3 className="text-sm font-semibold">{answer.question || askedQuestion}</h3><p className="mt-2 whitespace-pre-wrap text-sm leading-6">{answer.question_answer || answer.answer || NO_EVIDENCE}</p></section>}
          {draft && !answer && <p className="mx-4 mt-3 whitespace-pre-wrap text-sm text-slate-700">{draft}</p>}
        </article>}
      </div>
      {answer && !loading && <div className="px-4 pb-2 border-t border-slate-200 pt-3"><button type="button" onClick={() => { archiveCurrent(); setAnswer(null); setAskedQuestion(''); setError(''); setQuestion(''); }} className="flex w-full items-center justify-center rounded-lg border border-slate-300 bg-white py-2 text-xs font-semibold text-slate-700 hover:border-emerald-600 hover:text-emerald-700">Ask a new question</button></div>}
      <form className="copilot-composer" onSubmit={(e) => { e.preventDefault(); ask(); }}><label htmlFor="opslens-question" className="sr-only">Ask about the selected incident</label><div className="flex gap-2"><input id="opslens-question" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about this incident…" maxLength={1000} className="copilot-input" />{loading && <button type="button" onClick={() => abortRef.current?.abort()} className="copilot-stop">Stop</button>}<button disabled={loading || !question.trim()} aria-label="Send question" className="copilot-send"><Send size={17} /></button></div></form>
    </aside>
  </div>;
}
