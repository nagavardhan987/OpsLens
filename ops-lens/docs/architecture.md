# OpsLens — System Architecture & Integration Guide
### AI-Powered Runtime Copilot for Industrial HMI (Schneider Electric Innovation Marathon)

---

## 1. Executive Architecture Overview

OpsLens is designed to solve **Problem Statement 1 (PS1)**: equipping industrial operators with context-first situational intelligence directly in their runtime HMI workflow, while strictly accommodating **low-end HMI hardware platforms** (e.g., Schneider Electric EcoStruxure Operator Terminal Expert).

To ensure high performance without burdening resource-constrained HMI terminals, OpsLens enforces an **Edge PC vs. Lightweight HMI Split**:

```
+-----------------------------------------------------------------------------------------+
|                               INDUSTRIAL PLANT LEVEL                                    |
|   Sensors (PIT-02, FIT-02, MOT-02) • Actuators (VLV-04) • Alarm Annunciator System     |
+-----------------------------------------------------------------------------------------+
                                             │
                        (OPC UA / Modbus TCP / MQTT Fieldbus)
                                             ▼
+-----------------------------------------------------------------------------------------+
|                  OPSLENS EDGE INTELLIGENCE LAYER (Edge Industrial PC)                   |
|                                                                                         |
|   ┌───────────────────────────┐      ┌───────────────────────────┐                      |
|   │    Alarm Prioritizer      │      │     Context Correlator    │                      |
|   │ (Severity·Recency·Dev)    │      │  (Multi-Variable Physics) │                      |
|   └─────────────┬─────────────┘      └─────────────┬─────────────┘                      |
|                 │                                  │                                    |
|                 ▼                                  ▼                                    |
|   ┌───────────────────────────┐      ┌───────────────────────────┐                      |
|   │     Event Story Engine    │      │      Evidence Engine      │                      |
|   │ (Chronological Narrative) │      │ (-45%, -32%, +18%, +44%)  │                      |
|   └─────────────┬─────────────┘      └─────────────┬─────────────┘                      |
|                 │                                  │                                    |
|                 ▼                                  ▼                                    |
|   ┌───────────────────────────┐      ┌───────────────────────────┐                      |
|   │   SOP Knowledge Retrieval │      │ Operator Action & Handover│                      |
|   │  (Keyword Seam for RAG)   │      │ (Certified J. Rivera Log) │                      |
|   └───────────────────────────┘      └───────────────────────────┘                      |
|                                                                                         |
|   [ REST/JSON Fast API Service — Python 3.10+ / FastAPI @ Port 8000 ]                   |
+-----------------------------------------------------------------------------------------+
                                             │
                                    (REST / JSON API)
                                             ▼
+-----------------------------------------------------------------------------------------+
|                LIGHTWEIGHT HMI LAYER (EcoStruxure Operator Terminal Expert)              |
|                                                                                         |
|   - Stand-in Web Application (React + Vite + Tailwind CSS @ Port 5173)                   |
|   - Zero heavy AI compute on the HMI terminal (pure view rendering)                     |
|   - 5-Second Situational Awareness Layout:                                              |
|       • Sticky Status Header & Machine Envelopes                                        |
|       • High-Contrast Telemetry Readouts (Valve, Flow, Current, Pressure)               |
|       • Chronological Event Story Visual Pipeline                                       |
|       • Evidence-Backed Contributor Assessment                                          |
|       • Relevant SOP Modal (HP-P02 5-Step Procedure)                                    |
|       • Next-Best Action Guidance & 4 Operator Buttons                                  |
|       • Automated Continuous Shift Handover Dossier                                     |
+-----------------------------------------------------------------------------------------+
                                             │
                                  (Human Operator Decides)
                                             ▼
+-----------------------------------------------------------------------------------------+
|                  HUMAN OPERATOR IN THE LOOP (No Direct AI PLC Control)                  |
|     - AI recommends only. The human operator reviews, verifies, and executes actions.   |
|     - Every acknowledgment writes back to the audit ledger and shift handover card.     |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Low-End HMI Hardware Optimization Strategy

A critical real-world constraint in process automation (pharmaceutical, water/wastewater, food & beverage) is that installed HMI panels have limited CPU and RAM (ARM cortex or low-power x86, often 1–2 GB RAM).

OpsLens solves this through three strict design tenets:
1. **Zero Client-Side Machine Learning**: All anomaly correlation, timeline reconstruction, and evidence indexing execute on the Edge IPC (such as a Schneider Electric Magelis / Harmony iPC).
2. **Stateless Frontend Polling/Pacing**: On incident trigger (`POST /api/demo/start`), the backend computes the entire incident envelope and returns it in a single HTTP payload. The lightweight HMI manages the reveal cadence client-side, eliminating continuous network jitter and websocket reconnect overhead.
3. **No Canvas/WebGL Overhead**: The UI uses crisp, hardware-accelerated CSS and semantic DOM, ensuring rapid 60 FPS touch rendering even on low-spec resistive touch displays.

---

## 3. SE EcoStruxure Operator Terminal Expert Integration Seam

In production, OpsLens integrates into Schneider Electric EcoStruxure OTE via standard interfaces:
- **HTTP/REST Web Component or Embedded Web Control**: EcoStruxure OTE supports embedded Web Control elements capable of hosting the lightweight React application or rendering REST-driven screen scripts.
- **OPC UA Server on Edge IPC**: The Edge PC can act as an OPC UA server/client, reading PLC registers for `VLV-04-POS`, `FIT-02-FLW`, `MOT-02-CUR`, and `PIT-02-PRS` from Modicon M340/M580 PLCs.
- **Action Audit Handshake**: When an operator presses `[ VERIFY VALVE-04 ]`, OpsLens sends an authorized REST payload to the backend logger and can optionally pulse a dedicated internal bit in the PLC (via OPC UA) marking operator acknowledgment.

---

## 4. Edge SLM & Vector RAG Extensibility Seams

While this MVP operates **100% offline and deterministic** without cloud API dependency, the software architecture features explicit extension points for production Edge AI:

### A. SOP Retriever (`backend/intelligence/sop_retriever.py`)
- **Current MVP**: Keyword overlap matching with tagged SOP records (`["high pressure", "pump", "valve", "restriction"]`).
- **Production Seam**: Replace the `.retrieve()` method with an in-process vector search (e.g. ChromaDB / FAISS running locally on the Edge IPC with a quantized sentence-transformer embedding model like `bge-micro-v2`).

### B. Natural Language Explanation Seam (`backend/intelligence/evidence_engine.py`)
- **Current MVP**: Deterministic rule-based template generating certified explanation: *"Likely contributor based on correlated evidence."*
- **Production Seam**: Plug in a local quantized Small Language Model (SLM) such as **Phi-3-Mini (3.8B Q4_K_M)** or **Mistral-7B-Instruct (Q4)** hosted on the Edge IPC via `llama.cpp` or `Ollama`. The SLM consumes the JSON evidence payload and drafts contextual handover summaries in natural language.

---

## 5. Acceptance & Safety Standards
- **Operator-in-Control Principle**: AI never directly pulses actuators or bypasses interlocks.
- **Micro-Explanation Requirement**: All alarms provide direct transparency into *why* they are prioritized over background process deviations.
- **Deterministic Presentation**: Fixed operator signature (`J. Rivera (Shift 2)`) and verified mathematical deltas (`-45%`, `-32%`, `+18%`, `+44%`) ensure reliable reproducibility.
