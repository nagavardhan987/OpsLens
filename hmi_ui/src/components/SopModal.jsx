import React, { useEffect, useState } from 'react';
import { X, BookOpen, CheckCircle, ShieldCheck } from 'lucide-react';
import { getSop } from '../api/client';

export default function SopModal({ isOpen, onClose, sopData }) {
  const [document, setDocument] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(false);
  const [checkedSteps, setCheckedSteps] = useState({});
  const sopId = sopData?.sop_id || sopData?.sop?.sop_id;

  useEffect(() => {
    if (!isOpen || !sopId) return;
    let active = true;
    setLoading(true); setLoadError(''); setDocument(null); setCheckedSteps({});
    getSop(sopId).then((result) => { if (active) setDocument(result.data); })
      .catch((error) => { if (active) setLoadError(error.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [isOpen, sopId]);
  if (!isOpen) return null;

  const steps = (document?.steps || []).map((instruction, idx) => ({ step_number: idx + 1, instruction }));
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
              <span className="text-xs text-slate-400 font-mono-code">{document?.equipment || 'SOP'} • Rev {document?.revision || '—'}</span>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-700 text-slate-400 hover:text-white transition-colors cursor-pointer"><X className="w-5 h-5" /></button>
        </div>

        <div className="p-5 overflow-y-auto space-y-4">
          <div className="bg-[#0E1624] border border-blue-500/30 rounded-lg p-3 text-xs text-slate-300 flex items-center gap-3">
            <ShieldCheck className="w-5 h-5 text-blue-400 shrink-0" />
            <div><strong className="text-white block font-industrial">OPERATING DIRECTIVE:</strong>{document?.summary || document?.description || `Source: ${document?.source || 'SOP document store'}`}</div>
          </div>

          {sopData?.why_retrieved && <div className="bg-[#121A28] border border-slate-700 rounded-lg p-4">
            <h4 className="text-xs font-mono-code uppercase tracking-wider text-slate-400 font-bold mb-3">WHY THIS SOP WAS RETRIEVED</h4>
            <div className="grid grid-cols-2 gap-y-2 gap-x-4 text-xs">
              {[
                ['Incident', why.incident], ['Equipment', why.equipment], ['Alarm', why.alarm],
                ['Matching symptoms', Array.isArray(why.symptoms) ? why.symptoms.map((symptom) => `✓ ${symptom}`).join('\n') : why.symptoms],
                ['Likely contributor', why.likely_contributor], ['Relevant section', why.matching_section],
                ['Semantic relevance', sopData.semantic_similarity?.toFixed?.(4)],
                ['Retrieval method', sopData.retrieval_method === 'qdrant_vector_search' ? 'Qdrant semantic search' : sopData.retrieval_method],
                ['Embedding', sopData.embedding_model || 'all-MiniLM-L6-v2']
              ].filter(([, value]) => value !== undefined && value !== null && value !== '').map(([label, value]) => <div key={label} className="flex justify-between gap-2"><span className="text-slate-400">{label}:</span><span className="text-slate-100 text-right whitespace-pre-line">{String(value)}</span></div>)}
            </div>
          </div>}

          <div className="space-y-3">
            <h4 className="text-xs font-mono-code uppercase tracking-wider text-slate-400 font-bold">Procedure ({steps.length} Steps)</h4>
            {loading && <p className="text-xs text-slate-400">Loading procedure from SOP store…</p>}
            {loadError && <p className="text-xs text-amber-300">Procedure unavailable: {loadError}</p>}
            {!loading && !loadError && steps.map((step) => {
              const checked = !!checkedSteps[step.step_number];
              return <div key={step.step_number} onClick={() => toggleStep(step.step_number)} className={`p-3.5 rounded-lg border transition-all cursor-pointer ${checked ? 'bg-emerald-950/20 border-emerald-500/60' : 'bg-[#182335] border-slate-700/80 hover:border-slate-500'}`}>
                <div className="flex items-start gap-3">
                  <div className={`mt-0.5 w-5 h-5 rounded flex items-center justify-center border transition-colors ${checked ? 'bg-emerald-600 border-emerald-500 text-white' : 'border-slate-500 bg-slate-800 text-transparent'}`}><CheckCircle className="w-4 h-4" /></div>
                  <div className="flex-1 min-w-0"><div className="flex items-center justify-between"><span className="font-industrial font-bold text-sm text-slate-100">Step {step.step_number}. {step.instruction}</span>{checked && <span className="text-[10px] font-mono-code text-emerald-400 font-bold uppercase">✓ Verified</span>}</div></div>
                </div>
              </div>;
            })}
          </div>
        </div>

        <div className="bg-[#162234] px-5 py-3.5 border-t border-slate-700 flex items-center justify-between">
          <span className="text-xs font-mono-code text-slate-400">{Object.values(checkedSteps).filter(Boolean).length} of {steps.length} steps verified</span>
          <button onClick={onClose} className="px-4 py-2 rounded bg-slate-700 hover:bg-slate-600 text-white font-industrial font-semibold text-xs uppercase tracking-wider cursor-pointer transition-colors">Close SOP Viewer</button>
        </div>
      </div>
    </div>
  );
}
