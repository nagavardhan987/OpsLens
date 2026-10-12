"""
OpsLens - FastAPI REST & Real-Time Streaming Gateway (Component 11)

Exposes REST and SSE/WebSocket endpoints wrapping:
- GET  /api/events/{event_id} -> Full joined event details
- GET  /api/events/open        -> List of unresolved open event IDs
- POST /api/actions            -> Log human operator intervention with safety validation
- POST /api/handover           -> Compile shift handover summary
- GET  /api/handover           -> Query shift handover summary via GET
- GET  /api/events/stream      -> Server-Sent Events (SSE) live event feed
- WS   /api/events/ws          -> WebSocket live event stream
"""

import json
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from orchestrator import OpsLensOrchestrator
from scenarios import list_available_scenarios
from generator import SyntheticDataGenerator
from tag_registry import TAG_REGISTRY


class ActionRequest(BaseModel):
    event_id: str
    operator: str
    action_type: str
    notes: Optional[str] = None
    timestamp: Optional[str] = None


class HandoverRequest(BaseModel):
    shift_start: str
    shift_end: str


class ScenarioRunRequest(BaseModel):
    scenario_id: str = "valve_restriction"
    speed_multiplier: float = 10.0


def create_app(orchestrator: Optional[OpsLensOrchestrator] = None) -> FastAPI:
    """Create and configure the OpsLens FastAPI application."""
    app = FastAPI(
        title="OpsLens Industrial AI Copilot API",
        description="REST and real-time streaming backend for OpsLens",
        version="1.0.0"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    orch = orchestrator if orchestrator is not None else OpsLensOrchestrator()

    @app.get("/")
    async def root():
        return {
            "name": "OpsLens Industrial AI Copilot Backend Gateway",
            "status": "ONLINE",
            "message": "OpsLens backend is running! Open the interactive HMI Dashboard at http://localhost:5173",
            "dashboard_ui": "http://localhost:5173",
            "api_docs": "http://localhost:8000/docs",
            "endpoints": {
                "status": "/api/status",
                "scenarios": "/api/scenarios",
                "run_scenario": "/api/scenarios/run",
                "stream": "/api/events/stream",
                "open_events": "/api/events/open",
                "handover": "/api/handover",
                "actions": "/api/actions"
            }
        }

    router = APIRouter(prefix="/api")

    @router.get("/events/open")
    async def get_open_events():
        """Retrieve all currently active / open events."""
        open_events = orch.audit.get_open_events()
        return {"open_events": open_events, "count": len(open_events)}

    @router.get("/events/stream")
    async def stream_events(
        request: Request,
        max_events: Optional[int] = Query(None, description="Optional cap on events before closing stream")
    ):
        """
        Server-Sent Events (SSE) endpoint.
        Streams newly completed full events in real-time as they finish processing.
        """
        async def event_generator():
            queue = asyncio.Queue()
            orch.register_subscriber(queue)
            count = 0
            try:
                # Connection handshake
                yield "event: ping\ndata: connected\n\n"
                while True:
                    if max_events is not None and count >= max_events:
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=1.0)
                        yield f"data: {json.dumps(event)}\n\n"
                        count += 1
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        if max_events is not None:
                            count += 1
            except (asyncio.CancelledError, GeneratorExit):
                pass
            finally:
                orch.unregister_subscriber(queue)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @router.websocket("/events/ws")
    async def websocket_events(websocket: WebSocket):
        """
        WebSocket live stream endpoint.
        Pushes completed full events as JSON packets.
        """
        await websocket.accept()
        queue = asyncio.Queue()
        orch.register_subscriber(queue)
        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            orch.unregister_subscriber(queue)

    @router.get("/events/{event_id}")
    async def get_full_event(event_id: str):
        """
        Unified cross-table join query for an event.
        Returns candidate, correlated, timeline story, evidence, SOP, and actions.
        """
        full_event = orch.get_full_event(event_id)
        if full_event is None:
            raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found.")
        return full_event

    @router.post("/actions")
    async def log_action(req: ActionRequest):
        """
        Record a human operator decision/workflow action.
        Rejects invalid event IDs and forbidden machine/PLC control commands.
        """
        try:
            action = orch.audit.log_action(
                event_id=req.event_id,
                operator=req.operator,
                action_type=req.action_type,
                notes=req.notes,
                timestamp=req.timestamp
            )
            return action.model_dump()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/handover")
    async def compile_handover_post(req: HandoverRequest):
        """Compile shift handover summary for the given time window."""
        try:
            summary = orch.handover_compiler.compile_handover(
                shift_start=req.shift_start,
                shift_end=req.shift_end
            )
            return summary.model_dump()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get("/handover")
    async def compile_handover_get(
        shift_start: str = Query(..., description="ISO8601 UTC start timestamp"),
        shift_end: str = Query(..., description="ISO8601 UTC end timestamp")
    ):
        """Compile shift handover summary via GET query parameters."""
        try:
            summary = orch.handover_compiler.compile_handover(
                shift_start=shift_start,
                shift_end=shift_end
            )
            return summary.model_dump()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get("/scenarios")
    async def get_scenarios():
        """List available scenario archetypes for live simulation."""
        return {"scenarios": list_available_scenarios()}

    @router.post("/scenarios/run")
    async def run_scenario_endpoint(req: ScenarioRunRequest):
        """
        Execute a synthetic telemetry scenario in the background asynchronously,
        streaming readings into the live orchestrator pipeline without blocking the event loop.
        """
        async def _run():
            try:
                gen = SyntheticDataGenerator(db=orch.db, sample_interval=2.0)
                async for reading in gen.run_scenario_async(req.scenario_id, speed_multiplier=req.speed_multiplier):
                    await orch.process_reading(reading)

                # Await in-flight worker tasks
                if orch._in_flight_tasks:
                    await asyncio.gather(*orch._in_flight_tasks.values(), return_exceptions=True)

                # Guarantee final re-evaluation pass across open events to ensure full join completion
                # Candidate rows do not have a status column; openness is
                # tracked by event_stories/operator actions. Limit the final
                # refresh to event IDs the audit layer still considers open.
                open_event_ids = set(orch.audit.get_open_events())
                open_candidates = orch.db.get_candidate_events()
                for candidate in open_candidates:
                    if candidate.event_id in open_event_ids:
                        await orch.process_candidate_event(candidate)
            except Exception as e:
                import traceback
                traceback.print_exc()

        asyncio.create_task(_run())
        return {
            "status": "started",
            "scenario_id": req.scenario_id,
            "speed_multiplier": req.speed_multiplier
        }

    @router.post("/demo/reset")
    async def reset_demo_endpoint():
        """
        Reset live pipeline state: clear database readings/events,
        reset dedup clusters, and empty in-flight tasks for demo replay.
        """
        orch.db.clear_readings()
        conn = orch.db._get_connection()
        with conn:
            conn.execute("DELETE FROM candidate_events")
            conn.execute("DELETE FROM correlated_events")
            conn.execute("DELETE FROM event_stories")
            conn.execute("DELETE FROM evidence")
            conn.execute("DELETE FROM sop_matches")
            conn.execute("DELETE FROM guidance")
            conn.execute("DELETE FROM operator_actions")
        orch.dedup._active_clusters.clear()
        orch._completed_events.clear()
        orch._in_flight_tasks.clear()
        orch._processed_tags.clear()
        orch._processed_primary.clear()
        orch._pending_updates.clear()
        return {"status": "reset", "message": "Demo state reset successfully."}

    @router.get("/status")
    async def get_system_status():
        """Return system operational envelope and baseline status."""
        open_events = orch.audit.get_open_events()
        baselines = {}
        for tag, entry in TAG_REGISTRY.items():
            baselines[tag] = {
                "tag": tag,
                "equipment_id": entry.equipment_id,
                "unit": entry.unit,
                "baseline_min": entry.baseline_min,
                "baseline_max": entry.baseline_max,
                "nominal": (entry.baseline_min + entry.baseline_max) / 2.0 if entry.data_type == "float" else False
            }
        return {
            "status": "ONLINE",
            "system": "EcoStruxure HMI Copilot",
            "open_events_count": len(open_events),
            "open_events": open_events,
            "baselines": baselines
        }

    @router.get("/health")
    async def health_check():
        """Overall OpsLens system health."""
        open_events = orch.audit.get_open_events()
        return {
            "status": "ONLINE",
            "service": "OpsLens Edge Intelligence",
            "open_incidents": len(open_events),
            "components": {
                "alarm_engine": "deterministic",
                "correlator": "deterministic",
                "evidence_engine": "deterministic_scoring",
                "sop_retrieval": "qdrant_vector_search",
                "guidance": "llm_grounded",
            }
        }

    @router.get("/rag/health")
    async def rag_health():
        """
        Qdrant / VectorStore health check.
        Returns: connection status, collection name, chunk count, embedding model.
        """
        try:
            # Reuse the same persistent client as SOP retrieval. Creating a
            # second embedded client for the same Qdrant path fails because
            # embedded Qdrant locks its storage directory to one client.
            from sop_retriever import get_qdrant_store
            store = get_qdrant_store()
            h = store.health()
            return {
                **h,
                "documents": h.get("documents", 0),
                "chunks": h.get("chunks", h.get("total_chunks", 0)),
                "embedding_model": "all-MiniLM-L6-v2",
                "retrieval_method": "qdrant_vector_search",
                "fallback_method": "bm25",
                "note": "semantic_similarity is RAW cosine similarity, NOT probability"
            }
        except Exception as e:
            return {"vector_store": "qdrant", "connected": False, "error": str(e)}

    @router.get("/sops/library")
    async def get_sop_library():
        """List bundled procedures and PDFs indexed on this edge computer."""
        from pdf_sop_ingestion import list_sop_library
        return {"documents": list_sop_library()}

    @router.post("/sops/ingest-pdf")
    async def upload_sop_pdf(
        request: Request,
        sop_id: str = Query(..., min_length=1),
        title: str = Query(..., min_length=1),
        equipment: str = Query(""),
        equipment_type: str = Query(""),
        plant_area: str = Query(""),
        revision: str = Query("1.0"),
        effective_date: str = Query(""),
        filename: str = Query("sop.pdf"),
    ):
        """Ingest a local PDF body with SOP metadata passed as query fields."""
        content_type = request.headers.get("content-type", "").lower()
        if "application/pdf" not in content_type:
            raise HTTPException(status_code=415, detail="Upload the PDF as an application/pdf request body.")
        metadata = {
            "sop_id": sop_id,
            "title": title,
            "equipment": equipment,
            "equipment_type": equipment_type,
            "plant_area": plant_area,
            "revision": revision,
            "effective_date": effective_date,
        }
        try:
            pdf_bytes = await request.body()
            from pdf_sop_ingestion import ingest_pdf
            from sop_retriever import get_qdrant_store
            result = ingest_pdf(pdf_bytes, filename, metadata, get_qdrant_store())
            return {"status": "indexed", "data": result}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"SOP ingestion failed: {exc}")

    @router.get("/sops/{sop_id}/source")
    async def get_sop_source_pdf(sop_id: str):
        """Serve the preserved original PDF from local edge storage."""
        from pdf_sop_ingestion import get_pdf_path
        path = get_pdf_path(sop_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"No source PDF is stored for SOP '{sop_id}'.")
        return FileResponse(
            path,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{path.name}"'},
        )

    @router.get("/sops/{sop_id}")
    async def get_sop(sop_id: str):
        """
        Retrieve full SOP content from the configured document/vector store by sop_id.
        Used by the HMI 'View Full Procedure' button.
        Frontend must NOT hardcode SOP steps — it must call this endpoint.
        """
        try:
            # The retriever owns the process-wide embedded Qdrant client.
            # Reuse it instead of opening the same local storage a second time.
            from sop_retriever import get_qdrant_store
            store = get_qdrant_store()
            doc = store.get_document(sop_id)
            if doc and (doc.get("steps") or doc.get("content_pages")):
                return {"status": "found", "sop_id": sop_id, "data": doc}
            if doc:
                raise HTTPException(
                    status_code=404,
                    detail=f"SOP '{sop_id}' exists in Qdrant but has no procedure steps. Re-ingest the SOP document.",
                )
            raise HTTPException(status_code=404, detail=f"SOP '{sop_id}' not found.")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/debug/rag/{incident_id}")
    async def debug_rag(incident_id: str):
        """
        Full RAG traceability for a given incident.
        Shows: query_context, embedding_model, retrieval_method,
        candidate_documents, similarity_scores, selected_sop, retrieved_chunks.
        Use this during the Schneider technical demo to explain exactly why
        a specific SOP was retrieved.
        """
        from sop_retriever import RAG_TRACE_STORE

        trace = RAG_TRACE_STORE.get(incident_id)
        if not trace:
            # Try to rebuild from DB
            sop_matches = orch.db.get_sop_matches(event_id=incident_id)
            if sop_matches:
                m = sop_matches[0]
                trace = m.rag_trace or {
                    "event_id": incident_id,
                    "note": "Trace rebuilt from database (server may have restarted)",
                    "selected_sop_id": m.sop_id,
                    "semantic_similarity": m.semantic_similarity,
                    "retrieval_method": m.retrieval_method,
                    "query_context": m.query_context,
                    "retrieved_chunks": m.retrieved_chunks or [],
                    "why_retrieved": m.why_retrieved or {},
                    "process_context": {},
                }
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"No RAG trace found for incident '{incident_id}'. "
                           "Run the scenario first."
                )

        return {
            "incident_id": incident_id,
            "query_context": trace.get("query_context", ""),
            "embedding_model": "all-MiniLM-L6-v2",
            "vector_store": "Qdrant",
            "top_k": trace.get("top_k_requested", 5),
            "process_context": trace.get("process_context", {}),
            "results": [{
                "sop_id": x.get("sop_id", ""), "section": x.get("section", ""),
                "similarity": x.get("similarity", 0.0), "chunk_id": x.get("chunk_id", ""),
                "text": x.get("text", "")
            } for x in trace.get("retrieved_chunks", [])],
            "retrieval_method": trace.get("retrieval_method", "qdrant_vector_search"),
            "selected_sop_id": trace.get("selected_sop_id"),
            "semantic_similarity": trace.get("semantic_similarity")
        }

    @router.get("/debug/intelligence/{incident_id}")
    async def debug_intelligence(incident_id: str):
        """
        Complete intelligence pipeline trace for a given incident.
        Exposes deterministic stages + RAG + LLM for the Schneider demo.
        """
        from sop_retriever import RAG_TRACE_STORE

        full_event = orch.get_full_event(incident_id)
        if not full_event:
            raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found.")

        rag_trace = RAG_TRACE_STORE.get(incident_id, {})
        sop_match = full_event.get("sop_match", {})
        guidance = full_event.get("guidance", {})

        return {
            "incident_id": incident_id,
            "pipeline_stages": {
                "A_alarm_detection": {
                    "type": "DETERMINISTIC",
                    "file": "scenarios/valve_restriction.py",
                    "description": "Threshold-based alarm triggering. PIT-02-PRS >= 6.5 bar -> ALM-P02-HP = True",
                },
                "B_alarm_prioritization": {
                    "type": "DETERMINISTIC",
                    "file": "prioritizer.py",
                    "description": "Rule-based severity and deviation magnitude scoring",
                },
                "C_event_correlation": {
                    "type": "DETERMINISTIC_CALCULATED",
                    "file": "correlator.py",
                    "description": "Temporal window + topology graph distance correlation",
                },
                "D_event_story": {
                    "type": "DETERMINISTIC_CALCULATED",
                    "file": "event_story.py",
                    "description": "Chronological ordering of correlated deviations",
                },
                "E_evidence_engine": {
                    "type": "DETERMINISTIC_SCORING",
                    "file": "evidence_engine.py",
                    "formula": "(abs(deviation_pct)/100) * severity_weight * (1/(topology_distance+1)) * precedence_factor",
                    "description": "Mathematical attribution scoring — fully auditable",
                },
                "F_sop_retrieval": {
                    "type": "ML_SEMANTIC_SEARCH",
                    "file": "sop_retriever.py",
                    "embedding_model": "all-MiniLM-L6-v2",
                    "vector_store": "Qdrant (in-memory)",
                    "similarity_type": "cosine",
                    "score_label": "semantic_similarity (NOT confidence/probability)",
                    "query_context": rag_trace.get("query_context", sop_match.get("query_context")),
                    "semantic_similarity": sop_match.get("semantic_similarity"),
                    "retrieved_chunks": rag_trace.get("retrieved_chunks", sop_match.get("retrieved_chunks", [])),
                },
                "G_llm_guidance": {
                    "type": "LLM_GROUNDED",
                    "file": "guidance_generator.py",
                    "description": "LLM receives event story + evidence + retrieved SOP chunks. Cannot invent values.",
                    "cited_sop_id": guidance.get("cited_sop_id") if guidance else None,
                    "source": "cloud_llm or edge_slm or sop_fallback",
                },
                "H_handover": {
                    "type": "DETERMINISTIC_TEMPLATE",
                    "file": "shift_handover.py",
                    "description": "Structured shift handover from SQLite operator action log",
                },
            },
            "incident": full_event.get("candidate"),
            "event_story": full_event.get("story"),
            "evidence": full_event.get("evidence"),
            "sop_match": full_event.get("sop_match"),
            "guidance": full_event.get("guidance"),
            "operator_actions": full_event.get("actions", []),
        }

    @router.get("/integration/status")
    async def integration_status():
        """Status of all registered telemetry adapters."""
        adapters = [
            {
                "type": "simulator",
                "status": "ACTIVE",
                "description": "Synthetic telemetry generator for Pump-02 / Compressor-01 scenarios",
                "write_disabled": True,
            },
            {
                "type": "opcua",
                "status": "CONFIGURED_NOT_CONNECTED",
                "endpoint": "opc.tcp://localhost:4840",
                "description": "OPC UA CLIENT adapter — read-only, connects to EcoStruxure or other OPC UA servers",
                "write_disabled": True,
                "requires": "pip install asyncua + OPCUA_ENDPOINT env var",
            },
            {
                "type": "mqtt",
                "status": "CONFIGURED_NOT_CONNECTED",
                "broker": "localhost:1883",
                "description": "MQTT subscriber — read-only, subscribes to telemetry topics",
                "write_disabled": True,
                "requires": "pip install paho-mqtt + MQTT_BROKER_HOST env var",
            },
            {
                "type": "rest",
                "status": "CONFIGURED_NOT_CONNECTED",
                "endpoint": "http://localhost:9090/api/tags",
                "description": "REST polling adapter — read-only, polls external HTTP telemetry endpoint",
                "write_disabled": True,
                "requires": "REST_TELEMETRY_URL env var",
            },
        ]
        return {
            "adapters": adapters,
            "safety_note": "ALL adapters are READ-ONLY. OpsLens never writes to industrial equipment.",
            "hmi_agnostic": True,
            "common_model": "TagReading (tag, value, timestamp, unit, equipment_id, quality, source)"
        }

    app.include_router(router)
    return app


# Default app instance
app = create_app()
