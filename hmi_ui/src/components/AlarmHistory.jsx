import React from 'react';
import { AlertTriangle, Clock3, RefreshCw } from 'lucide-react';

const BAND_STYLES = {
  URGENT:   'bg-[#FEF3F2] text-[#D92D20] border border-[#D92D20]/30',
  ELEVATED: 'bg-[#FEF0C7] text-[#B7791F] border border-[#B7791F]/30',
  ROUTINE:  'bg-[#E8F5EC] text-[#006B35] border border-[#009530]/30',
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

export default function AlarmHistory({ events = [], loading = false, error = '', onSelectEvent }) {
  return (
    <section className="rounded-xl border border-[#D8E2DA] bg-white overflow-hidden shadow-sm">
      <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-[#D8E2DA] bg-[#F3F6F3]">
        <div>
          <h2 className="text-sm font-bold text-[#26352C]">Incident history</h2>
        </div>
      </div>
      {loading && <p className="px-5 py-4 text-xs text-[#64736A]">Loading event history…</p>}
      {!loading && error && <p className="px-5 py-4 text-xs text-[#D92D20]" role="alert">{error}</p>}
      {!loading && !error && events.length === 0 && (
        <div className="px-5 py-8 text-center">
          <Clock3 className="w-5 h-5 text-[#64736A] mx-auto mb-2" />
          <p className="text-xs text-[#64736A]">No recorded alarms yet. The operator screen is monitoring for the next event.</p>
        </div>
      )}
      {events.length > 0 && (
        <div className="divide-y divide-[#D8E2DA]">
          {events.map((event) => {
            const band = event.urgency_band;
            const bandStyle = BAND_STYLES[band];
            const repeatCount = event.repeat_count || 1;
            return (
              <button
                key={event.event_id}
                type="button"
                onClick={() => onSelectEvent?.(event.event_id)}
                className="w-full text-left px-5 py-3 hover:bg-[#F3F6F3] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#009530] cursor-pointer"
              >
                <div className="flex flex-wrap items-center justify-between gap-x-5 gap-y-2">
                  <div className="flex min-w-0 items-start gap-3">
                    <AlertTriangle className={`mt-0.5 w-4 h-4 shrink-0 ${event.is_open ? 'text-[#D92D20]' : 'text-[#64736A]'}`} />
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs font-bold text-[#26352C]">{event.alarm_id || 'Alarm ID unavailable'}</span>
                        <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${event.is_open ? 'bg-[#FEF3F2] text-[#D92D20] border border-[#D92D20]/30' : 'bg-[#F3F6F3] text-[#64736A] border border-[#D8E2DA]'}`}>
                          {event.status || 'Status unavailable'}
                        </span>
                        {band && bandStyle && (
                          <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${bandStyle}`}>
                            {band}
                          </span>
                        )}
                        {repeatCount > 1 && (
                          <span className="inline-flex items-center gap-0.5 rounded bg-[#FEF0C7] border border-[#B7791F]/30 px-1.5 py-0.5 text-[9px] font-bold text-[#B7791F]">
                            <RefreshCw size={8} />×{repeatCount}
                          </span>
                        )}
                        {event.alarm_severity && <span className="text-[10px] text-[#64736A]">Severity: {event.alarm_severity}</span>}
                      </div>
                      <p className="mt-1 text-xs text-[#26352C] truncate">{event.description || event.primary_tag || 'Recorded alarm'}</p>
                    </div>
                  </div>
                  <div className="text-right text-[10px] text-[#64736A]">
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
