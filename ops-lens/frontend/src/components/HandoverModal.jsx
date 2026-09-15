import React from 'react';
import { X, ClipboardCheck, User, Calendar, FileText, CheckCircle2, ShieldCheck, Printer } from 'lucide-react';

export default function HandoverModal({ isOpen, onClose, handover, isIncident = false, unitName = 'Pump-02' }) {
  if (!isOpen) return null;

  const data = handover || {};
  const eventsInWindow = data.events || data.events_in_window || [];
  const actionsInWindow = data.actions || data.actions_in_window || [];
  const openIssues = data.open_events || data.open_issues || [];
  const summaryText = data.summary_text || (eventsInWindow.length > 0
    ? `Shift summary: ${eventsInWindow.length} event(s) logged across operational shift window (${openIssues.length} active excursion(s)).`
    : (data.incident || "Normal operational parameters maintained throughout the shift."));

  const latestEvent = eventsInWindow.length > 0 ? (typeof eventsInWindow[eventsInWindow.length - 1] === 'object' ? eventsInWindow[eventsInWindow.length - 1] : { primary_tag: eventsInWindow[eventsInWindow.length - 1] }) : null;
  const operatorSignOff = data.operator || (actionsInWindow.length > 0 ? actionsInWindow[actionsInWindow.length - 1].operator_id : "J. Rivera (Shift 2)");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-[#121A28] border-2 border-slate-600 w-full max-w-2xl rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        
        {/* Header */}
        <div className="bg-[#162234] px-5 py-4 border-b border-slate-700 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded bg-emerald-600/30 border border-emerald-500 flex items-center justify-center text-emerald-400">
              <ClipboardCheck className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-industrial font-bold text-white text-base">
                OFFICIAL SHIFT HANDOVER DOSSIER
              </h3>
              <span className="text-xs text-slate-400 font-mono-code">
                EcoStruxure Operator Terminal Expert • Component 10 Memory Engine
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

        {/* Body */}
        <div className="p-5 overflow-y-auto space-y-4">
          
          {/* Metadata Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 bg-[#0E1624] p-3.5 rounded-lg border border-slate-800 text-xs font-mono-code">
            <div>
              <span className="text-slate-500 block">ASSET ID</span>
              <strong className="text-white">{unitName || data.unit || 'Pump-02'}</strong>
            </div>
            <div>
              <span className="text-slate-500 block">CURRENT SHIFT</span>
              <strong className="text-white">{data.shift || 'Shift 2 (Live)'}</strong>
            </div>
            <div>
              <span className="text-slate-500 block">OPERATOR SIGN-OFF</span>
              <strong className="text-se-lightgreen">{operatorSignOff}</strong>
            </div>
            <div>
              <span className="text-slate-500 block">HANDOVER STATUS</span>
              <span className="text-emerald-400 font-bold">{openIssues.length > 0 ? 'ATTN REQUIRED' : 'READY'}</span>
            </div>
          </div>

          {/* Shift Summary Banner */}
          <div className="bg-[#182436] rounded-lg p-4 border border-slate-700/80 space-y-2 text-xs">
            <h4 className="text-xs font-mono-code uppercase tracking-wider text-slate-400 font-bold">
              Shift Window Synthesis
            </h4>
            <p className="text-slate-200 leading-relaxed font-sans text-xs">
              {summaryText}
            </p>
          </div>

          {/* Events Logged in Shift Window */}
          <div className="space-y-2">
            <h4 className="text-xs font-mono-code uppercase tracking-wider text-slate-400 font-bold flex items-center justify-between">
              <span>Events In Shift Window ({eventsInWindow.length})</span>
              <span className="text-[10px] text-slate-500">Live Orchestrator Stream</span>
            </h4>
            
            {eventsInWindow.length > 0 ? (
              <div className="bg-[#0E1624] rounded-lg border border-slate-800 divide-y divide-slate-800 text-xs font-mono-code">
                {eventsInWindow.map((ev, idx) => (
                  <div key={idx} className="p-3 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-slate-200 font-bold">
                        {ev.causal_label || ev.primary_tag}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        Tag: {ev.primary_tag} • Time: {new Date(ev.trigger_timestamp).toLocaleTimeString()}
                      </div>
                    </div>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase shrink-0 ${
                      ev.status === 'RESOLVED'
                        ? 'bg-emerald-950 text-emerald-300 border border-emerald-500/40'
                        : 'bg-red-950 text-red-300 border border-red-500/40'
                    }`}>
                      {ev.status || (ev.is_open ? 'OPEN' : 'RESOLVED')}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="bg-[#0E1624] rounded-lg p-3 border border-slate-800 text-xs text-slate-400 italic">
                No critical excursions logged in current shift window.
              </div>
            )}
          </div>

          {/* Human-in-the-loop Actions Audit Trail */}
          <div className="space-y-2">
            <h4 className="text-xs font-mono-code uppercase tracking-wider text-slate-400 font-bold">
              Operator Interventions & Acknowledged Actions ({actionsInWindow.length})
            </h4>

            {actionsInWindow.length > 0 ? (
              <div className="bg-[#0E1624] rounded-lg p-3 border border-slate-800 space-y-2">
                {actionsInWindow.map((act, i) => (
                  <div key={i} className="flex items-start gap-2.5 text-xs text-slate-200 border-b border-slate-800/80 pb-2 last:border-0 last:pb-0">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-se-lightgreen">[{act.action_type}] {act.operator_id}</span>
                        <span className="text-[10px] font-mono-code text-slate-500">{new Date(act.timestamp).toLocaleTimeString()}</span>
                      </div>
                      <p className="text-slate-300 text-xs mt-0.5">{act.notes}</p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="bg-[#0E1624] rounded-lg p-3 border border-slate-800 text-xs text-slate-400 italic">
                {data.operator_action ? `Operator action: "${data.operator_action}"` : "No operator interventions logged yet."}
              </div>
            )}
          </div>

          {/* Compliance Statement */}
          <div className="bg-emerald-950/20 border border-emerald-500/30 rounded-lg p-3 text-[11px] text-emerald-300/90 font-mono-code flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>
              Schneider Electric Operational Compliance Standard: No automated AI writeback to PLC. Full operator auditability logged.
            </span>
          </div>

        </div>

        {/* Footer */}
        <div className="bg-[#162234] px-5 py-3.5 border-t border-slate-700 flex items-center justify-between">
          <button
            onClick={() => window.print()}
            className="px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-mono-code flex items-center gap-1.5 cursor-pointer"
          >
            <Printer className="w-3.5 h-3.5" />
            Print / Export Dossier
          </button>

          <button
            onClick={onClose}
            className="px-4 py-2 rounded bg-se-green hover:bg-se-lightgreen text-black font-industrial font-bold text-xs uppercase tracking-wider cursor-pointer transition-colors"
          >
            Close Handover Dossier
          </button>
        </div>

      </div>
    </div>
  );
}
