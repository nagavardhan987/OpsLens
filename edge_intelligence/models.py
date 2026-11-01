"""
OpsLens - Shared System Contract Models

Strict schema definitions matching the OpsLens system contract.
All timestamps are ISO8601 UTC strings.
All percentages are signed floats (e.g., -44.9, not "-45%").
"""

from typing import List, Optional, Literal, Union, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import uuid


def current_iso_utc() -> str:
    """Return current timestamp in ISO8601 UTC format with millisecond precision."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def to_iso_utc(dt: datetime) -> str:
    """Format any datetime to ISO8601 UTC format."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


# -----------------------------------------------------------------------------
# Core Telemetry & Registry Contracts
# -----------------------------------------------------------------------------

class TagReading(BaseModel):
    """
    TagReading schema:
    { "tag": str, "value": float|bool|str|None, "timestamp": ISO8601 str,
      "unit": str, "equipment_id": str }
    """
    tag: str
    value: Optional[Union[float, bool, str]] = None
    timestamp: str
    unit: str
    equipment_id: str
    alarm_state: Optional[str] = None
    # Alarm priority/severity passed through from the configured source when supplied.
    # This is not inferred from OpsLens evidence weights.
    alarm_severity: Optional[str] = None
    # Provenance metadata is additive; legacy/synthetic callers remain valid.
    received_timestamp: str = Field(default_factory=current_iso_utc)
    data_quality: Literal["VALID", "DEGRADED", "STALE", "INVALID", "UNKNOWN"] = "UNKNOWN"
    data_source: str = "unknown"
    connection_status: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tag": self.tag,
            "value": self.value,
            "timestamp": self.timestamp,
            "unit": self.unit,
            "equipment_id": self.equipment_id,
            "alarm_state": self.alarm_state,
            "alarm_severity": self.alarm_severity,
            "received_timestamp": self.received_timestamp,
            "data_quality": self.data_quality,
            "data_source": self.data_source,
            "connection_status": self.connection_status,
        }


class TagRegistryEntry(BaseModel):
    """
    TagRegistryEntry schema:
    { "tag": str, "equipment_id": str, "unit": str, "data_type": "float"|"bool"|"string",
      "baseline_min": float, "baseline_max": float, "trip_threshold": float|null,
      "severity_weight": float (0-1), "topology_upstream": [tag names this tag causally depends on] }
    """
    tag: str
    equipment_id: str
    unit: str
    data_type: Literal["float", "bool", "string"]
    baseline_min: float
    baseline_max: float
    trip_threshold: Optional[float] = None
    severity_weight: float = Field(ge=0.0, le=1.0)
    topology_upstream: List[str] = Field(default_factory=list)
    short_label: Optional[str] = None
    baseline_status: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "tag": self.tag,
            "equipment_id": self.equipment_id,
            "unit": self.unit,
            "data_type": self.data_type,
            "baseline_min": self.baseline_min,
            "baseline_max": self.baseline_max,
            "trip_threshold": self.trip_threshold,
            "severity_weight": self.severity_weight,
            "topology_upstream": list(self.topology_upstream),
        }
        if self.short_label is not None:
            d["short_label"] = self.short_label
        if self.baseline_status is not None:
            d["baseline_status"] = self.baseline_status
        return d


# -----------------------------------------------------------------------------
# Prioritization, Urgency & Lifecycle Contracts (Phase 2 & Phase 3)
# -----------------------------------------------------------------------------

class TimeToLimitEstimate(BaseModel):
    time_to_limit_seconds: Optional[float] = None
    target_limit: float
    current_value: float
    rate_per_second: float
    direction: Literal["rising", "falling", "steady"]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    assumptions: str
    timestamp: str


class UrgencyAssessment(BaseModel):
    source_priority: Optional[str] = None
    urgency_score: Optional[float] = None
    urgency_band: Literal["URGENT", "ELEVATED", "ROUTINE", "UNKNOWN"] = "UNKNOWN"
    urgency_reasons: List[str] = Field(default_factory=list)
    triggered_rules: List[str] = Field(default_factory=list)
    data_quality: Literal["VALID", "DEGRADED", "STALE", "INVALID"] = "VALID"
    time_to_limit: Optional[TimeToLimitEstimate] = None
    ttl_unavailable_reason: Optional[str] = None
    ranking_timestamp: str = Field(default_factory=current_iso_utc)
    scoring_breakdown: Dict[str, float] = Field(default_factory=dict)


class IndividualAlarmRecord(BaseModel):
    alarm_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_event_id: Optional[str] = None
    tag: str
    equipment_id: str
    alarm_type: str = "EXCURSION"
    value: Union[float, bool, str]
    threshold: Optional[float] = None
    source_priority: Optional[str] = None
    lifecycle_state: Literal["NEW", "ACTIVE", "ACKNOWLEDGED", "CLEARED", "RECURRING"] = "ACTIVE"
    repeat_count: int = 1
    first_seen_timestamp: str
    last_seen_timestamp: str
    cleared_timestamp: Optional[str] = None
    acknowledged_timestamp: Optional[str] = None
    fingerprint: str = ""


# -----------------------------------------------------------------------------
# Downstream Engines Contracts (For Complete Contract Integrity)
# -----------------------------------------------------------------------------

class CandidateEvent(BaseModel):
    """
    CandidateEvent (output of prioritization/dedup):
    { "event_id": str (uuid), "primary_tag": str, "primary_alarm": bool,
      "trigger_timestamp": ISO8601, "raw_deviation_pct": float,
      "clustered_tags": [tag names grouped into this event] }
    """
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    primary_tag: str
    primary_alarm: bool
    trigger_timestamp: str
    raw_deviation_pct: float
    clustered_tags: List[str] = Field(default_factory=list)
    alarm_severity: Optional[str] = None
    # Prioritization & lifecycle extensions (backward-compatible)
    source_priority: Optional[str] = None
    urgency: Optional[UrgencyAssessment] = None
    repeat_count: int = 1
    lifecycle_state: str = "ACTIVE"
    first_seen_timestamp: Optional[str] = None
    last_seen_timestamp: Optional[str] = None
    individual_alarms: List[IndividualAlarmRecord] = Field(default_factory=list)


class CorrelatedDeviation(BaseModel):
    tag: str
    deviation_pct: float
    timestamp: str
    precedes_primary: bool
    topology_distance: int
    value_before: Optional[Union[float, bool, str]] = None
    value_after: Optional[Union[float, bool, str]] = None
    unit: Optional[str] = None
    data_source: Optional[str] = None
    data_quality: Optional[str] = None
    connection_status: Optional[str] = None


class CorrelatedEvent(CandidateEvent):
    """
    CorrelatedEvent (output of correlation engine, extends CandidateEvent):
    { ...CandidateEvent fields, "correlated_deviations": [
        { "tag": str, "deviation_pct": float, "timestamp": ISO8601,
          "precedes_primary": bool, "topology_distance": int } ] }
    """
    correlated_deviations: List[CorrelatedDeviation] = Field(default_factory=list)
    temporal_context: Dict[str, Any] = Field(default_factory=dict)
    graph_context: List[str] = Field(default_factory=list)


class EventStoryStep(BaseModel):
    step_number: int
    tag: str
    timestamp: str
    description: str
    value_before: Optional[Union[float, bool, str]] = None
    value_after: Optional[Union[float, bool, str]] = None
    unit: Optional[str] = None
    data_source: Optional[str] = None
    data_quality: Optional[str] = None
    connection_status: Optional[str] = None


class EventStory(BaseModel):
    """
    EventStory (output of timeline constructor):
    { "event_id": str, "steps": [
        { "step_number": int, "tag": str, "timestamp": ISO8601,
          "description": str, "value_before": float, "value_after": float } ],
      "causal_label": str }
    """
    event_id: str
    steps: List[EventStoryStep] = Field(default_factory=list)
    causal_label: str


class SupportingDelta(BaseModel):
    tag: str
    delta_pct: float
    direction: Literal["up", "down"]


class Evidence(BaseModel):
    """
    Evidence (output of evidence engine):
    { "event_id": str, "likely_contributor_tag": str, "confidence_score": float (0-1),
      "confidence_label": "LOW"|"MEDIUM"|"HIGH",
      "supporting_deltas": [ { "tag": str, "delta_pct": float, "direction": "up"|"down" } ] }
    """
    event_id: str
    likely_contributor_tag: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_label: Literal["LOW", "MEDIUM", "HIGH"]
    supporting_deltas: List[SupportingDelta] = Field(default_factory=list)


class SopMatch(BaseModel):
    """
    SopMatch (output of Qdrant RAG retrieval):
    semantic_similarity is the RAW cosine similarity from Qdrant.
    It is NOT a probability, NOT a confidence score, NOT a percentage.
    Label it as: "Semantic relevance: 0.7645"
    """
    event_id: str
    sop_id: str
    sop_title: str
    title: Optional[str] = None
    revision: str = ""
    match_score: float                          # kept for backward compat
    semantic_similarity: Optional[float] = None # RAW cosine similarity (0.0–1.0)
    retrieval_method: str = "embedding"         # "qdrant_vector_search" | "bm25"
    embedding_model: str = "all-MiniLM-L6-v2"
    query_context: Optional[str] = None         # full contextual query that was embedded
    steps: List[str]
    source: Literal["bm25", "embedding", "unavailable"]
    why_retrieved: Optional[Dict[str, Any]] = None
    retrieved_chunks: Optional[List[Dict[str, Any]]] = None   # top-K Qdrant chunks
    chunks: Optional[List[Dict[str, Any]]] = None
    rag_trace: Optional[Dict[str, Any]] = None                # full audit record
    # Retrieval outcome is independent of the incident-analysis result.
    retrieval_status: str = "match_found"  # match_found | no_match | unavailable
    retrieval_error: Optional[str] = None   # sanitized reason code only


class Guidance(BaseModel):
    """
    Guidance (output of explanation/generation):
    { "event_id": str, "explanation_text": str, "next_best_actions": [str],
      "cited_sop_id": str }
    """
    event_id: str
    explanation_text: str
    next_best_actions: List[str]
    cited_sop_id: str


class OperatorAction(BaseModel):
    """
    OperatorAction:
    { "action_id": str (uuid), "event_id": str, "operator": str, "action_type": str,
      "timestamp": ISO8601, "notes": str|null }
    """
    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_id: str
    operator: str
    action_type: str
    timestamp: str
    notes: Optional[str] = None


class HandoverSummary(BaseModel):
    """
    HandoverSummary:
    { "shift_start": ISO8601, "shift_end": ISO8601,
      "events": [event_id list], "actions": [OperatorAction list],
      "open_events": [event_id list] }
    """
    shift_start: str
    shift_end: str
    events: List[str] = Field(default_factory=list)
    actions: List[OperatorAction] = Field(default_factory=list)
    open_events: List[str] = Field(default_factory=list)


class ContextWindow(BaseModel):
    start: str
    end: str
    duration_minutes: int = 30
    inclusive: bool = True


class ContextReading(BaseModel):
    tag: str
    value: Union[float, bool, str]
    unit: str
    equipment_id: str
    timestamp: str
    timestamp_utc: str
    source: str = "sqlite.tag_readings"
    received_timestamp: Optional[str] = None
    data_quality: str = "UNKNOWN"
    data_source: str = "unknown"
    connection_status: str = "unknown"


class ContextEventRecord(BaseModel):
    event_id: str
    alarm_id: str
    primary_alarm: bool
    timestamp: str
    timestamp_utc: str
    raw_deviation_pct: Optional[float] = None
    tags: List[str] = Field(default_factory=list)
    equipment_id: str
    configured_severity: Optional[str] = None
    status: str


class ContextOperatorAction(BaseModel):
    action_id: str
    event_id: str
    operator: str
    action_type: str
    timestamp: str
    timestamp_utc: str
    notes: Optional[str] = None


class SelectedEventContext(BaseModel):
    event_id: str
    alarm_id: Optional[str] = None
    primary_tag: Optional[str] = None
    equipment_id: str
    configured_severity: Optional[str] = None
    primary_alarm: Optional[bool] = None
    timestamp: Optional[str] = None
    timestamp_source: Optional[str] = None
    event_story_alarm_timestamp: Optional[str] = None
    alarm_state_timestamp: Optional[str] = None
    timestamp_discrepancy: bool = False
    status: str
    alarm_state: Optional[Dict[str, Any]] = None
    recorded_fact_source: str


class ContextTopology(BaseModel):
    equipment_id: str
    relevant_tags: List[str] = Field(default_factory=list)
    registry_dependencies: List[Dict[str, str]] = Field(default_factory=list)
    knowledge_graph_relationships: List[str] = Field(default_factory=list)
    interpretation: str


class ContextIncidentAnalysis(BaseModel):
    event_story: Optional[Dict[str, Any]] = None
    evidence: Optional[Dict[str, Any]] = None
    evidence_audit: Optional[Dict[str, Any]] = None
    matched_sop: Optional[Dict[str, Any]] = None
    interpretation: str


class IncidentContext(BaseModel):
    event_id: str
    reference_timestamp: str
    window: ContextWindow
    selected_event: SelectedEventContext
    readings: List[ContextReading] = Field(default_factory=list)
    trend_summaries: List[Dict[str, Any]] = Field(default_factory=list)
    related_events: List[ContextEventRecord] = Field(default_factory=list)
    operator_actions: List[ContextOperatorAction] = Field(default_factory=list)
    topology: ContextTopology
    incident_analysis: ContextIncidentAnalysis
    data_sources: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)
    hypotheses: List[str] = Field(default_factory=list)
    duplicate_readings_removed: int = 0
    assembly_latency_ms: float
    timings_ms: Dict[str, float] = Field(default_factory=dict)
