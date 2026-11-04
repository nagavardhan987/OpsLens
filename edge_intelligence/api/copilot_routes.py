"""
OpsLens - Additional read-only routes: PDF-derived alarm configuration,
alarm state summary, operator brief, data-source status and local-LLM health.

All routes are advisory. None of them writes to a PLC or changes equipment.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

import alarm_config

logger = logging.getLogger("opslens.api.copilot")


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def data_source_state(plc_status: Dict[str, Any], simulation_status: Optional[str], latest_source: Optional[str],
                      plc_enabled: bool) -> Dict[str, Any]:
    """Single source of truth for the HMI 'Data source' indicator.

    - SIMULATED: the simulator is the active source (running, or its readings
      are the latest recorded data and no PLC is enabled).
    - LIVE PLC: the OPC UA session is connected and fresh.
    - STALE: the PLC is connected but readings are older than the stale limit.
    - PLC DISCONNECTED: a PLC is enabled/configured but not connected.
    - NO DATA: nothing has been received yet.
    A simulation is never labelled 'PLC DISCONNECTED'.
    """
    latest = str(latest_source or "").lower()
    label = plc_status.get("source_label")
    if label == "LIVE PLC DATA":
        mode, detail = "LIVE PLC", "Read-only OPC UA session connected."
    elif label == "STALE DATA":
        mode, detail = "STALE", "PLC connected but readings are older than the stale limit."
    elif simulation_status in ("running", "recovering") or any(w in latest for w in ("simulat", "synthetic")):
        mode, detail = "SIMULATED", "Synthetic scenario data. Not live PLC telemetry."
    elif plc_enabled:
        mode, detail = "PLC DISCONNECTED", plc_status.get("last_error") or "PLC enabled but no session is connected."
    elif latest:
        mode, detail = "RECORDED", f"Latest readings came from '{latest_source}'."
    else:
        mode, detail = "NO DATA", "No telemetry received yet. Start a scenario or configure the PLC adapter."
    return {
        "mode": mode,
        "detail": detail,
        "simulation_status": simulation_status,
        "plc": {k: plc_status.get(k) for k in ("state", "configured", "connected", "last_read_at", "source_label", "last_error")},
        "plc_enabled": plc_enabled,
        "latest_reading_source": latest_source,
        "read_only": True,
    }


def alarm_state_rows(db, open_event_ids) -> list:
    """ISA-18.2-style state for each alarm input record.

    ACTIVE_UNACK -> ACTIVE_ACK (acknowledged, still active) ->
    RTN_UNACK (returned to normal, not acknowledged) -> NORMAL.
    Acknowledgement never changes the 'active' flag; only the source input does.
    """
    rows = []
    open_ids = set(open_event_ids or [])
    for alarm in db.get_all_individual_alarms():
        tag = alarm.get("tag")
        if not alarm_config.is_alarm_tag(tag):
            continue  # legacy rows created before status/measurement filtering
        latest = db.get_latest_reading(tag)
        input_active = None
        if latest is not None:
            input_active = latest.value is True or str(latest.value).lower() in ("true", "1", "1.0")
        lifecycle = str(alarm.get("lifecycle_state") or "").upper()
        acknowledged = bool(alarm.get("acknowledged_timestamp")) or lifecycle == "ACKNOWLEDGED"
        if lifecycle in ("CLEARED", "RETURNED_TO_NORMAL") and input_active is not True:
            input_active = False
        if input_active is None:
            state = "UNKNOWN"
        elif input_active and acknowledged:
            state = "ACTIVE_ACK"
        elif input_active:
            state = "ACTIVE_UNACK"
        elif acknowledged:
            state = "NORMAL"
        else:
            state = "RTN_UNACK"
        definition = alarm_config.definition_for_tag(tag)
        rows.append({
            "alarm_id": alarm.get("alarm_id"),
            "incident_id": alarm.get("incident_id"),
            "incident_open": alarm.get("incident_id") in open_ids,
            "tag": tag,
            "equipment_id": alarm.get("equipment_id"),
            "state": state,
            "input_active": input_active,
            "acknowledged": acknowledged,
            "first_seen": alarm.get("first_seen_timestamp"),
            "last_seen": alarm.get("last_seen_timestamp"),
            "repeat_count": alarm.get("repeat_count"),
            "source_priority": alarm.get("source_priority") or "NOT SUPPLIED",
            "data_source": getattr(latest, "data_source", None) if latest else None,
            "sop_reference": {
                "sop_id": definition.get("sop_id"), "page": definition.get("source_page"),
                "parameter": definition.get("parameter"),
            } if definition else None,
        })
    order = {"ACTIVE_UNACK": 0, "RTN_UNACK": 1, "ACTIVE_ACK": 2, "UNKNOWN": 3, "NORMAL": 4}
    rows.sort(key=lambda r: (order.get(r["state"], 9), r.get("last_seen") or ""), reverse=False)
    return rows


def register_copilot_routes(router: APIRouter, app, orch, simulation_state: Dict[str, Any]) -> None:

    @router.get("/alarms/reference")
    async def alarm_reference():
        """Alarm limits extracted from SOP-MAN-000 with page citations."""
        return {**alarm_config.summary(), "definitions": alarm_config.definitions()}

    @router.get("/alarms/conflicts")
    async def alarm_conflicts():
        """Differences between the SOP manual and the OpsLens tag registry (reported, not auto-fixed)."""
        conflicts = alarm_config.config_conflicts()
        return {"count": len(conflicts), "conflicts": conflicts,
                "policy": "Neither source is changed automatically. Confirm the site value, then update one source."}

    @router.get("/alarms/limit-check")
    async def alarm_limit_check(tag: str = Query(..., min_length=1), value: Optional[float] = None):
        """Compare a value (or the latest reading) with the manual's limits. Calculated in Python."""
        quality = None
        if value is None:
            latest = orch.db.get_latest_reading(tag)
            if latest is None:
                raise HTTPException(status_code=404, detail=f"No reading recorded for {tag}.")
            value, quality = latest.value, latest.data_quality
        ctx = alarm_config.limit_context(tag, value, data_quality=quality)
        if ctx is None:
            raise HTTPException(status_code=404, detail=f"SOP-MAN-000 has no limit mapped to {tag}.")
        return ctx

    @router.get("/alarms/active")
    async def active_alarm_states():
        """Alarm inputs with ISA-18.2-style states. Acknowledged alarms stay active until the source clears."""
        try:
            open_ids = orch.audit.get_open_events()
            rows = alarm_state_rows(orch.db, open_ids)
        except Exception as exc:
            logger.warning("Active alarm summary unavailable (%s)", type(exc).__name__)
            raise HTTPException(status_code=503, detail="Alarm state summary temporarily unavailable.")
        counts: Dict[str, int] = {}
        for row in rows:
            counts[row["state"]] = counts.get(row["state"], 0) + 1
        return {
            "alarms": rows,
            "counts": counts,
            "active_total": counts.get("ACTIVE_UNACK", 0) + counts.get("ACTIVE_ACK", 0),
            "unacknowledged_total": counts.get("ACTIVE_UNACK", 0) + counts.get("RTN_UNACK", 0),
            "note": "Only configured alarm inputs (ALM-*, *-FAULT, *-TRIP) are alarms. Status tags such as P101-RUN and analog measurements are evidence.",
        }

    @router.get("/events/{event_id}/brief")
    async def operator_brief(event_id: str):
        """Deterministic eight-part operator brief (no LLM)."""
        full_event = orch.get_full_event(event_id)
        if not full_event:
            raise HTTPException(status_code=404, detail="Incident not found.")
        from operator_brief import build_operator_brief
        try:
            # Runs on the event loop: it only reads SQLite, and the shared
            # connection must not be used from a second thread.
            return build_operator_brief(full_event, orch.db)
        except Exception as exc:
            logger.exception("Operator brief failed for %s", event_id)
            raise HTTPException(status_code=500, detail=f"Operator brief could not be built ({type(exc).__name__}).")

    def _diagnosis_facts(event_id: str):
        full_event = orch.get_full_event(event_id)
        if not full_event:
            raise HTTPException(status_code=404, detail="Incident not found.")
        from ai_diagnosis import build_facts
        # Facts are read from SQLite on the event loop; only the model call
        # runs in a worker thread.
        return build_facts(full_event, orch.db)

    @router.get("/events/{event_id}/diagnosis")
    async def incident_diagnosis(event_id: str):
        """Seven-section diagnosis: Qwen via Ollama, or a labelled deterministic fallback."""
        facts = _diagnosis_facts(event_id)
        from ai_diagnosis import stream_diagnosis_from_facts

        def run():
            final = {}
            for item in stream_diagnosis_from_facts(facts):
                if item["type"] == "done":
                    final = item
            return final
        return await asyncio.to_thread(run)

    @router.get("/events/{event_id}/diagnosis/stream")
    async def incident_diagnosis_stream(event_id: str):
        """Server-sent events: meta, token (unvalidated draft), done (validated result)."""
        import json as _json
        from fastapi.responses import StreamingResponse
        facts = _diagnosis_facts(event_id)
        from ai_diagnosis import stream_diagnosis_from_facts

        def generate():
            try:
                for item in stream_diagnosis_from_facts(facts):
                    yield f"event: {item['type']}\ndata: {_json.dumps(item, default=str)}\n\n"
            except Exception as exc:  # never leave the client hanging
                logger.exception("Diagnosis stream failed for %s", event_id)
                yield f"event: error\ndata: {_json.dumps({'detail': type(exc).__name__})}\n\n"
        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.get("/events/{event_id}/trends")
    async def incident_trends(event_id: str, points: int = Query(48, ge=8, le=200)):
        """Recorded readings for this incident's own analog tags, with normal
        band and SOP limits from the incident map. Read-only."""
        full_event = orch.get_full_event(event_id)
        if not full_event:
            raise HTTPException(status_code=404, detail="Incident not found.")
        import incident_catalog
        from datetime import timedelta
        cand = full_event.get("candidate") or {}
        spec = incident_catalog.scenario_for_incident(full_event.get("primary_tag"), cand.get("clustered_tags"))
        trigger = full_event.get("trigger_timestamp")
        try:
            t0 = datetime.fromisoformat(str(trigger).replace("Z", "+00:00"))
        except ValueError:
            t0 = None
        start = (t0 - timedelta(seconds=240)).isoformat().replace("+00:00", "Z") if t0 else None
        signals = list(spec.signals) if spec else []
        if not spec:
            from tag_registry import TAG_REGISTRY
            for tag in cand.get("clustered_tags") or []:
                entry = TAG_REGISTRY.get(tag)
                if entry and entry.unit not in ("bool", "status") and not tag.startswith("ALM-"):
                    signals.append(type("S", (), {"tag": tag, "label": entry.description, "unit": entry.unit,
                                                  "equipment_id": entry.equipment_id, "normal": None,
                                                  "normal_text": None, "limits": ()})())
        out = []
        for sig in signals:
            rows = orch.db.get_readings(tag=sig.tag, start_time=start, limit=2000)
            series = [(r.timestamp, float(r.value)) for r in rows if isinstance(r.value, (int, float)) and not isinstance(r.value, bool)]
            if len(series) > points:
                step = len(series) / points
                series = [series[int(i * step)] for i in range(points - 1)] + [series[-1]]
            latest = series[-1][1] if series else None
            beyond = None
            for lim in sig.limits or ():
                if latest is not None and ((lim.direction == "high" and latest >= lim.value) or (lim.direction == "low" and latest <= lim.value)):
                    beyond = lim.label
            normal = list(sig.normal) if isinstance(getattr(sig, "normal", None), tuple) else None
            out.append({
                "tag": sig.tag, "label": sig.label, "unit": sig.unit, "equipment_id": sig.equipment_id,
                "normal": normal, "normal_text": getattr(sig, "normal_text", None),
                "limits": [{"value": l.value, "direction": l.direction, "label": l.label} for l in (sig.limits or ())],
                "points": [{"t": t, "v": round(v, 3)} for t, v in series],
                "latest": latest, "beyond_limit": beyond,
                "data_source": (rows[-1].data_source if rows else None),
            })
        return {"event_id": event_id, "scenario_id": spec.scenario_id if spec else None,
                "trigger_timestamp": trigger, "signals": out,
                "note": "Recorded values only. Limits from SOP-MAN-000 (draft, not approved)."}

    @router.get("/plant/overview")
    async def plant_overview():
        """Monitoring view: latest recorded value of every plant tag, grouped
        by equipment, with its normal band. Not an incident. Read-only."""
        import incident_catalog
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        stale_after = float(os.environ.get("OPSLENS_STALE_AFTER_SECONDS", "120"))
        groups: Dict[str, Any] = {eq: [] for eq in incident_catalog.PLANT_EQUIPMENT}
        for tag, sig in incident_catalog.plant_signals().items():
            row = orch.db.get_latest_reading(tag)
            age = None
            if row is not None:
                try:
                    age = (now - datetime.fromisoformat(str(row.timestamp).replace("Z", "+00:00"))).total_seconds()
                except ValueError:
                    age = None
            value = row.value if row is not None else None
            beyond = None
            for lim in sig.limits:
                if isinstance(value, (int, float)) and not isinstance(value, bool) and (
                        (lim.direction == "high" and value >= lim.value) or (lim.direction == "low" and value <= lim.value)):
                    beyond = lim.label
            groups.setdefault(sig.equipment_id, []).append({
                "tag": tag, "label": sig.label, "unit": sig.unit, "normal_text": sig.normal_text,
                "value": value, "timestamp": row.timestamp if row is not None else None,
                "data_source": row.data_source if row is not None else None,
                "stale": age is None or age > stale_after, "beyond_limit": beyond,
            })
        return {"generated_at": now.isoformat().replace("+00:00", "Z"), "stale_after_seconds": stale_after,
                "equipment": [{"equipment_id": eq, "signals": sigs} for eq, sigs in groups.items() if sigs],
                "note": "Monitoring view. Values are the latest recorded readings; SIMULATED when produced by the Scenario Lab."}

    @router.get("/datasource")
    async def datasource():
        plc = app.state.opcua_adapter.status()
        latest_source = None
        try:
            row = orch.db._get_connection().execute(
                "SELECT data_source FROM tag_readings ORDER BY id DESC LIMIT 1").fetchone()
            latest_source = row[0] if row else None
        except Exception:
            latest_source = None
        enabled = str(os.environ.get("PLC_OPCUA_ENABLED", "false")).lower() in ("1", "true", "yes")
        return data_source_state(plc, simulation_state.get("status"), latest_source, enabled)

    @router.get("/copilot/ollama")
    async def ollama_status():
        """Local LLM status. The app works without Ollama (deterministic answers)."""
        from edge_slm import ollama_health, local_llm_timeout
        from llm_provider import provider_status
        health = await asyncio.to_thread(ollama_health)
        provider = provider_status()
        selected = provider.get("provider") == "ollama"
        return {
            **health,
            "selected_provider": provider.get("provider"),
            "ollama_selected": selected,
            "timeout_seconds": local_llm_timeout(),
            "verified_in_this_process": provider.get("verified"),
            "last_diagnosis_call": __import__("ai_diagnosis").LAST_CALL,
            "fallback": "deterministic record-grounded answers and verbatim SOP steps",
            "status_label": (
                "AI: deterministic (no LLM selected)" if not selected else
                "AI: Ollama ready" if health["reachable"] and health["model_installed"] else
                "AI: Ollama model missing" if health["reachable"] else
                "AI: Ollama unavailable — deterministic fallback"
            ),
        }

    @router.post("/copilot/ollama/warmup")
    async def ollama_warmup():
        """Load the local model into memory so the first question is not a cold start."""
        from edge_slm import warm_up_ollama
        return await asyncio.to_thread(warm_up_ollama)

    @router.get("/diagnostics")
    async def diagnostics():
        """One-call health summary for the troubleshooting guide."""
        from llm_provider import provider_status
        import importlib.util
        sentence = importlib.util.find_spec("sentence_transformers") is not None
        try:
            from sop_retriever import _QDRANT_STORE
            qdrant_connected = bool(_QDRANT_STORE and _QDRANT_STORE.health().get("connected"))
        except Exception:
            qdrant_connected = False
        counts = {}
        try:
            conn = orch.db._get_connection()
            for table in ("tag_readings", "candidate_events", "individual_alarms", "operator_actions", "guidance"):
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception as exc:
            counts["error"] = type(exc).__name__
        return {
            "backend": "ONLINE",
            "database": str(getattr(orch.db, "db_path", "")),
            "row_counts": counts,
            "simulation": {k: v for k, v in simulation_state.items() if k != "generator"},
            "retrieval": {
                "sentence_transformers_installed": sentence,
                "qdrant_connected": qdrant_connected,
                "active_method": "qdrant_vector_search" if (sentence and qdrant_connected) else "bm25_keyword (fallback)",
                "curated_manual_sections": "bundled_pdf_section (SOP-MAN-000 page ranges)",
            },
            "llm": provider_status(),
            "alarm_reference": alarm_config.summary(),
            "plc": app.state.opcua_adapter.status(),
            "advisory_only": True,
            "writes_to_plc": False,
        }
