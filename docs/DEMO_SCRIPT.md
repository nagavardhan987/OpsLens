# 3-minute demo script (interview / review)

**Setup (before the call):** run `start_all.bat`, open http://localhost:5173 (HMI, full screen at 1366×768 if you can) and http://localhost:5174 (console). Run `ollama serve` so the top-bar pill reads *qwen2.5:3b · ready*. In the console press *Reset demo data*. Optional: run one scenario beforehand so the model is warm.

**0:00 — The problem (20 s).** "An HMI tells an operator *that* an alarm is active. In an upset they get several at once and have to work out what happened first, what the procedure says and what to check. OpsLens answers that on one screen, on the edge PC, read-only."

**0:20 — Trigger (20 s).** Console → Scenario Lab → *2. The lift station pumps clog*. Show the incident-map table (normal / limit / during / after fix) and *SOP-LFT-001 · DRAFT — NOT APPROVED · coverage FULL*. Start. The button turns into **Stop** and the pipeline stages tick: telemetry → correlate/evidence/SOP → published.

**0:40 — The HMI (70 s).** Switch to 5173. Everything is on one screen, no scrolling:
- **What alarm** — banner: P1, *Wet well level high-high*, ALM-WW-101-HH, LiftStation-01, ACTIVE/UNACKNOWLEDGED, acknowledge within 2 minutes. Top bar: *SIMULATED DATA* — never shown as a live PLC.
- **What changed** — Event Story: P-102 flow falls first, then P-101 trips on winding temperature, level rises, H then HH. Trend tiles show the normal band and the SOP limit line.
- **Evidence** — readings vs SOP limits with page numbers: flow 90 m³/h below 300 (*suspect clog*), winding 118 °C above the 105 °C trip, level 3.85 m = P1 escalation.
- **Possible cause** — AI diagnosis streams in from Qwen: CONFIRMED / HYPOTHESIS / UNKNOWN, evidence for and against, what is missing. "Qwen explains; the facts come from the Evidence Engine, and every number, tag and step it writes is checked against the record."
- **What to check** — verbatim draft-SOP steps with page numbers, and the gap: *the SOP sets no limit for inflow*.

**1:50 — The honest gap (25 s).** Console → *6. Centrate poisons the plant inlet* → Start → HMI. SOP panel: *COVERAGE: PARTIAL* — "SOP-SLD-001 treats centrate as an ammonia load; it says nothing about toxic or inhibitory centrate. OpsLens says so instead of inventing a procedure; the AI is told the gap."

**2:15 — Workflow (25 s).** Press *Acknowledge ALM-WW-101-HH* — "acknowledging is not clearing; the input is still active." Console → *Simulate the fix*: values go to the after-fix column and the alarm input clears. Sidebar → *Shift Handover* shows the open incident to hand over.

**2:40 — Close (20 s).** "Read-only: no PLC writes, no pump or valve control, no automatic acknowledgement. If Ollama is down the panel says *DETERMINISTIC FALLBACK — not AI-generated*. 362 backend tests, end-to-end checks at 1366×768 for all six incidents."

**Likely questions:** *Why not let the LLM decide?* — numbers and procedures must be traceable; the model only explains, and an answer that introduces a number, tag or SOP step not in the record is rejected. *How fast is it?* — show `tools/benchmark_ai.py live` results from your laptop (time to first token and total). *How would it connect to a real plant?* — PLC_OPCUA_SETUP.md: read-only OPC UA account, browse, map NodeIds; LIVE PLC data is labelled separately from SIMULATED.
