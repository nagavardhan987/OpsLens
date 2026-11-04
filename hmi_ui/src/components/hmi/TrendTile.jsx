import React from 'react';

function fmt(v) {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1000) return Math.round(v).toLocaleString();
  if (a >= 100) return v.toFixed(0);
  if (a >= 10) return v.toFixed(1).replace(/\.0$/, '');
  return v.toFixed(2).replace(/0$/, '').replace(/\.0$/, '');
}

/** Sparkline of recorded values with the normal band and SOP limit lines. */
export function Sparkline({ points = [], normal, limits = [], width = 132, height = 34, alarm = false }) {
  const values = points.map((p) => p.v);
  if (values.length < 2) return <svg width={width} height={height} aria-hidden="true" />;
  const extras = [...limits.map((l) => l.value), ...(normal || []).filter((n) => typeof n === 'number')];
  let lo = Math.min(...values, ...extras);
  let hi = Math.max(...values, ...extras);
  if (hi === lo) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.08;
  lo -= pad; hi += pad;
  const x = (i) => (i / (values.length - 1)) * (width - 2) + 1;
  const y = (v) => height - 1 - ((v - lo) / (hi - lo)) * (height - 2);
  const path = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const band = normal && normal.length === 2 ? [normal[0] ?? lo, normal[1] ?? hi] : null;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="ov-spark" aria-hidden="true">
      {band && <rect x="0" width={width} y={y(band[1])} height={Math.max(1, y(band[0]) - y(band[1]))} className="ov-spark-band" />}
      {limits.map((l) => <line key={`${l.direction}-${l.value}`} x1="0" x2={width} y1={y(l.value)} y2={y(l.value)} className="ov-spark-limit" />)}
      <path d={path} className={`ov-spark-line ${alarm ? 'alarm' : ''}`} />
      <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r="2.4" className={`ov-spark-dot ${alarm ? 'alarm' : ''}`} />
    </svg>
  );
}

export default function TrendTile({ signal }) {
  const alarm = Boolean(signal.beyond_limit);
  const first = signal.points?.[0]?.v;
  const delta = typeof first === 'number' && typeof signal.latest === 'number' ? signal.latest - first : null;
  return (
    <div className={`ov-trend ${alarm ? 'alarm' : ''}`} title={`${signal.tag} · normal ${signal.normal_text || '—'}${signal.limits?.length ? ` · limit ${signal.limits.map((l) => l.label).join(' / ')}` : ''}`}>
      <div className="ov-trend-head"><span className="ov-trend-label">{signal.label}</span>{alarm && <span className="ov-chip red">LIMIT</span>}</div>
      <div className="ov-trend-body">
        <div className="ov-trend-value"><strong>{fmt(signal.latest)}</strong><small>{signal.unit}</small></div>
        <Sparkline points={signal.points} normal={signal.normal} limits={signal.limits} alarm={alarm} width={104} height={30} />
      </div>
      <div className="ov-trend-foot"><span className="mono">{signal.tag}</span><span>{delta != null && Math.abs(delta) > 0 ? `${delta > 0 ? '▲' : '▼'} ${fmt(Math.abs(delta))}` : 'steady'}</span></div>
      <div className="ov-trend-norm">Normal {signal.normal_text || '—'}</div>
    </div>
  );
}
