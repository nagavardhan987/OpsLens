import React, { useRef } from 'react';
import { Activity, ArrowDownRight, ArrowLeft, ArrowRight, ArrowUpRight, Gauge, Minus, SlidersHorizontal, Zap } from 'lucide-react';
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
  'DPT-110-SCR': Gauge,
  'FIT-110-IN': Activity,
  'FIT-101-DIS': Activity,
  'PIT-101-DIS': Gauge,
  'MOT-101-CUR': Zap,
  'LIT-101-WWL': Activity,
  'AIT-201-DO': Activity,
  'AIT-201-NH4': Activity,
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

function sourceLabel(source) {
  if (/synthetic|simulat/i.test(String(source || ''))) return 'SIMULATED';
  if (/opc.?ua|plc/i.test(String(source || ''))) return 'LIVE PLC';
  return 'RECORDED';
}

function getObserved(event, tag, unit = '', supportingReadings = []) {
  const scored = event?.evidence_audit?.scoring_breakdown?.tag_scores?.[tag]?.observed_reading;
  const step = [...(event?.story?.steps || [])].reverse().find((item) => item.tag === tag && typeof item.value_after === 'number');
  const recorded = supportingReadings.filter((item) => item.tag === tag && typeof item.value === 'number')
    .sort((a, b) => Date.parse(b.timestamp || b.timestamp_utc || '') - Date.parse(a.timestamp || a.timestamp_utc || ''))[0];
  if (recorded) return { ...recorded, timestamp: recorded.timestamp || recorded.timestamp_utc, unit: recorded.unit || unit, value_before: step?.value_before, source: recorded.data_source || recorded.source || 'Source not recorded' };
  if (scored && typeof scored.value === 'number') return { ...scored, unit: scored.unit || unit, value_before: step?.value_before, source: scored.data_source || scored.source || 'Source not recorded' };
  if (step) return { value: step.value_after, unit: unit || step.unit || '', timestamp: step.timestamp, source: step.data_source || step.source || 'Source not recorded', value_before: step.value_before };
  return null;
}

function MetricCard({ item, reading, event, equipmentId, isEquipmentStatus = false, compact = false }) {
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
          ) : <span className="text-slate-500" title="Change unavailable">—</span>}
          {isStale && <span className="freshness stale" title="Last reading more than 5 minutes ago">Stale</span>}
        </div>
      )}

      {/* Timestamp — in a collapsed detail so main card stays clean */}
      {!isEquipmentStatus && reading && (
        <details className="mt-1 group">
          <summary className="cursor-pointer text-[9px] text-slate-600 hover:text-slate-400 select-none list-none">
            <span className="group-open:hidden">Reading details ▸</span>
            <span className="hidden group-open:inline">Hide ▴</span>
          </summary>
          <div className="mt-1 text-[9px] text-slate-500 leading-relaxed">
            <div>{formatTimestamp(reading.timestamp)}</div>
            <div className="text-slate-600">{sourceLabel(reading.source)}</div>
          </div>
        </details>
      )}
    </article>
  );
}

export default function ProcessValues({ event, equipmentId, compact = false, onOpenDetails, supportingReadings = [] }) {
  const trackRef = useRef(null);
  const configuredTags = event ? getEquipmentProcessTags(event, equipmentId) : [];
  return (
    <section id="trends" className={`process-values-section${compact ? ' process-values-compact' : ''}`} aria-label="Equipment and sensor readings">
      <div className="section-heading-row">
        <div>
          <p className="section-kicker">{event ? 'Equipment overview' : 'Sensor trends'}</p>
          <h2 className="section-title">{event ? `${equipmentId || 'Equipment'} process values` : 'Recorded process values'}</h2>
        </div>
        <div className="process-values-tools">
          {compact && <><button type="button" aria-label="Previous equipment readings" onClick={() => trackRef.current?.scrollBy({ left: -300, behavior: 'smooth' })}><ArrowLeft size={14} /></button><button type="button" aria-label="Next equipment readings" onClick={() => trackRef.current?.scrollBy({ left: 300, behavior: 'smooth' })}><ArrowRight size={14} /></button><button type="button" onClick={onOpenDetails}>View details</button></>}
        </div>
      </div>
      {!event ? <div className="dashboard-panel text-sm leading-6 text-slate-400" role="status">
        No incident is selected, so there are no recorded sensor trends to show. Select an incident from Alarm Queue or Alarm History to view its stored readings here.
      </div> : <div ref={trackRef} className={compact ? 'process-values-track' : 'grid gap-3 sm:grid-cols-2 xl:grid-cols-5'}>
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
            reading={getObserved(event, item.tag, item.unit, supportingReadings)}
            event={event}
            equipmentId={equipmentId}
          compact={compact}
          />
        ))}
      </div>}
    </section>
  );
}
