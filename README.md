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
├── edge_intelligence/        # FastAPI backend
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
└── hmi_ui/                   # React + Vite HMI
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
cd edge_intelligence
pip install -r requirements.txt
python server.py
# FastAPI running at http://localhost:8000
```

### Frontend

```bash
cd hmi_ui
npm install
npm run dev
# Operator HMI at http://localhost:5173 (keep this page focused on operators)
```

In a second terminal, start the local engineering console:

```bash
cd hmi_ui
npm run dev:console
# Scenario Lab and SOP Library at http://localhost:5174
```

### Add a PDF SOP

1. Start the FastAPI backend and the engineering console as above, then open `http://localhost:5174`.
2. Select **SOP LIBRARY** in the top navigation.
3. Choose a text-based PDF (maximum 25 MB) and enter its SOP ID and title. Equipment and plant area help metadata-aware semantic retrieval.
4. Select **INGEST SOP PDF**. OpsLens extracts text locally, splits it by page, embeds it with `all-MiniLM-L6-v2`, stores the original PDF under `edge_intelligence/sop_documents/ingested_pdfs/`, and indexes the chunks in local Qdrant.
5. Confirm the result shows **Indexed in Qdrant** and a chunk count. The available-document list marks the SOP as **PDF · QDRANT**.
6. When an incident retrieves that SOP, use **VIEW FULL PROCEDURE** to read the extracted pages and open the preserved source PDF.

Scanned/image-only PDFs are rejected with an OCR-required message. OCR is not enabled yet. Re-ingesting an existing SOP ID replaces its indexed chunks and source PDF after confirmation.

The local API endpoints are `GET /api/sops/library`, `POST /api/sops/ingest-pdf`, `GET /api/sops/{sop_id}`, and `GET /api/sops/{sop_id}/source`.

### Run Tests

```bash
cd edge_intelligence
python -m unittest discover tests -v
# 49/49 tests pass
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, SQLite, asyncio |
| ML/RAG | sentence-transformers (all-MiniLM-L6-v2), Qdrant, optional BM25 fallback |
| Frontend | React 18, Vite, Tailwind CSS, Lucide Icons |
| LLM | Gemini API / Ollama (offline SLM) / deterministic fallback |
| Deployment | Edge PC, local Qdrant + SQLite, no cloud required |

## Local Qdrant RAG and edge deployment

Qdrant is the primary vector store. OpsLens connects to the local Qdrant service at `http://localhost:6333` by default; it does not require Pinecone or cloud access. SentenceTransformer uses `all-MiniLM-L6-v2` (384 dimensions). The model must be present in the local Hugging Face/SentenceTransformer cache before disconnecting the edge PC from the internet.

### Start Qdrant on the edge PC

From the repository root, with Docker Engine/Desktop installed:

```powershell
docker compose up -d qdrant
```

Qdrant's REST API is at `http://localhost:6333`, and its data is persisted in the `qdrant_storage` Docker volume. To run Qdrant as a native edge service instead, install the Qdrant server on that PC and set `QDRANT_URL` to its local HTTP endpoint. OpsLens never connects to a hosted Qdrant by default.

### Collection and payload schema

The collection is `opslens_sops`, configured by `QDRANT_COLLECTION`. It uses 384 dimensional vectors with cosine distance. Each point is one SOP section/step chunk; its vector is generated from chunk text by `all-MiniLM-L6-v2`. Payload fields include `document_id`, `document_name`, `sop_id`, `title`, `revision`, `equipment`, `equipment_type`, `plant_area`, `section`, `page`, `source`, `effective_date`, `chunk_id`, and the original `text`, plus source-document fields such as `instruction`, `keywords`, and `reference_limits`.

### Install and ingest SOPs

```powershell
cd edge_intelligence
python -m pip install -r requirements.txt
# If this machine has internet on initial setup, cache the model before going offline:
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
$env:QDRANT_URL = 'http://localhost:6333'
$env:QDRANT_COLLECTION = 'opslens_sops'
python ingest_sops.py
```

Ingestion reads each JSON file in `edge_intelligence/sop_documents/`, creates an overview chunk and procedure chunks, embeds them locally, and upserts deterministic point IDs into Qdrant. Repeat `python ingest_sops.py` after adding or changing SOP files. The existing `VectorStore` abstraction allows replacing the Qdrant implementation without changing ingestion or RAG orchestration.

### Run the complete local system

Start Qdrant first as above. In one terminal, from `edge_intelligence`, install requirements, ensure the embedding model is cached, set the two environment variables above, and run:

```powershell
python server.py
```

In another terminal:

```powershell
cd hmi_ui
npm install
npm run dev
```

Open `http://localhost:5173`. The simulator, SQLite database, FastAPI backend, Qdrant, embedding model, and optional local Ollama/SLM all run on the edge PC. OPC UA remains available as a read-only adapter. Cloud LLM credentials are optional; Qdrant and retrieval use only local services. For a single-process development setup, `QDRANT_URL=embedded` selects persistent embedded Qdrant storage under `QDRANT_PATH` (default `./qdrant_data`); use the Qdrant service for normal multi-request deployments.

### Retrieval flow and example

Time-series processing keeps bounded per-tag history and emits baseline deviation, trend, rate-of-change, threshold, and change-point observations. The alarm synthesis layer combines those observations with the event story. The NetworkX graph adds relationships among Pump-02, Valve-04, Flow-02, Motor-02, Pressure-02, and their tags. The RAG query includes equipment, synthesized alarm, symptoms, latest telemetry, event story, likely contributor, and graph context. Qdrant applies equipment/plant-area payload filters as a preference and retries unfiltered if the preferred subset is empty.

Example Qdrant vector search (the application supplies the 384-value embedding generated from the complete contextual incident string):

```python
hits = client.query_points(
    collection_name="opslens_sops",
    query=incident_embedding.tolist(),  # 384-vector for the complete contextual incident
    limit=5,
    with_payload=True,
).points
# hit.score is Qdrant's cosine similarity; hit.payload contains the SOP chunk.
```

OpsLens returns each hit's actual Qdrant cosine score as `similarity` and the best SOP's score as `semantic_similarity`, never as a probability or confidence. A retrieval object has this shape:

```json
{
  "sop_id": "SOP-P02-VLV-01",
  "title": "Pump-02 Throttling Valve Restriction Remediation",
  "revision": "1.0",
  "semantic_similarity": 0.7645,
  "retrieval_method": "qdrant_vector_search",
  "embedding_model": "all-MiniLM-L6-v2",
  "why_retrieved": {
    "incident": "Pump-02 High Pressure",
    "equipment": "Pump-02",
    "alarm": "ALM-P02-HP",
    "symptoms": ["Valve position decreased", "Flow decreased", "Motor current increased", "Pressure increased"],
    "matching_section": "step"
  },
  "chunks": [
    {"document_id": "SOP-P02-VLV-01", "sop_id": "SOP-P02-VLV-01", "title": "Pump-02 Throttling Valve Restriction Remediation", "revision": "1.0", "section": "step", "page": 2, "chunk_id": "…", "text": "…", "similarity": 0.7645}
  ]
}
```

`GET /api/rag/health` reports Qdrant connection state, collection, SOP document count, chunk count, and embedding model. `GET /api/debug/rag/{incident_id}` exposes the embedded contextual query and top-K Qdrant results. `GET /api/sops/{sop_id}` reconstructs the full procedure from Qdrant payloads; the existing SOP viewer fetches this endpoint when opened and does not contain hardcoded procedure steps. The model receives the incident context, evidence, and retrieved chunks and is instructed to rely only on those facts; when evidence is insufficient it must respond with “Operator verification required.”

Industrial adapters remain read-only. Qdrant, RAG, and the language model provide advisory content only; there is no path from retrieval or generation to PLC, pump, valve, actuator, or setpoint writes.

---

## License

MIT
