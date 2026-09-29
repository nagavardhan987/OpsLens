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
    { "tag": str, "value": float|bool|str, "timestamp": ISO8601 str,
      "unit": str, "equipment_id": str }
    """
    tag: str
    value: Union[float, bool, str]
    timestamp: str
    unit: str
    equipment_id: str
    alarm_state: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tag": self.tag,
            "value": self.value,
            "timestamp": self.timestamp,
            "unit": self.unit,
            "equipment_id": self.equipment_id,
            "alarm_state": self.alarm_state,
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
        return d


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


class CorrelatedDeviation(BaseModel):
    tag: str
    deviation_pct: float
    timestamp: str
    precedes_primary: bool
    topology_distance: int


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
    value_before: float
    value_after: float


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
    source: Literal["bm25", "embedding"]
    why_retrieved: Optional[Dict[str, Any]] = None
    retrieved_chunks: Optional[List[Dict[str, Any]]] = None   # top-K Qdrant chunks
    chunks: Optional[List[Dict[str, Any]]] = None
    rag_trace: Optional[Dict[str, Any]] = None                # full audit record


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
