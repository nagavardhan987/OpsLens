"""
OpsLens REST API Router
Exposes the clean REST/JSON contract for EcoStruxure Operator Terminal Expert / Lightweight HMI.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from backend.data.scenario_data import (
    NORMAL_MACHINE_STATE,
    INCIDENT_MACHINE_STATE,
    TIMELINE_EVENTS,
    EVIDENCE_PAYLOAD,
    SOP_HP_P02,
    NEXT_BEST_ACTIONS,
    FIXED_OPERATOR
)
from backend.intelligence.alarm_prioritizer import AlarmPrioritizer
from backend.intelligence.context_correlator import ContextCorrelator
from backend.intelligence.event_story import EventStoryEngine
from backend.intelligence.evidence_engine import EvidenceEngine
from backend.intelligence.sop_retriever import SOPRetriever
from backend.intelligence.operator_actions import OperatorActionLogger
from backend.intelligence.shift_handover import ShiftHandoverEngine

router = APIRouter(prefix="/api")

# In-memory singleton state
class AppState:
    def __init__(self):
        self.is_incident: bool = False
        self.action_logger = OperatorActionLogger()
        self.current_monitoring_status: str = "Monitoring"

    def reset(self):
        self.is_incident = False
        self.action_logger.clear()
        self.current_monitoring_status = "Nominal"

state = AppState()


class ActionRequest(BaseModel):
    action_id: str
    action_name: str
    notes: Optional[str] = ""


@router.get("/machine")
def get_machine():
    """Current Pump-02 state (normal or incident)"""
    if state.is_incident:
        return {"status": "success", "data": INCIDENT_MACHINE_STATE}
    return {"status": "success", "data": NORMAL_MACHINE_STATE}


@router.get("/alarms")
def get_alarms():
    """Active alarms prioritized with micro-explanation"""
    data = AlarmPrioritizer.prioritize(state.is_incident)
    return {"status": "success", "data": data}


@router.get("/incident")
def get_incident():
    """Current incident summary, context correlation, and status"""
    correlation = ContextCorrelator.correlate(state.is_incident)
    prioritization = AlarmPrioritizer.prioritize(state.is_incident)
    return {
        "status": "success",
        "data": {
            "is_incident": state.is_incident,
            "incident_name": "Pump-02 – High Pressure" if state.is_incident else "None",
            "micro_explanation": prioritization.get("micro_explanation"),
            "correlation": correlation
        }
    }


@router.get("/event-story")
def get_event_story():
    """Chronological timeline of events"""
    story = EventStoryEngine.get_summary(state.is_incident)
    return {"status": "success", "data": story}


@router.get("/evidence")
def get_evidence():
    """Likely contributor + supporting evidence with exact verified percentages"""
    evidence = EvidenceEngine.get_evidence(state.is_incident)
    return {"status": "success", "data": evidence}


@router.get("/sop")
def get_sop():
    """Relevant SOP for current incident"""
    sop_data = SOPRetriever.get_for_incident(state.is_incident)
    return {"status": "success", "data": sop_data}


@router.post("/operator-action")
def record_operator_action(req: ActionRequest):
    """Record an operator action (human-in-the-loop)"""
    record = state.action_logger.record_action(
        action_id=req.action_id,
        action_name=req.action_name,
        notes=req.notes or ""
    )
    # If action was marked complete or verified, update status
    if "COMPLETE" in req.action_id.upper():
        state.current_monitoring_status = "Action Completed / Stabilizing"
    else:
        state.current_monitoring_status = "Monitoring"

    handover = ShiftHandoverEngine.generate_summary(
        is_incident=state.is_incident,
        operator_actions=state.action_logger.get_actions(),
        current_status=state.current_monitoring_status
    )
    return {
        "status": "success",
        "message": "Operator action recorded",
        "record": record,
        "updated_handover": handover
    }


@router.get("/handover")
def get_handover():
    """Shift handover summary reflecting logged actions"""
    handover = ShiftHandoverEngine.generate_summary(
        is_incident=state.is_incident,
        operator_actions=state.action_logger.get_actions(),
        current_status=state.current_monitoring_status
    )
    return {"status": "success", "data": handover}


@router.post("/demo/start")
def start_demo():
    """
    Trigger full incident simulation.
    Returns the complete precomputed deterministic payload in one response.
    """
    state.is_incident = True
    state.current_monitoring_status = "Monitoring"

    # Precomputed payload for deterministic client-side pacing
    full_payload = {
        "incident_active": True,
        "machine": INCIDENT_MACHINE_STATE,
        "alarms": AlarmPrioritizer.prioritize(True),
        "correlation": ContextCorrelator.correlate(True),
        "event_story": EventStoryEngine.get_summary(True),
        "evidence": EvidenceEngine.get_evidence(True),
        "sop": SOPRetriever.get_for_incident(True),
        "next_best_actions": NEXT_BEST_ACTIONS,
        "initial_handover": ShiftHandoverEngine.generate_summary(
            is_incident=True,
            operator_actions=state.action_logger.get_actions(),
            current_status=state.current_monitoring_status
        ),
        "pacing_schedule": [
            {"time_sec": 0, "event_id": "evt-01", "stage": "VALVE_RESTRICTION", "desc": "Valve-04 position: 78% → 43%"},
            {"time_sec": 4, "event_id": "evt-02", "stage": "FLOW_DROP", "desc": "Flow: 82 → 56 L/min"},
            {"time_sec": 6, "event_id": "evt-03", "stage": "MOTOR_SURGE", "desc": "Motor current: 7.8 → 9.2 A"},
            {"time_sec": 8, "event_id": "evt-04", "stage": "PRESSURE_SURGE", "desc": "Pressure: 4.8 → 6.9 bar"},
            {"time_sec": 10, "event_id": "evt-05", "stage": "ALARM_TRIGGER", "desc": "HIGH PRESSURE ALARM TRIP"},
            {"time_sec": 12, "stage": "ANALYSIS_CASCADE", "desc": "OpsLens Context & Evidence Engine Activated"},
            {"time_sec": 14, "stage": "SOP_MATCH", "desc": "Relevant SOP HP-P02 Retrieved"},
            {"time_sec": 16, "stage": "ACTION_GUIDANCE", "desc": "Next-Best Actions Published with Operator Approval Required"}
        ]
    }
    return {
        "status": "success",
        "message": "Incident simulation started",
        "data": full_payload
    }


@router.post("/demo/reset")
def reset_demo():
    """Return machine state to normal, clear alarms/actions/handover"""
    state.reset()
    return {
        "status": "success",
        "message": "Demo state reset to normal operating conditions",
        "data": {
            "machine": NORMAL_MACHINE_STATE,
            "alarms": AlarmPrioritizer.prioritize(False),
            "event_story": EventStoryEngine.get_summary(False),
            "evidence": EvidenceEngine.get_evidence(False),
            "sop": SOPRetriever.get_for_incident(False),
            "handover": ShiftHandoverEngine.generate_summary(False, [])
        }
    }
