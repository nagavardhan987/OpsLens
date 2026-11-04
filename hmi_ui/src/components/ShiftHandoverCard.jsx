import React from 'react';
import { ClipboardList, FileSpreadsheet, UserCheck } from 'lucide-react';

export default function ShiftHandoverCard({ handover, onOpenModal, onOpenPage }) {
  const latest = handover?.latest_handover;
  const openAlarms = handover?.open_alarms || [];
  const unresolved = handover?.unresolved_incidents || [];
  const actions = handover?.outstanding_operator_actions?.items || [];
  const pendingValue = handover?.outstanding_operator_actions?.status === 'Unavailable' ? 'Not tracked' : actions.length;
  const status = latest?.status === 'RECEIVED' ? 'Received by incoming operator' : latest ? 'Awaiting incoming confirmation' : 'No submitted handover recorded';
  return <section className="shift-handover-overview" aria-label="Shift handover summary">
    <div className="shift-handover-overview-heading"><div><span className="operator-eyebrow"><ClipboardList size={13} /> Shift Handover</span><strong>{handover?.current_shift?.name ? `${handover.current_shift.name} shift · ${handover.current_shift.date || 'date not set'}` : handover?.current_shift ? 'Shift timing not configured (set OPSLENS_SHIFT_NAME / _START / _END)' : 'Current shift unavailable'}</strong><small>{status}</small></div><div className="shift-handover-overview-actions"><button type="button" onClick={onOpenPage}>Open handover</button><button type="button" onClick={onOpenModal}><FileSpreadsheet size={13} /> Review / submit</button></div></div>
    <div className="shift-handover-overview-stats"><span><b>{openAlarms.length}</b> open alarms</span><span><b>{unresolved.length}</b> unresolved incidents</span><span><b>{pendingValue}</b> pending actions</span></div>
    <p className="shift-handover-overview-footer"><UserCheck size={13} /> Outgoing: {latest?.outgoing_operator || 'Not recorded'} · Incoming: {latest?.incoming_operator || 'Not confirmed'} · Carry forward remains open until separately resolved.</p>
  </section>;
}
