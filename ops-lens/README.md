# OpsLens — AI-Powered Runtime Copilot for Industrial HMI
### Schneider Electric Innovation Marathon (Problem Statement 1: Smart Evidence-Backed Situational Intelligence)

**Team Name:** Sentient Screens  
**Members:** Aditya S, Daksh M, Nagavardhan N  
**Target Platform:** Schneider Electric EcoStruxure Operator Terminal Expert & Edge IPC  

---

## 1. Executive Summary

**OpsLens** is a context-first industrial AI copilot specifically optimized for **low-end HMI hardware platforms**. It is **NOT** a chatbot; it combines real-time alarm logs, continuous process telemetry, operator action history, runtime context, and Standard Operating Procedures (SOPs) into an actionable, evidence-backed situational intelligence feed.

### Core Value Drivers:
1. **Alarm Flood Prioritization**: Suppresses noise and correlates process excursions into one prioritized critical event.
2. **Chronological Event Story**: Reconstructs the exact causal timeline leading up to an alarm.
3. **Empirical Evidence & Verifiable Deltas**: Transparent mathematical percentages (-45%, -32%, +18%, +44%) that operators can trust.
4. **Instant SOP Retrieval**: Immediate 5-step response procedure matching without manual binder lookups.
5. **Human-in-the-Loop Safety**: AI advises only; operator approval is strictly required before any action is logged.
6. **Continuous Shift Handover**: Automatic operational memory generation, preserving tribal knowledge across shifts.

---

## 2. Architecture: Edge PC vs. Lightweight HMI Split

```
[ Industrial Field Sensors & Alarms ]
   (VLV-04, FIT-02, MOT-02, PIT-02)
                 │
                 ▼ (OPC UA / Modbus TCP / MQTT)
[ OpsLens Edge Intelligence Layer ]  ← Runs on Edge PC (Offloads compute)
   ├── Alarm Prioritizer
   ├── Context Correlator
   ├── Event Story Engine
   ├── Evidence Engine (-45%, -32%, +18%, +44%)
   └── SOP Knowledge Retrieval (Edge RAG Seam)
                 │
                 ▼ (REST / JSON API @ Port 8000)
[ Lightweight HMI Layer ]           ← EcoStruxure Operator Terminal Expert
   ├── React + Vite Single Page Application (@ Port 5173)
   ├── 5-Second Situational Awareness Layout
   └── Deterministic Client-Side Pacing Engine
                 │
                 ▼
[ Human Operator ] ────► [ Action Log / Shift Handover Dossier ]
```

---

## 3. How to Run (Quickstart)

### Prerequisites:
- Python 3.10+ or 3.11+
- Node.js LTS (v20+ / v24+)

### Step 1: Start the Backend (FastAPI)
Open a terminal in `C:\Users\adity\.gemini\antigravity\scratch\ops-lens`:
```powershell
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```
*The REST API will be active at `http://localhost:8000`.*
*Interactive OpenAPI Swagger docs available at `http://localhost:8000/docs`.*

### Step 2: Start the Frontend (React + Vite)
Open a second terminal in `C:\Users\adity\.gemini\antigravity\scratch\ops-lens\frontend`:
```powershell
npm run dev
```
*The HMI application will be active at `http://localhost:5173`.*

---

## 4. 3-Minute Demonstration Guide

1. **Baseline State**: Open `http://localhost:5173`. Notice Pump-02 running normally:
   - Valve-04: `78%`
   - Flow: `82 L/min`
   - Motor Current: `7.8 A`
   - Pressure: `4.8 bar` (Trip Limit: 6.0 bar)
   - Status: `● SYSTEM RUNNING NOMINAL`, 0 Active Alarms.

2. **Trigger Incident**: Click **`[ START INCIDENT ]`** in the sticky header:
   - Watch the deterministic cascade unfold over ~20 seconds:
     - `t+0s`: Valve-04 position drops to **43%** (**-45%**)
     - `t+4s`: Flow drops to **56 L/min** (**-32%**)
     - `t+6s`: Motor current surges to **9.2 A** (**+18%**)
     - `t+8s`: Pressure surges to **6.9 bar** (**+44%**)
     - `t+10s`: **HIGH PRESSURE ALARM** annunciates with critical pulse
     - `t+12s`: **Event Story** timeline and **Evidence Card** cascade in with verified percentages
     - `t+14s`: **SOP HP-P02** retrieved
     - `t+16s`: **Next-Best Actions** appear with 4 operator buttons.

3. **Explore SOP**: Click **`[ VIEW SOP ]`** to open the interactive 5-step High Pressure Response procedure with step verification checkmarks and safety notes.

4. **Human Decision**: Click **`[ VERIFY VALVE-04 ]`** or **`[ REVIEW PUMP-02 ]`**:
   - Immediate feedback: `✓ Operator action recorded`.
   - Action is logged via `POST /api/operator-action` with fixed operator `J. Rivera (Shift 2)`.

5. **Shift Handover**: Click **`[ MARK ACTION COMPLETE ]`** or **`[ Full Handover Ledger ]`**:
   - Inspect the compiled Shift Handover dossier ready for the incoming shift.

6. **Reset**: Click **`[ RESET DEMO ]`** to immediately return the machine to nominal state.

---

## 5. REST/JSON API Contract

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/machine` | Current Pump-02 state (normal or incident) |
| `GET` | `/api/alarms` | Active alarms prioritized with micro-explanation |
| `GET` | `/api/incident` | Current incident summary and context correlation |
| `GET` | `/api/event-story` | Chronological timeline of events (14:31 to 14:32) |
| `GET` | `/api/evidence` | Contributor + supporting evidence (-45%, -32%, +18%, +44%) |
| `GET` | `/api/sop` | Relevant SOP for current incident (HP-P02) |
| `POST` | `/api/operator-action` | Record operator acknowledgment/action (`operator: J. Rivera`) |
| `GET` | `/api/handover` | Shift handover summary |
| `POST` | `/api/demo/start` | Trigger deterministic incident; returns full precomputed payload |
| `POST` | `/api/demo/reset` | Return machine state to normal, clear alarms/actions/handover |

---

## 6. Integration Seams for Production

- **EcoStruxure Operator Terminal Expert**: The React SPA embeds directly into an OTE Web Control, consuming the Edge IPC's local REST API.
- **OPC UA / Modbus Gateway**: In production, `backend/api/routes.py` connects to an OPC UA client reading tags from Modicon M340/M580 PLCs.
- **Edge SLM / Vector RAG Seam**: `backend/intelligence/sop_retriever.py` and `evidence_engine.py` are architected as drop-in seams where a quantized local model (e.g., Phi-3-Mini 3.8B or Mistral 7B via Ollama / llama.cpp) and ChromaDB vector store can generate extended natural-language reasoning without external internet access.

---

## 7. Acceptance Criteria Verification

- [x] Backend starts successfully (`uvicorn backend.main:app`)
- [x] Frontend builds and starts successfully (`npm run dev` / `npm run build`)
- [x] Demo data loads; Pump-02 normal state displayed
- [x] `START INCIDENT` triggers the full deterministic sequence
- [x] Multiple correlated events generated in fixed order
- [x] Critical alarm prioritized and visually distinct
- [x] Event Story timeline renders correctly as centerpiece
- [x] Likely contributor + evidence displayed with correct percentages (-45%, -32%, +18%, +44%)
- [x] Correct SOP (HP-P02) retrieved via keyword match
- [x] Next-best action displayed with "Operator approval required"
- [x] All four operator buttons functional; action recorded via API
- [x] Shift handover reflects the recorded action, fixed operator name `J. Rivera (Shift 2)`
- [x] `RESET DEMO` returns everything to normal
- [x] No internet connection required for core demo
- [x] UI reads as industrial HMI, not a generic SaaS site
- [x] Architecture docs clearly show Edge PC vs lightweight-HMI split
