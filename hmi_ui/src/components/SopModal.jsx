import React, { useEffect, useState } from 'react';
import { X, BookOpen, CheckCircle, ShieldCheck, RefreshCw, ChevronDown } from 'lucide-react';
import { getSop, getSopSourceUrl } from '../api/client';

export default function SopModal({ isOpen, onClose, sopData }) {
  const [document, setDocument] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(false);
  const [checkedSteps, setCheckedSteps] = useState({});
  const [reloadKey, setReloadKey] = useState(0);
  const sopId = sopData?.sop_id || sopData?.sop?.sop_id;

  useEffect(() => {
    if (!isOpen || !sopId) return;
    let active = true;
    setLoading(true); setLoadError(''); setDocument(null); setCheckedSteps({});
    getSop(sopId).then((result) => { if (active) setDocument(result.data); })
      .catch((error) => { if (active) setLoadError(error.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [isOpen, sopId, reloadKey]);
  if (!isOpen) return null;

  const rawSteps = (document?.steps && document.steps.length > 0) ? document.steps : (sopData?.steps || []);
  const steps = rawSteps.map((instruction, idx) => ({ step_number: idx + 1, instruction }));
  const contentPages = document?.content_pages || [];
  const retrievedChunks = sopData?.retrieved_chunks || sopData?.chunks || [];
  const hasPdfSource = Boolean(document?.source_pdf);
  const why = sopData?.why_retrieved || {};
  const toggleStep = (n) => setCheckedSteps((prev) => ({ ...prev, [n]: !prev[n] }));
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-[#121A28] border-2 border-slate-600 w-full max-w-2xl rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        <div className="bg-[#162234] px-5 py-4 border-b border-slate-700 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded bg-blue-600/30 border border-blue-500 flex items-center justify-center text-blue-400"><BookOpen className="w-5 h-5" /></div>
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded bg-blue-950 border border-blue-500/40 text-blue-300 font-mono-code font-bold text-xs">{sopId || '—'}</span>
                <h3 className="font-industrial font-bold text-white text-base">{document?.title || sopData?.sop_title || 'Operating Procedure'}</h3>
              </div>
              <span className="text-xs text-slate-400 font-mono-code">{document?.equipment || sopData?.equipment || 'SOP'} • Rev {document?.revision || '1.0'}</span>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-700 text-slate-400 hover:text-white transition-colors cursor-pointer"><X className="w-5 h-5" /></button>
        </div>

        <div className="p-5 overflow-y-auto space-y-4">
          <div className="bg-[#0E1624] border border-blue-500/30 rounded-lg p-3 text-xs text-slate-300 flex items-center gap-3">
            <ShieldCheck className="w-5 h-5 text-blue-400 shrink-0" />
            <div className="min-w-0 flex-1"><strong className="text-white block font-industrial">SOURCE DOCUMENT</strong>{(document?.document_status || sopData?.document_status || 'APPROVED PROCEDURE — EcoStruxure Machine Expert Verified') && <strong className="mb-1 block text-emerald-400 font-mono-code text-[11px]">{document?.document_status || sopData?.document_status || 'APPROVED PROCEDURE — EcoStruxure Machine Expert Verified'}</strong>}{document?.summary || document?.description || `Source: ${document?.source || 'Bundled Schneider SOP repository'}`}
              {hasPdfSource && <a href={getSopSourceUrl(sopId)} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1.5 font-semibold text-blue-300 hover:text-blue-200">Source PDF: {document.source_pdf} <span aria-hidden="true">↗</span></a>}
            </div>
          </div>

          {sopData?.why_retrieved && <details className="group bg-[#121A28] border border-slate-700 rounded-lg">
            <summary className="flex cursor-pointer list-none items-center justify-between p-3 text-xs font-semibold text-slate-300">
              <span>Why this reference matched</span><ChevronDown className="h-4 w-4 text-slate-500 transition-transform group-open:rotate-180" />
            </summary>
            <div className="grid grid-cols-2 gap-y-2 gap-x-4 border-t border-slate-700 p-4 text-xs">
              {[
                ['Incident', why.incident], ['Equipment', why.equipment], ['Alarm', why.alarm],
                ['Matching symptoms', Array.isArray(why.symptoms) ? why.symptoms.map((symptom) => `✓ ${symptom}`).join('\n') : why.symptoms],
                ['Likely contributor', why.likely_contributor], ['Relevant section', why.matching_section],
                ['Retrieval method', sopData.retrieval_method === 'qdrant_vector_search' ? 'Qdrant semantic search' : sopData.retrieval_method],
                ['Embedding', sopData.embedding_model || 'all-MiniLM-L6-v2']
              ].filter(([, value]) => value !== undefined && value !== null && value !== '').map(([label, value]) => <div key={label} className="flex justify-between gap-2"><span className="text-slate-400">{label}:</span><span className="text-slate-100 text-right whitespace-pre-line">{String(value)}</span></div>)}
            </div>
          </details>}

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-mono-code uppercase tracking-wider text-slate-400 font-bold">Procedure</h4>
              {steps.length > 0 && <span className="text-[10px] text-slate-500">{steps.length} source steps</span>}
            </div>
            {loading && <div className="rounded-lg border border-slate-700 bg-[#0E1624] p-4 text-sm text-slate-400">Loading the full procedure…</div>}
            {loadError && steps.length === 0 && <div role="alert" className="rounded-lg border border-amber-500/30 bg-amber-950/20 p-4">
              <p className="text-sm font-semibold text-amber-200">The full procedure could not be loaded.</p>
              <p className="mt-1 text-xs leading-5 text-amber-100/70">{loadError} Retrieved excerpts, if shown below, are source references and may not contain the complete approved procedure.</p>
              <button type="button" onClick={() => setReloadKey((value) => value + 1)} className="mt-3 inline-flex items-center gap-2 rounded-md border border-amber-400/30 px-3 py-2 text-xs font-semibold text-amber-100 hover:bg-amber-400/10"><RefreshCw size={13} />Try again</button>
            </div>}
            {!loading && steps.length === 0 && contentPages.length === 0 && <div className="rounded-lg border border-slate-700 bg-[#0E1624] p-4 text-sm text-slate-400">No complete procedure text is available for this reference.</div>}
            {!loading && contentPages.map((page) => (
              <article key={page.page} className="rounded-lg border border-slate-700/80 bg-[#182335] p-4">
                <h5 className="mb-2 text-[10px] font-mono-code uppercase tracking-wider text-blue-300">Source page {page.page}</h5>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-200">{page.text}</p>
              </article>
            ))}
            {!loading && steps.map((step) => {
              const checked = !!checkedSteps[step.step_number];
              return <button type="button" key={step.step_number} onClick={() => toggleStep(step.step_number)} className={`w-full p-3.5 rounded-lg border text-left transition-all ${checked ? 'bg-emerald-950/20 border-emerald-500/60' : 'bg-[#182335] border-slate-700/80 hover:border-slate-500'}`}>
                <span className="flex items-start gap-3">
                  <span className={`mt-0.5 w-5 h-5 rounded flex items-center justify-center border transition-colors ${checked ? 'bg-emerald-600 border-emerald-500 text-white' : 'border-slate-500 bg-slate-800 text-transparent'}`}><CheckCircle className="w-4 h-4" /></span>
                  <span className="flex-1 min-w-0"><span className="flex items-center justify-between gap-3"><span className="font-industrial font-bold text-sm text-slate-100">Step {step.step_number}</span>{checked && <span className="text-[10px] font-mono-code text-emerald-400 font-bold uppercase">Verified</span>}</span><span className="mt-1 block text-sm leading-5 text-slate-300">{step.instruction}</span></span>
                </span>
              </button>;
            })}
          </section>

          {retrievedChunks.length > 0 && <details className="group rounded-lg border border-slate-700 bg-[#0E1624]">
            <summary className="flex cursor-pointer list-none items-center justify-between p-3 text-xs font-semibold text-slate-300">
              <span>Retrieved source excerpts <span className="ml-1 text-slate-500">({retrievedChunks.length})</span></span><ChevronDown className="h-4 w-4 text-slate-500 transition-transform group-open:rotate-180" />
            </summary>
            <div className="space-y-2 border-t border-slate-700 p-3">
              <p className="text-[11px] leading-5 text-slate-500">Search excerpts are shown for traceability. They are not a substitute for a complete approved procedure.</p>
              {retrievedChunks.slice(0, 5).map((chunk, index) => <article key={chunk.chunk_id || index} className="rounded-lg border border-slate-700/80 bg-[#111a28] p-3">
              <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] font-mono-code text-blue-300">
                <span>{chunk.document_name || chunk.document_id || sopId || 'SOP source'}</span>
                {chunk.revision && <span>Rev {chunk.revision}</span>}
                {chunk.section && <span>Section: {chunk.section}</span>}
                {chunk.page != null && <span>Page {chunk.page}</span>}
              </div>
              <p className="whitespace-pre-wrap text-xs leading-relaxed text-slate-200">{chunk.text || 'Passage text unavailable.'}</p>
              </article>)}
            </div>
          </details>}
        </div>

        <div className="bg-[#162234] px-5 py-3.5 border-t border-slate-700 flex items-center justify-between">
          <span className="text-xs font-mono-code text-slate-400">{contentPages.length ? `${document?.source_pdf || 'PDF SOP'} · ${contentPages.length} pages` : steps.length ? `${Object.values(checkedSteps).filter(Boolean).length} of ${steps.length} steps checked` : 'Source status shown above'}</span>
          <button onClick={onClose} className="px-4 py-2 rounded bg-slate-700 hover:bg-slate-600 text-white font-industrial font-semibold text-xs uppercase tracking-wider cursor-pointer transition-colors">Close SOP Viewer</button>
        </div>
      </div>
    </div>
  );
}
