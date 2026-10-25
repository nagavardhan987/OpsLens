import React from 'react';
import { Activity, ArrowDownRight, ArrowUpRight, Gauge, Minus, SlidersHorizontal, Zap } from 'lucide-react';
import { getEquipmentProcessTags } from '../lib/equipmentPresentation';

const TAG_ICONS = {
  'FIT-02-FLW': Activity,
  'PIT-02-PRS': Gauge,
  'MOT-02-CUR': Zap,
  'VLV-04-POS': SlidersHorizontal,
  'CMP-01-SPD': Gauge,
  'CMP-01-VIB': Activity,
  'CMP-01-CUR': Zap,
  'CMP-01-TMP': Gauge,
  'TNK-01-LVL': Activity,
};

function formatTimestamp(value) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Timestamp unavailable';
  return new Intl.DateTimeFormat(undefined, {
    month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
  }).format(new Date(value));
}

function formatValue(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
}

function getObserved(event, tag, unit = '') {
  const scored = event?.evidence_audit?.scoring_breakdown?.tag_scores?.[tag]?.observed_reading;
  const step = [...(event?.story?.steps || [])].reverse().find((item) => item.tag === tag && typeof item.value_after === 'number');
  if (scored && typeof scored.value === 'number') return { ...scored, unit: scored.unit || unit, value_before: step?.value_before, source: 'Evidence Engine record' };
  if (step) return { value: step.value_after, unit: unit || step.unit || '', timestamp: step.timestamp, source: 'Event story record', value_before: step.value_before };
  return null;
}

function MetricCard({ item, reading, event, equipmentId, isEquipmentStatus = false }) {
  const Icon = TAG_ICONS[item.tag] || item.icon || Activity;
  const value = isEquipmentStatus ? null : reading?.value;
  const delta = reading && typeof reading.value_before === 'number' ? reading.value - reading.value_before : null;
  // Distinguish pp change (% tag) from relative % change
  const deltaUnit = item.unit === '%' ? 'pp' : item.unit;
  const isStale = reading?.timestamp && Date.now() - Date.parse(reading.timestamp) > 5 * 60 * 1000;
  const alarmActive = isEquipmentStatus && event?.runtime_alarm_state?.active === true;

  return (
    <article className={`metric-card flex flex-col justify-between${alarmActive ? ' alarm' : ''}`}>
      {/* Label + icon row */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="metric-label truncate">{item.label}</p>
          <p className="metric-tag">{isEquipmentStatus ? 'EQUIPMENT OVERVIEW' : item.tag}</p>
        </div>
        <span className={`metric-icon shrink-0${alarmActive ? ' red' : ''}`}><Icon size={17} /></span>
      </div>

      {/* Primary value */}
      <div className={`metric-value-row${isEquipmentStatus ? ' metric-equipment-value-row' : ''}`}>
        {isEquipmentStatus ? (
          <>
            <span className={`metric-value${alarmActive ? ' red-text' : ''}`}>{equipmentId || 'Equipment'}</span>
            <span className={`metric-state${alarmActive ? ' red' : event?.runtime_alarm_state?.active === false ? ' green' : ' muted'}`}>
              {alarmActive ? 'Alarm active' : event?.runtime_alarm_state?.active === false ? 'Alarm input clear' : 'State unavailable'}
            </span>
          </>
        ) : reading ? (
          <>
            <span className="metric-value">{formatValue(value)}</span>
            <span className="metric-unit">{reading.unit || item.unit}</span>
          </>
        ) : (
          <span className="metric-empty">No reading recorded</span>
        )}
      </div>

      {/* Delta + freshness */}
      {!isEquipmentStatus && (
        <div className="metric-foot">
          {delta !== null ? (
            <span className={`metric-delta${delta < 0 ? ' down' : delta > 0 ? ' up' : ' flat'}`}>
              {delta < 0 ? <ArrowDownRight size={13} /> : delta > 0 ? <ArrowUpRight size={13} /> : <Minus size={13} />}
              {delta > 0 ? '+' : ''}{formatValue(delta)}&thinsp;{deltaUnit}
              {item.unit === '%' && <span className="ml-1 opacity-60 text-[9px]">pp</span>}
            </span>
          ) : <span className="text-slate-600">Change unavailable</span>}
          {isStale && <span className="freshness stale" title="Last reading more than 5 minutes ago">Stale</span>}
        </div>
      )}

      {/* Timestamp — in a collapsed detail so main card stays clean */}
      {!isEquipmentStatus && reading && (
        <details className="mt-1 group">
          <summary className="cursor-pointer text-[9px] text-slate-600 hover:text-slate-400 select-none list-none">
            <span className="group-open:hidden">Show reading time ▸</span>
            <span className="hidden group-open:inline">Hide ▴</span>
          </summary>
          <div className="mt-1 text-[9px] text-slate-500 leading-relaxed">
            <div>{formatTimestamp(reading.timestamp)}</div>
            <div className="text-slate-600">{reading.source || 'Recorded value'}</div>
            <div className="mt-0.5 text-slate-600 italic">
              Recorded reading · not guaranteed live telemetry
            </div>
          </div>
        </details>
      )}
    </article>
  );
}

export default function ProcessValues({ event, equipmentId }) {
  const configuredTags = getEquipmentProcessTags(event, equipmentId);
  return (
    <section id="trends" className="space-y-3" aria-label="Equipment and sensor readings">
      <div className="section-heading-row">
        <div>
          <p className="section-kicker">Equipment overview</p>
          <h2 className="section-title">{equipmentId || 'Equipment'} process values</h2>
        </div>
        <span className="text-[10px] text-slate-500">
          Recorded readings · not live telemetry
        </span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard
          item={{ tag: 'equipment-status', label: 'Equipment status', icon: Activity }}
          event={event}
          equipmentId={equipmentId}
          isEquipmentStatus
        />
        {configuredTags.map((item) => (
          <MetricCard
            key={item.tag}
            item={{ ...item, icon: TAG_ICONS[item.tag] || Activity }}
            reading={getObserved(event, item.tag, item.unit)}
            event={event}
            equipmentId={equipmentId}
          />
        ))}
      </div>
    </section>
  );
}
