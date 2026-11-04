import React from 'react';
import { ArrowDown, ArrowUp, Activity, Gauge, Disc, Sliders } from 'lucide-react';

const TAG_META = {
  'VLV-04-POS': { name: 'Valve Position',       unit: '%',    icon: Sliders,  max: 100 },
  'FIT-02-FLW': { name: 'Flow Rate',             unit: 'L/m',  icon: Activity, max: 100 },
  'MOT-02-CUR': { name: 'Motor Current',         unit: 'A',    icon: Disc,     max: 12  },
  'PIT-02-PRS': { name: 'Line Pressure',         unit: 'bar',  icon: Gauge,    max: 8   },
  'CMP-01-VIB': { name: 'Vibration',             unit: 'mm/s', icon: Gauge,    max: 12  },
  'CMP-01-TMP': { name: 'Bearing Temp',          unit: '°C',   icon: Gauge,    max: 100 },
  'CMP-01-RPM': { name: 'Shaft Speed',           unit: 'RPM',  icon: Disc,     max: 3500},
  'CMP-01-SPD': { name: 'Shaft Speed',           unit: 'RPM',  icon: Disc,     max: 3600},
  'CMP-01-CUR': { name: 'Stator Current',        unit: 'A',    icon: Disc,     max: 80  },
  'CMP-01-PWR': { name: 'Compressor Power',      unit: 'kW',   icon: Activity, max: 80  },
  'FILT-01-DP': { name: 'Filter ΔP',             unit: 'bar',  icon: Gauge,    max: 2   },
  'TNK-01-LVL': { name: 'Tank Level',            unit: '%',    icon: Gauge,    max: 100 },
};

function getTagMeta(tag) {
  if (TAG_META[tag]) return TAG_META[tag];
  if (tag.includes('VLV')) return { name: tag, unit: '%',  icon: Sliders,  max: 100 };
  if (tag.includes('FLW') || tag.includes('FIT')) return { name: tag, unit: 'L/m', icon: Activity, max: 100 };
  return { name: tag, unit: 'u', icon: Gauge, max: 100 };
}

const PUMP_FALLBACK = [
  { id: 'VLV-04-POS', tag: 'VLV-04-POS', value: '78',   unit: '%',   bar: 78, deviated: false, critical: false, delta: null, trend: null },
  { id: 'FIT-02-FLW', tag: 'FIT-02-FLW', value: '82',   unit: 'L/m', bar: 82, deviated: false, critical: false, delta: null, trend: null },
  { id: 'MOT-02-CUR', tag: 'MOT-02-CUR', value: '7.8',  unit: 'A',   bar: 65, deviated: false, critical: false, delta: null, trend: null },
  { id: 'PIT-02-PRS', tag: 'PIT-02-PRS', value: '4.8',  unit: 'bar', bar: 60, deviated: false, critical: false, delta: null, trend: null },
];

const COMP_FALLBACK = [
  { id: 'CMP-01-VIB', tag: 'CMP-01-VIB', value: '1.8',   unit: 'mm/s', bar: 22, deviated: false, critical: false, delta: null, trend: null },
  { id: 'CMP-01-TMP', tag: 'CMP-01-TMP', value: '62.0',  unit: '°C',   bar: 62, deviated: false, critical: false, delta: null, trend: null },
  { id: 'CMP-01-RPM', tag: 'CMP-01-RPM', value: '2980',  unit: 'RPM',  bar: 85, deviated: false, critical: false, delta: null, trend: null },
  { id: 'CMP-01-PWR', tag: 'CMP-01-PWR', value: '45.0',  unit: 'kW',   bar: 56, deviated: false, critical: false, delta: null, trend: null },
];

export default function ProcessValues({ revealedStep = 5, isIncident = false, storySteps = [], equipmentId = 'Pump-02', primaryTag = null }) {
  let items = [];

  const analogSteps = storySteps.filter(s => !s.tag.startsWith('ALM-'));

  if (isIncident && analogSteps.length > 0) {
    const tagMap = new Map();
    analogSteps.forEach(s => { if (!tagMap.has(s.tag) || s.tag === primaryTag) tagMap.set(s.tag, s); });

    items = Array.from(tagMap.values()).map(step => {
      const meta = getTagMeta(step.tag);
      const isRevealed = revealedStep >= step.step_number;
      const val = isRevealed ? step.value_after : step.value_before;
      const deltaPct = step.value_before ? ((step.value_after - step.value_before) / step.value_before) * 100 : 0;
      const deviated = isRevealed && Math.abs(deltaPct) > 1;
      const critical = isRevealed && (step.tag === primaryTag || Math.abs(deltaPct) > 30);
      return {
        id: step.tag, tag: step.tag,
        name: meta.name,
        value: typeof val === 'number' ? (Number.isInteger(val) ? val.toString() : val.toFixed(1)) : String(val),
        unit: meta.unit,
        bar: Math.max(4, Math.min(100, (val / meta.max) * 100)),
        deviated, critical,
        delta: `${deltaPct >= 0 ? '+' : ''}${deltaPct.toFixed(0)}%`,
        trend: step.value_after < step.value_before ? 'down' : 'up',
      };
    });
  }


  if (items.length === 0) {
    if (equipmentId?.toLowerCase().includes('comp')) {
      items = COMP_FALLBACK;
    } else if (equipmentId?.toLowerCase().includes('tank')) {
      items = [
        { id: 'TNK-01-LVL', tag: 'TNK-01-LVL', value: '60', unit: '%', bar: 60, deviated: false, critical: false, delta: null, trend: null },
      ];
    } else {
      items = PUMP_FALLBACK;
    }
  }

  return (
    <div className="grid grid-cols-4 gap-3">
      {items.map(item => (
        <div key={item.id} className={`rounded-xl border p-4 transition-all duration-300 ${
          item.critical
            ? 'border-red-500/60 bg-[#150e10]'
            : item.deviated
            ? 'border-amber-500/40 bg-[#14120a]'
            : 'border-[#1a2535] bg-[#0d1420]'
        }`}>
          {/* Tag + Name */}
          <div className="flex items-start justify-between mb-3">
            <div>
              <div className="text-[9px] font-mono font-bold uppercase tracking-widest text-slate-500">{item.tag}</div>
              <div className="text-xs font-medium text-slate-300 mt-0.5">{item.name}</div>
            </div>
            {item.deviated && (
              <span className={`flex items-center gap-0.5 text-[10px] font-bold font-mono px-1.5 py-0.5 rounded ${
                item.critical ? 'bg-red-500/20 text-red-300' : 'bg-amber-500/20 text-amber-300'
              }`}>
                {item.trend === 'down' ? <ArrowDown className="w-2.5 h-2.5" /> : <ArrowUp className="w-2.5 h-2.5" />}
                {item.delta}
              </span>
            )}
          </div>

          {/* Big value */}
          <div className={`text-3xl font-black tracking-tight leading-none ${
            item.critical ? 'text-red-400' : item.deviated ? 'text-amber-300' : 'text-emerald-400'
          }`}>
            {item.value}
            <span className="text-sm font-normal text-slate-500 ml-1">{item.unit}</span>
          </div>

          {/* Bar */}
          <div className="mt-3 h-1 bg-[#1a2535] rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                item.critical ? 'bg-red-500' : item.deviated ? 'bg-amber-400' : 'bg-emerald-500'
              }`}
              style={{ width: `${item.bar}%` }}
            />
          </div>

          {/* Status */}
          {!item.deviated && (
            <div className="mt-1.5 text-[10px] text-emerald-600 font-mono">Nominal</div>
          )}
        </div>
      ))}
    </div>
  );
}
