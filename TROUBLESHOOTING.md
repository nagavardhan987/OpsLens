# Troubleshooting

First stop for any problem: **http://127.0.0.1:8001/api/diagnostics** (database row counts, simulation state, retrieval method actually in use, LLM provider, PLC adapter, alarm reference). Then the specific endpoints below.

| Endpoint | Answers |
|---|---|
| `/api/health` | Is the backend up? Which SOP retrieval path is really available? |
| `/api/datasource` | SIMULATED / LIVE PLC / STALE / PLC DISCONNECTED / NO DATA, and why |
| `/api/copilot/ollama` | Is Ollama running, is `qwen2.5:3b` installed, what timeout is used |
| `/api/alarms/active` | Alarm inputs and their states |
| `/api/scenarios/status` | Simulation state, last error, current event |
| `/api/integration/status` | PLC/OPC UA adapter state |

---

## Startup

**`setup_windows.bat` says Python not found** — install Python 3.10+ from python.org with *Add python.exe to PATH*, open a new terminal, run setup again.

**pip fails on `torch` / `sentence-transformers`** — the setup script automatically falls back to `requirements-core.txt`. Everything works; SOP retrieval uses BM25 and the HMI/diagnostics say so. To enable vector search later: `edge_intelligence\.venv\Scripts\python -m pip install sentence-transformers` (needs internet once to download `all-MiniLM-L6-v2`).

**Backend window closes / `address already in use` on 8001** — another backend is running. Close the other window, or find it: `netstat -ano | findstr :8001` then `taskkill /PID <pid> /F`. To use another port set `OPSLENS_PORT` in `.env` **and** `VITE_API_BASE_URL=http://127.0.0.1:<port>/api` before `npm run dev` (and change the proxy target in `hmi_ui/vite.config.js` and `hmi_ui/workbench/vite.config.js`).

**Frontend shows a blank page / `vite` not found** — run `npm ci` in `hmi_ui` (or `setup_windows.bat`). Do not copy `node_modules` from another computer.

**Port 5173/5174 in use** — close old `npm run dev` windows; `5174` uses `--strictPort` and will refuse to start rather than move silently.

## Dashboard messages

**"Active alarms are temporarily unavailable" (intermittent, older versions)** — root cause found and fixed in v2: the backend shared one SQLite connection between the event loop and the Ask OpsLens worker thread, so concurrent requests interleaved transactions (`cannot commit - no transaction is active`, `bad parameter or other API misuse`). Each thread now has its own connection. If you still see it, the backend is not reachable: check the backend window and `/api/health`.

**Data source shows `DISCONNECTED` while a scenario runs (older versions)** — fixed. The status now comes from `/api/datasource`; a simulation always shows `SIMULATED`. `PLC DISCONNECTED` appears only when `PLC_OPCUA_ENABLED=true` and the session is down. `NO DATA` means nothing has been received yet.

**"null shift · null" in Shift Handover** — fixed; set `OPSLENS_SHIFT_NAME`, `OPSLENS_SHIFT_START`, `OPSLENS_SHIFT_END` in `.env` (24-hour `HH:MM`). Without them the card says *Shift timing not configured*.

**Repeat count ×400+** — fixed. Periodic samples of an alarm that stays TRUE no longer count as repeats. Press *Reset demo data* in the Scenario Lab to clear old counts.

**`P101-RUN` listed as an active alarm** — fixed. Status tags are evidence only. Old records created before the fix are filtered out of `/api/alarms/active`; *Reset demo data* removes them.

## Scenario Lab

**HTTP 409 "A synthetic scenario is already running"** — expected for a duplicate submission while a run is in progress; no second incident is created. The response includes `running_scenario_id` and `elapsed_seconds`. A run still marked running after `OPSLENS_SCENARIO_STALE_SECONDS` (default 600) is treated as stale and a new run is allowed. A 409 does not mean the pipeline failed — check `/api/scenarios/status` and `/api/alarms/active`.

**"Scenario accepted. Waiting for the event pipeline"** — normal for a few seconds at 10× speed. If it never completes, check `/api/scenarios/status` → `error`, and the backend window.

**Acknowledgement time looks earlier than the alarm (older versions)** — fixed: fast-forwarded scenarios are stamped so the last sample is "now", never in the future.

## AI / Ollama

**AI pill says `qwen2.5:3b · OFFLINE`** — Ollama is not running or the model is missing. Start it:
```bat
set OLLAMA_MODELS=E:\Ollamma\Models
E:\Ollamma\App\ollama.exe serve
E:\Ollamma\App\ollama.exe pull qwen2.5:3b
```
Check `/api/copilot/ollama`. OpsLens keeps working with deterministic answers meanwhile.

**Ollama answers time out after ~5 s (older versions)** — fixed. The old default timeout was 4 s for every provider, and a failed native call was retried on `/v1/chat/completions`, doubling the wait. Local providers now use `OPSLENS_OLLAMA_TIMEOUT` (default 60 s), a 2 s connect timeout, one attempt, and `keep_alive=30m`. The backend warms the model up at start-up; you can also `POST /api/copilot/ollama/warmup`.

**Answers are slow on the first question** — cold model load. Wait for "Ollama warm-up" in the backend window, or reduce `OPSLENS_OLLAMA_NUM_PREDICT`.

**The LLM answer was replaced by a deterministic one** — by design when the model output contains a number, unit, timestamp or SOP text that is not in the incident record (`fallback_reason` in the response). Numbers are always calculated by the backend.

**Groq** — set `OPSLENS_LLM_PROVIDER=groq` and `GROQ_API_KEY` in `.env` (never in the frontend). Without internet, use `ollama` or `none`.

**AI diagnosis panel says "DETERMINISTIC FALLBACK — not AI-generated"** — the line under it gives the reason: *Ollama is not running* (start `ollama serve`), *model not found* (`ollama pull qwen2.5:3b`), *timeout* (raise `OPSLENS_OLLAMA_TIMEOUT`), or *Qwen output rejected by the validator* (the model quoted a number, tag or SOP step that is not in this incident's record; the rejected text is kept in the API response as `rejected_ai_text`). Press ↻ on the panel to retry. The top-bar pill shows `qwen2.5:3b · verified` only after a real successful call.

**Diagnosis is slow** — the first call after start-up loads the model (watch for *Ollama warm-up* in the backend window). Smaller output: `OPSLENS_DIAG_NUM_PREDICT=400`. Smaller context: `OPSLENS_DIAG_NUM_CTX=3072`. Measure with `python tools/benchmark_ai.py live`.

## Scenario Lab

**"Another scenario is already running"** — wait for the run (progress bar) or press **Stop**.

**"… is still active in open incident …"** — the same scenario's alarm is still active. Press *Simulate the fix* (after-fix values) or *Reset demo data*, then start it again.

**"The same alarm re-annunciated while its earlier incident is still open"** — by design the recurrence joins the open incident (repeat count) instead of creating a duplicate. Close the earlier incident on the HMI to get a new one.

**Old scenarios (Pump-02, UV, filters) are gone** — only the six incident-map scenarios are offered. Legacy runs for old records: `OPSLENS_ENABLE_LEGACY_SCENARIOS=true`.

## SOP retrieval / Qdrant

**`Qdrant ... connection refused`** — Qdrant is optional. Without it, retrieval uses BM25 (reported in `/api/health` → `components.sop_retrieval`). To start it: install Docker Desktop, then from the project root `docker compose up -d qdrant`. Vector search also needs `sentence-transformers` and its model cached locally.

**Uploaded PDF says "Added for keyword (BM25) search · vector index unavailable"** — the PDF was stored and is searchable by keyword; re-ingest after starting Qdrant for vector search.

**"OCR required" / extraction failed** — the PDF has no selectable text (scanned). OCR is not implemented; use a text PDF or OCR it first.

**SOP-MAN-000 hidden for LiftStation-01 ("does not match LiftStation-01") (older versions)** — fixed: plant-wide manuals apply to every wastewater process area.

**Uploaded SOP shows "DRAFT / REFERENCE ONLY — NOT APPROVED"** — by design. Uploading never approves a document.

## Data

**Start from a clean database** — stop the backend and delete `edge_intelligence\opslens.db*` (back it up first if you need the history), or use *Reset demo data* in the Scenario Lab.

**Logs** — the backend logs to its console window. To keep a file: `start_backend.bat > backend.log 2>&1`.
