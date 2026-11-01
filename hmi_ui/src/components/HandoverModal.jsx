import React from 'react';
import { X, ClipboardCheck, User, Calendar, FileText, CheckCircle2, ShieldCheck, Printer } from 'lucide-react';

export default function HandoverModal({ isOpen, onClose, handover, isIncident = false, unitName = 'Pump-02' }) {
  if (!isOpen) return null;

  const data = handover || {};
  const eventsInWindow = data.events || data.events_in_window || [];
  const actionsInWindow = data.actions || data.actions_in_window || [];
  const openIssues = data.open_events || data.open_issues || [];
  const summaryText = data.summary_text || (eventsInWindow.length > 0
    ? `${eventsInWindow.length} event(s) logged during this shift (${openIssues.length} still active).`
    : (data.incident || "Normal operational parameters maintained throughout the shift."));

  const latestEvent = eventsInWindow.length > 0 ? (typeof eventsInWindow[eventsInWindow.length - 1] === 'object' ? eventsInWindow[eventsInWindow.length - 1] : { primary_tag: eventsInWindow[eventsInWindow.length - 1] }) : null;
  const operatorSignOff = data.operator || (actionsInWindow.length > 0 ? actionsInWindow[actionsInWindow.length - 1].operator_id : "J. Rivera (Shift 2)");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-white border border-[#D8E2DA] w-full max-w-2xl rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">

        {/* Header */}
        <div className="bg-[#F3F6F3] px-5 py-4 border-b border-[#D8E2DA] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded bg-[#E8F5EC] border border-[#009530]/40 flex items-center justify-center text-[#009530]">
              <ClipboardCheck className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-industrial font-bold text-[#26352C] text-base">
                Shift handover
              </h3>
              <span className="text-xs text-[#64736A] font-mono-code">
                {unitName || data.unit || 'Selected equipment'}
              </span>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-[#E8ECE8] text-[#64736A] hover:text-[#26352C] transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 overflow-y-auto space-y-4">

          {/* Metadata Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 bg-[#F3F6F3] p-3.5 rounded-lg border border-[#D8E2DA] text-xs font-mono-code">
            <div>
              <span className="text-[#64736A] block">EQUIPMENT</span>
              <strong className="text-[#26352C]">{unitName || data.unit || 'Pump-02'}</strong>
            </div>
            <div>
              <span className="text-[#64736A] block">SHIFT</span>
              <strong className="text-[#26352C]">{data.shift || 'Shift 2 (Live)'}</strong>
            </div>
            <div>
              <span className="text-[#64736A] block">OPERATOR</span>
              <strong className="text-[#009530]">{operatorSignOff}</strong>
            </div>
            <div>
              <span className="text-[#64736A] block">STATUS</span>
              <span className={`font-bold ${openIssues.length > 0 ? 'text-[#D92D20]' : 'text-[#009530]'}`}>{openIssues.length > 0 ? 'ATTN REQUIRED' : 'READY'}</span>
            </div>
          </div>

          {/* Shift Summary Banner */}
          <div className="bg-[#F3F6F3] rounded-lg p-4 border border-[#D8E2DA] space-y-2 text-xs">
            <h4 className="text-xs font-mono-code uppercase tracking-wider text-[#64736A] font-bold">
              Summary
            </h4>
            <p className="text-[#26352C] leading-relaxed font-sans text-xs">
              {summaryText}
            </p>
          </div>

          {/* Events Logged in Shift Window */}
          <div className="space-y-2">
            <h4 className="text-xs font-mono-code uppercase tracking-wider text-[#64736A] font-bold flex items-center justify-between">
              <span>Events ({eventsInWindow.length})</span>
            </h4>

            {eventsInWindow.length > 0 ? (
              <div className="bg-[#F3F6F3] rounded-lg border border-[#D8E2DA] divide-y divide-[#D8E2DA] text-xs font-mono-code">
                {eventsInWindow.map((ev, idx) => (
                  <div key={idx} className="p-3 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-[#26352C] font-bold">
                        {ev.primary_tag || ev.alarm_id || 'Recorded event'}
                      </div>
                      <div className="text-[11px] text-[#64736A]">
                        {new Date(ev.trigger_timestamp).toLocaleString()}
                      </div>
                    </div>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase shrink-0 ${
                      ev.status === 'RESOLVED'
                        ? 'bg-[#E8F5EC] text-[#006B35] border border-[#009530]/40'
                        : 'bg-[#FEF3F2] text-[#D92D20] border border-[#D92D20]/40'
                    }`}>
                      {ev.status || (ev.is_open ? 'OPEN' : 'RESOLVED')}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="bg-[#F3F6F3] rounded-lg p-3 border border-[#D8E2DA] text-xs text-[#64736A] italic">
                No critical excursions logged in current shift window.
              </div>
            )}
          </div>

          {/* Human-in-the-loop Actions Audit Trail */}
          <div className="space-y-2">
            <h4 className="text-xs font-mono-code uppercase tracking-wider text-[#64736A] font-bold">
              Operator actions ({actionsInWindow.length})
            </h4>

            {actionsInWindow.length > 0 ? (
              <div className="bg-[#F3F6F3] rounded-lg p-3 border border-[#D8E2DA] space-y-2">
                {actionsInWindow.map((act, i) => (
                  <div key={i} className="flex items-start gap-2.5 text-xs text-[#26352C] border-b border-[#D8E2DA] pb-2 last:border-0 last:pb-0">
                    <CheckCircle2 className="w-4 h-4 text-[#009530] shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-[#009530]">[{act.action_type}] {act.operator_id}</span>
                        <span className="text-[10px] font-mono-code text-[#64736A]">{new Date(act.timestamp).toLocaleTimeString()}</span>
                      </div>
                      <p className="text-[#64736A] text-xs mt-0.5">{act.notes}</p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="bg-[#F3F6F3] rounded-lg p-3 border border-[#D8E2DA] text-xs text-[#64736A] italic">
                {data.operator_action ? `Operator action: "${data.operator_action}"` : "No operator interventions logged yet."}
              </div>
            )}
          </div>

          {/* Compliance Statement */}
          <div className="bg-[#E8F5EC] border border-[#009530]/30 rounded-lg p-3 text-[11px] text-[#006B35] font-mono-code flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-[#009530] shrink-0" />
            <span>OpsLens does not control equipment. Operator actions are recorded.</span>
          </div>

        </div>

        {/* Footer */}
        <div className="bg-[#F3F6F3] px-5 py-3.5 border-t border-[#D8E2DA] flex items-center justify-between">
          <button
            onClick={() => window.print()}
            className="px-3 py-1.5 rounded bg-white hover:bg-[#E8ECE8] text-[#26352C] text-xs font-mono-code flex items-center gap-1.5 cursor-pointer border border-[#D8E2DA]"
          >
            <Printer className="w-3.5 h-3.5" />
            Print
          </button>

          <button
            onClick={onClose}
            className="px-4 py-2 rounded bg-[#009530] hover:bg-[#006B35] text-white font-industrial font-bold text-xs uppercase tracking-wider cursor-pointer transition-colors"
          >
            Close
          </button>
        </div>

      </div>
    </div>
  );
}
