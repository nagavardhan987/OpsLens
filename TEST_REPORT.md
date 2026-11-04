# Test Report — OpsLens v2.1.0

**Date:** 4 November 2026 · **Environment:** Linux container, Python 3.13, Node.js 22, Chromium (Playwright).
**Not available here:** a real Ollama/Qwen model (downloads are blocked in this container and the laptop folder was not shared with this session), Docker/Qdrant, the lab PLC. Nothing below is claimed as tested that was not run.

## Summary

| Suite | Command | Result |
|---|---|---|
| Backend (`edge_intelligence/tests`) | `python -m pytest tests -q` | **362 passed**, 0 failed (+152 subtests) |
| Same, venv from `requirements-dev.txt` (no PyTorch) | same | **362 passed** |
| New `tests/test_six_incidents.py` | — | 18 passed: exact values (incident + after fix) for all six, normal-period values, tag→equipment ownership, LiftStation-01 vs Pump-02 isolation, SOP-SLD-001 text check, per-scenario SOP retrieval, timestamps strictly increasing, causal order, start/stop/409/details/trends, back-to-back runs (2 rounds) |
| New `tests/test_ai_diagnosis.py` (fake Ollama `/api/chat` over real HTTP) | — | 10 passed: prompt scope, streaming, payload (`keep_alive`, `num_ctx`), validation (foreign tag, invented numbers, invented SOP step, control claim, "approved SOP", missing sections), Ollama down / model missing / provider none → labelled fallback, cache, health `last_diagnosis_call`, SSE endpoint |
| Frontend unit tests (`hmi_ui`) | `npm test` | **29 passed** |
| HMI + console builds | `npm run build`, `npx vite build workbench` | **OK** |
| End-to-end, 1366×768 (`hmi_ui/e2e/hmi_1366.e2e.cjs`) | backend + both UIs running | **21/21 checks for each of the six scenarios**, with reset between runs and in **two back-to-back rounds without reset** (12 runs) |
| Legacy scripts outside `tests/` (`edge_intelligence/test_*.py`) | `pytest test_*.py` | 18 passed, 13 failed — unchanged from v2.0 baseline, not maintained |

### End-to-end checks (per scenario)
Console lists exactly six incidents and none of the removed ones · Start becomes Stop while running and is never re-enabled mid-run · run completes with this run's incident · no "could not be started" error · **no vertical or horizontal page scroll at 1366×768** · no overlapping panels · all panels inside the viewport · workflow bar fully visible and buttons not clipped · data marked SIMULATED · SOP shown as *DRAFT — NOT APPROVED* · diagnosis labelled AI or *DETERMINISTIC FALLBACK* (and "Not AI-generated" when fallback) · trend tiles show only the incident's own tags · all sidebar pages open · shift handover page renders · Acknowledge targets the banner alarm and does not clear the input · simulated fix reaches after-fix values and clears the alarm input · no uncaught page errors.

## AI response time — what was and was not measured

**Real Qwen latency was not measured**: no Ollama runtime is reachable from this container. To measure on the laptop (Ollama running, backend with `OPSLENS_LLM_PROVIDER=ollama`):

```
cd edge_intelligence
python tools/benchmark_ai.py live            # all six scenarios
```
It prints, per scenario, the **before** path (`/api/assistant/ask`, not streamed) and the **after** path (`/diagnosis/stream`: time to first token, total, cached repeat) and writes `benchmark_results.json`.

**Measured here** (`python tools/benchmark_ai.py capture`, requests recorded by a fake Ollama — sizes, not latency):

| Scenario | Before: prompt chars (`/api/generate`, not streamed, num_predict 320) | After: prompt chars (`/api/chat`, streamed, num_predict 650) |
|---|---|---|
| Rags jam the bar screen | 17,802 | 5,518 |
| Lift station pumps clog | 19,324 | 6,674 |
| Nocardia foam | 20,448 | 6,419 |
| RAS pump fails | 17,746 | 5,928 |
| CHP engine trips | 18,475 | 6,420 |
| Centrate poisons the inlet | 19,803 | 7,045 |

The prompt the model must read is ~3× smaller (prompt evaluation dominates CPU latency for a 3B model), the operator sees text as soon as the first token arrives, the HMI no longer fires an extra assistant question on every incident, and a repeat view is served from cache. The pipeline overhead was checked against a test server that streams slowly: first token reached the browser 1.8 s after the request with a 1.5 s artificial server delay, i.e. ~0.3 s OpsLens overhead.

---

# Previous: Test Report — OpsLens v2.0.0

**Date:** 3 November 2026 · **Environment:** Linux container, Python 3.13.18, Node.js 22.23.4, Chromium (Playwright) for UI checks.
**Not available in this environment:** Ollama, Docker, Qdrant server, sentence-transformers/PyTorch, the lab PLC/HMI. Results for those are marked below; nothing is claimed as tested that was not run.

## Summary

| Suite | Command | Result |
|---|---|---|
| Backend unit + integration (`edge_intelligence/tests`) | `python -m pytest tests -q` | **348 passed**, 0 failed (+64 subtests) — baseline before changes: 292 passed, 12 failed |
| Same suite in a **fresh venv from `requirements-core.txt`** (no PyTorch) | same | **348 passed** |
| New: `tests/test_alarm_reference_and_brief.py` | — | 37 passed |
| New: `tests/test_ollama_transport.py` (fake Ollama HTTP server) | — | 6 passed |
| Frontend unit tests (`hmi_ui`) | `npm test` | **31 passed** |
| Operator HMI production build | `npm run build` | **OK** |
| Engineering console build | `npx vite build workbench` | **OK** |
| Legacy acceptance scripts (`edge_intelligence/test_*.py`, outside `tests/`) | `pytest test_*.py` | 18 passed, 13 failed — **pre-existing**: 15 passed, 16 failed on the original code. Superseded by `tests/`; not part of the maintained suite |
| Clean-copy portability check | copy of the delivered file set → new venv → `server.py` → scenario → brief; `npm ci` + build | **OK** |

## Part 15 checklist

| # | Requirement | How it was tested | Result |
|---|---|---|---|
| 1 | Backend imports and startup | `server.py` started from a clean copy with `.env.example`; also with Ollama selected but absent | Pass. Startup logs *"Ollama not ready … Deterministic answers remain available"* |
| 2 | Frontend dependency/build | `npm ci`, `npm run build`, workbench build | Pass |
| 3 | API health | `/api/health`, `/api/diagnostics`, `/api/datasource`, `/api/copilot/ollama` | Pass; retrieval reported as `bm25_keyword_fallback (sentence-transformers not installed)` |
| 4 | Scenario execution | All 11 scenarios via `POST /api/scenarios/run` (10 primary + Scenario 7) | Pass: each → `awaiting_corrective_action`, 1 incident, repeat 1, no tracebacks |
| 5 | Event creation | Pipeline test + API; one incident per run | Pass |
| 6 | Alarm trigger conditions | `ALM-WW-101-HH` TRUE at level ≥ 3.6 m (p.14); limit checks at 3.8/3.9/1.7 m; low-direction RAS flow | Pass |
| 7 | Alarm acknowledgement | `POST /api/actions` ACKNOWLEDGE → `/api/alarms/active` = `ACTIVE_ACK`, input still TRUE | Pass (API + `AlarmStateTests`) |
| 8 | Return-to-normal | FALSE at a later timestamp → `RTN_UNACK` / `NORMAL`; valve-restriction simulated recovery → `alarm_clear_observed`, brief = *returned to normal — awaiting operator confirmation* | Pass |
| 9 | Alarm history | `/api/alarms/history`, `/api/alarms/active`, occurrences table; checked independently of the scenario response | Pass; only alarm inputs recorded |
| 10 | SOP PDF ingestion | SOP manual uploaded via `POST /api/sops/ingest-pdf` without Qdrant → `stored_keyword_only`, auto-detected *draft*, 45 chunks, source PDF served; invalid PDF → 422 | Pass. **Vector indexing not tested** (no Qdrant/embeddings) |
| 11 | SOP retrieval | Curated manual sections for 7 wastewater scenarios; BM25 discrimination tests; plant-wide manual visibility | Pass (BM25 + curated). Qdrant path: not tested here |
| 12 | Evidence Engine | Existing evidence tests + brief ranking label ("NOT a probability") | Pass |
| 13 | Guidance with deterministic provider | Verbatim SOP-LFT-001 steps 1–3 with pages; regenerated when SOP/evidence change | Pass |
| 14 | Provider-unavailable fallback | Ollama absent: assistant answers deterministically in **0.11 s**; `complete_chat` raises `ProviderError` (no invented text); fake slow Ollama times out after one attempt at the configured budget | Pass |
| 15 | Missing sensor data | `limit_context(None)` not applied; brief lists MISSING/STALE tags and un-instrumented SOP parameters | Pass |
| 16 | Incorrect or stale readings | STALE quality → limit not evaluated; 0 A on a tripped pump not treated as low-load; unit/tag-swapped LLM numbers rejected | Pass |
| 17 | Duplicate scenario submissions | Second POST → 409 with `running_scenario_id`; still exactly 1 incident | Pass |
| 18 | Shift handover | Existing handover tests; `/api/handover/current` with configured shift | Pass |
| 19 | Frontend/backend integration | Playwright: HMI shows *Active alarms 2*, *Data source SIMULATED*, *AI DETERMINISTIC*, Operator Brief with SOP limit table; console Scenario Lab (*Repeat ×1*) and Alarm Reference; 390 px width has no horizontal scroll | Pass |

## Concurrency reproduction (root cause of "temporarily unavailable")

One writer thread + three reader threads on the same `Database`:

| Code | Result (3 runs) |
|---|---|
| Original `database.py` | `InterfaceError('bad parameter or other API misuse')` in 3/3 runs; corrupted reads (`TagReading.tag = None`) in 2/3 |
| v2 per-thread connections | 0 errors |

## Dependency status

| Dependency | Status |
|---|---|
| Ollama + `qwen2.5:3b` | **Not tested locally** (not installed). Transport tested against a fake Ollama HTTP server (health, generate, stream, keep-alive, timeout, warm-up). **Requires verification on the original laptop.** |
| Groq | Not tested (no key; no outbound access). Existing mocked provider tests pass. |
| Qdrant + sentence-transformers | **Not tested** (not installed). BM25 fallback tested; existing mocked Qdrant validation tests pass. **Requires verification on the original laptop** (`docker compose up -d qdrant`). |
| Docker | Not available. Optional. |
| PLC / OPC UA (M241, HMIST6600) | Unit-tested with mocked OPC UA clients only. **Requires access to the actual lab equipment.** |
| Windows `.bat` scripts | Written for Windows `cmd` (CRLF); **not executed here** (Linux). Requires a first run on the laptop. |

## How to re-run on the laptop

```bat
run_tests.bat
```
or
```bat
cd edge_intelligence && .venv\Scripts\python -m pytest tests -q
cd ..\hmi_ui && npm test && npm run build
```
With Ollama running, also check `http://127.0.0.1:8001/api/copilot/ollama` → `"status_label": "AI: Ollama ready"`, then ask a question in Ask OpsLens and confirm `llm_used: true` in the response (or a `fallback_reason` explaining why the answer was replaced).
