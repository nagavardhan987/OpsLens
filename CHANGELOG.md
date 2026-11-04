# Changelog

## v2.1.0 — 2026-11-04 — Six incident-map scenarios, Qwen diagnosis, 1366×768 HMI

### Scenario Lab: only the six incidents from the plant incident map
- New single source of truth `edge_intelligence/incident_catalog.py`: the six incidents with the exact normal / limit / during-incident / after-fix values from *"Wastewater plant: six incidents on one map"*. Tags, equipment owner, units, alarm inputs, trips and SOP mapping are all defined there; the tag registry, alarm reference, simulator, trend endpoint and frontend tag map are derived from it (`tools/gen_frontend_tags.py`, checked by a test).
- Removed the previous incidents (Pump-02 valve restriction, filters/UV disinfection, low DO/ammonia, filter sensor fault, monitoring due). Legacy Pump-02/Compressor/Tank scenarios stay in code for old records only; `/api/scenarios/run` refuses them unless `OPSLENS_ENABLE_LEGACY_SCENARIOS=true`.
- SOP mapping (SOP-MAN-000 Rev 0, **Draft for review — NOT APPROVED**): 1 SOP-INL-001 · 2 SOP-LFT-001 · 3 SOP-BIO-001 · 4 SOP-BIO-002 · 5 SOP-GAS-001 · 6 SOP-SLD-001.
- Coverage inspected against the SOP text. Five are full coverage with named gaps; **SOP-SLD-001 is partial**: it treats centrate as an ammonia *load* only and has no inhibitory/toxic-centrate, nitrification-inhibition or toxicity-test content (the words "toxic", "inhibit", "nitrification" do not appear; a test checks this against the SOP text). Gaps are shown in the console, the HMI SOP panel and the AI facts.
- "After fix" for every scenario (`POST /api/scenarios/corrective-action` ramps to the incident map's after-fix values); `POST /api/scenarios/stop`; `GET /api/scenarios/{id}/details`; run status now has `progress`, `stage` and sample counts.

### AI: Qwen via Ollama is the explanation layer, the Evidence Engine is the factual source
- New `ai_diagnosis.py`: compact incident-scoped facts (this incident's tags only, readings vs SOP limits, event sequence, ranking score labelled *not a probability*, draft SOP steps and coverage gaps) → Ollama `/api/chat` streaming with `keep_alive`, `num_ctx 4096`, `num_predict 650`, `temperature 0.2` → seven sections (summary, confirmed observations, possible causes, evidence for/against, missing information, safe checks, engineering assessment).
- Every output is validated: headings present, tags must belong to this incident, numbers must exist in the facts, cited SOP steps must exist, no claims of operating equipment or of an *approved* SOP. Failing output is replaced by the deterministic diagnosis and the reason is shown.
- Fallback is labelled **"DETERMINISTIC FALLBACK — not AI-generated"** everywhere and is never presented as model output. `/api/copilot/ollama` and `/api/copilot/health` report `last_diagnosis_call` (attempted / succeeded / error / latency); `verified` is set only after a successful model call.
- Speed: one model call per incident instead of a call per question on load; prompt about 3× smaller; streaming to the HMI (time to first token shown); result cache keyed on incident + facts hash + model; warm-up at start-up (existing). `tools/benchmark_ai.py live` measures real latency on the laptop.

### Operator HMI redesigned for a 1366×768 panel
- Fixed-height layout, no page scroll: top status bar (alarm counts, SIMULATED/LIVE source, AI state, handover, clock) · alarm banner (severity, alarm, equipment, state, first time, acknowledgement deadline) · three columns: alarm groups + readings/trends with sparklines and limit lines · Event Story + readings-vs-SOP-limits table · streaming AI diagnosis + SOP panel (draft badge, coverage, gaps, verbatim steps) · operator workflow bar.
- Detail views in the sidebar: Event Story, Evidence Engine, Operator Brief, AI Diagnosis, Plant Overview (monitoring view, not an incident), Incident History, Shift Handover, SOP Library.
- Acknowledge targets the alarm shown in the banner first (then the remaining inputs) and never clears the alarm.

### Bugs found and fixed in this round
| # | Symptom | Root cause | Fix | Test |
|---|---|---|---|---|
| 20 | Console showed *"Scenario could not be started. Try again."* | The console set "not running" whenever any open incident existed, so **Start** was re-enabled mid-run; the second POST got 409 and the generic message hid it | Run state comes only from `/api/scenarios/status`; Start becomes **Stop** while running; backend reason shown | e2e `hmi_1366.e2e.cjs` |
| 21 | Console ran a different scenario than the one selected | A late `/api/scenarios` response reset the selection to the first item | Keep a valid selection | e2e |
| 22 | Run status reported an older incident as this run's result | Status fell back to "latest open incident" | Only incidents created (or repeated) by this run | `test_six_incidents` |
| 23 | Back-to-back runs merged incidents: RAS-P1 alarms were added to the open foam incident | 90 s clustering window + shared downstream tags (AER-201-MLSS, EFF-301-TSS) | Run boundary seals clusters of other scenarios (`dedup.seal_clusters`) | `BackToBackRunsTests` (fails without the fix) |
| 24 | A recurrence after the old cluster expired created an incident with **no** primary alarm row and re-activated the old incident's alarm | Alarm fingerprint record and cluster disagreed on the owning incident | A recurrence joining a different incident gets a fresh alarm record | `BackToBackRunsTests` round 2 (fails without the fix) |
| 25 | After a previous fix, the next run's alarm looked already cleared | Simulated fix readings were stamped later than the next back-dated run | Simulated time is monotonic across runs and fixes | `BackToBackRunsTests` |
| 26 | Re-running a scenario whose alarm was still active silently produced "no incident" | Nothing new can annunciate | 409 with *"… still active in open incident …; run the simulated fix first"*; a repeat into an open incident is reported as `incident_repeated` | `ScenarioStartStopApiTests` |
| 27 | Generic words ("pump", "motor current", "discharge pressure") on a lift-station question could flag it as Pump-02 | Over-broad equipment keywords | Specific terms per equipment, catalog-derived tags | `test_generic_pump_words_on_lift_station_do_not_point_at_pump02` |
| 28 | Diagnosis restarted mid-stream when the brief loaded (two model calls per incident) | Refresh key included a field that arrives later | Key on incident status only | e2e against a test server |

## v2.0.0 — 2026-11-03 — Stabilisation, SOP-manual alarm configuration, operator brief

Baseline: `nagavardhan987/opslens` @ `aa92b09` ("Update OpsLens incident workflows, scenarios, and assistant"). The original folder is preserved; this update edits files in place and adds new ones. Active code: `edge_intelligence/` (backend) and `hmi_ui/` (frontends). `ops-lens/` and `opslens-generator/` were not changed.

### Bugs discovered and fixed (each verified by running the code)

| # | Symptom | Root cause | Fix | Test |
|---|---|---|---|---|
| 1 | Dashboard intermittently showed *"Active alarms temporarily unavailable"* (known issue 1) | One SQLite connection (`check_same_thread=False`) was shared by the event loop and the Ask OpsLens worker thread; concurrent use interleaved transactions. Reproduced on the original code: `InterfaceError: bad parameter or other API misuse`, corrupted reads (`tag=None`), and `cannot commit - no transaction is active` | Per-thread SQLite connections (`database.py`), WAL unchanged | `DatabaseThreadSafetyTests` |
| 2 | `P101-RUN` (pump running) recorded as an ACTIVE alarm; every analog excursion (level, flow, current, pressure) also stored as an "alarm" — 12 alarm rows for one wet-well incident (known issue 8) | `dedup.py` saved every breaching tag as an individual alarm; `prioritizer.py` treated **any** boolean TRUE as a trip alarm, so a *running* pump was a breach and a *stopped* pump was not | New `alarm_config.classify_tag`: only `ALM-*`, `*-FAULT`, `*-TRIP` are alarms. Status tags are evidence only when they leave their configured normal state. Wet-well incident now has exactly `ALM-WW-101-HH` + `P101-FAULT` | `TagClassificationTests`, `AlarmRepeatAndLifecycleTests`, pipeline test |
| 3 | Repeat count ×52 after one scenario, ×416 in the field | Every 2 s sample of an alarm that stayed TRUE incremented `repeat_count` and wrote an occurrence row | Repeat = re-activation after return-to-normal, or explicit re-annunciation (`alarm_state="REANNUNCIATED"`, used by *Trigger same alarm again*). Polled sources (simulator/OPC UA) no longer inflate. Out-of-order FALSE samples are ignored | repeat tests; all 11 scenarios now show repeat 1 |
| 4 | Data source showed **DISCONNECTED** during simulation (known issue 2) | HMI fell back to `DISCONNECTED` when no event-specific source was known | New `GET /api/datasource` (SIMULATED / LIVE PLC / STALE / PLC DISCONNECTED / NO DATA); HMI uses it | `DataSourceLabelTests` |
| 5 | SOP-MAN-000 match hidden: *"All wastewater process areas does not match LiftStation-01"* (known issue 7) | Equipment check compared strings literally; plant-wide check covered only 4 area prefixes | Plant-wide manuals apply to all wastewater areas (RAS, clarifier, biogas, centrifuge, monitoring, filters added) | `PlantWideSopVisibilityTests` |
| 6 | Ollama inference timed out after ~5–6 s (known issue 5) | Global 4 s timeout for every provider; on timeout `call_local_edge_slm` retried `/v1/chat/completions` with the same timeout (≈2×); guidance used a hard 3 s timeout; no keep-alive | Provider-aware timeout (`OPSLENS_OLLAMA_TIMEOUT`, default 60 s; cloud 8 s), 2 s connect timeout, single attempt, `keep_alive=30m`, background warm-up at start-up, `/api/copilot/ollama` health | `tests/test_ollama_transport.py` (fake Ollama server) |
| 7 | Guidance "Next best actions" were raw page text (Purpose/Scope/PPE table) and the explanation said *"Supporting deviations are unavailable"* although 4 deviations existed; cited SOP-MAN-000 while the incident matched SOP-LFT-001 | (a) `is_sop_available` rejected `bundled_pdf_section` matches; (b) guidance cached per event on the first, smaller cluster and never refreshed | Verbatim numbered procedure steps with page numbers (`sop_steps.py`); cache keyed on contributor/deltas/SOP; stale DB cache regenerated | `test_guidance_uses_verbatim_lift_station_steps`, `SopStepTests` |
| 8 | BM25 fallback crashed with `ValidationError: SopMatch.revision` | JSON SOP chunks carry `revision=None` | Coerce to string | `tests/test_retrieval_engine.py` (previously failing) |
| 9 | Event story builder crashed: `UnboundLocalError: primary_desc` | Missing branch for an analog primary signal with a recorded value (masked before because `P101-RUN` was always primary) | Branch added | scenario runs, pipeline test |
| 10 | Orchestrator wrote an older cluster snapshot over a newer one (incident collapsed to 1 tag under burst input) | Worker scheduled with a stale `CandidateEvent` saved it back | Worker reloads the persisted candidate if it is a superset | `OperatorBriefPipelineTests` |
| 11 | Acknowledgement timestamp could be earlier than the alarm | Fast-forwarded scenarios stamped samples up to 80 s in the future | Scenario timeline ends at "now" | `ScenarioApiTests` |
| 12 | Duplicate scenario submission returned a bare 409 string | — (409 itself is correct; known issue 4) | 409 detail now includes `running_scenario_id`, `status`, `elapsed_seconds`; stale "running" state auto-expires after `OPSLENS_SCENARIO_STALE_SECONDS` | `ScenarioApiTests` |
| 13 | `/api/health` always claimed `qdrant_vector_search` | Hard-coded string | Reports the method actually available | manual API check |
| 14 | Qdrant `connection refused` printed full stack traces (known issue 6) | `logger.exception` | One-line warning with the start command | server log check |
| 15 | PDF ingestion failed outright without Qdrant/embeddings | Hard dependency | Stores PDF + metadata for BM25 keyword retrieval; status `stored_keyword_only`; strict mode via `OPSLENS_PDF_BM25_FALLBACK=false` | `KeywordOnlyPdfIngestionTests`, ingestion safety tests |
| 16 | Shift handover card showed **"null shift · null"** | Unconfigured shift rendered literally | Shows *Shift timing not configured*; `.env.example` sets a demo shift | build + screenshot |
| 17 | `SOP-GEN-002` lost steps 8–9 | Page range stopped at page 7 | Pages 6–8 | `SopStepTests` |
| 18 | LLM answer *"FIT-02-FLW fell by 1.8 A"* (units swapped between tags) was accepted | Unit-matched tag overrode the tag the sentence attributed the number to | Reject unit/tag mismatch | `test_compound_open_ended_trend_answer_scopes_values_to_nearest_tag` (previously failing) |
| 19 | Wet-well scenario defaulted the level to 47.5 m before the ramp | Typo-level default | 1.7 m (registry midpoint) | scenario tests |

Stale tests updated to the current, intentional behaviour (no production logic weakened): event-story label prefix, 90-tag registry in the stream test, constant-value tags in the noise test, workflow-route stub, curated SOP-INL-001 mapping, provider-aware timeout test.

### Added

- `edge_intelligence/config/alarm_reference.json` — 31 parameters from **SOP-MAN-000** with page numbers, P1/P2/P3 convention (p.4), SOP-GEN-003 alarm-response rules, verification criteria, restrictions, `NOT SPECIFIED` where the manual is silent, and mapping to OpsLens tags.
- `alarm_config.py` — tag classification, SOP limit check (margins in Python), conditional/unconditional P1, conflict report.
- `operator_brief.py` + `GET /api/events/{id}/brief` — deterministic 8-part brief.
- `sop_steps.py` — verbatim procedure steps with page numbers for all 12 SOPs.
- API: `/api/alarms/reference`, `/api/alarms/conflicts`, `/api/alarms/limit-check`, `/api/alarms/active`, `/api/datasource`, `/api/copilot/ollama`, `POST /api/copilot/ollama/warmup`, `/api/diagnostics`.
- HMI: **Operator Brief** panel, AI status pill, data-source fix. Console: **Alarm Reference** page.
- `tools/opcua_browse.py` for PLC node discovery.
- Windows: `setup_windows.bat`, `start_all.bat`, `start_backend.bat`, `start_frontend.bat`, `run_tests.bat` (`START_DEMO.bat` now calls `start_all.bat`).
- `requirements-core.txt` (no PyTorch), `requirements-dev.txt`; `hmi_ui/package-lock.json` committed.
- Docs: README, ARCHITECTURE, ALARM_CONFIGURATION, PLC_OPCUA_SETUP, TROUBLESHOOTING, TEST_REPORT. Previous README kept in `docs/previous/`.
- Tests: `tests/test_alarm_reference_and_brief.py` (37), `tests/test_ollama_transport.py` (6).

### Changed configuration defaults

| Setting | Before | After |
|---|---|---|
| Local LLM timeout | 4 s (shared) | `OPSLENS_OLLAMA_TIMEOUT` 60 s |
| Cloud LLM timeout | 4 s | `OPSLENS_LLM_TIMEOUT` 8 s |
| Default Ollama model | `qwen2.5:0.5b` | `qwen2.5:3b` |
| Pipeline guidance | LLM attempted when an SOP matched | Deterministic verbatim steps; LLM drafting opt-in (`OPSLENS_GUIDANCE_USE_LLM=true`) |
| Assistant single-flight wait | 30 s | max(30 s, provider timeout + 15 s) |
| PDF ingestion without Qdrant | error | stored for BM25 (`OPSLENS_PDF_BM25_FALLBACK`) |

### Database schema changes and migration

- **No table or column changes.** Existing `opslens.db` files open unchanged.
- Recommended once: stop the backend and delete `edge_intelligence\opslens.db*` (or *Reset demo data*) so old rows created under the previous alarm/repeat logic (e.g. `P101-RUN` alarms, inflated repeat counts) do not appear in history. `/api/alarms/active` already hides legacy status/measurement rows.
- Optional `OPSLENS_DB_PATH` moves the database.

### Incomplete / not implemented (honest list)

- Live PLC connection — adapter implemented and unit-tested with mocks; **not verified against lab hardware** (needs endpoint, Symbol Configuration, mapping, registry entries for the lab motor tags).
- MQTT and REST adapters — classes exist, not started by `server.py`.
- OCR for scanned PDFs — not implemented (rejected with a clear message).
- The manual gives no alarm deadbands, on/off delays or reset conditions; OpsLens therefore implements return-to-normal on the source input only.
- 40 registry-vs-manual conflicts are reported but **not resolved** (needs a site decision); most important: `PIT-101-DIS` direction.
- `ops-lens/` and `opslens-generator/` are earlier iterations; their tests are not maintained.
- Legacy acceptance scripts at `edge_intelligence/test_*.py` (outside `tests/`) were already failing before this update (16 of 31); now 13 of 31. They predate the current scenario catalogue and are superseded by `tests/`.

### Assumptions

- The SOP manual PDF supplied is the same file as the repository's `SOP-MAN-000` (verified byte-identical).
- `PIT-101-DIS` is treated as *assumed* to be the per-pump discharge pressure for the SOP limit check (labelled in the UI).
- Normal states of status tags (`P101-RUN` normally running, flare normally off, …) are OpsLens demo configuration, not from the PDF.
- Simulated scenario data represents the last *N* seconds compressed, ending at the current time.
