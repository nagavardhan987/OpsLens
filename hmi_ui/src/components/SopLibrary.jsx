import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, Circle, ExternalLink, FileText, LoaderCircle, ShieldAlert, Upload } from 'lucide-react';
import { getSopIngestionJob, getSopSourceUrl, ingestSopPdf, listSopLibrary } from '../api/client';

const initialMetadata = { sop_id: '', title: '', equipment: '', equipment_type: '', plant_area: '', revision: '', effective_date: '' };
const fieldClass = 'mt-1 w-full rounded-lg border border-[#D8E2DA] bg-white px-3 py-2.5 text-sm text-[#26352C] placeholder:text-[#64736A] focus:border-[#009530] focus:outline-none focus:ring-2 focus:ring-[#009530]/20';
const fieldDetails = {
  sop_id: 'Enter the identifier from the controlled source document.',
  title: 'Use the exact document title.',
  equipment: 'Enter the applicable asset or equipment scope.',
  equipment_type: 'Specify the equipment category.',
  plant_area: 'Specify the process area.',
  revision: 'Use the revision recorded in the source document. Leave blank if it is not stated.',
  effective_date: 'Use the approved effective date, if present. This field may be blank for draft/reference documents.',
};

function MetadataField({ name, label, placeholder, type = 'text', required, metadata, onChange }) {
  return <label className="block text-sm font-semibold text-[#26352C]" htmlFor={`sop-${name}`}>
    {label}{required && <span className="text-[#D92D20]"> *</span>}
    <input id={`sop-${name}`} name={name} type={type} value={metadata[name]} onChange={onChange}
      placeholder={placeholder} required={required} className={fieldClass} />
    <span className="mt-1 block text-xs font-normal leading-relaxed text-[#64736A]">{fieldDetails[name]}</span>
  </label>;
}

function StageRow({ stage }) {
  const partial = stage.status === 'partial';
  const running = stage.status === 'running';
  const unverified = stage.status === 'unverified' || (stage.complete === false && !running && !partial);
  const Icon = running ? LoaderCircle : unverified || partial ? ShieldAlert : stage.complete ? CheckCircle2 : Circle;
  const color = unverified ? 'text-[#B7791F]' : partial ? 'text-[#B7791F]' : stage.complete ? 'text-[#009530]' : 'text-[#64736A]';
  return <li className="flex items-start gap-2 text-sm">
    <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${color} ${running ? 'animate-spin' : ''}`} aria-hidden="true" />
    <span className="min-w-0 text-[#26352C]">{stage.name}</span>
  </li>;
}

function ingestionErrorText(error) {
  if (error?.stage === 'still_processing') return 'Processing is still underway. Check the status before trying again.';
  if (error?.stage === 'validation_failed') return error.message === 'Choose a PDF file first.' || error.message === 'Choose a PDF document.' || error.message === 'PDF files must be 25 MB or smaller.' || error.message === 'SOP ID and procedure title are required.' ? error.message : 'Check the selected file and procedure details.';
  if (error?.stage === 'extraction_failed') return error.manualReviewRequired ? 'Text could not be extracted. OCR or manual review is required.' : 'No readable text was found. The document was not indexed.';
  if (error?.stage === 'indexing_failed') return 'The document could not be added. No indexing success was recorded.';
  if (error?.stage === 'library_unavailable' || error?.stage === 'status_unavailable') return 'Document information is temporarily unavailable. Try again.';
  return 'The document could not be processed. Try again or contact document control.';
}

export default function SopLibrary() {
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [metadata, setMetadata] = useState(initialMetadata);
  const [documents, setDocuments] = useState([]);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [jobProgress, setJobProgress] = useState(null);

  const refresh = async () => {
    try {
      const response = await listSopLibrary();
      setDocuments(response.documents || []);
    } catch (err) {
      setError({ stage: 'library_unavailable', message: err.message });
    }
  };

  useEffect(() => { refresh(); }, []);
  const update = (event) => setMetadata((current) => ({ ...current, [event.target.name]: event.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    setResult(null);
    setJobProgress({ status: 'processing', current_stage: 'upload_received', stages: [{ name: 'PDF uploading', status: 'running', complete: false }] });
    if (!file) { setError({ stage: 'validation_failed', message: 'Choose a PDF file first.' }); return; }
    if (file.type && file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      setError({ stage: 'validation_failed', message: 'Choose a PDF document.' }); return;
    }
    if (file.size > 25 * 1024 * 1024) { setError({ stage: 'validation_failed', message: 'PDF files must be 25 MB or smaller.' }); return; }
    if (!metadata.sop_id.trim() || !metadata.title.trim()) { setError({ stage: 'validation_failed', message: 'SOP ID and procedure title are required.' }); return; }
    setBusy(true);
    try {
      let response = await ingestSopPdf(file, metadata);
      let data = response.data;
      if (response.status === 'processing' && response.job_id) {
        setJobProgress({ ...response, stages: [{ name: 'PDF uploaded', status: 'complete', complete: true }] });
        const deadline = Date.now() + 120_000;
        while (Date.now() < deadline) {
          const job = await getSopIngestionJob(response.job_id);
          setJobProgress(job);
          if (job.status === 'completed') { data = job.data; break; }
          if (job.status === 'failed') {
            const jobError = new Error(job.error?.message || 'Ingestion failed. No success was recorded.');
            jobError.stage = job.error?.stage;
            jobError.manualReviewRequired = job.error?.manual_review_required;
            throw jobError;
          }
          await new Promise((resolve) => setTimeout(resolve, 700));
        }
        if (!data) {
          setJobProgress((current) => ({ ...current, status: 'processing', timed_out: true }));
          setError({ stage: 'still_processing', message: 'The backend is still processing this upload. Do not submit it again; refresh the library or check its status before retrying.' });
          return;
        }
      }
      if (!['indexed', 'partial_extraction', 'duplicate'].includes(data?.status)) {
        const incomplete = new Error('The backend did not confirm extraction and indexing. No success was recorded.');
        incomplete.stage = 'ingestion_failed';
        throw incomplete;
      }
      setResult(data);
      if (data?.status === 'indexed' || data?.status === 'partial_extraction' || data?.status === 'duplicate') {
        setFile(null);
        if (fileRef.current) fileRef.current.value = '';
        await refresh();
      }
    } catch (err) {
      setError({ stage: err.stage || 'ingestion_failed', message: err.message, manualReviewRequired: err.manualReviewRequired });
    } finally {
      setBusy(false);
    }
  };

  const checkJobStatus = async () => {
    if (!jobProgress?.job_id) return;
    setBusy(true);
    setError(null);
    try {
      const job = await getSopIngestionJob(jobProgress.job_id);
      setJobProgress(job);
      if (job.status === 'completed' && ['indexed', 'partial_extraction', 'duplicate'].includes(job.data?.status)) {
        setResult(job.data);
        setError(null);
        setFile(null);
        if (fileRef.current) fileRef.current.value = '';
        await refresh();
      } else if (job.status === 'failed') {
        setError({ stage: job.error?.stage || 'ingestion_failed', message: job.error?.message || 'Ingestion failed. No success was recorded.', manualReviewRequired: job.error?.manual_review_required });
      } else {
        setError({ stage: 'still_processing', message: 'The backend is still working. Check status again shortly; do not upload this document again yet.' });
      }
    } catch (err) {
      setError({ stage: 'status_unavailable', message: err.message });
    } finally {
      setBusy(false);
    }
  };

  const resultTitle = result?.status === 'duplicate' ? 'This document is already in the library' : result?.status === 'partial_extraction' ? 'Added for review · text may be incomplete' : result?.status === 'indexed' ? 'Reference added' : 'Document status';
  const resultTone = result?.status === 'indexed' ? 'border-[#009530]/30 bg-[#E8F5EC]' : 'border-[#B7791F]/30 bg-[#FFF8E8]';
  const visibleDocuments = documents.filter((doc) => `${doc.sop_id} ${doc.title} ${doc.equipment} ${doc.process_area}`.toLowerCase().includes(search.trim().toLowerCase()));

  return <main className="flex-1 w-full max-w-6xl mx-auto px-4 py-7 sm:px-6 space-y-6 bg-[#F3F6F3]">
    <header>
      <p className="text-xs font-mono uppercase tracking-[0.22em] text-[#009530] font-bold">LOCAL KNOWLEDGE BASE</p>
      <h1 className="mt-2 text-3xl font-bold text-[#26352C]">SOP Library</h1>
      <p className="mt-2 max-w-3xl text-sm leading-relaxed text-[#64736A]">Add procedures for reference. Adding a document does not approve it.</p>
    </header>

    <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-5">
      <form onSubmit={submit} noValidate className="xl:col-span-3 rounded-2xl border border-[#D8E2DA] bg-white p-5 shadow-sm sm:p-6">
        <div className="mb-5">
          <h2 className="text-lg font-bold text-[#26352C]">Add a procedure PDF</h2>
          <p className="mt-1 text-xs leading-relaxed text-[#64736A]">Scanned pages may need manual text extraction and review.</p>
        </div>

        <div className="space-y-5">
          <section className="rounded-xl border border-[#D8E2DA] bg-[#F8FAF8] p-4">
            <h3 className="text-sm font-bold text-[#26352C]">1. Document file</h3>
            <label htmlFor="sop-pdf-file" className="mt-3 block text-sm font-semibold text-[#26352C]">PDF file <span className="text-[#D92D20]">*</span></label>
            <input id="sop-pdf-file" ref={fileRef} type="file" accept="application/pdf,.pdf" required
              onChange={(e) => { setFile(e.target.files?.[0] || null); setError(null); }}
              className="mt-1 block w-full rounded-lg border border-dashed border-[#D8E2DA] bg-white p-3 text-sm text-[#26352C] file:mr-3 file:rounded-md file:border-0 file:bg-[#009530] file:px-3 file:py-2 file:font-semibold file:text-white hover:file:bg-[#006B35] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#009530]" />
            <p className="mt-2 text-xs text-[#64736A]">PDF only · maximum size 25 MB. Existing revisions are preserved.</p>
            {file && <p className="mt-2 text-xs font-semibold text-[#006B35]">Selected: {file.name} · {(file.size / 1024 / 1024).toFixed(2)} MB</p>}
          </section>

          <section className="rounded-xl border border-[#D8E2DA] p-4">
            <h3 className="text-sm font-bold text-[#26352C]">2. Document identity</h3>
            <p className="mt-1 text-xs text-[#64736A]">Enter values as written in the controlled source document.</p>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <MetadataField name="sop_id" label="SOP ID" placeholder="Identifier from source" required metadata={metadata} onChange={update} />
              <MetadataField name="title" label="Procedure title" placeholder="Exact document title" required metadata={metadata} onChange={update} />
            </div>
          </section>

          <section className="rounded-xl border border-[#D8E2DA] p-4">
            <h3 className="text-sm font-bold text-[#26352C]">3. Equipment and applicability</h3>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <MetadataField name="equipment" label="Equipment" placeholder="Asset or equipment scope" metadata={metadata} onChange={update} />
              <MetadataField name="equipment_type" label="Equipment type" placeholder="Equipment category" metadata={metadata} onChange={update} />
              <div className="md:col-span-2"><MetadataField name="plant_area" label="Plant area" placeholder="Process area" metadata={metadata} onChange={update} /></div>
            </div>
          </section>

          <section className="rounded-xl border border-[#D8E2DA] p-4">
            <h3 className="text-sm font-bold text-[#26352C]">4. Revision and effective date</h3>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <MetadataField name="revision" label="Revision" placeholder="As shown in source" metadata={metadata} onChange={update} />
              <MetadataField name="effective_date" label="Effective date (optional)" type="date" metadata={metadata} onChange={update} />
            </div>
          </section>

          <section className="rounded-xl border border-[#B7791F]/30 bg-[#FFF8E8] p-4">
            <h3 className="text-sm font-bold text-[#26352C]">5. Approval status</h3>
            <div className="mt-3 flex items-start gap-2 rounded-lg border border-[#B7791F]/40 bg-white p-3 text-xs font-bold tracking-wide text-[#805600]" role="status">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />DRAFT / REFERENCE ONLY — NOT APPROVED
            </div>
            <p className="mt-2 text-xs leading-relaxed text-[#64736A]">Approval must be verified separately. Adding a file does not authorize its instructions.</p>
            {error && <div role="alert" className="mt-4 flex gap-2 rounded-lg border border-[#D92D20]/40 bg-[#FEF3F2] p-3 text-sm text-[#B42318]">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /><span><strong className="block">{error.stage === 'still_processing' ? 'Still processing' : error.stage === 'validation_failed' ? 'Check the document details' : 'Unable to complete'}</strong>{ingestionErrorText(error)}</span>
            </div>}
            {busy && <div className="mt-4 rounded-lg border border-[#D8E2DA] bg-white p-3 text-sm text-[#26352C]" role="status" aria-live="polite"><div className="mb-2 flex items-center gap-2"><LoaderCircle className="h-4 w-4 animate-spin text-[#009530]" /><strong>Ingestion in progress</strong></div><ol className="space-y-2">{(jobProgress?.stages || []).map((stage, index) => <StageRow key={`${stage.name}-${index}`} stage={stage} />)}</ol></div>}
            <button type="submit" disabled={busy} className="mt-4 flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-[#009530] text-sm font-bold text-white shadow-sm transition-colors hover:bg-[#006B35] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#006B35] disabled:cursor-wait disabled:opacity-60">
              {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}{busy ? 'ADDING DOCUMENT…' : 'ADD REFERENCE PDF'}
            </button>
          </section>
        </div>
      </form>

      <section className="xl:col-span-2 rounded-2xl border border-[#D8E2DA] bg-white p-5 shadow-sm sm:p-6" aria-live="polite">
        <h2 className="text-lg font-bold text-[#26352C]">Document status</h2>
        {!result && !busy && <p className="mt-3 text-sm leading-relaxed text-[#64736A]">The document status will appear here.</p>}
        {busy && <div className="mt-3"><ol className="space-y-3">{(jobProgress?.stages || []).map((stage, index) => <StageRow key={`${stage.name}-${index}`} stage={stage} />)}</ol></div>}
        {error?.stage === 'still_processing' && jobProgress && <div className="mt-4 rounded-lg border border-[#B7791F]/30 bg-[#FFF8E8] p-3 text-sm text-[#805600]">Wait for this document to finish before trying again.<button type="button" onClick={checkJobStatus} disabled={busy} className="mt-2 block rounded-md border border-[#B7791F]/40 bg-white px-3 py-1.5 text-xs font-semibold text-[#805600] disabled:opacity-60">Check status</button></div>}
        {result && <div className="mt-4 space-y-4">
          <div className={`rounded-lg border p-3 ${resultTone}`}>
            <div className="font-semibold text-[#26352C]">{resultTitle}</div>
            <div className="mt-1 break-words text-xs text-[#64736A]">{result.sop_id} · Rev {result.revision || 'unknown'} · {result.source_pdf}</div>
            <div className="mt-2 text-xs font-bold text-[#805600]">DRAFT / REFERENCE ONLY — NOT APPROVED</div>
            {result.extraction_warnings?.map((warning) => <div key={warning} className="mt-2 text-xs text-[#805600]">Manual review: {warning}</div>)}
          </div>
          <details className="rounded-lg border border-[#D8E2DA] p-3"><summary className="cursor-pointer text-xs font-semibold text-[#64736A]">Processing details</summary><ol className="mt-3 space-y-3" aria-label="Document processing stages">{(result.stages || []).map((stage, index) => <StageRow key={`${stage.name}-${index}`} stage={stage} />)}</ol></details>
          {result.source_pdf && result.sha256 && <a className="inline-flex items-center gap-1 pt-1 text-xs font-semibold text-[#006B35] hover:underline" href={getSopSourceUrl(result.sop_id, result.revision, result.sha256)} target="_blank" rel="noreferrer">Open stored source PDF <ExternalLink className="h-3 w-3" /></a>}
        </div>}
      </section>
    </div>

    <section className="overflow-hidden rounded-2xl border border-[#D8E2DA] bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#D8E2DA] bg-[#F3F6F3] px-5 py-4">
        <div><h2 className="font-bold text-[#26352C]">Available procedures</h2></div>
        <span className="text-xs text-[#64736A]">{visibleDocuments.length} of {documents.length} procedures</span>
      </div>
      <div className="border-b border-[#D8E2DA] p-4"><label className="sr-only" htmlFor="sop-library-search">Search procedures</label><input id="sop-library-search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by SOP ID, title, or area" className={fieldClass} /></div>
      {visibleDocuments.length === 0 ? <p className="p-5 text-sm text-[#64736A]">{documents.length ? 'No procedures match this search.' : 'No documents found.'}</p> : <div className="divide-y divide-[#D8E2DA]">
        {visibleDocuments.map((doc) => <div key={`${doc.sop_id}:${doc.revision}:${doc.sha256 || doc.storage_type}`} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 hover:bg-[#F3F6F3]">
          <div className="flex min-w-0 items-start gap-3"><FileText className="mt-0.5 h-4 w-4 shrink-0 text-[#64736A]" /><div className="min-w-0"><div className="text-sm font-semibold text-[#26352C]">{doc.title}</div><div className="mt-1 text-xs text-[#64736A]">{doc.sop_id} · {doc.equipment || 'Equipment unspecified'} · Rev {doc.revision || 'unknown'} · Pages {(doc.source_pages || []).join(', ') || 'see source document'}</div>{doc.source_pdf && <div className="mt-1 text-xs text-[#64736A]">{doc.source_pdf}</div>}{doc.document_status && <div className="mt-1 text-xs text-[#805600]">{doc.document_status}</div>}{doc.source_pdf && doc.sha256 && <a className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-[#006B35] hover:underline" href={getSopSourceUrl(doc.sop_id, doc.revision, doc.sha256)} target="_blank" rel="noreferrer">Open source pages <ExternalLink className="h-3 w-3" /></a>}</div></div>
          <span className={`rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider ${doc.approved === true && doc.approval_reference ? 'border-[#009530]/30 bg-[#E8F5EC] text-[#006B35]' : 'border-[#B7791F]/30 bg-[#FFF8E8] text-[#805600]'}`}>{doc.approved === true && doc.approval_reference ? 'APPROVED' : 'NOT APPROVED'}</span>
        </div>)}
      </div>}
    </section>
  </main>;
}
