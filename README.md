# OpsLens — Runtime Copilot for Industrial Operators

> **Team:** Sentient Screens | **Event:** Schneider Electric Innovation Marathon MVP

OpsLens is an **edge-deployable AI copilot for industrial operators** (HMI/SCADA/DCS). It watches real-time sensor data from equipment like pumps, valves, and compressors — and when an anomaly is detected, it automatically reconstructs a causal event story, identifies the root cause, retrieves the relevant SOP, and guides operators with next-best actions.

**Runs on low-power edge PCs. Zero mandatory cloud dependency.**

---

## Architecture

```
┌──────────────────────────────────────────┐
│        Frontend — React + Vite           │
│  (1920×1080 HMI Dashboard, port 5173)   │
└──────────────────┬───────────────────────┘
                   │ REST + SSE
┌──────────────────▼───────────────────────┐
│        Backend — FastAPI + SQLite        │
│              (port 8000)                 │
│                                          │
│  Orchestrator → Correlator → Evidence   │
│  RAG Retrieval (SentenceTransformers)   │
│  Guidance Engine (LLM Fallback Chain)   │
│  Shift Handover · Operator Audit Log    │
└──────────────────────────────────────────┘
```

### LLM Fallback Chain (offline-first)
```
1. Local SOP + deterministic inference
2. Cloud LLM (Gemini/GPT) — online only
3. Ollama SLM (Mistral 7B) — offline
4. Deterministic template — always works
```

---

## Project Structure

```
opslens/
├── opslens-generator/        # FastAPI backend
│   ├── server.py             # Entry point (port 8000)
│   ├── orchestrator.py       # Pipeline manager
│   ├── correlator.py         # Topology-aware root cause correlation
│   ├── evidence_engine.py    # Confidence scoring & attribution
│   ├── retrieval_engine.py   # RAG: semantic + BM25 SOP lookup
│   ├── guidance_engine.py    # LLM fallback chain
│   ├── shift_handover.py     # Shift ledger compilation
│   ├── operator_actions.py   # Audit log (safety allowlist)
│   ├── generator.py          # Synthetic telemetry generator
│   ├── tag_registry.py       # 11-tag topology DAG
│   ├── scenarios/            # 7 incident archetypes
│   │   ├── valve_restriction.py
│   │   ├── bearing_wear.py
│   │   ├── seal_leak.py
│   │   ├── sensor_fault.py
│   │   ├── tank_overflow.py       # No SOP match → fallback path
│   │   ├── compressor_overspeed.py
│   │   └── pump_cavitation.py
│   ├── sop_documents/        # SOP JSON library
│   ├── api/
│   │   └── routes.py
│   └── tests/
│
└── ops-lens/
    └── frontend/             # React + Vite HMI
        ├── src/
        │   ├── App.jsx       # Root: all state management
        │   ├── api/client.js # All REST + SSE calls
        │   └── components/
        │       ├── Header.jsx             # Logo, alarm popover, controls
        │       ├── AlarmPrioritization.jsx
        │       ├── ProcessValues.jsx      # 4-tile sensor grid
        │       ├── EventStory.jsx         # Causal chain timeline
        │       ├── EvidenceSection.jsx    # Root cause + deltas
        │       ├── RelevantSop.jsx
        │       ├── NextBestAction.jsx     # 3 steps + 4 action buttons
        │       ├── ShiftHandoverCard.jsx
        │       ├── HandoverModal.jsx
        │       └── SopModal.jsx
        ├── public/
        │   └── opslens-logo.png
        └── tailwind.config.js
```

---

## Scenarios (7 total)

| ID | Name | Equipment | Key Signature |
|----|------|-----------|--------------|
| `valve_restriction` | Pump-02 Valve Restriction | Pump-02 | VLV closes → flow↓ → pressure↑ → alarm |
| `bearing_wear` | Compressor Bearing Wear | Compressor-01 | Gradual vibration rise |
| `seal_leak` | Pump-02 Mechanical Seal Leak | Pump-02 | Flow↓ + Pressure↓ together, valve open |
| `sensor_fault` | Sensor Fault / False Positive | Pump-02 | Single tag spike, no correlation |
| `tank_overflow` | Tank-01 High Level | Tank-01 | No SOP match → fallback guidance |
| `compressor_overspeed` | Compressor-01 Overspeed | Compressor-01 | Speed→Vibration→Current→Temp→Alarm |
| `pump_cavitation` | Pump-02 Cavitation | Pump-02 | Flow↓ with valve fully open |

---

## Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+

### Backend

```bash
cd opslens-generator
pip install -r requirements.txt
python server.py
# FastAPI running at http://localhost:8000
```

### Frontend

```bash
cd ops-lens/frontend
npm install
npm run dev
# Vite dev server at http://localhost:5173
```

### Run Tests

```bash
cd opslens-generator
python -m unittest discover tests -v
# 49/49 tests pass
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, SQLite, asyncio |
| ML/RAG | sentence-transformers (all-MiniLM-L6-v2), BM25 |
| Frontend | React 18, Vite, Tailwind CSS, Lucide Icons |
| LLM | Gemini API / Ollama (offline SLM) / deterministic fallback |
| Deployment | Edge PC, single SQLite DB, no cloud required |

---

## License

MIT
