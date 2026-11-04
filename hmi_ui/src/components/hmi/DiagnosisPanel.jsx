import React, { useEffect, useRef, useState } from 'react';
import { Bot, Loader2, RefreshCw, ShieldAlert } from 'lucide-react';
import { streamDiagnosis } from '../../api/client';
import { parseDiagnosis } from '../../lib/diagnosisFormat';

const CHIP = { CONFIRMED: 'green', HYPOTHESIS: 'amber', UNKNOWN: 'grey' };

/**
 * Seven-section incident diagnosis. While Qwen writes, the draft streams in
 * (marked "draft — validating"); the validated result replaces it. A
 * deterministic fallback is always labelled and never shown as AI output.
 */
export default function DiagnosisPanel({ eventId, refreshKey, expanded = false }) {
  const [draft, setDraft] = useState('');
  const [result, setResult] = useState(null);
  const [meta, setMeta] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [nonce, setNonce] = useState(0);
  const bodyRef = useRef(null);

  useEffect(() => {
    if (!eventId) return undefined;
    const controller = new AbortController();
    const started = performance.now();
    setDraft(''); setResult(null); setMeta(null); setError(''); setLoading(true); setElapsed(0);
    const tick = window.setInterval(() => setElapsed((performance.now() - started) / 1000), 200);
    streamDiagnosis(eventId, {
      signal: controller.signal,
      onMeta: setMeta,
      onToken: (t) => setDraft((d) => d + t),
      onDone: (r) => setResult(r),
      onError: (e) => setError(e.detail || 'Diagnosis failed.'),
    }).catch((e) => { if (e.name !== 'AbortError') setError(`Diagnosis unavailable: ${e.message}`); })
      .finally(() => { window.clearInterval(tick); if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); window.clearInterval(tick); };
  }, [eventId, refreshKey, nonce]);

  useEffect(() => {
    if (loading && bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [draft, loading]);

  const isAi = result?.engine === 'ollama';
  const text = result?.text || draft;
  const parsed = parseDiagnosis(text);
  const lat = result?.latency || {};

  let badge;
  if (!result) badge = <span className="ov-chip blue">{draft ? 'DRAFT — VALIDATING' : 'WAITING FOR MODEL'}</span>;
  else if (isAi) badge = <span className="ov-chip green">AI · {meta?.model || 'qwen2.5:3b'} · OLLAMA</span>;
  else badge = <span className="ov-chip amber">DETERMINISTIC FALLBACK</span>;

  return (
    <section className={`ov-panel ov-diag ${expanded ? 'expanded' : ''}`} aria-label="AI diagnosis" aria-busy={loading}>
      <header className="ov-panel-head">
        <h2><Bot size={14} /> AI diagnosis</h2>
        <div className="ov-head-right">
          {badge}
          <button type="button" className="ov-icon-btn" title="Regenerate" aria-label="Regenerate diagnosis" disabled={loading || !eventId} onClick={() => setNonce((n) => n + 1)}><RefreshCw size={13} /></button>
        </div>
      </header>
      {!eventId && <p className="ov-empty">Select an alarm to see its diagnosis.</p>}
      {eventId && (
        <div className="ov-diag-body" ref={bodyRef}>
          {loading && !draft && (
            <p className="ov-loading"><Loader2 size={14} className="spin" /> {meta?.model ? `Asking ${meta.model} (local) · ${elapsed.toFixed(1)} s` : `Preparing incident facts · ${elapsed.toFixed(1)} s`}</p>
          )}
          {result && !isAi && (
            <p className="ov-fallback"><ShieldAlert size={13} /> <span><b>Not AI-generated.</b> {result.fallback_reason}</span></p>
          )}
          {parsed.sections.map((s, i) => (
            <div key={`${i}-${s.title}`} className="ov-diag-section">
              {s.title && <h3>{s.title}</h3>}
              <ul>{s.items.map((it, j) => <li key={j}>{it.label && <span className={`ov-chip sm ${CHIP[it.label]}`}>{it.label}</span>}{it.text}</li>)}</ul>
            </div>
          ))}
          {loading && draft && <span className="ov-caret" aria-hidden="true" />}
          {error && <p role="alert" className="ov-error">{error}</p>}
        </div>
      )}
      {result && (
        <footer className="ov-diag-foot">
          {isAi ? <>
            <span>First token {lat.time_to_first_token_ms != null ? `${(lat.time_to_first_token_ms / 1000).toFixed(1)} s` : '—'}</span>
            <span>Total {lat.total_ms != null ? `${(lat.total_ms / 1000).toFixed(1)} s` : '—'}</span>
            {lat.tokens_per_second && <span>{lat.tokens_per_second} tok/s</span>}
            {result.cached && <span>cached</span>}
            {result.validation?.warnings?.length ? <span className="warn" title={result.validation.warnings.join('; ')}>⚠ {result.validation.warnings.length} check</span> : <span>validated against record</span>}
          </> : <span>Built from recorded facts only · {lat.total_ms != null ? `${Math.round(lat.total_ms)} ms` : ''}</span>}
        </footer>
      )}
    </section>
  );
}
