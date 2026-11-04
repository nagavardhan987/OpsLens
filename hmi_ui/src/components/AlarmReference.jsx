import React, { useEffect, useMemo, useState } from 'react';
import { API_BASE } from '../api/client';

/**
 * Engineering view of the alarm configuration extracted from SOP-MAN-000.
 * Shows each parameter's normal range and limits with the source page, how
 * it maps to an OpsLens tag, and every conflict with the tag registry.
 * Read-only: nothing here changes a threshold.
 */
const MAPPING_STYLE = {
  direct: 'bg-[#E8F5EC] text-[#006B35]',
  assumed: 'bg-[#FDF3DC] text-[#7A5410]',
  unit_mismatch: 'bg-[#FBE9E7] text-[#A1332B]',
  conflict: 'bg-[#FBE9E7] text-[#A1332B]',
  none: 'bg-[#EEF1EF] text-[#64736A]',
};

export default function AlarmReference() {
  const [reference, setReference] = useState(null);
  const [conflicts, setConflicts] = useState(null);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => {
    let active = true;
    Promise.all([
      fetch(`${API_BASE}/alarms/reference`).then((r) => (r.ok ? r.json() : Promise.reject(r.status))),
      fetch(`${API_BASE}/alarms/conflicts`).then((r) => (r.ok ? r.json() : Promise.reject(r.status))),
    ]).then(([ref, conf]) => { if (active) { setReference(ref); setConflicts(conf); } })
      .catch(() => { if (active) setError('Alarm reference is unavailable. Is the backend running on port 8001?'); });
    return () => { active = false; };
  }, []);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (reference?.definitions || []).filter((d) => !q || JSON.stringify(d).toLowerCase().includes(q));
  }, [reference, query]);

  if (error) return <main className="mx-auto max-w-7xl p-6 text-sm text-[#A1332B]">{error}</main>;
  if (!reference) return <main className="mx-auto max-w-7xl p-6 text-sm text-[#64736A]">Loading alarm reference…</main>;

  const src = reference.source_document || {};
  const levels = reference.priority_convention?.levels || [];
  return (
    <main className="mx-auto max-w-7xl space-y-5 p-6 text-[#26352C]">
      <section>
        <p className="font-mono text-[11px] font-bold uppercase tracking-[.2em] text-[#009530]">Alarm configuration</p>
        <h1 className="mt-1 text-3xl font-black">Alarm reference from {src.document_id}</h1>
        <p className="mt-2 max-w-4xl text-sm text-[#5B6E64]">{reference.definition_count} parameters extracted from <b>{src.file_name}</b> ({src.page_count} pages), each with its source page. {reference.applied_definitions} are mapped to OpsLens tags and used in the operator brief's SOP limit check. Status: <b className="text-[#8A5A00]">{src.approval_status}</b>.</p>
      </section>

      <section className="grid gap-3 md:grid-cols-3">
        {levels.map((level) => (
          <div key={level.priority} className="rounded-xl border border-[#D8E2DA] bg-white p-4">
            <div className="text-lg font-black">{level.priority}</div>
            <div className="text-xs text-[#5B6E64]">{level.meaning}</div>
            <div className="mt-2 text-xs">Acknowledge within <b>{level.acknowledge_within_text}</b> · on location within <b>{level.operator_on_location_within_text}</b></div>
          </div>
        ))}
      </section>
      <p className="text-xs text-[#64736A]">Priority convention: SOP-MAN-000 Section 6, page 4.</p>

      <section className="rounded-xl border border-[#D8E2DA] bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-black">Parameters and limits</h2>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter (e.g. wet well, SOP-GAS-001, LIT-101)" className="h-9 w-80 max-w-full rounded-lg border border-[#D8E2DA] px-3 text-sm" />
        </div>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[900px] border-collapse text-xs">
            <thead><tr className="text-left text-[#64736A]"><th className="border-b p-2">Parameter</th><th className="border-b p-2">SOP · page</th><th className="border-b p-2">Normal</th><th className="border-b p-2">Alarm / limits</th><th className="border-b p-2">OpsLens tag</th><th className="border-b p-2">Reset condition</th></tr></thead>
            <tbody>
              {rows.map((d) => {
                const mapping = d.opslens_mapping || {};
                return (
                  <tr key={d.id} className="align-top">
                    <td className="border-b p-2"><b>{d.parameter}</b><div className="text-[#64736A]">{d.process_area}</div></td>
                    <td className="border-b p-2 font-mono">{d.sop_id} · p.{d.source_page}</td>
                    <td className="border-b p-2">{d.normal?.text}</td>
                    <td className="border-b p-2">{(d.limits || []).length ? d.limits.map((l) => <div key={l.name}><b>{l.name}</b> {l.value} {d.unit} <span className="text-[#64736A]">(p.{l.source_page}{l.priority ? ` · ${l.priority}` : ''})</span></div>) : <span className="text-[#64736A]">none stated</span>}</td>
                    <td className="border-b p-2"><span className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-bold ${MAPPING_STYLE[mapping.mapping] || ''}`}>{mapping.mapping}</span> <span className="font-mono">{mapping.tag || '—'}</span>{mapping.alarm_tag ? <div className="font-mono text-[#64736A]">alarm: {mapping.alarm_tag}</div> : null}</td>
                    <td className="border-b p-2 text-[#8A5A00]">{d.reset_condition}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border border-[#F0C9C3] bg-white p-4">
        <h2 className="text-base font-black">Conflicts with the OpsLens tag registry ({conflicts?.count || 0})</h2>
        <p className="mt-1 text-xs text-[#5B6E64]">{conflicts?.policy}</p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[700px] border-collapse text-xs">
            <thead><tr className="text-left text-[#64736A]"><th className="border-b p-2">Tag</th><th className="border-b p-2">Field</th><th className="border-b p-2">SOP manual</th><th className="border-b p-2">OpsLens registry</th><th className="border-b p-2">Page</th></tr></thead>
            <tbody>{(conflicts?.conflicts || []).map((c, i) => <tr key={i}><td className="border-b p-2 font-mono">{c.tag}</td><td className="border-b p-2">{c.field}</td><td className="border-b p-2">{String(c.manual)}</td><td className="border-b p-2">{String(c.opslens)}</td><td className="border-b p-2">p.{c.source_page}</td></tr>)}</tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border border-[#D8E2DA] bg-white p-4 text-xs">
        <h2 className="text-base font-black">Gaps in the manual</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5">{(reference.known_gaps || []).map((g) => <li key={g}>{g}</li>)}</ul>
      </section>
    </main>
  );
}
