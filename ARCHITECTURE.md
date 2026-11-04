# OpsLens Architecture

OpsLens runs on one edge PC: a FastAPI backend with SQLite, and two React/Vite frontends. Everything that decides *what happened* is deterministic Python. Language models are optional and only rephrase answers that are then checked against the record.

```text
                 ┌──────────────── Telemetry sources (read-only) ────────────────┐
                 │  Synthetic scenario generator  │  OPC UA client (M241/M251)   │
                 │  data_source = "simulated"     │  data_source = "live_plc"    │
                 └───────────────┬────────────────┴──────────────┬───────────────┘
                                 ▼                               ▼
                         SQLite tag_readings  ◄──── write-through, timestamps, quality
                                 │
          ┌──────────────────────▼───────────────────────────────────────────────┐
          │ Orchestrator (asyncio)                                               │
          │  1 Time-series contextualiser (baseline, trend, rate of change)      │
          │  2 Prioritiser  — alarm input? status change? analog excursion?      │
          │  3 Dedup + alarm lifecycle (fingerprints, re-activation = repeat)    │
          │  4 Correlator   — equipment, tag topology DAG, time window           │
          │  5 Event story  — recorded chronological sequence (not causal proof) │
          │  6 Evidence engine — heuristic ranking (NOT a probability)           │
          │  7 SOP retrieval — curated manual section │ Qdrant vectors │ BM25    │
          │  8 Guidance     — verbatim SOP steps + calculated evidence           │
          └──────────────────────┬───────────────────────────────────────────────┘
                                 │  persisted per stage (SQLite) + SSE broadcast
          ┌──────────────────────▼───────────────────────────────────────────────┐
          │ FastAPI  /api/...                                                    │
          │  events, incidents, alarms/active, alarms/history, alarms/reference, │
          │  events/{id}/brief, assistant/ask(+stream), handover, scenarios,     │
          │  sops/*, datasource, copilot/ollama, diagnostics, integration/status │
          └───────────────┬──────────────────────────────┬───────────────────────┘
                          ▼                              ▼
              Operator HMI (5173)               Engineering console (5174)
              alarms · story · brief ·          Scenario Lab · Procedures (PDF
              Ask OpsLens · handover            ingest) · Alarm Reference · Metrics
```

## Components and status

| Component | File(s) | Status |
|---|---|---|
| Synthetic scenarios (10 primary + Scenario 7 UV/filters + legacy Pump-02/Compressor cases) | `generator.py`, `scenarios/` | Implemented. Timestamps end at "now" (never in the future). |
| Read-only OPC UA client | `adapters/opcua_adapter.py` | Implemented and unit-tested with mocked clients; started by `server.py` only when `PLC_OPCUA_ENABLED=true` and a mapping file exists. **Not tested against real lab hardware.** |
| MQTT / REST adapters | `adapters/mqtt_adapter.py`, `rest_adapter.py` | Classes exist; **not wired** into `server.py`. Planned. |
| Tag registry + topology DAG | `tag_registry.py`, `topology.py`, `knowledge_graph.py` | Implemented (demo configuration). |
| **Alarm configuration from the SOP PDF** | `config/alarm_reference.json`, `alarm_config.py` | **New.** 31 parameters, page-cited. Used for tag classification, SOP limit checks, P1/P2/P3 deadlines and the conflict report. |
| Alarm lifecycle | `alarm_lifecycle.py`, `dedup.py`, `database.py` | Implemented; **fixed** (see CHANGELOG). States exposed as ACTIVE_UNACK / ACTIVE_ACK / RTN_UNACK / NORMAL by `/api/alarms/active`. |
| Correlator, event story, evidence engine | `correlator.py`, `event_story.py`, `evidence_engine.py` | Implemented. |
| SOP retrieval | `sop_retriever.py`, `demo_sop_sections.py`, `vector_store/` | Three paths, always reported: `bundled_pdf_section` (curated page ranges of SOP-MAN-000 for the primary scenarios), `qdrant_vector_search` (needs sentence-transformers + Qdrant), `bm25` (always available). |
| PDF SOP ingestion | `pdf_sop_ingestion.py` | Implemented. Selectable-text extraction (no OCR). Uploaded SOPs are never auto-approved; "Draft" covers are detected. **New:** stores keyword-only when Qdrant/embeddings are missing. |
| Verbatim procedure steps | `sop_steps.py` | **New.** Returns the numbered steps of the SOP's "Procedure" section exactly as printed, with page numbers. |
| Guidance | `guidance_generator.py`, `fallback_template.py` | Deterministic by default (verbatim steps); optional LLM drafting via `OPSLENS_GUIDANCE_USE_LLM=true`, run in a worker thread with its own DB connection. |
| **Operator brief** | `operator_brief.py`, `/api/events/{id}/brief` | **New.** 8-part, LLM-free brief: observed alarm, hypotheses, OBSERVED vs CALCULATED evidence, missing evidence, verbatim steps, approval status, verification criteria, resolution. |
| Ask OpsLens assistant | `assistant.py`, `context_builder.py`, `llm_provider.py` | Implemented: record-grounded deterministic answer; optional LLM rephrase validated for numbers, units, timestamps and SOP text. |
| LLM providers | `llm_provider.py`, `edge_slm.py` | Ollama (default local), Groq, Gemini, OpenAI, Anthropic, none. **Fixed** timeouts; health and warm-up added. |
| Shift handover | `shift_handover.py`, `operational_history.py` | Implemented; shift window from `.env`. |
| Operator audit log | `operator_actions.py` | Implemented; allow-listed action types; never writes to a PLC. |

## Key design rules

1. **Alarms come from alarm inputs.** Only `ALM-*`, `*-FAULT` and `*-TRIP` tags create alarm records. `P101-RUN` (status) and analog measurements are correlation evidence. A status tag is evidence only when it leaves its configured normal state (`status_normal_states` in `alarm_reference.json`).
2. **Acknowledgement is not clearing.** Acknowledging records who/when; the alarm stays ACTIVE until the source input reads FALSE at a later timestamp. Resolving an incident additionally requires operator confirmation.
3. **Repeat count = re-annunciation.** Polled samples of an alarm that stays TRUE are not repeats. A repeat is counted when the input returned to normal and became active again, or the source explicitly re-sent it.
4. **Numbers are calculated in Python.** Margins to limits, deltas, deadlines and percentages are computed by the backend; LLM text containing a number that is not in the record (or attaches it to the wrong tag/unit) is rejected.
5. **No invented procedures.** Steps shown to the operator are copied from the SOP text with a page number, and labelled `DRAFT / REFERENCE ONLY — NOT APPROVED` unless the document is marked approved.
6. **Honest provenance.** Every reading carries `data_source`; the HMI shows SIMULATED for simulator data and never "PLC DISCONNECTED" for a simulation. `/api/health` reports the retrieval method actually available.
7. **Nothing optional is mandatory.** Ollama, Groq, Qdrant, sentence-transformers, Docker and the PLC can all be absent; the app starts and the operator brief still works.

## Database

SQLite file `edge_intelligence/opslens.db` (or `OPSLENS_DB_PATH`), WAL mode. Tables: `tag_readings`, `candidate_events`, `individual_alarms`, `alarm_occurrences`, `alarm_transitions`, `correlated_events`, `event_stories`, `evidence`, `sop_matches`, `guidance`, `operator_actions`, `assistant_messages`, `shift_handovers`, `handover_item_responses`.

**No schema changes were made in this update.** The connection handling changed: each thread now gets its own SQLite connection (the previous single shared connection was used concurrently by the event loop and the Ask OpsLens worker thread).

## Ports

| Port | Service |
|---|---|
| 8001 | FastAPI backend (`OPSLENS_PORT`) |
| 5173 | Operator HMI (Vite, proxies `/api` → 8001) |
| 5174 | Engineering console (Vite) |
| 11434 | Ollama (optional) |
| 6333 | Qdrant (optional) |
