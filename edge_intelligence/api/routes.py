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
import copy
import logging
import os
import threading
import uuid
from time import perf_counter
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from fastapi import BackgroundTasks, FastAPI, APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from orchestrator import OpsLensOrchestrator
from scenarios import list_primary_demo_scenarios
from generator import SyntheticDataGenerator
from tag_registry import TAG_REGISTRY
from assistant import answer_incident_question, resolve_event_sop_reference
from assistant_cache import cache_key, clear as clear_assistant_cache, context_fingerprint, get as cache_get, put as cache_put, question_is_volatile
from context_builder import ContextBuilder, ContextEventNotFound, InvalidContextTimestamp, parse_timestamp
from models import IncidentContext, TagReading, current_iso_utc
from llm_provider import configuration_error, provider_status, selected_provider
from adapters.opcua_adapter import OPCUAAdapter
from operational_history import (build_handover_summary, configured_shift_window,
                                 generate_shift_narrative, list_alarm_history)

logger = logging.getLogger(__name__)
SCENARIO_STALE_AFTER_SECONDS = float(os.environ.get("OPSLENS_SCENARIO_STALE_SECONDS", "600"))
_sop_ingestion_jobs: Dict[str, Dict[str, Any]] = {}
_sop_ingestion_jobs_lock = threading.Lock()
_assistant_request_flights: Dict[str, Dict[str, Any]] = {}
_assistant_request_flights_lock = threading.Lock()


def _update_sop_ingestion_job(job_id: str, stage: Dict[str, Any]) -> None:
    with _sop_ingestion_jobs_lock:
        job = _sop_ingestion_jobs.get(job_id)
        if not job:
            return
        stages = list(job.get("stages") or [])
        index = next((i for i, item in enumerate(stages) if item.get("name") == stage.get("name")), None)
        if index is None:
            stages.append(dict(stage))
        else:
            stages[index] = dict(stage)
        job["stages"] = stages
        job["current_stage"] = stage.get("name")
        job["status"] = "processing"


def _run_sop_ingestion_job(job_id: str, pdf_bytes: bytes, filename: str, metadata: Dict[str, str]) -> None:
    """Run PDF ingestion in a background task and expose stage-safe progress."""
    try:
        from pdf_sop_ingestion import PdfExtractionError, PdfIndexingError, ingest_pdf
        from sop_retriever import get_qdrant_store
        result = ingest_pdf(
            pdf_bytes, filename, metadata, get_qdrant_store(),
            progress_callback=lambda stage: _update_sop_ingestion_job(job_id, stage),
        )
        with _sop_ingestion_jobs_lock:
            job = _sop_ingestion_jobs.get(job_id)
            if job is not None:
                job.update({
                    "status": "completed", "current_stage": "complete",
                    "stages": result.get("stages", []), "data": result, "error": None,
                })
    except PdfExtractionError as exc:
        with _sop_ingestion_jobs_lock:
            job = _sop_ingestion_jobs.get(job_id)
            if job is not None:
                manual = "scanned" in str(exc).lower() or "ocr" in str(exc).lower()
                job.update({
                    "status": "failed", "current_stage": "extraction_failed",
                    "error": {"stage": "extraction_failed", "message": str(exc), "manual_review_required": manual},
                    "stages": list(job.get("stages") or []) + [{
                        "name": "Text extraction failed", "status": "failed", "complete": False,
                        "detail": "OCR or manual review is required." if manual else "No extracted text was indexed.",
                    }],
                })
    except PdfIndexingError as exc:
        with _sop_ingestion_jobs_lock:
            job = _sop_ingestion_jobs.get(job_id)
            if job is not None:
                job.update({
                    "status": "failed", "current_stage": "indexing_failed",
                    "error": {"stage": "indexing_failed", "code": exc.code, "message": str(exc)},
                    "stages": list(job.get("stages") or []) + [{
                        "name": "Indexing failed", "status": "failed", "complete": False,
                        "detail": "The PDF was not reported as indexed.",
                    }],
                })
    except ValueError as exc:
        with _sop_ingestion_jobs_lock:
            job = _sop_ingestion_jobs.get(job_id)
            if job is not None:
                job.update({
                    "status": "failed", "current_stage": "validation_failed",
                    "error": {"stage": "validation_failed", "message": str(exc)},
                    "stages": list(job.get("stages") or []) + [{
                        "name": "Document validation failed", "status": "failed", "complete": False,
                        "detail": "Check the PDF file and required document metadata.",
                    }],
                })
    except Exception as exc:
        logger.exception("SOP ingestion job failed job_id=%s error_type=%s", job_id, type(exc).__name__)
        with _sop_ingestion_jobs_lock:
            job = _sop_ingestion_jobs.get(job_id)
            if job is not None:
                job.update({
                    "status": "failed", "current_stage": "ingestion_failed",
                    "error": {"stage": "ingestion_failed", "message": "SOP ingestion failed. No success was recorded."},
                    "stages": list(job.get("stages") or []) + [{
                        "name": "Ingestion failed", "status": "failed", "complete": False,
                        "detail": "No success was recorded; inspect backend diagnostics.",
                    }],
                })


def _incident_failure(event_id: str, code: str, message: str) -> HTTPException:
    """Log diagnostic context and return a safe, actionable operator error."""
    request_id = uuid.uuid4().hex[:12]
    logger.exception("%s request_id=%s event_id=%s", code, request_id, event_id)
    return HTTPException(
        status_code=500,
        detail=message,
        headers={"X-Request-ID": request_id, "X-OpsLens-Error-Code": code},
    )


def _load_bundled_sop(sop_id: str) -> Optional[Dict[str, Any]]:
    """Load a bundled SOP directly so its full procedure is available offline."""
    try:
        from demo_sop_sections import load_demo_sop_document
        demo_document = load_demo_sop_document(sop_id)
        if demo_document:
            return demo_document
    except Exception:
        pass
    try:
        from pathlib import Path
        sop_dir = Path(__file__).resolve().parent.parent / "sop_documents"
        if sop_dir.exists():
            for p in sop_dir.glob("*.json"):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if data.get("sop_id") == sop_id:
                            return data
                except Exception:
                    pass
    except Exception:
        pass
    try:
        from embed_index import SOP_DIR, load_all_sops
        return next((document for document in load_all_sops(SOP_DIR)
                     if document.get("sop_id") == sop_id), None)
    except Exception:
        return None


def _load_sop_document(sop_id: str, qdrant_store_loader=None) -> Optional[Dict[str, Any]]:
    """Resolve packaged procedures locally, then fall back to indexed PDFs."""
    document = _load_bundled_sop(sop_id)
    if document:
        return document
    try:
        if qdrant_store_loader is None:
            from sop_retriever import get_qdrant_store
            qdrant_store_loader = get_qdrant_store
        return qdrant_store_loader().get_document(sop_id)
    except Exception:
        return None


class ActionRequest(BaseModel):
    event_id: str
    operator: str
    action_type: str
    alarm_id: Optional[str] = None
    notes: Optional[str] = None
    timestamp: Optional[str] = None


class MarkUnresolvedRequest(BaseModel):
    operator: str = Field(min_length=1, max_length=120)
    reason: Optional[str] = Field(default=None, max_length=1000)
    timestamp: Optional[str] = None


class HandoverRequest(BaseModel):
    shift_start: str
    shift_end: str


class HandoverSubmitRequest(BaseModel):
    shift_date: str = Field(min_length=8, max_length=20)
    shift_name: str = Field(min_length=1, max_length=80)
    shift_start: str
    shift_end: str
    outgoing_operator: str = Field(min_length=1, max_length=120)
    incoming_operator: Optional[str] = Field(default=None, max_length=120)
    fields: Dict[str, str] = Field(default_factory=dict)


class HandoverItemResponseRequest(BaseModel):
    operator: str = Field(min_length=1, max_length=120)
    comment: Optional[str] = Field(default=None, max_length=2000)
    acknowledged: bool = False


class HandoverConfirmRequest(BaseModel):
    incoming_operator: str = Field(min_length=1, max_length=120)
    signature_name: str = Field(min_length=1, max_length=120)
    face_to_face_confirmed: bool = False
    walkthrough_confirmed: bool = False


def _timestamp_is_after(value: Optional[str], reference: Optional[str]) -> bool:
    """Compare source timestamps as instants; malformed values never satisfy the clear interlock."""
    if not value or not reference:
        return False
    try:
        return parse_timestamp(value) > parse_timestamp(reference)
    except InvalidContextTimestamp:
        return False


def _is_clear_alarm_reading(
    reading: Any,
    alarm_tag: Optional[str],
    alarm_timestamp: Optional[str],
    equipment_id: Optional[str] = None,
    minimum_timestamp: Optional[str] = None,
) -> bool:
    """A clear interlock requires the correct source tag/equipment and a later false-like sample."""
    if reading is None or not alarm_tag or getattr(reading, "tag", None) != alarm_tag:
        return False
    clear_value = getattr(reading, "value", None) is False or str(getattr(reading, "value", "")).strip().lower() in ("false", "0", "clear", "inactive", "off")
    observed_equipment = getattr(reading, "equipment_id", None)
    equipment_matches = not equipment_id or bool(observed_equipment and str(observed_equipment).casefold() == str(equipment_id).casefold())
    reading_timestamp = getattr(reading, "timestamp", None)
    newer_than_alarm = _timestamp_is_after(reading_timestamp, alarm_timestamp)
    newer_than_minimum = not minimum_timestamp or _timestamp_is_after(reading_timestamp, minimum_timestamp)
    return bool(clear_value and equipment_matches and newer_than_alarm and newer_than_minimum)


class ScenarioRunRequest(BaseModel):
    scenario_id: str = "wet_well_high_level"
    speed_multiplier: float = 10.0


class AssistantAskRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=3, max_length=1000)
    reference_timestamp: Optional[str] = None
    conversation_id: Optional[str] = Field(default=None, max_length=80)


class AssistantAskResponse(BaseModel):
    """Typed assistant status fields; preserve the evolving evidence payload."""
    answer: str = ""
    llm_used: bool = False
    fallback_used: bool = True
    fallback_reason: Optional[str] = None
    correction_failure_reason: Optional[str] = None
    selected_provider: Optional[str] = None
    selected_model: Optional[str] = None
    used_provider: Optional[str] = None
    used_model: Optional[str] = None
    provider_metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "allow"


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
    app.state.opcua_adapter = OPCUAAdapter()
    context_builder = ContextBuilder(
        db=orch.db,
        event_loader=orch.get_full_event,
        knowledge_graph=getattr(orch, "knowledge_graph", None),
    )
    # In-memory lifecycle state for the explicitly synthetic demonstration.
    # Production adapters continue to report their own readings and states.
    simulation_state: Dict[str, Any] = {"status": "idle", "scenario_id": None, "event_id": None, "generator": None}
    # Rolling measurements of context assembly latency (in milliseconds)
    context_assembly_measurements: List[float] = []
    context_assembly_failures: List[Dict[str, Any]] = []

    def record_context_failure(started: float, reason: str) -> None:
        context_assembly_failures.append({"latency_ms": round((perf_counter() - started) * 1000, 3), "reason": reason})
        if len(context_assembly_failures) > 200:
            del context_assembly_failures[:-200]

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

    @router.get("/incidents/ranked")
    async def get_ranked_incidents(limit: int = Query(20, ge=1, le=100)):
        """
        Return active incidents ordered by deterministic urgency ranking policy.

        Ranking tiers:
        1. Hard rules active (URGENT safety rules fire)
        2. Time-to-limit (smaller TTL ranks higher)
        3. Urgency band (URGENT > ELEVATED > ROUTINE > UNKNOWN)
        4. Urgency score (higher first)
        5. Trigger timestamp (older = more persistent = higher)

        Each incident includes ranking_position and ranking_rationale.
        """
        from alarm_urgency import rank_incidents
        open_event_ids = orch.audit.get_open_events()
        incidents = []
        for event_id in open_event_ids[:limit]:
            full_event = orch.get_full_event(event_id)
            if not full_event:
                continue
            candidate = full_event.get("candidate") or {}
            # Attach urgency from stored candidate event if available
            stored_candidates = orch.db.get_candidate_events(event_id=event_id)
            urgency_data = None
            if stored_candidates and stored_candidates[0].urgency:
                urgency_data = stored_candidates[0].urgency.model_dump()
            individual_alarms = []
            try:
                individual_alarms = orch.db.get_individual_alarms(event_id)
            except Exception:
                pass
            incidents.append({
                **full_event,
                "urgency": urgency_data,
                "repeat_count": stored_candidates[0].repeat_count if stored_candidates else 1,
                "lifecycle_state": stored_candidates[0].lifecycle_state if stored_candidates else "ACTIVE",
                "source_priority": candidate.get("source_priority") or candidate.get("alarm_severity"),
                "individual_alarms": individual_alarms,
            })

        ranked = rank_incidents(incidents)
        return {
            "ranked_incidents": ranked,
            "count": len(ranked),
            "advisory_only": True,
            "ranking_disclaimer": (
                "Provisional urgency ranking. Based on deterministic rules and recorded telemetry. "
                "Human operator judgment required. OpsLens does not control equipment."
            ),
        }

    @router.get("/events/recent")
    async def get_recent_events(limit: int = Query(10, ge=1, le=50)):
        """Return a compact local alarm/event history from persisted event timestamps."""
        summaries = []
        for event_id in orch.db.get_recent_event_ids(limit):
            event = orch.get_full_event(event_id)
            if not event:
                continue
            candidate = event.get("candidate") or {}
            story = event.get("story") or {}
            steps = story.get("steps") or []
            alarm_step = next((step for step in reversed(steps) if str(step.get("tag", "")).startswith("ALM-")), None)
            primary_tag = (alarm_step or {}).get("tag") or candidate.get("primary_tag", "UNKNOWN")
            summaries.append({
                "event_id": event_id,
                "status": event.get("status", "UNKNOWN"),
                "is_open": event.get("is_open", False),
                "alarm_id": primary_tag,
                "alarm_severity": candidate.get("alarm_severity"),
                "equipment": orch._equipment_for(primary_tag),
                "timestamp": (alarm_step or {}).get("timestamp") or candidate.get("trigger_timestamp"),
                "description": (alarm_step or {}).get("description") or story.get("causal_label", "Event details unavailable"),
                "causal_label": story.get("causal_label", ""),
                "urgency_band": (event.get("urgency") or {}).get("urgency_band", "UNKNOWN"),
                "urgency_score": (event.get("urgency") or {}).get("urgency_score"),
                "repeat_count": event.get("repeat_count", 1),
                "lifecycle_state": event.get("lifecycle_state", "ACTIVE"),
            })
        return {"events": summaries, "count": len(summaries)}

    @router.get("/alarms/history")
    async def get_alarm_history(
        q: Optional[str] = None, status: Optional[str] = None,
        start: Optional[str] = None, end: Optional[str] = None,
        alarm_id: Optional[str] = None, equipment: Optional[str] = None,
        process_area: Optional[str] = None, severity: Optional[str] = None,
        priority: Optional[str] = None, operator: Optional[str] = None,
        incident_id: Optional[str] = None, limit: int = Query(500, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        """Return persistent alarm occurrences and their linked incident/action history."""
        filters = {"q": q, "status": status, "start": start, "end": end,
                   "alarm_id": alarm_id, "equipment": equipment, "process_area": process_area,
                   "severity": severity, "priority": priority, "operator": operator,
                   "incident_id": incident_id}
        alarms = list_alarm_history(orch.db, filters)
        return {"alarms": alarms[offset:offset + limit], "count": len(alarms),
                "offset": offset, "limit": limit, "has_more": offset + limit < len(alarms),
                "recorded_count": len(alarms), "retention": "Persistent local SQLite records",
                "advisory_only": True}

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
        full_event["individual_alarms"] = orch.db.get_individual_alarms(event_id)
        full_event["sop_resolution"], full_event["resolved_sop_sources"] = resolve_event_sop_reference(full_event)
        steps = (full_event.get("story") or {}).get("steps") or []
        alarm_step = next((step for step in reversed(steps) if str(step.get("tag", "")).startswith("ALM-")), None)
        alarm_tag = (alarm_step or {}).get("tag")
        latest = orch.db.get_latest_reading(alarm_tag) if alarm_tag else None
        alarm_timestamp = (alarm_step or {}).get("timestamp")
        later_than_alarm = bool(latest and _timestamp_is_after(latest.timestamp, alarm_timestamp))
        if latest:
            is_active = latest.value is True or str(latest.value).strip().lower() in ("true", "1", "active", "on")
            full_event["runtime_alarm_state"] = {
                "tag": alarm_tag,
                "active": is_active,
                "observed": True,
                "timestamp": latest.timestamp,
                "value": latest.value,
                "is_later_than_alarm": later_than_alarm,
                "received_timestamp": latest.received_timestamp,
                "data_quality": latest.data_quality,
                "data_source": latest.data_source,
                "connection_status": latest.connection_status,
                "source": "synthetic_simulator" if simulation_state.get("event_id") == event_id else "timestamped_reading",
            }
        else:
            full_event["runtime_alarm_state"] = {"tag": alarm_tag, "active": None, "observed": False, "timestamp": None, "is_later_than_alarm": False}
        return full_event

    @router.get("/events/{event_id}/context", response_model=IncidentContext)
    async def get_incident_context(event_id: str, reference_timestamp: Optional[str] = Query(None)):
        """Preview the timestamped, preceding 30-minute incident context."""
        try:
            return context_builder.build(event_id, reference_timestamp)
        except ContextEventNotFound:
            raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found.")
        except InvalidContextTimestamp as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    def _bind_conversation(event_id: str, conversation_id: Optional[str]) -> str:
        convo = (conversation_id or "").strip() or str(uuid.uuid4())
        bound = getattr(orch.db, "get_conversation_event_id", lambda *_: None)(convo)
        if bound and bound != event_id:
            raise HTTPException(status_code=409, detail="Conversation is bound to a different incident.")
        return convo

    def _similar_incidents(full_event: Dict[str, Any], context_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        getter = getattr(orch.db, "get_similar_incidents", None)
        if getter is None:
            return []
        selected = context_payload.get("selected_event") or {}
        stamp = selected.get("timestamp") or full_event.get("trigger_timestamp")
        if not stamp:
            return []
        try:
            reference = parse_timestamp(stamp)
        except InvalidContextTimestamp:
            return []
        day_start = reference.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        equipment = selected.get("equipment_id") or ""
        primary = selected.get("primary_tag") or selected.get("alarm_id")
        try:
            return getter(
                equipment_id=equipment,
                primary_tag=primary,
                day_start=day_start.isoformat().replace("+00:00", "Z"),
                before_timestamp=stamp,
                exclude_event_id=full_event.get("event_id"),
            )
        except TypeError:
            return []

    def _answer_question_impl(req: AssistantAskRequest, progress_callback=None) -> Dict[str, Any]:
        full_event = orch.get_full_event(req.event_id)
        if full_event is None:
            raise HTTPException(status_code=404, detail="Selected incident was not found.")
        if progress_callback:
            progress_callback("preparing_context")
        conversation_id = _bind_conversation(req.event_id, req.conversation_id)
        context_started = perf_counter()
        try:
            context = context_builder.build(req.event_id, req.reference_timestamp, event_record=full_event)
        except ContextEventNotFound:
            record_context_failure(context_started, "event_not_found")
            raise HTTPException(status_code=404, detail="Selected incident was not found.")
        except InvalidContextTimestamp as exc:
            record_context_failure(context_started, "invalid_or_missing_event_timestamp")
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception:
            record_context_failure(context_started, "context_assembly_error")
            raise
        context_payload = context.model_dump(mode="json")
        if progress_callback:
            progress_callback("evidence_ready")
        if context.assembly_latency_ms is not None and context.assembly_latency_ms >= 0:
            context_assembly_measurements.append(float(context.assembly_latency_ms))
            if len(context_assembly_measurements) > 200:
                del context_assembly_measurements[:-200]
        alarm_state = context_payload["selected_event"].get("alarm_state")
        story_steps = (full_event.get("story") or {}).get("steps") or []
        alarm_step = next((step for step in reversed(story_steps)
                           if str(step.get("tag", "")).startswith("ALM-")), None)
        alarm_tag = (alarm_state or {}).get("tag") or context_payload["selected_event"].get("alarm_id")
        latest_alarm = orch.db.get_latest_reading(alarm_tag) if alarm_tag else None
        alarm_timestamp = (alarm_step or {}).get("timestamp") or full_event.get("trigger_timestamp")
        if latest_alarm:
            full_event["runtime_alarm_state"] = {
                "tag": alarm_tag,
                "active": latest_alarm.value is True or str(latest_alarm.value).strip().lower() in ("true", "1", "active", "on"),
                "observed": True,
                "timestamp": latest_alarm.timestamp,
                "value": latest_alarm.value,
                "source": "sqlite.tag_readings",
                "is_later_than_alarm": _timestamp_is_after(latest_alarm.timestamp, alarm_timestamp),
            }
        else:
            full_event["runtime_alarm_state"] = {"tag": alarm_tag, "active": None,
                                                  "observed": False, "timestamp": None,
                                                  "is_later_than_alarm": False}
        history_limit = int(os.environ.get("OPSLENS_ASSISTANT_HISTORY_LIMIT", "8"))
        history = []
        if hasattr(orch.db, "get_assistant_messages"):
            history = orch.db.get_assistant_messages(conversation_id, req.event_id, limit=history_limit)
        fingerprint = context_fingerprint(full_event, context_payload)
        history_tail = "|".join(f"{item.get('role')}:{item.get('content')}" for item in history[-4:])
        key = cache_key(req.event_id, req.question, fingerprint, history_tail)
        if not question_is_volatile(req.question):
            cached = cache_get(key)
            if cached:
                cached["cache_hit"] = True
                cached["conversation_id"] = conversation_id
                return cached
        similar = _similar_incidents(full_event, context_payload)
        result = answer_incident_question(
            full_event,
            req.question,
            context=context_payload,
            similar_incidents=similar,
            conversation_id=conversation_id,
            conversation=history,
            assembly_latency_ms=context.assembly_latency_ms,
            progress_callback=progress_callback,
        )
        result["cache_hit"] = False
        if hasattr(orch.db, "save_assistant_message"):
            orch.db.save_assistant_message(conversation_id, req.event_id, "user", req.question)
            orch.db.save_assistant_message(conversation_id, req.event_id, "assistant", result.get("answer") or "")
        if not question_is_volatile(req.question):
            cache_put(key, result)
        return result

    def _answer_question(req: AssistantAskRequest, progress_callback=None) -> Dict[str, Any]:
        """Coalesce identical in-flight incident questions before context/RAG/LLM work."""
        request_key = json.dumps({
            "event_id": req.event_id,
            "question": req.question.strip().casefold(),
            "reference_timestamp": req.reference_timestamp,
            "conversation_id": req.conversation_id,
        }, sort_keys=True, default=str)
        with _assistant_request_flights_lock:
            state = _assistant_request_flights.get(request_key)
            owner = state is None
            if owner:
                state = {"event": threading.Event(), "result": None, "error": None}
                _assistant_request_flights[request_key] = state

        if not owner:
            if progress_callback:
                progress_callback("waiting_for_identical_analysis")
            # Wait at least as long as one provider call can take (a local
            # Ollama answer may need up to OPSLENS_OLLAMA_TIMEOUT seconds).
            from llm_provider import llm_timeout as _provider_timeout
            default_wait = max(30.0, _provider_timeout() + 15.0)
            wait_seconds = max(0.1, float(os.environ.get("OPSLENS_ASSISTANT_SINGLEFLIGHT_TIMEOUT") or default_wait))
            if not state["event"].wait(wait_seconds):
                raise HTTPException(status_code=503, detail="An identical incident analysis is still in progress. Retry shortly.")
            if state["error"] is not None:
                raise state["error"]
            result = copy.deepcopy(state["result"])
            result["cache_hit"] = True
            result["coalesced_request"] = True
            return result

        try:
            result = _answer_question_impl(req, progress_callback)
            state["result"] = result
            return result
        except Exception as exc:
            state["error"] = exc
            raise
        finally:
            state["event"].set()
            with _assistant_request_flights_lock:
                if _assistant_request_flights.get(request_key) is state:
                    _assistant_request_flights.pop(request_key, None)

    @router.post("/assistant/ask", response_model=AssistantAskResponse)
    async def ask_ops_lens(req: AssistantAskRequest):
        """Answer an incident-scoped question using its persisted 30-minute context."""
        try:
            # SQLite, optional vector lookup and synchronous provider clients
            # must not block the ASGI event loop used by streaming/HMI traffic.
            return await asyncio.to_thread(_answer_question, req)
        except HTTPException:
            raise
        except Exception:
            raise _incident_failure(
                req.event_id,
                "INCIDENT_ASSESSMENT_FAILED",
                "The incident assessment could not be completed. Retry; if it continues, share the request ID with an engineer.",
            )

    @router.post("/assistant/ask/stream")
    async def ask_ops_lens_stream(req: AssistantAskRequest):
        """SSE progress plus a fully validated response (draft tokens are never exposed)."""
        def sse(event_name: str, payload: Dict[str, Any]) -> str:
            return f"event: {event_name}\ndata: {json.dumps(payload, default=str)}\n\n"

        async def generate():
            stage_messages = {
                "preparing_context": "Preparing incident context from recorded telemetry and alarm metadata…",
                "waiting_for_identical_analysis": "Waiting for the identical incident assessment already in progress…",
                "evidence_ready": "Recorded readings, timeline and evidence are available.",
                "retrieving_procedure": "Checking procedure references and approval status…",
                "generating_explanation": "Generating explanation and validating numeric claims…",
                "deterministic_analysis_available": "Deterministic record-grounded analysis is available.",
            }
            progress_queue: asyncio.Queue = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def report_progress(stage: str) -> None:
                loop.call_soon_threadsafe(progress_queue.put_nowait, stage)

            try:
                # Stream only stages emitted by the work as they actually occur.
                worker = asyncio.create_task(asyncio.to_thread(_answer_question, req, report_progress))
                while not worker.done():
                    try:
                        stage = await asyncio.wait_for(progress_queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    yield sse("status", {"stage": stage, "message": stage_messages.get(stage, stage), "advisory_only": True})
                result = await worker
                while not progress_queue.empty():
                    stage = progress_queue.get_nowait()
                    yield sse("status", {"stage": stage, "message": stage_messages.get(stage, stage), "advisory_only": True})
            except HTTPException as exc:
                yield sse("error", {
                    "detail": exc.detail,
                    "status": exc.status_code,
                    "code": (exc.headers or {}).get("X-OpsLens-Error-Code"),
                    "request_id": (exc.headers or {}).get("X-Request-ID"),
                })
                return
            except Exception:
                logger.exception("assistant_stream_failed event_id=%s question=%r", req.event_id, req.question)
                failure = _incident_failure(
                    req.event_id,
                    "INCIDENT_ASSESSMENT_FAILED",
                    "The incident assessment could not be completed. Retry; if it continues, share the request ID with an engineer.",
                )
                yield sse("error", {
                    "detail": failure.detail,
                    "status": 500,
                    "code": failure.headers.get("X-OpsLens-Error-Code"),
                    "request_id": failure.headers.get("X-Request-ID"),
                })
                return

            assembly_ms = result.get("assembly_latency_ms", 0.0)
            yield sse("status", {
                "stage": "analysis_ready",
                "assembly_latency_ms": assembly_ms,
                "fallback_used": result.get("fallback_used"),
                "llm_used": result.get("llm_used"),
                "cache_hit": result.get("cache_hit", False),
                "timings_ms": result.get("timings_ms") or {},
                "message": (
                    "Deterministic analysis ready" if result.get("fallback_used")
                    else "Grounded explanation ready"
                ),
            })

            answer = (result.get("operator_response") or {}).get("bottom_line") or result.get("answer") or ""
            if not answer:
                yield sse("error", {"detail": "The assistant produced an empty response; deterministic fallback was unavailable."})
                yield sse("done", result)
                return

            # Numeric/SOP grounding runs on the complete answer, so never expose
            # unvalidated model draft tokens. Send the accepted response at once
            # instead of adding artificial per-word UI delay.
            yield sse("token", {"text": answer})

            yield sse("done", result)

        return StreamingResponse(generate(), media_type="text/event-stream")

    @router.get("/metrics/impact")
    async def get_impact_metrics(
        scope: str = Query("session", description="Scope of metrics: 'session' (all recent incidents) or 'selected' (requires event_id)"),
        event_id: Optional[str] = Query(None, description="Specific event_id for incident-specific metrics"),
        baseline_mttr: Optional[float] = None,
    ):
        """
        Return MTTR and operational impact metrics calculated from real recorded data.

        - If scope='selected' and event_id is supplied, calculates metrics specific to that single incident.
        - Otherwise, calculates session-wide metrics across all recorded incidents in the database.
        - MTTR is computed ONLY from valid resolved incidents with valid, non-negative resolution durations.
        - When zero valid resolved incidents exist, avg_mttr_minutes and mttr_reduction_pct return None (null).
        - No hardcoded 18.5 min or 58.9% fallbacks are ever used.
        """
        import statistics

        # Validate baseline
        valid_baseline = baseline_mttr if (baseline_mttr is not None and baseline_mttr > 0) else None

        # Fetch incident IDs based on scope
        if scope == "selected" and event_id:
            all_event_ids = [event_id]
        else:
            # Query all distinct event_ids recorded in SQLite candidate_events
            conn = orch.db._get_connection()
            cursor = conn.execute("SELECT event_id FROM candidate_events ORDER BY trigger_timestamp DESC")
            all_event_ids = [row["event_id"] for row in cursor.fetchall()]

        resolved_count = 0
        open_count = 0
        total_incidents = len(all_event_ids)
        valid_durations_minutes: List[float] = []
        resolution_details: List[Dict[str, Any]] = []

        for eid in all_event_ids:
            ev = orch.get_full_event(eid)
            if not ev:
                continue

            actions = ev.get("actions") or []
            trigger_ts = ev.get("trigger_timestamp")
            resolve_action = next(
                (a for a in actions if (a.get("action_type") or "").upper() in ("RESOLVE", "RESOLVED")),
                None
            )

            if resolve_action and trigger_ts:
                try:
                    t_start = parse_timestamp(trigger_ts)
                    t_end = parse_timestamp(resolve_action.get("timestamp", trigger_ts))
                    delta_seconds = (t_end - t_start).total_seconds()
                    delta_minutes = delta_seconds / 60.0

                    # Only count non-negative, valid durations (<= 480 minutes / 8 hours window)
                    if 0.0 <= delta_minutes <= 480.0:
                        valid_durations_minutes.append(round(delta_minutes, 2))
                        resolved_count += 1
                        resolution_details.append({
                            "event_id": eid,
                            "duration_minutes": round(delta_minutes, 2),
                            "resolved_at": resolve_action.get("timestamp"),
                        })
                    else:
                        # Invalid/negative duration: excluded from MTTR
                        resolved_count += 1
                except Exception:
                    resolved_count += 1
            elif ev.get("is_open"):
                open_count += 1
            elif ev.get("status") in ("RESOLVE", "RESOLVED"):
                resolved_count += 1

        # Calculate MTTR: sum of valid durations / count of valid durations
        if valid_durations_minutes:
            avg_mttr = round(sum(valid_durations_minutes) / len(valid_durations_minutes), 1)
        else:
            avg_mttr = None

        # Calculate MTTR Reduction: only when both a valid MTTR and valid baseline exist
        if avg_mttr is not None and valid_baseline is not None and valid_baseline > 0:
            mttr_reduction_pct = round(((valid_baseline - avg_mttr) / valid_baseline) * 100, 1)
        else:
            mttr_reduction_pct = None

        # Context assembly latency statistics from actual recorded measurements
        if context_assembly_measurements:
            sorted_latencies = sorted(context_assembly_measurements)
            n = len(sorted_latencies)
            p95_idx = min(int(n * 0.95), n - 1)
            assembly_stats = {
                "sample_count": n,
                "avg_ms": round(statistics.mean(sorted_latencies), 1),
                "median_ms": round(statistics.median(sorted_latencies), 1),
                "p95_ms": round(sorted_latencies[p95_idx], 1),
                "min_ms": round(sorted_latencies[0], 1),
                "max_ms": round(sorted_latencies[-1], 1),
                "failed_attempts": len(context_assembly_failures),
                "last_failure_ms": context_assembly_failures[-1]["latency_ms"] if context_assembly_failures else None,
                "last_failure_reason": context_assembly_failures[-1]["reason"] if context_assembly_failures else None,
            }
        else:
            assembly_stats = {
                "sample_count": 0,
                "avg_ms": None,
                "median_ms": None,
                "p95_ms": None,
                "min_ms": None,
                "max_ms": None,
                "failed_attempts": len(context_assembly_failures),
                "last_failure_ms": context_assembly_failures[-1]["latency_ms"] if context_assembly_failures else None,
                "last_failure_reason": context_assembly_failures[-1]["reason"] if context_assembly_failures else None,
            }

        return {
            "scope": scope if (scope == "selected" and event_id) else "session",
            "selected_event_id": event_id if (scope == "selected" and event_id) else None,
            "total_incidents": total_incidents,
            "resolved_incidents": resolved_count,
            "open_incidents": open_count,
            "valid_samples_count": len(valid_durations_minutes),
            "avg_mttr_minutes": avg_mttr,
            "baseline_mttr_minutes": valid_baseline,
            "mttr_reduction_pct": mttr_reduction_pct,
            "context_assembly_target_ms": 2000,
            "context_assembly_stats": assembly_stats,
            "context_assembly_achieved_ms": assembly_stats["avg_ms"],
            "advisory_only": True,
            "human_in_the_loop": True,
            "writes_to_plc": False,
            "data_source": "synthetic_demo_events",
            "mttr_note": (
                "Calculated strictly from valid resolved incidents in the demo session. "
                "Returns null when no valid resolution samples exist. Not validated real-world performance data."
            ),
            "baseline_note": (
                "No comparison baseline is configured by default. Supply a validated, comparable baseline explicitly "
                "before interpreting MTTR reduction; no live plant comparison has been performed."
            ),
            "context_assembly_note": (
                "Target SLA is < 2000 ms. Measured stats reflect actual per-request ContextBuilder runs."
            ),
        }

    @router.post("/actions")
    async def log_action(req: ActionRequest):
        """
        Record a human operator decision/workflow action.
        Rejects invalid event IDs and forbidden machine/PLC control commands.
        """
        try:
            if req.action_type.strip().upper() in ("ACKNOWLEDGE", "ACKNOWLEDGED") and req.alarm_id:
                action, created = orch.db.record_alarm_acknowledgement(
                    event_id=req.event_id,
                    alarm_id=req.alarm_id,
                    operator=req.operator,
                    notes=req.notes,
                    timestamp=req.timestamp,
                )
                return {
                    **(action.model_dump() if action else {
                        "event_id": req.event_id,
                        "alarm_id": req.alarm_id,
                        "action_type": "ACKNOWLEDGE",
                        "operator": req.operator.strip() or "anonymous",
                        "timestamp": req.timestamp or current_iso_utc(),
                    }),
                    "alarm_id": req.alarm_id,
                    "alarm_state": "ACTIVE — ACKNOWLEDGED",
                    "already_acknowledged": not created,
                    "writes_to_plc": False,
                }
            if req.action_type.upper() in ("RESOLVE", "RESOLVED"):
                full = orch.get_full_event(req.event_id)
                if full is None:
                    raise ValueError(f"Event '{req.event_id}' not found.")
                story_steps = (full.get("story") or {}).get("steps") or []
                alarm_step = next((step for step in reversed(story_steps) if str(step.get("tag", "")).startswith("ALM-")), None)
                alarm_tag = (alarm_step or {}).get("tag")
                latest = orch.db.get_latest_reading(alarm_tag) if alarm_tag else None
                equipment_id = orch._equipment_for(alarm_tag) if alarm_tag else None
                if not _is_clear_alarm_reading(latest, alarm_tag, (alarm_step or {}).get("timestamp"), equipment_id):
                    raise ValueError("Cannot resolve: a later timestamped reading confirming the alarm input is clear has not been observed.")
            action = orch.audit.log_action(
                event_id=req.event_id,
                operator=req.operator,
                action_type=req.action_type,
                notes=req.notes,
                timestamp=req.timestamp
            )
            transition = {"ACKNOWLEDGE": "ACKNOWLEDGED", "ACKNOWLEDGED": "ACKNOWLEDGED",
                          "RESOLVE": "RESOLVED", "RESOLVED": "RESOLVED",
                          "MARK_UNRESOLVED": "UNRESOLVED"}.get(req.action_type.upper())
            if transition:
                for alarm in orch.db.get_individual_alarms(req.event_id):
                    orch.db.record_alarm_transition(alarm["alarm_id"], req.event_id, transition,
                                                    req.operator, action.timestamp, req.notes)
            return action.model_dump()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/incidents/{event_id}/unresolved")
    async def mark_incident_unresolved(event_id: str, req: MarkUnresolvedRequest):
        """Record a distinct unresolved status transition without changing telemetry."""
        if orch.get_full_event(event_id) is None:
            raise HTTPException(status_code=404, detail="Incident not found.")
        try:
            action = orch.audit.log_action(
                event_id=event_id,
                operator=req.operator.strip(),
                action_type="MARK_UNRESOLVED",
                notes=req.reason.strip() if req.reason and req.reason.strip() else None,
                timestamp=req.timestamp,
            )
            for alarm in orch.db.get_individual_alarms(event_id):
                orch.db.record_alarm_transition(alarm["alarm_id"], event_id, "UNRESOLVED",
                                                req.operator.strip(), action.timestamp, req.reason)
        except ValueError:
            raise HTTPException(status_code=400, detail="Incident status could not be updated.")
        return {
            "event_id": event_id,
            "status": "UNRESOLVED",
            "is_open": True,
            "action": action.model_dump(),
        }

    @router.get("/handover/current")
    async def get_current_handover():
        """Regenerate the handover from stored records and configured shift timing."""
        shift = configured_shift_window()
        start = shift.get("start") if shift else None
        end = shift.get("end") if shift else None
        summary = build_handover_summary(orch.db, start, end)
        summary["sop_reference"] = {
            "sop_id": "SOP-GEN-003", "title": "Alarm Response and Shift Handover",
            "revision": "0 (Draft for review)", "approval_status": "Draft for review — not approved",
            "approved": False, "document_status": "Revision 0 — Draft for review. Approval table is incomplete. REFERENCE ONLY — NOT APPROVED.",
            "requirements": [
                "Complete the shift log before handover.",
                "Conduct a face-to-face handover at the control panel for at least 15 minutes.",
                "Review open alarms, equipment out of service, active permits and LOTO, process changes, abnormal readings, chemical and polymer stock, and pending laboratory results.",
                "The incoming operator reviews the log, walks key areas, and signs to accept the plant.",
                "The outgoing operator remains available until the incoming operator confirms understanding.",
            ],
        }
        previous = orch.db.list_shift_handovers({"date": shift["date"], "shift": shift["name"]}, limit=1) if shift else []
        summary["latest_handover"] = previous[0] if previous else None
        summary["current_shift"] = shift or {"name": None, "date": None, "start": None, "end": None,
                                             "configured": False, "status": "Shift timing not configured"}
        summary["outgoing_operator_session"] = {"status": "Unavailable", "operator": None,
                                                 "detail": "No authenticated operator session is configured."}
        summary["shift_narrative"] = generate_shift_narrative(summary)
        return summary

    @router.get("/handover/sop-reference")
    async def handover_sop_reference():
        return {
            "sop_id": "SOP-GEN-003", "title": "Alarm Response and Shift Handover",
            "revision": "0 (Draft for review)", "approval_status": "Draft for review — not approved",
            "approved": False,
            "document_status": "Revision 0 — Draft for review. Approval table is incomplete. REFERENCE ONLY — NOT APPROVED.",
            "requirements": [
                "Complete the shift log before handover.",
                "Conduct a face-to-face handover at the control panel for at least 15 minutes.",
                "Review open alarms, equipment out of service, active permits and LOTO, process changes, abnormal readings, chemical and polymer stock, and pending laboratory results.",
                "The incoming operator reviews the log, walks key areas, and signs to accept the plant.",
                "The outgoing operator remains available until the incoming operator confirms understanding.",
            ],
        }

    @router.post("/handover/records")
    async def submit_handover(req: HandoverSubmitRequest):
        try:
            start_dt = datetime.fromisoformat(req.shift_start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(req.shift_end.replace("Z", "+00:00"))
            if start_dt >= end_dt:
                raise ValueError("Shift end must be after shift start.")
            summary = build_handover_summary(orch.db, req.shift_start, req.shift_end)
            summary["shift_narrative"] = generate_shift_narrative(summary)
            summary["sop_reference"] = {
                "sop_id": "SOP-GEN-003", "revision": "0 (Draft for review)",
                "approval_status": "Draft for review — not approved", "approved": False,
                "face_to_face": True, "minimum_duration_minutes": 15,
                "incoming_walkthrough_required": True, "acceptance_signature_required": True,
            }
            field_names = ["outgoing_confirmation", "shift_notes", "equipment_observations", "maintenance_updates",
                           "important_context", "unresolved_issues", "highlighted_alarms", "pending_work",
                           "equipment_out_of_service", "active_permits_loto", "process_changes", "abnormal_readings",
                           "chemical_polymer_stock", "pending_laboratory_results"]
            manual_fields = {name: (req.fields.get(name) or "").strip() or "Not recorded" for name in field_names}
            entries = []
            for key in ("open_alarms", "unacknowledged_alarms", "unresolved_incidents", "outstanding_operator_actions"):
                source_items = summary.get(key) or []
                if isinstance(source_items, dict):
                    source_items = source_items.get("items") or []
                for index, item in enumerate(source_items):
                    identity = item.get("alarm_record_id") or item.get("incident_id") or item.get("action_id") or index
                    entries.append({"item_id": f"{key}:{identity}", "category": key, "item": item})
            for key, value in manual_fields.items():
                if value != "Not recorded":
                    entries.append({"item_id": f"manual:{key}", "category": key, "value": value,
                                    "recorded": True})
            submitted_at = current_iso_utc()
            record = {
                "handover_id": str(uuid.uuid4()), "shift_date": req.shift_date,
                "shift_name": req.shift_name, "shift_start": req.shift_start, "shift_end": req.shift_end,
                "outgoing_operator": req.outgoing_operator.strip(), "incoming_operator": (req.incoming_operator or "").strip() or None,
                "submitted_at": submitted_at, "status": "PENDING_RECEIPT", "summary": summary,
                "manual_fields": manual_fields, "entries": entries,
            }
            orch.db.save_shift_handover(record)
            return {**record, "item_responses": []}
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.get("/handover/records")
    async def list_handover_records(
        date: Optional[str] = None, shift: Optional[str] = None, operator: Optional[str] = None,
        equipment: Optional[str] = None, incident: Optional[str] = None,
        limit: int = Query(100, ge=1, le=500),
    ):
        records = orch.db.list_shift_handovers({"date": date, "shift": shift, "operator": operator}, limit)
        if equipment:
            records = [row for row in records if equipment.casefold() in json.dumps(row.get("entries", []), ensure_ascii=False).casefold()]
        if incident:
            records = [row for row in records if incident.casefold() in json.dumps(row.get("summary", {}), ensure_ascii=False).casefold()]
        for row in records:
            row["item_responses"] = orch.db.get_handover_item_responses(row["handover_id"])
        return {"handovers": records, "count": len(records)}

    @router.get("/handover/records/{handover_id}")
    async def get_handover_record(handover_id: str):
        record = orch.db.get_shift_handover(handover_id)
        if not record:
            raise HTTPException(status_code=404, detail="Handover record not found.")
        record["item_responses"] = orch.db.get_handover_item_responses(handover_id)
        return record

    @router.post("/handover/records/{handover_id}/items/{item_id}/response")
    async def respond_to_handover_item(handover_id: str, item_id: str, req: HandoverItemResponseRequest):
        record = orch.db.get_shift_handover(handover_id)
        if not record:
            raise HTTPException(status_code=404, detail="Handover record not found.")
        if not any(entry.get("item_id") == item_id for entry in record.get("entries", [])):
            raise HTTPException(status_code=404, detail="Handover item not found.")
        response = orch.db.save_handover_item_response(
            handover_id, item_id, req.operator.strip(), req.comment.strip() if req.comment and req.comment.strip() else None,
            req.acknowledged, current_iso_utc(),
        )
        return {"response": response, "alarm_or_incident_state_changed": False}

    @router.post("/handover/records/{handover_id}/confirm")
    async def confirm_handover_record(handover_id: str, req: HandoverConfirmRequest):
        record = orch.db.get_shift_handover(handover_id)
        if not record:
            raise HTTPException(status_code=404, detail="Handover record not found.")
        timestamp = current_iso_utc()
        try:
            orch.db.confirm_shift_handover(handover_id, req.incoming_operator.strip(), req.signature_name.strip(), timestamp,
                                           req.face_to_face_confirmed, req.walkthrough_confirmed)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        record = orch.db.get_shift_handover(handover_id)
        record["item_responses"] = orch.db.get_handover_item_responses(handover_id)
        record["alarm_or_incident_state_changed"] = False
        return record

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
        """List the ten curated primary scenarios; legacy registry IDs remain runnable."""
        return {"scenarios": list_primary_demo_scenarios()}

    def _last_simulated_timestamp():
        """Timestamp of the newest simulated reading, as an aware datetime."""
        try:
            row = orch.db._get_connection().execute(
                "SELECT timestamp FROM tag_readings WHERE data_source = 'simulated' "
                "ORDER BY julianday(timestamp) DESC LIMIT 1").fetchone()
        except Exception:
            return None
        if not row or not row[0]:
            return None
        try:
            value = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        except ValueError:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    @router.post("/scenarios/run")
    async def run_scenario_endpoint(req: ScenarioRunRequest):
        """
        Execute a synthetic telemetry scenario in the background asynchronously,
        streaming readings into the live orchestrator pipeline without blocking the event loop.
        """
        if simulation_state["status"] in ("running", "recovering"):
            started_at = simulation_state.get("started_at")
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds() if started_at else None
            # A run that never finished (e.g. the task was killed) must not
            # block the Scenario Lab forever.
            if elapsed is not None and elapsed > SCENARIO_STALE_AFTER_SECONDS:
                logger.warning("Scenario %s marked stale after %.0fs; allowing a new run",
                               simulation_state.get("scenario_id"), elapsed)
                simulation_state["status"] = "error"
            else:
                raise HTTPException(status_code=409, detail={
                    "message": "A synthetic scenario is already running. Duplicate submission ignored; no second incident was created.",
                    "running_scenario_id": simulation_state.get("scenario_id"),
                    "status": simulation_state.get("status"),
                    "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None,
                })
        try:
            from scenarios import get_scenario, is_primary_scenario
            if not is_primary_scenario(req.scenario_id) and \
                    os.environ.get("OPSLENS_ENABLE_LEGACY_SCENARIOS", "false").lower() not in ("1", "true", "yes"):
                raise HTTPException(status_code=400, detail={
                    "message": f"'{req.scenario_id}' is not one of the six Scenario Lab incidents.",
                    "stage": "validation"})
            scenario_duration = float(get_scenario(req.scenario_id).duration_seconds)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "stage": "validation"})
        # A scenario whose primary alarm is still active in an open incident
        # cannot re-annunciate it; running it again would produce nothing new.
        import incident_catalog as _ic
        _spec = _ic.SCENARIO_BY_ID.get(req.scenario_id)
        if _spec is not None:
            for _cand in orch.db.get_candidate_events():
                if _cand.primary_tag != _spec.primary_alarm:
                    continue
                for _a in orch.db.get_individual_alarms(_cand.event_id):
                    if _a.get("tag") == _spec.primary_alarm and str(_a.get("lifecycle_state")).upper() in ("ACTIVE", "ACKNOWLEDGED"):
                        raise HTTPException(status_code=409, detail={
                            "message": (f"{_spec.primary_alarm} is still active in open incident {_cand.event_id[:8]}. "
                                        "Run the simulated fix (or reset demo data) before starting this scenario again."),
                            "stage": "alarm_still_active", "event_id": _cand.event_id})
        simulation_state.update({"status": "running", "scenario_id": req.scenario_id, "event_id": None,
                                 "started_at": datetime.now(timezone.utc), "error": None,
                                 "duration_seconds": scenario_duration, "speed_multiplier": req.speed_multiplier,
                                 "readings_emitted": 0, "samples_emitted": 0, "simulated_elapsed_seconds": 0.0,
                                 "stage": "generating_telemetry", "stopped": False})

        # Run boundary: earlier incidents of OTHER scenarios stop absorbing
        # readings, so shared downstream tags (AER-201-MLSS, EFF-301-TSS) and
        # the clustering time window cannot merge two incidents.
        if _spec is not None:
            sealed = orch.dedup.seal_clusters(
                keep=lambda c: _ic.scenario_for_incident(c.primary_tag, c.clustered_tags) is _spec)
            if sealed:
                logger.info("Scenario %s: sealed %d earlier incident cluster(s) %s", req.scenario_id, len(sealed), [e[:8] for e in sealed])
        pre_run_event_ids = {c.event_id for c in orch.db.get_candidate_events()}
        # Repeat counts of this scenario's primary alarm before the run, so a
        # recurrence folded into an already-open incident can be recognised.
        def _primary_repeat_counts():
            from scenarios import get_scenario as _gs
            alarm_tag = getattr(getattr(_gs(req.scenario_id), "spec", None), "primary_alarm", None)
            counts = {}
            for cand in orch.db.get_candidate_events():
                if alarm_tag and cand.primary_tag == alarm_tag:
                    for a in orch.db.get_individual_alarms(cand.event_id):
                        if a.get("tag") == alarm_tag:
                            counts[cand.event_id] = a.get("repeat_count") or 1
            return counts
        pre_run_repeats = _primary_repeat_counts()

        async def _run():
            try:
                # Fast-forwarded scenarios are stamped so that the last sample
                # lands at "now": simulated timestamps never lie in the future,
                # so operator acknowledgements are never earlier than the alarm.
                speed = req.speed_multiplier if req.speed_multiplier and req.speed_multiplier > 0 else 1.0
                compression = 0.0 if speed == float("inf") else max(0.0, 1.0 - 1.0 / speed)
                start_time = datetime.now(timezone.utc) - timedelta(seconds=scenario_duration * compression)
                # Simulated time is monotonic across runs: a new run never
                # starts before the last simulated reading (e.g. the previous
                # run's after-fix values), or "latest reading" would show that
                # earlier run's normal values instead of this run's alarm.
                last_sim = _last_simulated_timestamp()
                if last_sim and start_time <= last_sim:
                    start_time = last_sim + timedelta(seconds=2.0)
                gen = SyntheticDataGenerator(db=orch.db, sample_interval=2.0, start_time=start_time)
                simulation_state["generator"] = gen
                last_ts = None
                async for reading in gen.run_scenario_async(req.scenario_id, speed_multiplier=req.speed_multiplier):
                    await orch.process_reading(reading)
                    simulation_state["readings_emitted"] = simulation_state.get("readings_emitted", 0) + 1
                    if reading.timestamp != last_ts:
                        last_ts = reading.timestamp
                        simulation_state["samples_emitted"] = simulation_state.get("samples_emitted", 0) + 1
                        simulation_state["simulated_elapsed_seconds"] = round(gen.scenario_elapsed, 1)
                simulation_state["stage"] = "processing_incident"

                # Await in-flight worker tasks
                if orch._in_flight_tasks:
                    await asyncio.gather(*orch._in_flight_tasks.values(), return_exceptions=True)

                # Guarantee final re-evaluation pass across open events to ensure full join completion
                # Candidate rows do not have a status column; openness is
                # tracked by event_stories/operator actions. Limit the final
                # refresh to event IDs the audit layer still considers open.
                # Only incidents created by THIS run are refreshed and linked to
                # it; an earlier incident is never presented as this run's result.
                run_candidates = [c for c in orch.db.get_candidate_events() if c.event_id not in pre_run_event_ids]
                for candidate in run_candidates:
                    await orch.process_candidate_event(candidate)
                from scenarios import get_scenario as _get
                expected_alarm = getattr(getattr(_get(req.scenario_id), "spec", None), "primary_alarm", None)
                refreshed = [c for c in orch.db.get_candidate_events() if c.event_id not in pre_run_event_ids]
                preferred = [c.event_id for c in refreshed if c.primary_tag == expected_alarm]
                simulation_state["event_id"] = (preferred or [c.event_id for c in refreshed] or [None])[-1]
                simulation_state["run_event_ids"] = [c.event_id for c in refreshed]
                repeated = False
                if not simulation_state["event_id"] and expected_alarm:
                    # The same alarm re-annunciated while its earlier incident
                    # is still open: by design it is folded into that incident
                    # (repeat count) instead of creating a duplicate. Report it.
                    for eid, count in _primary_repeat_counts().items():
                        if eid in pre_run_repeats and count > pre_run_repeats[eid]:
                            full = orch.get_full_event(eid)
                            if full and full.get("status") != "RESOLVED":
                                simulation_state["event_id"] = eid
                                simulation_state["repeat_count"] = count
                                repeated = True
                if gen.stop_requested:
                    simulation_state["status"] = "stopped"
                    simulation_state["stage"] = "stopped_by_user"
                else:
                    simulation_state["status"] = "awaiting_corrective_action" if simulation_state["event_id"] else "completed"
                    simulation_state["stage"] = ("incident_repeated" if repeated else "incident_published") if simulation_state["event_id"] else "no_incident"
            except Exception as e:
                logger.exception("Scenario %s failed", req.scenario_id)
                simulation_state["status"] = "error"
                simulation_state["error"] = f"{type(e).__name__}: {e}"

        asyncio.create_task(_run())
        return {
            "status": "started",
            "scenario_id": req.scenario_id,
            "speed_multiplier": req.speed_multiplier
        }

    @router.get("/scenarios/status")
    async def get_scenario_status():
        data = {key: (value.isoformat() if isinstance(value, datetime) else value)
                for key, value in simulation_state.items() if key != "generator"}
        eid = simulation_state.get("event_id")
        # While a run is in progress its incident may not exist yet; never
        # report an older incident as the result of the current run.
        if not eid and simulation_state.get("status") in ("idle", None):
            open_events = orch.audit.get_open_events()
            if open_events:
                eid = open_events[-1]
            else:
                candidates = orch.db.get_candidate_events()
                open_cands = [c for c in candidates if c.lifecycle_state != "RESOLVED"]
                if open_cands:
                    eid = open_cands[-1].event_id
                elif candidates:
                    eid = candidates[-1].event_id

        if eid:
            data["event_id"] = eid
            candidates = orch.db.get_candidate_events(event_id=eid)
            if candidates:
                cand = candidates[0]
                data["repeat_count"] = cand.repeat_count
                data["last_seen_timestamp"] = cand.last_seen_timestamp or cand.trigger_timestamp
                data["lifecycle_state"] = cand.lifecycle_state
                data["urgency_score"] = cand.urgency.urgency_score if cand.urgency else None
                data["alarm_tag"] = cand.primary_tag
                data["equipment_id"] = orch._equipment_for(cand.primary_tag)
                if data.get("status") in ("idle", None) and cand.lifecycle_state != "RESOLVED":
                    data["status"] = "awaiting_corrective_action"
        duration = simulation_state.get("duration_seconds")
        if duration:
            data["progress"] = round(min(1.0, (simulation_state.get("simulated_elapsed_seconds") or 0.0) / duration), 3)
        return data

    @router.post("/scenarios/stop")
    async def stop_scenario():
        """Stop telemetry generation for the running simulation. Readings and
        any incident already created are kept; nothing is sent to a PLC."""
        gen = simulation_state.get("generator")
        if simulation_state.get("status") != "running" or gen is None:
            raise HTTPException(status_code=409, detail={"message": "No simulated scenario is running.",
                                                         "status": simulation_state.get("status")})
        gen.stop_requested = True
        simulation_state["stage"] = "stopping"
        return {"status": "stopping", "scenario_id": simulation_state.get("scenario_id"),
                "message": "Telemetry generation will stop after the current sample."}

    @router.get("/scenarios/{scenario_id}/details")
    async def scenario_details(scenario_id: str):
        """Incident-map table, SOP mapping and coverage for one Scenario Lab incident."""
        import incident_catalog
        spec = incident_catalog.SCENARIO_BY_ID.get(scenario_id)
        if spec is None:
            raise HTTPException(status_code=404, detail="Unknown Scenario Lab incident.")
        return incident_catalog.scenario_summary(spec)

    @router.post("/scenarios/trigger-alarm-repeat")
    async def trigger_alarm_repeat():
        """
        Resend the active alarm for the currently active scenario through the real
        backend deduplication pipeline without creating a new incident or clearing the alarm.
        """
        if simulation_state.get("status") not in ("awaiting_corrective_action", "running"):
            open_events = orch.audit.get_open_events()
            candidate_events = orch.db.get_candidate_events()
            open_candidates = [c for c in candidate_events if c.lifecycle_state != "RESOLVED"]
            if not open_events and not simulation_state.get("event_id") and not open_candidates:
                raise HTTPException(
                    status_code=409,
                    detail="No active synthetic incident is awaiting repeat notifications."
                )

        event_id = simulation_state.get("event_id")
        if not event_id:
            open_events = orch.audit.get_open_events()
            if open_events:
                event_id = open_events[-1]
            else:
                candidate_events = orch.db.get_candidate_events()
                if candidate_events:
                    event_id = candidate_events[-1].event_id

        full_event = orch.get_full_event(event_id) if event_id else None
        steps = (full_event.get("story") or {}).get("steps") or [] if full_event else []
        alarm_step = next((step for step in reversed(steps) if str(step.get("tag", "")).startswith("ALM-")), None)
        alarm_tag = (alarm_step or {}).get("tag") or "ALM-P02-HP"
        equipment = (full_event.get("candidate") or {}).get("equipment_id") if full_event else None
        if not equipment:
            equipment = orch._equipment_for(alarm_tag)

        now_dt = datetime.now(timezone.utc)
        now_ts = now_dt.isoformat().replace("+00:00", "Z")

        reading = TagReading(
            tag=alarm_tag,
            value=True,
            timestamp=now_ts,
            unit="status",
            equipment_id=equipment,
            alarm_severity=(full_event.get("candidate") or {}).get("alarm_severity") if full_event else None,
            # An explicit re-send of the active notification; counted as a repeat
            # (periodic samples of an alarm that stays active are not).
            alarm_state="REANNUNCIATED",
            data_quality="VALID",
            data_source="simulated",
            connection_status="simulation",
        )

        orch.db.insert_reading(reading)
        candidate = await orch.process_reading(reading)

        if not event_id and candidate:
            event_id = candidate.event_id

        updated_event = orch.get_full_event(event_id) if event_id else None
        updated_cand = (updated_event.get("candidate") or {}) if updated_event else {}
        repeat_count = updated_cand.get("repeat_count") or (candidate.repeat_count if candidate else 1)
        last_seen = updated_cand.get("last_seen_timestamp") or now_ts

        simulation_state["repeat_count"] = repeat_count
        simulation_state["last_seen_timestamp"] = last_seen
        simulation_state["event_id"] = event_id
        if simulation_state.get("status") not in ("running", "recovering"):
            simulation_state["status"] = "awaiting_corrective_action"

        return {
            "status": "alarm_repeated",
            "event_id": event_id,
            "alarm_tag": alarm_tag,
            "equipment_id": equipment,
            "repeat_count": repeat_count,
            "last_seen_timestamp": last_seen,
            "lifecycle_state": updated_cand.get("lifecycle_state", "ACTIVE"),
            "advisory_only": True,
            "writes_to_plc": False,
            "message": f"Repeat alarm notification processed for {alarm_tag}. Repeat count is now {repeat_count}.",
        }

    @router.post("/scenarios/corrective-action")
    async def apply_simulated_corrective_action():
        """Run the Pump-02 synthetic recovery trajectory; never calls a control adapter."""
        if simulation_state.get("status") != "awaiting_corrective_action" or not simulation_state.get("generator"):
            raise HTTPException(status_code=409, detail="No completed synthetic scenario is awaiting a simulated corrective action.")
        from scenarios import is_primary_scenario
        catalog_recovery = is_primary_scenario(simulation_state.get("scenario_id"))
        if not catalog_recovery and simulation_state.get("scenario_id") not in ("valve_restriction", "valve_restriction_cascade", "scenario_a"):
            raise HTTPException(status_code=400, detail="No simulated recovery trajectory is defined for this scenario.")
        event_id = simulation_state.get("event_id")
        full_event = orch.get_full_event(event_id) if event_id else None
        story_steps = (full_event.get("story") or {}).get("steps") or [] if full_event else []
        alarm_step = next((step for step in reversed(story_steps) if str(step.get("tag", "")).startswith("ALM-")), None)
        alarm_tag = (alarm_step or {}).get("tag")
        alarm_timestamp = (alarm_step or {}).get("timestamp")
        equipment_id = (full_event.get("candidate") or {}).get("equipment_id") if full_event else None
        if not equipment_id and alarm_tag:
            equipment_id = orch._equipment_for(alarm_tag)
        if not alarm_tag or not alarm_timestamp or not equipment_id:
            raise HTTPException(status_code=409, detail="The incident's source alarm, timestamp, or equipment could not be verified; recovery cannot confirm clearance.")
        reading_before_recovery = orch.db.get_latest_reading(alarm_tag)
        if reading_before_recovery is None:
            raise HTTPException(status_code=409, detail="No source alarm reading is recorded for this incident.")
        simulation_state["status"] = "recovering"
        try:
            gen = simulation_state["generator"]
            if catalog_recovery:
                # Back-date the after-fix readings like the run itself, but
                # never before the last simulated reading.
                from incident_catalog import RECOVERY_DURATION_S
                floor = _last_simulated_timestamp() or gen.sim_clock
                gen.sim_clock = max(floor + timedelta(seconds=2.0),
                                    datetime.now(timezone.utc) - timedelta(seconds=RECOVERY_DURATION_S * 0.9))
            recovery = gen.run_recovery_async(speed_multiplier=10.0) if catalog_recovery \
                else gen.run_valve_restriction_recovery_async(speed_multiplier=10.0)
            async for reading in recovery:
                await orch.process_reading(reading)
            if orch._in_flight_tasks:
                await asyncio.gather(*orch._in_flight_tasks.values(), return_exceptions=True)
            alarm = orch.db.get_latest_reading(alarm_tag)
            if not _is_clear_alarm_reading(
                alarm,
                alarm_tag,
                alarm_timestamp,
                equipment_id,
                minimum_timestamp=reading_before_recovery.timestamp,
            ):
                simulation_state["status"] = "awaiting_corrective_action"
                raise HTTPException(status_code=409, detail="The simulated recovery did not produce a newer, correctly associated clear reading for this incident.")
            simulation_state["status"] = "alarm_clear_observed"
            simulation_state["timestamp"] = alarm.timestamp
            return {"status": simulation_state["status"], "event_id": event_id, "alarm_tag": alarm_tag, "equipment_id": equipment_id, "alarm_active": False, "timestamp": alarm.timestamp, "source": "synthetic_simulator"}
        except HTTPException:
            raise
        except Exception as exc:
            simulation_state["status"] = "error"
            raise HTTPException(status_code=500, detail=f"Synthetic recovery failed: {exc}")

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
            conn.execute("DELETE FROM assistant_messages")
            conn.execute("DELETE FROM individual_alarms")
        clear_assistant_cache()
        context_assembly_measurements.clear()
        context_assembly_failures.clear()
        try:
            from alarm_lifecycle import get_lifecycle_manager
            get_lifecycle_manager().clear_all()
        except Exception:
            pass
        orch.dedup._active_clusters.clear()
        orch._completed_events.clear()
        orch._in_flight_tasks.clear()
        orch._processed_tags.clear()
        orch._processed_primary.clear()
        orch._pending_updates.clear()
        simulation_state.update({"status": "idle", "scenario_id": None, "event_id": None, "generator": None})
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
            "baselines": baselines,
            "telemetry_mode": "synthetic_or_timestamped_records",
            "eote_live_connection": False,
            "advisory_only": True,
            "llm": provider_status(),
        }

    def _active_retrieval_method() -> str:
        """Report the retrieval path actually available, never a claimed one."""
        import importlib.util
        if importlib.util.find_spec("sentence_transformers") is None:
            return "bm25_keyword_fallback (sentence-transformers not installed)"
        try:
            from sop_retriever import _QDRANT_STORE
            if _QDRANT_STORE is not None and _QDRANT_STORE.health().get("connected"):
                return "qdrant_vector_search"
            if _QDRANT_STORE is None:
                return "qdrant_not_yet_contacted (bm25 fallback if unreachable)"
        except Exception:
            pass
        return "bm25_keyword_fallback (Qdrant unreachable)"

    @router.get("/health")
    async def health_check():
        """Overall OpsLens system health."""
        open_events = orch.audit.get_open_events()
        llm = provider_status()
        llm_error = configuration_error()
        return {
            "status": "ONLINE",
            "service": "OpsLens Edge Intelligence",
            "open_incidents": len(open_events),
            "advisory_only": True,
            "eote_live_connection": False,
            "telemetry_mode": "synthetic_or_timestamped_records",
            "llm": {**llm, "configuration_error": llm_error, "selected": selected_provider()},
            "components": {
                "alarm_engine": "deterministic",
                "correlator": "deterministic",
                "evidence_engine": "deterministic_scoring",
                "sop_retrieval": _active_retrieval_method(),
                "guidance": "sop_then_llm_with_deterministic_fallback",
                "assistant": "record_grounded_with_optional_llm",
            }
        }

    @router.get("/copilot/health")
    async def copilot_health():
        """Hackathon copilot layer: LLM, RAG, and safety posture."""
        llm = provider_status()
        try:
            from sop_retriever import get_qdrant_store
            rag = get_qdrant_store().health()
        except Exception as exc:
            rag = {"connected": False, "error": str(exc), "fallback_method": "bm25"}
        return {
            "advisory_only": True,
            "human_in_the_loop": True,
            "writes_to_plc": False,
            "eote_live_connection": False,
            "demo_fallback": "synthetic_scenarios_and_deterministic_assistant",
            "llm": {**llm, "configuration_error": configuration_error(),
                    "last_diagnosis_call": __import__("ai_diagnosis").LAST_CALL},
            "rag": rag,
            "cache": {"assistant_ttl_seconds": float(os.environ.get("OPSLENS_ASSISTANT_CACHE_TTL", "120"))},
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
        background_tasks: BackgroundTasks,
        sop_id: str = Query(..., min_length=1),
        title: str = Query(..., min_length=1),
        equipment: str = Query(""),
        equipment_type: str = Query(""),
        plant_area: str = Query(""),
        revision: str = Query("unknown"),
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
            if "respond-async" in request.headers.get("prefer", "").lower():
                job_id = uuid.uuid4().hex
                initial = {
                    "job_id": job_id,
                    "status": "processing",
                    "current_stage": "upload_received",
                    "stages": [{"name": "PDF uploaded", "status": "complete", "complete": True}],
                    "data": None,
                    "error": None,
                }
                with _sop_ingestion_jobs_lock:
                    _sop_ingestion_jobs[job_id] = initial
                background_tasks.add_task(_run_sop_ingestion_job, job_id, pdf_bytes, filename, metadata)
                return JSONResponse(status_code=202, content={"status": "processing", "job_id": job_id})

            from pdf_sop_ingestion import PdfExtractionError, PdfIndexingError, ingest_pdf
            from sop_retriever import get_qdrant_store
            result = ingest_pdf(pdf_bytes, filename, metadata, get_qdrant_store())
            return {"status": result.get("status", "indexed"), "data": result}
        except PdfExtractionError as exc:
            raise HTTPException(status_code=422, detail={
                "stage": "extraction_failed",
                "message": str(exc),
                "manual_review_required": "scanned" in str(exc).lower() or "ocr" in str(exc).lower(),
            })
        except PdfIndexingError as exc:
            logger.error("SOP PDF indexing request failed code=%s", exc.code)
            raise HTTPException(status_code=503, detail={"stage": "indexing_failed", "code": exc.code, "message": str(exc)})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"stage": "validation_failed", "message": str(exc)})
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"stage": "indexing_failed", "message": str(exc)})
        except Exception as exc:
            logger.exception("SOP PDF ingestion request failed error_type=%s", type(exc).__name__)
            raise HTTPException(status_code=500, detail={"stage": "ingestion_failed", "message": "SOP ingestion failed before a verified result was recorded. See backend logs for the full diagnostic."})

    @router.get("/sops/ingestion-jobs/{job_id}")
    async def get_sop_ingestion_job(job_id: str):
        with _sop_ingestion_jobs_lock:
            job = _sop_ingestion_jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="SOP ingestion job was not found or has expired after a backend restart.")
            return dict(job)

    @router.get("/sops/{sop_id}/source")
    async def get_sop_source_pdf(sop_id: str, revision: Optional[str] = Query(None), sha256: Optional[str] = Query(None)):
        """Serve the preserved original PDF from local edge storage."""
        from pdf_sop_ingestion import get_pdf_path
        demo_document = None
        try:
            from demo_sop_sections import load_demo_sop_document
            demo_document = load_demo_sop_document(sop_id)
        except Exception:
            pass
        source_id = "SOP-MAN-000" if demo_document else sop_id
        path = get_pdf_path(source_id,
                            revision or (demo_document or {}).get("revision", ""),
                            sha256 or (demo_document or {}).get("sha256", ""))
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"No source PDF is stored for SOP '{sop_id}'.")
        return FileResponse(
            path,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{path.name}"'},
        )

    def _load_keyword_only_pdf(sop_id: str) -> Optional[Dict[str, Any]]:
        """Rebuild page text for a PDF stored without a vector index (BM25 only)."""
        try:
            import fitz
            from pdf_sop_ingestion import PDF_DIR, get_pdf_path
            for metadata_path in sorted(PDF_DIR.glob("*.json"), reverse=True):
                record = json.loads(metadata_path.read_text(encoding="utf-8"))
                if record.get("sop_id") != sop_id or record.get("vector_indexed") is not False:
                    continue
                pdf_path = get_pdf_path(sop_id, record.get("revision", ""), record.get("sha256", ""))
                with fitz.open(pdf_path) as pdf:
                    pages = [{"page": i, "text": page.get_text("text").strip()} for i, page in enumerate(pdf, start=1)]
                return {**record, "content_pages": [p for p in pages if p["text"]],
                        "retrieval_method": "bm25_keyword_only"}
        except Exception as exc:
            logger.info("Keyword-only SOP reconstruction unavailable for %s (%s)", sop_id, type(exc).__name__)
        return None

    @router.get("/sops/{sop_id}")
    async def get_sop(sop_id: str, revision: Optional[str] = Query(None), sha256: Optional[str] = Query(None)):
        """
        Retrieve full SOP content from the configured document/vector store by sop_id.
        Used by the HMI 'View Full Procedure' button.
        Frontend must NOT hardcode SOP steps — it must call this endpoint.
        """
        # Bundled JSON is the source of truth for packaged procedures. Qdrant
        # remains the source for uploaded PDFs and is only needed when the
        # requested document is not bundled.
        doc = _load_sop_document(sop_id)
        if revision and sha256:
            try:
                from sop_retriever import get_qdrant_store
                selected_pdf = get_qdrant_store().get_document(sop_id, document_id=f"{sop_id}::{revision}::{sha256}")
                if selected_pdf:
                    doc = selected_pdf
            except Exception:
                pass
        if not doc:
            doc = _load_keyword_only_pdf(sop_id)
        if doc and (doc.get("steps") or doc.get("content_pages")):
            if not doc.get("document_status"):
                doc["document_status"] = "SOURCE DOCUMENT — approval status not verified"
            return {"status": "found", "sop_id": sop_id, "data": doc}
        if doc:
            raise HTTPException(
                status_code=404,
                detail=f"SOP '{sop_id}' is indexed, but no complete procedure text is available.",
            )
        raise HTTPException(status_code=404, detail=f"SOP '{sop_id}' was not found in the local document store.")

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
        plc = app.state.opcua_adapter.status()
        adapters = [
            {
                "type": "simulator",
                "status": "RUNNING" if simulation_state.get("status") == "running" else "AVAILABLE",
                "source_label": "SIMULATED DATA" if simulation_state.get("status") == "running" else "NO SIMULATION RUNNING",
                "description": "Synthetic telemetry generator for Pump-02 / Compressor-01 scenarios",
                "write_disabled": True,
            },
            {
                "type": "opcua",
                "status": plc["state"].upper(),
                "connected": plc["connected"],
                "configured": plc["configured"],
                "source_label": plc["source_label"],
                "last_read_at": plc["last_read_at"],
                "mapped_tag_count": plc["mapped_tag_count"],
                "missing_tags": plc["missing_tags"],
                "invalid_tags": plc["invalid_tags"],
                "last_error": plc["last_error"],
                "description": "OPC UA client — read-only; reports live readings only while the configured PLC session is healthy",
                "write_disabled": True,
                "requires": None if plc["configured"] else "Set PLC_OPCUA_ENABLED, PLC_OPCUA_ENDPOINT, and an explicit PLC_OPCUA_TAG_MAPPING file",
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
            "simulation": {"status": simulation_state.get("status"),
                "event_id": simulation_state.get("event_id"),
                "source_label": "SIMULATED DATA" if simulation_state.get("status") == "running" else "NO SIMULATION RUNNING"},
            "safety_note": "ALL adapters are READ-ONLY. OpsLens never writes to industrial equipment.",
            "hmi_agnostic": True,
            "common_model": "TagReading (tag, value, timestamp, unit, equipment_id, quality, source)"
        }

    from api.copilot_routes import register_copilot_routes
    register_copilot_routes(router, app, orch, simulation_state)

    app.include_router(router)
    return app


# Default app instance
app = create_app()
