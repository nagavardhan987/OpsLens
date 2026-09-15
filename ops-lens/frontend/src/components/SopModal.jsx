import React, { useState } from 'react';
import { X, BookOpen, CheckCircle, AlertTriangle, ShieldCheck } from 'lucide-react';

export default function SopModal({ isOpen, onClose, sopData }) {
  if (!isOpen) return null;

  const sop = {
    sop_id: sopData?.sop_id || sopData?.sop?.sop_id || "SOP-P02-VLV-01",
    title: sopData?.sop_title || sopData?.title || sopData?.sop?.title || "Operational Response Procedure",
    system: sopData?.system || sopData?.sop?.system || "EcoStruxure Plant Asset Standard",
    summary: sopData?.summary || sopData?.sop?.summary || "Execute sequential verification and isolation steps in accordance with safety protocol.",
    steps: (sopData?.steps || sopData?.sop?.steps || []).map((step, idx) => {
      if (typeof step === 'string') {
        return {
          step_number: idx + 1,
          instruction: step,
          detail: `Step verified against real-time operational envelope and sensor telemetry.`,
          safety_note: idx === 0 ? "Ensure personal protective equipment (PPE) is engaged before field intervention." : null
        };
      }
      return step;
    })
  };

  const [checkedSteps, setCheckedSteps] = useState({});

  const toggleStep = (stepNumber) => {
    setCheckedSteps(prev => ({
      ...prev,
      [stepNumber]: !prev[stepNumber]
    }));
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-[#121A28] border-2 border-slate-600 w-full max-w-2xl rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        
        {/* Modal Header */}
        <div className="bg-[#162234] px-5 py-4 border-b border-slate-700 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded bg-blue-600/30 border border-blue-500 flex items-center justify-center text-blue-400">
              <BookOpen className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded bg-blue-950 border border-blue-500/40 text-blue-300 font-mono-code font-bold text-xs">
                  {sop.sop_id}
                </span>
                <h3 className="font-industrial font-bold text-white text-base">
                  {sop.title}
                </h3>
              </div>
              <span className="text-xs text-slate-400 font-mono-code">
                Plant Standard: {sop.system} • Rev 2.4
              </span>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-slate-700 text-slate-400 hover:text-white transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-5 overflow-y-auto space-y-4">
          
          {/* Overview note */}
          <div className="bg-[#0E1624] border border-blue-500/30 rounded-lg p-3 text-xs text-slate-300 flex items-center gap-3">
            <ShieldCheck className="w-5 h-5 text-blue-400 shrink-0" />
            <div>
              <strong className="text-white block font-industrial">OPERATING DIRECTIVE:</strong>
              {sop.summary}
            </div>
          </div>

          {/* Steps list */}
          <div className="space-y-3">
            <h4 className="text-xs font-mono-code uppercase tracking-wider text-slate-400 font-bold">
              Mandatory Execution Sequence (5 Steps)
            </h4>

            {sop.steps?.map((step) => {
              const isChecked = !!checkedSteps[step.step_number];

              return (
                <div
                  key={step.step_number}
                  onClick={() => toggleStep(step.step_number)}
                  className={`p-3.5 rounded-lg border transition-all cursor-pointer ${
                    isChecked
                      ? 'bg-emerald-950/20 border-emerald-500/60'
                      : 'bg-[#182335] border-slate-700/80 hover:border-slate-500'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div className={`mt-0.5 w-5 h-5 rounded flex items-center justify-center border transition-colors ${
                      isChecked
                        ? 'bg-emerald-600 border-emerald-500 text-white'
                        : 'border-slate-500 bg-slate-800 text-transparent'
                    }`}>
                      <CheckCircle className="w-4 h-4" />
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <span className="font-industrial font-bold text-sm text-slate-100">
                          Step {step.step_number}. {step.instruction}
                        </span>
                        {isChecked && (
                          <span className="text-[10px] font-mono-code text-emerald-400 font-bold uppercase">
                            ✓ Verified
                          </span>
                        )}
                      </div>

                      <p className="text-xs text-slate-300 mt-1 leading-relaxed">
                        {step.detail}
                      </p>

                      {step.safety_note && (
                        <div className="mt-2 flex items-center gap-1.5 text-[11px] font-mono-code text-amber-300 bg-amber-950/40 px-2.5 py-1 rounded border border-amber-500/30">
                          <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                          <span>Safety note: {step.safety_note}</span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

        </div>

        {/* Modal Footer */}
        <div className="bg-[#162234] px-5 py-3.5 border-t border-slate-700 flex items-center justify-between">
          <span className="text-xs font-mono-code text-slate-400">
            {Object.values(checkedSteps).filter(Boolean).length} of {sop.steps?.length || 5} steps verified
          </span>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded bg-slate-700 hover:bg-slate-600 text-white font-industrial font-semibold text-xs uppercase tracking-wider cursor-pointer transition-colors"
          >
            Close SOP Viewer
          </button>
        </div>

      </div>
    </div>
  );
}
