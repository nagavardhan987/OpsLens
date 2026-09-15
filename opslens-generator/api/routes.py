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
from fastapi.responses import StreamingResponse
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
                open_candidates = orch.db.get_candidate_events(status="OPEN")
                for c in open_candidates:
                    await orch.process_candidate_event(c)
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

    app.include_router(router)
    return app


# Default app instance
app = create_app()
