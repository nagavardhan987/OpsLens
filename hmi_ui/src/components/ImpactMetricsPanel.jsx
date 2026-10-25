import React from 'react';
import { Activity, Clock3, TrendingDown, Zap } from 'lucide-react';

async function fetchMetrics() {
  const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';
  const bases = [API_BASE, 'http://localhost:8001/api', 'http://localhost:8000/api'];
  for (const base of bases) {
    try {
      const res = await fetch(`${base}/metrics/impact`, { signal: AbortSignal.timeout(2000) });
      if (res.ok) return res.json();
    } catch (_) {}
  }
  return null;
}

export default function ImpactMetricsPanel() {
  const [metrics, setMetrics] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetchMetrics().then(m => { setMetrics(m); setLoading(false); });
    const interval = setInterval(() => fetchMetrics().then(m => { if (m) setMetrics(m); }), 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading || !metrics) return null;

  return (
    <details className="dashboard-details">
      <summary>
        <span className="flex items-center gap-1.5">
          <TrendingDown size={14} className="text-emerald-500/70" />
          Operational impact metrics
        </span>
        <span className="details-hint">Demo session · estimated — not validated production results</span>
      </summary>

      <div className="border-t border-slate-800 p-4 space-y-3">
        <p className="text-[10px] text-amber-500/80 bg-amber-950/20 border border-amber-800/30 rounded px-3 py-1.5 leading-relaxed">
          These metrics are estimated from synthetic demo events. The {metrics.mttr_reduction_pct ?? '—'}% MTTR
          reduction figure compares to an assumed {metrics.baseline_mttr_minutes ?? 45}-minute baseline and is
          not validated real-world performance data.
        </p>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-3 text-center">
            <div className="text-xl font-bold text-emerald-400">
              {metrics.mttr_reduction_pct != null ? `${metrics.mttr_reduction_pct}%` : '—'}
            </div>
            <div className="mt-1 text-[10px] font-semibold uppercase tracking-wider text-emerald-600">
              MTTR Reduction
            </div>
            <div className="mt-0.5 text-[10px] text-slate-500">estimated · demo only</div>
          </div>

          <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-3 text-center">
            <div className="text-xl font-bold text-slate-200">
              {metrics.avg_mttr_minutes != null ? `${metrics.avg_mttr_minutes}m` : '—'}
            </div>
            <div className="mt-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400 flex items-center justify-center gap-1">
              <Clock3 size={9} />Avg MTTR
            </div>
            <div className="mt-0.5 text-[10px] text-slate-500">demo session</div>
          </div>

          <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-3 text-center">
            <div className="text-xl font-bold text-blue-400">&lt;2s</div>
            <div className="mt-1 text-[10px] font-semibold uppercase tracking-wider text-blue-500 flex items-center justify-center gap-1">
              <Zap size={9} />Context Assembly
            </div>
            <div className="mt-0.5 text-[10px] text-slate-500">target SLA</div>
          </div>

          <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-3 text-center">
            <div className="text-xl font-bold text-slate-200">{metrics.total_incidents ?? 0}</div>
            <div className="mt-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400 flex items-center justify-center gap-1">
              <Activity size={9} />Incidents
            </div>
            <div className="mt-0.5 text-[10px] text-slate-500">
              {metrics.open_incidents ?? 0} open · {metrics.resolved_incidents ?? 0} resolved
            </div>
          </div>
        </div>

        <p className="text-[10px] text-slate-600 text-center">
          Advisory only · AI copilot does not write to PLC or control equipment · Human-in-the-loop required
        </p>
      </div>
    </details>
  );
}
