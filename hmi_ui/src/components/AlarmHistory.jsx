import React from 'react';
import { AlertTriangle, Clock3, RefreshCw } from 'lucide-react';

const BAND_STYLES = {
  URGENT:   'bg-red-500/15 text-red-300',
  ELEVATED: 'bg-amber-500/15 text-amber-300',
  ROUTINE:  'bg-slate-700/40 text-slate-400',
};

function formatSourceTimestamp(value) {
  if (typeof value !== 'string' || !value.trim()) return 'Time unavailable';
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return 'Time unavailable';
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit', second: '2-digit', timeZoneName: 'short',
  }).format(timestamp);
}

export default function AlarmHistory({ events = [], loading = false, onSelectEvent }) {
  return (
    <section className="rounded-xl border border-[#1a2535] bg-[#0d1420] overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-[#1a2535]">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-widest text-blue-400">Operator Log</div>
          <h2 className="text-sm font-bold text-white mt-0.5">Recent alarms and incidents</h2>
          <p className="text-[10px] text-slate-500 mt-0.5">All incidents from this session · across all equipment</p>
        </div>
        <span className="text-[10px] font-mono text-slate-500">Local OpsLens event history</span>
      </div>
      {loading && <p className="px-5 py-4 text-xs text-slate-500">Loading event history…</p>}
      {!loading && events.length === 0 && (
        <div className="px-5 py-8 text-center">
          <Clock3 className="w-5 h-5 text-slate-600 mx-auto mb-2" />
          <p className="text-xs text-slate-400">No recorded alarms yet. The operator screen is monitoring for the next event.</p>
        </div>
      )}
      {events.length > 0 && (
        <div className="divide-y divide-[#1a2535]">
          {events.map((event) => {
            const band = event.urgency_band;
            const bandStyle = BAND_STYLES[band];
            const repeatCount = event.repeat_count || 1;
            return (
              <button
                key={event.event_id}
                type="button"
                onClick={() => onSelectEvent?.(event.event_id)}
                className="w-full text-left px-5 py-3 hover:bg-[#111a28] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                <div className="flex flex-wrap items-center justify-between gap-x-5 gap-y-2">
                  <div className="flex min-w-0 items-start gap-3">
                    <AlertTriangle className={`mt-0.5 w-4 h-4 shrink-0 ${event.is_open ? 'text-red-400' : 'text-slate-500'}`} />
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs font-bold text-slate-100">{event.alarm_id || 'Alarm ID unavailable'}</span>
                        <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${event.is_open ? 'bg-red-500/10 text-red-300' : 'bg-slate-800 text-slate-400'}`}>
                          {event.status || 'Status unavailable'}
                        </span>
                        {band && bandStyle && (
                          <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${bandStyle}`}>
                            {band}
                          </span>
                        )}
                        {repeatCount > 1 && (
                          <span className="inline-flex items-center gap-0.5 rounded bg-orange-900/30 px-1.5 py-0.5 text-[9px] font-bold text-orange-400">
                            <RefreshCw size={8} />×{repeatCount}
                          </span>
                        )}
                        <span className="text-[10px] text-slate-500">Source severity: {event.alarm_severity || 'not supplied'}</span>
                      </div>
                      <p className="mt-1 text-xs text-slate-400 truncate">{event.causal_label || event.description || 'Event details unavailable'}</p>
                    </div>
                  </div>
                  <div className="text-right text-[10px] text-slate-500">
                    <div>{event.equipment || 'Equipment unavailable'}</div>
                    <time dateTime={event.timestamp || undefined}>{formatSourceTimestamp(event.timestamp)}</time>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
