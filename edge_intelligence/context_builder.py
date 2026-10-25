"""Build a timestamp-faithful, incident-scoped 30-minute context from SQLite."""
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any, Callable, Dict, List, Optional

from database import Database
from models import (
    ContextEventRecord,
    ContextOperatorAction,
    ContextReading,
    ContextWindow,
    IncidentContext,
    to_iso_utc,
)
from tag_registry import TAG_REGISTRY, get_equipment_tags
from trend_analysis import summarize_readings


class ContextEventNotFound(Exception):
    """The requested event does not exist in the orchestrator's event records."""


class InvalidContextTimestamp(ValueError):
    """A provided or stored reference timestamp is missing or malformed."""


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp; naive values follow the model's UTC convention."""
    if not isinstance(value, str) or not value.strip():
        raise InvalidContextTimestamp("A non-empty ISO-8601 timestamp is required.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidContextTimestamp(f"Invalid ISO-8601 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class ContextBuilder:
    """Assemble recorded facts and clearly marked hypotheses for one incident."""

    WINDOW = timedelta(minutes=30)

    def __init__(
        self,
        db: Database,
        event_loader: Callable[[str], Optional[Dict[str, Any]]],
        knowledge_graph: Optional[Any] = None,
    ):
        self.db = db
        self.event_loader = event_loader
        self.knowledge_graph = knowledge_graph

    def build(
        self,
        event_id: str,
        reference_timestamp: Optional[str] = None,
        event_record: Optional[Dict[str, Any]] = None,
    ) -> IncidentContext:
        started = perf_counter()
        event = event_record if event_record is not None else self.event_loader(event_id)
        if event is None:
            raise ContextEventNotFound(event_id)

        candidate = event.get("candidate") or {}
        story = event.get("story") or {}
        steps = story.get("steps") or []
        story_alarm_step = next((step for step in reversed(steps)
                                 if str(step.get("tag", "")).startswith("ALM-")), None)
        story_alarm_timestamp = (story_alarm_step or {}).get("timestamp")
        candidate_timestamp = candidate.get("trigger_timestamp")
        event_timestamp = event.get("trigger_timestamp")
        trigger_timestamp = (
            candidate_timestamp
            or event_timestamp
            or story_alarm_timestamp
            or next((step.get("timestamp") for step in steps if step.get("timestamp")), None)
        )
        trigger_timestamp_source = (
            "candidate_events.trigger_timestamp" if candidate_timestamp else
            "event.trigger_timestamp" if event_timestamp else
            "event_stories.steps.alarm.timestamp" if story_alarm_timestamp else
            "event_stories.steps.first_timestamp" if steps else None
        )
        reference_value = reference_timestamp or trigger_timestamp
        if not reference_value:
            raise InvalidContextTimestamp(
                "The event has no recorded timestamp; provide reference_timestamp to build context."
            )
        reference = parse_timestamp(reference_value)
        start = reference - self.WINDOW
        start_iso, end_iso = to_iso_utc(start), to_iso_utc(reference)

        primary_tag = candidate.get("primary_tag") or event.get("primary_tag") or ""
        equipment = ((event.get("correlated") or {}).get("equipment_id")
                     or self._equipment_for(primary_tag))
        clustered = candidate.get("clustered_tags") or []
        relevant_tags = {entry.tag for entry in get_equipment_tags(equipment)}
        relevant_tags.update(
            tag for tag in clustered
            if tag not in TAG_REGISTRY or TAG_REGISTRY[tag].equipment_id == equipment
        )
        if primary_tag and (primary_tag not in TAG_REGISTRY or TAG_REGISTRY[primary_tag].equipment_id == equipment):
            relevant_tags.add(primary_tag)

        raw_readings = self.db.get_context_readings(
            equipment_id=equipment,
            tags=sorted(relevant_tags),
            start_time=start_iso,
            end_time=end_iso,
        ) if equipment != "Unknown equipment" else []

        readings: List[tuple[datetime, ContextReading, int]] = []
        seen_readings = set()
        duplicates_removed = 0
        invalid_reading_timestamps = 0
        for item in raw_readings:
            try:
                timestamp = parse_timestamp(item["timestamp"])
            except InvalidContextTimestamp:
                invalid_reading_timestamps += 1
                continue
            if timestamp < start or timestamp > reference:
                continue
            duplicate_key = (
                item["tag"], to_iso_utc(timestamp), repr(item["value"]),
                item.get("unit", ""), item.get("equipment_id", ""),
            )
            if duplicate_key in seen_readings:
                duplicates_removed += 1
                continue
            seen_readings.add(duplicate_key)
            readings.append((timestamp, ContextReading(
                tag=item["tag"], value=item["value"], unit=item.get("unit", ""),
                equipment_id=item.get("equipment_id", equipment),
                timestamp=item["timestamp"], timestamp_utc=to_iso_utc(timestamp),
            ), int(item.get("record_id") or 0)))
        readings.sort(key=lambda pair: (pair[0], pair[1].tag, pair[2]))
        reading_models = [item[1] for item in readings]

        raw_events = self.db.get_context_events(
            equipment_id=equipment,
            start_time=start_iso,
            end_time=end_iso,
            include_event_id=event_id,
        ) if equipment != "Unknown equipment" else []
        selected_record = next((item for item in raw_events if item["event_id"] == event_id), None)
        related_events: List[tuple[datetime, ContextEventRecord]] = []
        seen_event_ids = set()
        for item in raw_events:
            if item["event_id"] == event_id or item["event_id"] in seen_event_ids:
                continue
            try:
                timestamp = parse_timestamp(item["timestamp"])
            except InvalidContextTimestamp:
                continue
            if start <= timestamp <= reference:
                seen_event_ids.add(item["event_id"])
                related_events.append((timestamp, ContextEventRecord(
                    **item, timestamp_utc=to_iso_utc(timestamp)
                )))
        related_events.sort(key=lambda pair: (pair[0], pair[1].event_id))
        related_models = [item[1] for item in related_events]

        event_ids = [event_id, *(item.event_id for item in related_models)]
        raw_actions = self.db.get_context_actions(event_ids, start_iso, end_iso)
        actions: List[tuple[datetime, ContextOperatorAction]] = []
        seen_actions = set()
        for item in raw_actions:
            if item["action_id"] in seen_actions:
                continue
            try:
                timestamp = parse_timestamp(item["timestamp"])
            except InvalidContextTimestamp:
                continue
            if start <= timestamp <= reference:
                seen_actions.add(item["action_id"])
                actions.append((timestamp, ContextOperatorAction(
                    **item, timestamp_utc=to_iso_utc(timestamp)
                )))
        actions.sort(key=lambda pair: (pair[0], pair[1].action_id))
        action_models = [item[1] for item in actions]

        alarm_id = next((step.get("tag") for step in reversed(steps)
                         if str(step.get("tag", "")).startswith("ALM-")), None)
        if not alarm_id and candidate.get("primary_alarm"):
            alarm_id = primary_tag
        alarm_reading = next((item for item in reversed(reading_models) if item.tag == alarm_id), None)

        topology = self._topology_context(equipment, relevant_tags)
        sop_match = event.get("sop_match") or {}
        sop_references = []
        for chunk in sop_match.get("retrieved_chunks") or sop_match.get("chunks") or []:
            payload = chunk.get("payload") or chunk
            sop_references.append({
                "document_name": payload.get("document_name") or payload.get("document_id") or payload.get("source"),
                "sop_id": payload.get("sop_id") or sop_match.get("sop_id"),
                "title": payload.get("title") or sop_match.get("sop_title"),
                "revision": payload.get("revision") or sop_match.get("revision"),
                "section": payload.get("section"),
                "page": payload.get("page"),
                "chunk_id": payload.get("chunk_id") or chunk.get("chunk_id"),
                "similarity_score": chunk.get("similarity_score", chunk.get("similarity")),
                "text": chunk.get("text") or payload.get("text"),
                "retrieval_method": sop_match.get("retrieval_method"),
            })

        contributor = (event.get("evidence") or {}).get("likely_contributor_tag")
        hypotheses = []
        if contributor:
            hypotheses.append(
                f"Evidence Engine ranks {contributor} as a possible contributor; this is a hypothesis, not confirmed physical causation."
            )
        selected_event = {
            "event_id": event_id,
            "alarm_id": alarm_id or primary_tag or None,
            "primary_tag": primary_tag or None,
            "equipment_id": equipment,
            "configured_severity": candidate.get("alarm_severity"),
            "primary_alarm": candidate.get("primary_alarm"),
            "timestamp": trigger_timestamp,
            "timestamp_source": trigger_timestamp_source,
            "event_story_alarm_timestamp": story_alarm_timestamp,
            "alarm_state_timestamp": alarm_reading.timestamp if alarm_reading else None,
            "timestamp_discrepancy": bool(
                candidate_timestamp and story_alarm_timestamp
                and parse_timestamp(candidate_timestamp) != parse_timestamp(story_alarm_timestamp)
            ),
            "status": event.get("status") or (selected_record or {}).get("status", "UNKNOWN"),
            "alarm_state": ({
                "tag": alarm_reading.tag,
                "value": alarm_reading.value,
                "timestamp": alarm_reading.timestamp,
                "source": alarm_reading.source,
            } if alarm_reading else None),
            "recorded_fact_source": "SQLite candidate/event records",
        }
        missing_data = []
        if not reading_models:
            missing_data.append("No relevant timestamped process readings were recorded in this window.")
        if not related_models:
            missing_data.append("No other related event records were recorded in this window.")
        if not action_models:
            missing_data.append("No relevant operator audit actions were recorded in this window.")
        if not steps:
            missing_data.append("No event story was stored for this incident.")
        if not sop_references:
            missing_data.append("No retrieved SOP chunks are attached to this incident.")
        if selected_event["timestamp_discrepancy"]:
            missing_data.append(
                "The candidate event trigger timestamp and event-story alarm-step timestamp differ; "
                "both recorded timestamps are preserved with their source fields. The context window "
                "uses the candidate event trigger timestamp."
            )
        if invalid_reading_timestamps:
            missing_data.append(f"{invalid_reading_timestamps} reading(s) with invalid timestamps were excluded.")

        result = IncidentContext(
            event_id=event_id,
            reference_timestamp=to_iso_utc(reference),
            window=ContextWindow(start=start_iso, end=to_iso_utc(reference)),
            selected_event=selected_event,
            readings=reading_models,
            trend_summaries=summarize_readings(
                [item.model_dump() if hasattr(item, "model_dump") else item.dict() for item in reading_models],
                reference_timestamp=to_iso_utc(reference),
                window_start=start_iso,
                expected_tags=sorted(relevant_tags),
            ),
            related_events=related_models,
            operator_actions=action_models,
            topology=topology,
            incident_analysis={
                "event_story": story,
                "evidence": event.get("evidence"),
                "evidence_audit": event.get("evidence_audit"),
                "matched_sop": {
                    "sop_id": sop_match.get("sop_id"),
                    "title": sop_match.get("sop_title") or sop_match.get("title"),
                    "revision": sop_match.get("revision"),
                    "retrieval_method": sop_match.get("retrieval_method"),
                    "similarity_score": sop_match.get("semantic_similarity"),
                    "references": sop_references,
                } if sop_match else None,
                "interpretation": "Event story and contributor ranking are recorded correlation/evidence outputs; they do not prove physical root cause.",
            },
            data_sources=[
                "SQLite.tag_readings",
                "SQLite.candidate_events",
                "SQLite.operator_actions",
                "OpsLens event story/evidence/SOP match records",
                "Tag registry topology",
                *( ["NetworkX industrial knowledge graph"] if self.knowledge_graph is not None else [] ),
            ],
            missing_data=missing_data,
            hypotheses=hypotheses,
            duplicate_readings_removed=duplicates_removed,
            assembly_latency_ms=0.0,
        )
        result.assembly_latency_ms = round((perf_counter() - started) * 1000, 3)
        return result

    @staticmethod
    def _equipment_for(tag: str) -> str:
        entry = TAG_REGISTRY.get(tag)
        if entry:
            return entry.equipment_id
        if any(token in tag for token in ("P02", "FLW", "VLV", "PIT", "MOT")):
            return "Pump-02"
        if "CMP" in tag:
            return "Compressor-01"
        if "TNK" in tag:
            return "Tank-01"
        if "FLT" in tag:
            return "Filter-01"
        return "Unknown equipment"

    def _topology_context(self, equipment: str, tags: set[str]) -> Dict[str, Any]:
        dependencies = []
        for tag in sorted(tags):
            entry = TAG_REGISTRY.get(tag)
            if entry:
                dependencies.extend({
                    "source": source,
                    "relation": "topology_upstream",
                    "target": tag,
                } for source in entry.topology_upstream)
        relationships = []
        if self.knowledge_graph is not None:
            relationships = self.knowledge_graph.context(equipment, sorted(tags))
        return {
            "equipment_id": equipment,
            "relevant_tags": sorted(tags),
            "registry_dependencies": dependencies,
            "knowledge_graph_relationships": relationships,
            "interpretation": "Configured structural relationships provide context; they are not proof of causation.",
        }
