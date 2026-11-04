import React from 'react';
import { ClipboardList, UserCheck, FileSpreadsheet } from 'lucide-react';

export default function ShiftHandoverCard({ handover, onOpenModal, isIncident = false, unitName = 'Pump-02', fullEvent = null }) {
  const eventsInWindow  = handover?.events || handover?.events_in_window || [];
  const actionsInWindow = handover?.actions || handover?.actions_in_window || [];
  const openIssues      = handover?.open_events || handover?.open_issues || [];
  const latestEvent     = eventsInWindow.length > 0
    ? (typeof eventsInWindow[eventsInWindow.length - 1] === 'object' ? eventsInWindow[eventsInWindow.length - 1] : { primary_tag: eventsInWindow[eventsInWindow.length - 1] })
    : null;
  const latestAction    = actionsInWindow.length > 0 ? actionsInWindow[actionsInWindow.length - 1] : null;

  const contributor = fullEvent?.evidence?.likely_contributor_tag
    || latestEvent?.likely_contributor
    || handover?.likely_contributor
    || (isIncident ? 'Under Investigation' : '—');

  const eventCount = Math.max(eventsInWindow.length, isIncident ? 1 : 0);
  const issueCount = Math.max(openIssues.length, isIncident ? 1 : 0);

  const rows = [
    { label: 'Events logged',    value: eventCount > 0 ? `${eventCount} event(s)` : 'None', highlight: eventCount > 0 },
    { label: 'Open issues',      value: issueCount > 0 ? `${issueCount} active` : 'None',   highlight: issueCount > 0 },
    { label: 'Root contributor', value: contributor,                                          amber: true },
    { label: 'Operator actions', value: actionsInWindow.length > 0 ? `${actionsInWindow.length} logged (${latestAction?.action_type || ''})` : 'None required', highlight: false },
    { label: 'Status',           value: issueCount > 0 || isIncident ? 'Active Incident' : 'Nominal', highlight: issueCount > 0 || isIncident },
  ];

  const operator = handover?.operator || (actionsInWindow.length > 0 ? actionsInWindow[actionsInWindow.length - 1].operator_id : 'J. Rivera (Shift 2)');

  return (
    <div className="rounded-xl border border-[#1a2535] bg-[#0d1420] p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center">
            <ClipboardList className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <div>
            <div className="text-[10px] font-mono uppercase tracking-widest text-emerald-400">Shift Handover</div>
            <div className="text-sm font-bold text-white">{unitName}</div>
          </div>
        </div>
        <button
          onClick={onOpenModal}
          className="h-7 px-3 rounded-lg text-[11px] font-medium flex items-center gap-1.5 bg-[#111827] hover:bg-[#1a2535] text-slate-300 border border-[#1a2535] cursor-pointer transition-all"
        >
          <FileSpreadsheet className="w-3 h-3 text-emerald-400" />
          Full Ledger
        </button>
      </div>

      {/* Rows */}
      <div className="space-y-2">
        {rows.map((row, i) => (
          <div key={i} className="flex items-center justify-between text-xs">
            <span className="text-slate-500 font-mono">{row.label}</span>
            <span className={`font-semibold ${
              row.amber ? 'text-amber-300' : row.highlight ? 'text-red-400' : 'text-slate-300'
            }`}>{row.value}</span>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className="mt-4 pt-3 border-t border-[#1a2535] flex items-center gap-1.5 text-[11px] text-slate-500">
        <UserCheck className="w-3 h-3 text-emerald-400" />
        <span>{operator}</span>
      </div>
    </div>
  );
}
