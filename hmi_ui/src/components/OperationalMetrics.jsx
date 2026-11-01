/**
 * OperationalMetrics — Engineering Console page (port 5174).
 *
 * Real Data Operational Metrics Dashboard for OpsLens.
 *
 * Key features & contracts:
 *  - Calculates metrics strictly from real backend database records.
 *  - Supports both Session-Wide scope and Selected-Incident scope with explicit UI toggles.
 *  - When zero valid resolved incidents exist, MTTR and MTTR reduction display as "—"
 *    with clear explanations (no fake 18.5 min or 58.9% fallbacks).
 *  - MTTR reduction is calculated ONLY when both a valid measured MTTR and a valid (>0)
 *    baseline exist: ((baseline - mttr) / baseline) * 100.
 *  - Assumed baseline (45 min) is explicitly labeled as a synthetic/assumed reference,
 *    never presented as a measured plant result.
 *  - Context assembly SLA (< 2 s) is kept strictly separate from actual measured latency.
 *    Displays real recorded latency stats (sample count, avg, median, p95) or
 *    "No measurements yet" if none recorded.
 *  - Auto-refreshes every 10 seconds, plus manual one-click refresh.
 */

import React, { useEffect, useState, useCallback } from 'react';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock3,
  Layers,
  RefreshCw,
  ShieldCheck,
  TrendingDown,
  Zap,
} from 'lucide-react';
import { getImpactMetrics } from '../api/client';

// ── helpers ──────────────────────────────────────────────────────────────────

function fmt(value, suffix = '') {
  return value != null ? `${value}${suffix}` : '—';
}

// ── sub-components ────────────────────────────────────────────────────────────

function MetricCard({ icon: Icon, label, value, sub, accent = 'emerald', wide = false }) {
  const accentMap = {
    emerald: 'text-[#006B35] border-[#009530]/30 bg-[#E8F5EC]',
    amber: 'text-[#B7791F] border-[#B7791F]/30 bg-[#FEF0C7]',
    blue: 'text-[#155EEF] border-[#155EEF]/30 bg-[#EFF8FF]',
    slate: 'text-[#26352C] border-[#D8E2DA] bg-white shadow-sm',
    red: 'text-[#D92D20] border-[#D92D20]/30 bg-[#FEF3F2]',
  };
  const cls = accentMap[accent] || accentMap.slate;

  return (
    <div className={`rounded-xl border p-4 ${cls} ${wide ? 'col-span-2' : ''}`}>
      <div className="flex items-center gap-2 mb-3">
        <Icon className="h-4 w-4 opacity-80" />
        <span className="text-[11px] font-semibold uppercase tracking-wider opacity-80">{label}</span>
      </div>
      <div className="text-2xl font-black font-mono">
        {value === '—' ? <span className="text-[#64736A] text-lg font-normal">—</span> : value}
      </div>
      {sub && (
        <div className="mt-1 text-[10px] text-[#64736A] leading-snug">{sub}</div>
      )}
    </div>
  );
}

function SectionHeader({ children }) {
  return (
    <h2 className="mt-8 mb-3 text-[11px] font-semibold uppercase tracking-[0.15em] text-[#64736A] border-b border-[#D8E2DA] pb-2">
      {children}
    </h2>
  );
}

// ── main component ────────────────────────────────────────────────────────────

export default function OperationalMetrics({ activeEventId = null }) {
  const [scope, setScope] = useState('session'); // 'session' | 'selected'
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [lastFetched, setLastFetched] = useState(null);

  const fetchMetrics = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = {
        scope: scope,
        ...(scope === 'selected' && activeEventId ? { eventId: activeEventId } : {}),
      };
      const data = await getImpactMetrics(params);
      setMetrics(data);
      setLastFetched(new Date());
    } catch (e) {
      setError('Operational metrics are temporarily unavailable. Try again.');
    } finally {
      setLoading(false);
    }
  }, [scope, activeEventId]);

  useEffect(() => {
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 10_000);
    return () => clearInterval(interval);
  }, [fetchMetrics]);

  const latencyStats = metrics?.context_assembly_stats;
  const hasLatencyMeasurements = latencyStats && latencyStats.sample_count > 0;

  return (
    <div className="mx-auto max-w-5xl px-6 pb-16 pt-6 font-sans text-[#26352C]">
      {/* Top Header & Scope Toggles */}
      <div className="flex flex-wrap items-center justify-between gap-4 mb-3">
        <div>
          <h1 className="text-xl font-black tracking-tight text-[#26352C] flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-[#009530]" />
            Operational metrics
          </h1>
          {lastFetched && <p className="mt-0.5 text-xs text-[#64736A]">Updated {lastFetched.toLocaleTimeString()}</p>}
        </div>

        <div className="flex items-center gap-2">
          {/* Scope Toggle Selector */}
          <div className="flex rounded-lg border border-[#D8E2DA] bg-white p-0.5 text-xs shadow-sm">
            <button
              onClick={() => setScope('session')}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 font-semibold transition cursor-pointer ${
                scope === 'session'
                  ? 'bg-[#E8F5EC] text-[#006B35] border border-[#009530]/30 shadow-xs'
                  : 'text-[#64736A] hover:text-[#26352C]'
              }`}
            >
              <Layers className="h-3 w-3" />
              All incidents
            </button>
            <button
              onClick={() => setScope('selected')}
              disabled={!activeEventId}
              title={!activeEventId ? 'No active incident selected' : ''}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 font-semibold transition cursor-pointer ${
                scope === 'selected'
                  ? 'bg-[#EFF8FF] text-[#155EEF] border border-[#155EEF]/30 shadow-xs'
                  : 'text-[#64736A] hover:text-[#26352C] disabled:opacity-30 disabled:hover:text-[#64736A]'
              }`}
            >
              <Activity className="h-3 w-3" />
              This incident
            </button>
          </div>

          <button
            onClick={fetchMetrics}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-lg border border-[#D8E2DA] bg-white px-3 py-2 text-xs font-semibold text-[#64736A] hover:text-[#26352C] hover:bg-[#F3F6F3] disabled:opacity-40 transition shadow-sm cursor-pointer"
            aria-label="Refresh metrics"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      <details className="mb-5 rounded-lg border border-[#D8E2DA] bg-white px-4 py-3 text-xs text-[#64736A]">
        <summary className="cursor-pointer font-semibold text-[#26352C]">About these metrics</summary>
        <p className="mt-2">Values use recorded incident and operator-action data. Time to resolution requires valid resolved records; comparison requires an explicit baseline.</p>
      </details>

      {/* Error state */}
      {error && (
        <div className="mb-6 rounded-xl border border-[#D92D20]/30 bg-[#FEF3F2] px-4 py-3 text-xs text-[#D92D20]">
          {error}
        </div>
      )}

      {/* Skeleton while loading */}
      {loading && !metrics && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 animate-pulse">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-24 rounded-xl border border-[#D8E2DA] bg-white shadow-sm" />
          ))}
        </div>
      )}

      {metrics && (
        <>
          {/* ── Incident Counts ──────────────────────────────────────────────── */}
          <SectionHeader>
            Incident counts
          </SectionHeader>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <MetricCard
              icon={Activity}
              label="Total incidents"
              value={fmt(metrics.total_incidents)}
              sub={scope === 'session' ? 'All incidents' : 'This incident'}
              accent="slate"
            />
            <MetricCard
              icon={AlertTriangle}
              label="Active incidents"
              value={fmt(metrics.open_incidents)}
              sub="Currently active"
              accent={metrics.open_incidents > 0 ? 'amber' : 'slate'}
            />
            <MetricCard
              icon={CheckCircle2}
              label="Resolved incidents"
              value={fmt(metrics.resolved_incidents)}
              sub="Recorded as resolved"
              accent="emerald"
            />
            <MetricCard
              icon={Clock3}
              label="Timed resolutions"
              value={fmt(metrics.valid_samples_count)}
              sub="Resolved with recorded times"
              accent={metrics.valid_samples_count > 0 ? 'emerald' : 'slate'}
            />
          </div>

          {/* ── MTTR & MTTR Reduction ────────────────────────────────────────── */}
          <SectionHeader>Time to resolution</SectionHeader>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <MetricCard
              icon={Clock3}
              label="Average time"
              value={fmt(metrics.avg_mttr_minutes, ' min')}
              sub={
                metrics.avg_mttr_minutes != null
                  ? `From ${metrics.valid_samples_count} resolved incident(s)`
                  : 'No timed resolutions yet'
              }
              accent={metrics.avg_mttr_minutes != null ? 'emerald' : 'slate'}
            />
            <MetricCard
              icon={TrendingDown}
              label="Change vs baseline"
              value={fmt(metrics.mttr_reduction_pct, ' %')}
              sub={
                metrics.mttr_reduction_pct != null
                  ? `Compared with ${metrics.baseline_mttr_minutes} min`
                  : 'Needs timed resolutions and a baseline'
              }
              accent={metrics.mttr_reduction_pct != null ? 'emerald' : 'slate'}
            />
            <MetricCard
              icon={Clock3}
              label="Comparison baseline"
              value={fmt(metrics.baseline_mttr_minutes, ' min')}
              sub={metrics.baseline_mttr_minutes != null ? 'Set for comparison' : 'Not set'}
              accent="slate"
            />
          </div>
          <details className="mt-2 text-[10px] text-[#64736A]"><summary className="cursor-pointer">Calculation notes</summary><div className="mt-1 space-y-1"><p>{metrics.mttr_note}</p><p>{metrics.baseline_note}</p></div></details>

          <details className="mt-5 rounded-lg border border-[#D8E2DA] bg-white px-4 py-3">
          <summary className="cursor-pointer text-sm font-semibold text-[#26352C]">System performance details</summary>
          <div className="pt-2">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <MetricCard
              icon={Zap}
              label="Design Target SLA"
              value="< 2.0 s"
              sub="target SLA (< 2000 ms)"
              accent="blue"
            />
            <MetricCard
              icon={Zap}
              label="Average Latency"
              value={hasLatencyMeasurements ? fmt(latencyStats.avg_ms, ' ms') : '—'}
              sub={hasLatencyMeasurements ? `across ${latencyStats.sample_count} request(s)` : 'No measurements yet'}
              accent={hasLatencyMeasurements ? 'emerald' : 'slate'}
            />
            <MetricCard
              icon={Zap}
              label="Median Latency"
              value={hasLatencyMeasurements ? fmt(latencyStats.median_ms, ' ms') : '—'}
              sub={hasLatencyMeasurements ? '50th percentile' : 'No measurements yet'}
              accent={hasLatencyMeasurements ? 'emerald' : 'slate'}
            />
            <MetricCard
              icon={Zap}
              label="P95 Latency"
              value={hasLatencyMeasurements ? fmt(latencyStats.p95_ms, ' ms') : '—'}
              sub={hasLatencyMeasurements ? '95th percentile' : 'No measurements yet'}
              accent={hasLatencyMeasurements ? 'emerald' : 'slate'}
            />
          </div>
          <p className="mt-2 text-[10px] text-[#64736A]">{metrics.context_assembly_note}</p>
          </div>
          </details>

          <SectionHeader>System status</SectionHeader>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <MetricCard
              icon={ShieldCheck}
              label="PLC control"
              value={metrics.writes_to_plc ? 'ENABLED' : 'DISABLED'}
              sub="No control commands are sent"
              accent={metrics.writes_to_plc ? 'red' : 'emerald'}
            />
            <MetricCard
              icon={ShieldCheck}
              label="Guidance"
              value={metrics.advisory_only ? 'ACTIVE' : 'OFF'}
              sub="Operator decision support"
              accent="emerald"
            />
            <MetricCard
              icon={ShieldCheck}
              label="Confirmation"
              value={metrics.human_in_the_loop ? 'REQUIRED' : 'NO'}
              sub="Operator action required"
              accent="emerald"
            />
            <MetricCard
              icon={Activity}
              label="Data source"
              value="SIMULATED"
              sub="Scenario readings"
              accent="slate"
            />
          </div>

          <p className="mt-8 text-[10px] text-[#64736A] text-center font-medium">
            OpsLens · Recorded operational data
          </p>
        </>
      )}
    </div>
  );
}
