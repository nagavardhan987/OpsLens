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
  const selectedSource = sopData?.resolved_sop_sources?.[0];
  const sourceRevision = selectedSource?.revision || sopData?.retrieved_chunks?.[0]?.revision || '';
  const sourceHash = sopData?.retrieved_chunks?.[0]?.sha256 || '';

  useEffect(() => {
    if (!isOpen || !sopId) return;
    let active = true;
    setLoading(true); setLoadError(''); setDocument(null); setCheckedSteps({});
    getSop(sopId, sourceRevision, sourceHash).then((result) => { if (active) setDocument(result.data); })
      .catch(() => { if (active) setLoadError('The procedure could not be loaded. Try again.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [isOpen, sopId, sourceRevision, sourceHash, reloadKey]);
  if (!isOpen) return null;

  const rawSteps = (document?.steps && document.steps.length > 0) ? document.steps : (sopData?.steps || []);
  const steps = rawSteps.map((instruction, idx) => ({ step_number: idx + 1, instruction }));
  const contentPages = document?.content_pages || [];
  const retrievedChunks = sopData?.retrieved_chunks || sopData?.chunks || [];
  const hasPdfSource = Boolean(document?.source_pdf);
  const approvalVerified = document?.approved === true && document?.approval_status === 'approved' && Boolean(document?.approval_reference);
  const why = sopData?.why_retrieved || {};
  const toggleStep = (n) => setCheckedSteps((prev) => ({ ...prev, [n]: !prev[n] }));
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-white border border-[#D8E2DA] w-full max-w-2xl rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        <div className="bg-[#F3F6F3] px-5 py-4 border-b border-[#D8E2DA] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded bg-[#E8F5EC] border border-[#009530]/40 flex items-center justify-center text-[#009530]"><BookOpen className="w-5 h-5" /></div>
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded bg-[#E8F5EC] border border-[#009530]/30 text-[#006B35] font-mono-code font-bold text-xs">{sopId || '—'}</span>
                <h3 className="font-industrial font-bold text-[#26352C] text-base">{document?.title || sopData?.sop_title || 'Operating Procedure'}</h3>
              </div>
              <span className="text-xs text-[#64736A] font-mono-code">{document?.equipment || sopData?.equipment || 'SOP'} • Rev {document?.revision || '1.0'}</span>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-[#E8ECE8] text-[#64736A] hover:text-[#26352C] transition-colors cursor-pointer"><X className="w-5 h-5" /></button>
        </div>

        <div className="p-5 overflow-y-auto space-y-4 text-[#26352C]">
          <div className="bg-[#F3F6F3] border border-[#D8E2DA] rounded-lg p-3 text-xs text-[#64736A] flex items-center gap-3">
            <ShieldCheck className="w-5 h-5 text-[#009530] shrink-0" />
            <div className="min-w-0 flex-1"><strong className="text-[#26352C] block font-industrial">{approvalVerified ? 'APPROVED GUIDANCE' : 'REFERENCE ONLY — NOT APPROVED'}</strong>{document?.summary || document?.description || 'Procedure source'}
              {hasPdfSource && <a href={getSopSourceUrl(sopId, document.revision, document.sha256)} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1.5 font-semibold text-[#155EEF] hover:underline">Source PDF: {document.source_pdf} <span aria-hidden="true">↗</span></a>}
            </div>
          </div>

          {sopData?.why_retrieved && <details className="group bg-[#F3F6F3] border border-[#D8E2DA] rounded-lg">
            <summary className="flex cursor-pointer list-none items-center justify-between p-3 text-xs font-semibold text-[#26352C]">
              <span>Why this reference matched</span><ChevronDown className="h-4 w-4 text-[#64736A] transition-transform group-open:rotate-180" />
            </summary>
            <div className="grid grid-cols-2 gap-y-2 gap-x-4 border-t border-[#D8E2DA] p-4 text-xs">
              {[
                ['Incident', why.incident], ['Equipment', why.equipment], ['Alarm', why.alarm],
                ['Matching symptoms', Array.isArray(why.symptoms) ? why.symptoms.map((symptom) => `✓ ${symptom}`).join('\n') : why.symptoms],
                ['Likely contributor', why.likely_contributor], ['Relevant section', why.matching_section],
              ].filter(([, value]) => value !== undefined && value !== null && value !== '').map(([label, value]) => <div key={label} className="flex justify-between gap-2"><span className="text-[#64736A]">{label}:</span><span className="text-[#26352C] text-right whitespace-pre-line font-medium">{String(value)}</span></div>)}
            </div>
          </details>}

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-mono-code uppercase tracking-wider text-[#64736A] font-bold">Procedure</h4>
              {steps.length > 0 && <span className="text-[10px] text-[#64736A]">{steps.length} source steps</span>}
            </div>
            {loading && <div className="rounded-lg border border-[#D8E2DA] bg-[#F3F6F3] p-4 text-sm text-[#64736A]">Loading the full procedure…</div>}
            {loadError && steps.length === 0 && <div role="alert" className="rounded-lg border border-[#B7791F]/30 bg-[#FEF0C7] p-4">
              <p className="text-sm font-semibold text-[#B7791F]">The full procedure could not be loaded.</p>
              <p className="mt-1 text-xs leading-5 text-[#805400]">{loadError} Any excerpt shown below is a source reference, not proof of approval.</p>
              <button type="button" onClick={() => setReloadKey((value) => value + 1)} className="mt-3 inline-flex items-center gap-2 rounded-md border border-[#B7791F]/40 px-3 py-2 text-xs font-semibold text-[#805400] hover:bg-[#B7791F]/10"><RefreshCw size={13} />Try again</button>
            </div>}
            {!loading && steps.length === 0 && contentPages.length === 0 && <div className="rounded-lg border border-[#D8E2DA] bg-[#F3F6F3] p-4 text-sm text-[#64736A]">No complete procedure text is available for this reference.</div>}
            {!loading && contentPages.map((page) => (
              <article key={page.page} className="rounded-lg border border-[#D8E2DA] bg-[#F3F6F3] p-4">
                <h5 className="mb-2 text-[10px] font-mono-code uppercase tracking-wider text-[#155EEF] font-bold">Source page {page.page}</h5>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-[#26352C]">{page.text}</p>
              </article>
            ))}
            {!loading && steps.map((step) => {
              const checked = !!checkedSteps[step.step_number];
              return <button type="button" key={step.step_number} onClick={() => toggleStep(step.step_number)} className={`w-full p-3.5 rounded-lg border text-left transition-all ${checked ? 'bg-[#E8F5EC] border-[#009530]/60' : 'bg-[#F3F6F3] border-[#D8E2DA] hover:border-[#009530]/40 hover:bg-[#E8F5EC]/30'}`}>
                <span className="flex items-start gap-3">
                  <span className={`mt-0.5 w-5 h-5 rounded flex items-center justify-center border transition-colors ${checked ? 'bg-[#009530] border-[#009530] text-white' : 'border-[#D8E2DA] bg-white text-transparent'}`}><CheckCircle className="w-4 h-4" /></span>
                  <span className="flex-1 min-w-0"><span className="flex items-center justify-between gap-3"><span className="font-industrial font-bold text-sm text-[#26352C]">Step {step.step_number}</span>{checked && <span className="text-[10px] font-mono-code text-[#006B35] font-bold uppercase">Reviewed</span>}</span><span className="mt-1 block text-sm leading-5 text-[#425349]">{step.instruction}</span></span>
                </span>
              </button>;
            })}
          </section>

          {retrievedChunks.length > 0 && <details className="group rounded-lg border border-[#D8E2DA] bg-[#F3F6F3]">
            <summary className="flex cursor-pointer list-none items-center justify-between p-3 text-xs font-semibold text-[#26352C]">
              <span>Retrieved source excerpts <span className="ml-1 text-[#64736A]">({retrievedChunks.length})</span></span><ChevronDown className="h-4 w-4 text-[#64736A] transition-transform group-open:rotate-180" />
            </summary>
            <div className="space-y-2 border-t border-[#D8E2DA] p-3">
              <p className="text-[11px] leading-5 text-[#64736A]">Search excerpts are shown for traceability. They are not a substitute for a complete approved procedure.</p>
              {retrievedChunks.slice(0, 5).map((chunk, index) => <article key={chunk.chunk_id || index} className="rounded-lg border border-[#D8E2DA] bg-white p-3">
              <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] font-mono-code text-[#155EEF]">
                <span className="font-bold">{chunk.document_name || chunk.document_id || sopId || 'SOP source'}</span>
                {chunk.revision && <span>Rev {chunk.revision}</span>}
                {chunk.section && <span>Section: {chunk.section}</span>}
                {chunk.page != null && <span>Page {chunk.page}</span>}
              </div>
              <p className="whitespace-pre-wrap text-xs leading-relaxed text-[#26352C]">{chunk.text || 'Passage text unavailable.'}</p>
              </article>)}
            </div>
          </details>}
        </div>

        <div className="bg-[#F3F6F3] px-5 py-3.5 border-t border-[#D8E2DA] flex items-center justify-between">
          <span className="text-xs font-mono-code text-[#64736A]">{contentPages.length ? `${document?.source_pdf || 'PDF SOP'} · ${contentPages.length} pages` : steps.length ? `${Object.values(checkedSteps).filter(Boolean).length} of ${steps.length} steps checked` : 'Source status shown above'}</span>
          <button onClick={onClose} className="px-4 py-2 rounded bg-[#009530] hover:bg-[#006B35] text-white font-industrial font-semibold text-xs uppercase tracking-wider cursor-pointer transition-colors">Close SOP Viewer</button>
        </div>
      </div>
    </div>
  );
}
