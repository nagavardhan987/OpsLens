import React, { useEffect, useRef, useState } from 'react';
import { CheckCircle2, FileText, LoaderCircle, Upload, ExternalLink, AlertCircle } from 'lucide-react';
import { getSopSourceUrl, ingestSopPdf, listSopLibrary } from '../api/client';

const initialMetadata = { sop_id: '', title: '', equipment: '', equipment_type: '', plant_area: '', revision: '1.0', effective_date: '' };
const fieldClass = 'mt-1 w-full rounded-lg border border-[#29374a] bg-[#080d15] px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none';

export default function SopLibrary() {
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [metadata, setMetadata] = useState(initialMetadata);
  const [documents, setDocuments] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  const refresh = async () => {
    try {
      const response = await listSopLibrary();
      setDocuments(response.documents || []);
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => { refresh(); }, []);

  const update = (event) => setMetadata((current) => ({ ...current, [event.target.name]: event.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    setError(''); setResult(null);
    if (!file) { setError('Choose a PDF file first.'); return; }
    if (file.size > 25 * 1024 * 1024) { setError('PDF files must be 25 MB or smaller.'); return; }
    if (!metadata.sop_id.trim() || !metadata.title.trim()) { setError('SOP ID and title are required.'); return; }
    const existing = documents.find((doc) => doc.sop_id === metadata.sop_id.trim());
    if (existing && !window.confirm(`SOP ${metadata.sop_id.trim()} already exists. Replace its indexed chunks and stored source PDF?`)) return;
    setBusy(true);
    try {
      const response = await ingestSopPdf(file, metadata);
      setResult(response.data);
      setFile(null);
      if (fileRef.current) fileRef.current.value = '';
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex-1 w-full max-w-6xl mx-auto px-6 py-8 space-y-7">
      <header>
        <p className="text-xs font-mono uppercase tracking-[0.22em] text-emerald-400">LOCAL KNOWLEDGE BASE</p>
        <h1 className="mt-2 text-3xl font-bold text-white">SOP Library</h1>
        <p className="mt-2 text-slate-400">Add approved procedures to the edge document store. PDFs stay on this computer; extracted text is embedded and indexed in local Qdrant.</p>
      </header>

      <div className="grid grid-cols-1 xl:grid-cols-5 gap-6 items-start">
        <form onSubmit={submit} className="xl:col-span-3 rounded-2xl border border-[#1a2535] bg-[#0d1420] p-6 space-y-5">
          <div>
            <h2 className="text-lg font-bold text-white">Ingest a PDF procedure</h2>
            <p className="mt-1 text-xs text-slate-500">PDF text extraction runs locally. Text-only PDFs are supported; scanned image PDFs require OCR first.</p>
            <p className="mt-2 text-xs text-amber-300/80">Reusing an SOP ID replaces that SOP’s indexed chunks and stored source PDF with this revision.</p>
          </div>

          <label className="block text-sm font-medium text-slate-300">PDF file
            <input ref={fileRef} type="file" accept="application/pdf,.pdf" onChange={(e) => { setFile(e.target.files?.[0] || null); setError(''); }} className="mt-2 block w-full rounded-lg border border-dashed border-[#34445b] bg-[#080d15] p-4 text-sm text-slate-300 file:mr-4 file:rounded-md file:border-0 file:bg-emerald-700 file:px-3 file:py-2 file:font-semibold file:text-white hover:file:bg-emerald-600" />
            {file && <span className="mt-2 block text-xs text-emerald-300">{file.name} · {(file.size / 1024 / 1024).toFixed(2)} MB</span>}
          </label>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[
              ['sop_id', 'SOP ID *', 'e.g. SOP-P02-VLV-02'],
              ['title', 'Procedure title *', 'e.g. Pump discharge pressure response'],
              ['equipment', 'Equipment', 'e.g. Pump-02'],
              ['equipment_type', 'Equipment type', 'e.g. Pump'],
              ['plant_area', 'Plant area', 'e.g. Pumping'],
              ['revision', 'Revision', 'e.g. 2.1'],
              ['effective_date', 'Effective date', 'e.g. 2026-10-12'],
            ].map(([name, label, placeholder]) => <label key={name} className="block text-xs font-semibold text-slate-400">{label}<input name={name} value={metadata[name]} onChange={update} placeholder={placeholder} required={name === 'sop_id' || name === 'title'} className={fieldClass} /></label>)}
          </div>

          {error && <div role="alert" className="flex gap-2 rounded-lg border border-red-800/70 bg-red-950/30 p-3 text-sm text-red-200"><AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />{error}</div>}
          {busy && <div className="flex items-center gap-2 text-sm text-blue-200"><LoaderCircle className="h-4 w-4 animate-spin" />Uploading, extracting text, embedding, and indexing locally…</div>}
          <button disabled={busy} className="h-11 w-full rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-sm font-bold text-white flex items-center justify-center gap-2"><Upload className="h-4 w-4" />{busy ? 'INGESTING PDF…' : 'INGEST SOP PDF'}</button>
        </form>

        <section className="xl:col-span-2 rounded-2xl border border-[#1a2535] bg-[#0d1420] p-6">
          <h2 className="text-lg font-bold text-white">Ingestion result</h2>
          {!result && !busy && <p className="mt-3 text-sm text-slate-500">After ingestion, the completed processing stages and indexed chunk count will appear here.</p>}
          {busy && <p className="mt-3 text-sm text-blue-200">Processing on this edge PC. Large documents can take a little while while the embedding model runs.</p>}
          {result && <div className="mt-4 space-y-3">
            <div className="rounded-lg border border-emerald-700/50 bg-emerald-950/20 p-3"><div className="font-semibold text-emerald-200">{result.title}</div><div className="mt-1 text-xs text-slate-400">{result.sop_id} · Rev {result.revision} · {result.source_pdf}</div></div>
            {result.stages.map((stage) => <div key={stage.name} className="flex items-start gap-2 text-xs"><CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" /><span className="text-slate-200">{stage.name}<span className="ml-1 text-slate-500">{stage.detail || ''}</span></span></div>)}
            <a className="inline-flex items-center gap-1 pt-2 text-xs font-semibold text-blue-300 hover:text-blue-200" href={getSopSourceUrl(result.sop_id)} target="_blank" rel="noreferrer">Open stored source PDF <ExternalLink className="h-3 w-3" /></a>
          </div>}
        </section>
      </div>

      <section className="rounded-2xl border border-[#1a2535] bg-[#0d1420] overflow-hidden">
        <div className="flex items-center justify-between border-b border-[#1a2535] px-5 py-4"><div><h2 className="font-bold text-white">Available SOP documents</h2><p className="mt-1 text-xs text-slate-500">Bundled JSON procedures and PDFs indexed on this edge PC.</p></div><span className="text-xs text-slate-500">{documents.length} documents</span></div>
        {documents.length === 0 ? <p className="p-5 text-sm text-slate-500">No documents found.</p> : <div className="divide-y divide-[#1a2535]">
          {documents.map((doc) => <div key={doc.sop_id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
            <div className="flex items-start gap-3"><FileText className={`mt-0.5 h-4 w-4 ${doc.storage_type === 'local_pdf' ? 'text-blue-300' : 'text-slate-500'}`} /><div><div className="text-sm font-semibold text-slate-100">{doc.title}</div><div className="mt-1 text-xs text-slate-500">{doc.sop_id} · {doc.equipment || 'Equipment unspecified'} · Rev {doc.revision || '1.0'}</div>{doc.source_pdf && <div className="mt-1 text-xs text-blue-300">Source PDF: {doc.source_pdf} · {doc.chunk_count} indexed chunks</div>}</div></div>
            <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider ${doc.storage_type === 'local_pdf' ? 'bg-blue-500/10 text-blue-300' : 'bg-slate-800 text-slate-400'}`}>{doc.storage_type === 'local_pdf' ? 'PDF · QDRANT' : 'BUNDLED · JSON'}</span>
          </div>)}
        </div>}
      </section>
    </main>
  );
}
