"""
OpsLens - Live Pipeline Orchestrator (Component 11)

Asynchronous pipeline orchestrator tying together Components 1 through 10.
- Subscribes to live TagStream telemetry.
- Evaluates and deduplicates candidate events.
- Fans out concurrent event worker tasks (asyncio.create_task per event).
- Sequentially executes Correlation -> Event Story -> Evidence -> SOP Retrieval -> Guidance.
- Persists outputs to SQLite stage-by-stage as each finishes (not batched).
- Provides single point of truth for cross-table joins (get_full_event).
- Broadcasts completed events to real-time subscribers (SSE / WebSocket).
- Guarantees restart idempotency.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Set
from datetime import datetime

from models import (
    TagReading, CandidateEvent, CorrelatedEvent, EventStory,
    Evidence, SopMatch, Guidance, OperatorAction, HandoverSummary
)
from database import Database
from stream import TagStream
from prioritizer import PrioritizationEngine
from dedup import DeduplicationEngine
from correlator import CorrelationEngine
from event_story import EventStoryConstructor
from evidence_engine import EvidenceEngine
from sop_retriever import SopRetriever
from guidance_generator import GuidanceGenerator
from operator_actions import OperatorActionAudit
from shift_handover import ShiftHandoverCompiler
from time_series import TimeSeriesProcessor
from knowledge_graph import IndustrialKnowledgeGraph
from alarm_synthesis import AlarmSynthesisEngine

logger = logging.getLogger("opslens.orchestrator")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class OpsLensOrchestrator:
    """
    Central pipeline orchestrator and unified cross-table query interface.
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        stream: Optional[TagStream] = None,
        lookback_seconds: float = 120.0,
        cluster_window_seconds: float = 90.0
    ):
        self.db = db if db is not None else Database()
        self.stream = stream if stream is not None else TagStream(db_path=self.db.db_path)

        # Initialize component engines
        self.prioritizer = PrioritizationEngine()
        self.dedup = DeduplicationEngine(
            db=self.db,
            prioritizer=self.prioritizer,
            cluster_window_seconds=cluster_window_seconds
        )
        self.correlator = CorrelationEngine(
            stream=self.stream,
            db=self.db,
            lookback_seconds=lookback_seconds
        )
        self.story_constructor = EventStoryConstructor(db=self.db)
        self.evidence_engine = EvidenceEngine(db=self.db)
        self.sop_retriever = SopRetriever(db=self.db)
        self.guidance_generator = GuidanceGenerator(db=self.db)
        self.audit = OperatorActionAudit(db=self.db)
        self.handover_compiler = ShiftHandoverCompiler(db=self.db)
        self.time_series = TimeSeriesProcessor()
        self.knowledge_graph = IndustrialKnowledgeGraph()
        self.alarm_synthesis = AlarmSynthesisEngine()

        # Concurrency & Fan-out State
        self._in_flight_tasks: Dict[str, asyncio.Task] = {}
        self._completed_events: Set[str] = set()
        self._processed_tags: Dict[str, Set[str]] = {}
        self._processed_primary: Dict[str, str] = {}
        self._pending_updates: Dict[str, CandidateEvent] = {}
        self._load_completed_events()
        self._subscribers: List[asyncio.Queue] = []
        self._running: bool = False
        self._consumer_task: Optional[asyncio.Task] = None

    def _load_completed_events(self) -> None:
        """Hydrate already completed event IDs from guidance table in SQLite on startup."""
        try:
            records = self.db.get_guidance()
            for r in records:
                self._completed_events.add(r.event_id)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Subscription & Event Fan-out
    # -------------------------------------------------------------------------

    def register_subscriber(self, queue: asyncio.Queue) -> None:
        """Register a queue for live event broadcasts (SSE / WebSockets)."""
        if queue not in self._subscribers:
            self._subscribers.append(queue)

    def unregister_subscriber(self, queue: asyncio.Queue) -> None:
        """Unregister a live event broadcast queue."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def _broadcast(self, full_event: Dict[str, Any]) -> None:
        """Broadcast a newly completed full event to all active subscribers."""
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(full_event)
            except Exception as e:
                logger.warning(f"[Orchestrator] Broadcast error to subscriber queue: {e}")

    async def start_streaming(self, from_latest: bool = False) -> None:
        """
        Start the background stream consumer task.
        Consumes readings from TagStream and fans out event processing.
        """
        if self._running:
            return
        self._running = True
        self._consumer_task = asyncio.create_task(self._consume_stream(from_latest=from_latest))
        logger.info("[Orchestrator] Stream consumer task started.")

    async def stop(self) -> None:
        """Gracefully terminate stream consumption and await inflight tasks."""
        self._running = False
        if self._consumer_task and not self._consumer_task.done():
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass

        # Await any remaining inflight event pipeline workers
        if self._in_flight_tasks:
            logger.info(f"[Orchestrator] Awaiting {len(self._in_flight_tasks)} inflight event workers...")
            await asyncio.gather(*self._in_flight_tasks.values(), return_exceptions=True)
            self._in_flight_tasks.clear()

        logger.info("[Orchestrator] Stopped gracefully.")

    async def _consume_stream(self, from_latest: bool = False) -> None:
        """Internal loop listening to TagStream subscription."""
        try:
            async for reading in self.stream.subscribe(from_latest=from_latest):
                if not self._running:
                    break
                await self.process_reading(reading)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[Orchestrator] Exception in stream consumer: {e}", exc_info=True)

    async def process_reading(self, reading: TagReading) -> Optional[CandidateEvent]:
        """
        Feed a single reading into the prioritizer and deduplication engine.
        If a CandidateEvent is formed or updated, fans out a concurrent pipeline task.
        """
        self.time_series.process(reading)
        candidate = self.dedup.process_reading(reading)
        if candidate is not None:
            event_id = candidate.event_id
            curr_tags = set(candidate.clustered_tags)
            prev_tags = self._processed_tags.get(event_id, set())
            has_new_tags = not curr_tags.issubset(prev_tags)
            primary_changed = candidate.primary_tag != self._processed_primary.get(event_id)

            # If not already processing and (new event OR cluster has evolved)
            if event_id not in self._in_flight_tasks:
                if event_id not in self._completed_events or has_new_tags or primary_changed:
                    task = asyncio.create_task(self.process_candidate_event(candidate))
                    self._in_flight_tasks[event_id] = task
            else:
                # Worker in flight; record pending update so it re-runs when current finish
                if has_new_tags or primary_changed:
                    self._pending_updates[event_id] = candidate

        return candidate

    async def process_candidate_event(self, candidate: CandidateEvent) -> Dict[str, Any]:
        """
        Sequential execution of stages 4 -> 5 -> 6 -> 7 -> 8 for a single event.
        Persists each stage output to SQLite immediately upon completion.
        Broadcasts completed event to real-time subscribers.
        """
        event_id = candidate.event_id
        logger.info(f"[Orchestrator] Spawning pipeline worker for event {event_id} (tag={candidate.primary_tag}, tags={candidate.clustered_tags})")

        try:
            self._processed_tags[event_id] = set(candidate.clustered_tags)
            self._processed_primary[event_id] = candidate.primary_tag

            equipment = self._equipment_for(candidate.primary_tag)
            temporal_context = {"equipment": equipment,
                                "telemetry": self.time_series.snapshot(equipment),
                                "observations": self.time_series.observations(equipment)}
            graph_context = self.knowledge_graph.context(equipment, candidate.clustered_tags)

            # Stage 4: Correlation consumes existing temporal and graph context.
            correlated = await self.correlator.correlate_event(
                candidate, temporal_context=temporal_context, graph_context=graph_context)

            # Stage 5: Event Story Construction (writes to event_stories)
            story = self.story_constructor.construct_story(correlated, persist=True)

            # Stage 6: Evidence & Attribution (writes to evidence)
            evidence = self.evidence_engine.evaluate_event(
                correlated, persist=True, temporal_context=temporal_context, graph_context=graph_context)

            telemetry = temporal_context["telemetry"]
            temporal_observations = temporal_context["observations"]
            synthesized_alarm = self.alarm_synthesis.synthesize(candidate, story, telemetry, temporal_observations)
            process_context = {"equipment": equipment, "telemetry": telemetry,
                               "observations": temporal_observations, "graph_context": graph_context,
                               "event_sequence": [step.description for step in story.steps],
                               "alarm": synthesized_alarm}

            # Stage 7: SOP Retrieval (writes to sop_matches)
            sop_match = self.sop_retriever.retrieve(
                story=story,
                evidence=evidence,
                primary_tag=candidate.primary_tag,
                telemetry_snapshot=process_context,
                persist=True
            )

            # Stage 8: Guidance Generation (writes to guidance)
            guidance = self.guidance_generator.generate(
                story=story,
                evidence=evidence,
                sop_match=sop_match
            )

            # Build full event response
            full_event = self.get_full_event(event_id)
            if full_event:
                await self._broadcast(full_event)

            self._completed_events.add(event_id)
            logger.info(f"[Orchestrator] Successfully completed pipeline for event {event_id}")
            return full_event or {}

        except Exception as e:
            logger.error(f"[Orchestrator] Pipeline failed for event {event_id}: {e}", exc_info=True)
            raise
        finally:
            self._in_flight_tasks.pop(event_id, None)
            # If an updated candidate arrived while worker was processing, re-run
            pending = self._pending_updates.pop(event_id, None)
            if pending is not None:
                task = asyncio.create_task(self.process_candidate_event(pending))
                self._in_flight_tasks[event_id] = task

    @staticmethod
    def _equipment_for(tag: str) -> str:
        if any(token in tag for token in ("P02", "FLW", "VLV", "PIT", "MOT")): return "Pump-02"
        if "CMP" in tag: return "Compressor-01"
        if "TNK" in tag: return "Tank-01"
        if "FLT" in tag: return "Filter-01"
        return "Unknown equipment"

    # -------------------------------------------------------------------------
    # Unified Cross-Table Join (Requirement 3)
    # -------------------------------------------------------------------------

    def get_full_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """
        Single point of truth cross-table join.
        Joins candidate_events, correlated_events, event_stories, evidence,
        sop_matches, guidance, and operator_actions into a unified response.
        """
        candidates = self.db.get_candidate_events(event_id=event_id)
        correlated = self.db.get_correlated_events(event_id=event_id)
        stories = self.db.get_event_stories(event_id=event_id)
        evidence = self.db.get_evidence(event_id=event_id)
        sop_matches = self.db.get_sop_matches(event_id=event_id)
        guidance = self.db.get_guidance(event_id=event_id)
        actions = self.db.get_operator_actions(event_id=event_id)

        # If event does not exist in any stage, return None
        if not any([candidates, correlated, stories, evidence, sop_matches, guidance]):
            return None

        # Determine overall incident resolution state
        is_resolved = any(a.action_type.upper() in ("RESOLVE", "RESOLVED") for a in actions)
        is_acked = any(a.action_type.upper() in ("ACKNOWLEDGE", "ACKNOWLEDGED") for a in actions)
        status = "RESOLVED" if is_resolved else ("ACKNOWLEDGED" if is_acked else "OPEN")

        candidate_obj = candidates[0] if candidates else None
        correlated_obj = correlated[0] if correlated else None
        story_obj = stories[0] if stories else None
        evidence_obj = evidence[0] if evidence else None
        sop_obj = sop_matches[0] if sop_matches else None
        guidance_obj = guidance[0] if guidance else None

        return {
            "event_id": event_id,
            "primary_tag": candidate_obj.primary_tag if candidate_obj else (story_obj.steps[0].tag if story_obj and story_obj.steps else "UNKNOWN"),
            "trigger_timestamp": candidate_obj.trigger_timestamp if candidate_obj else (story_obj.steps[0].timestamp if story_obj and story_obj.steps else None),
            "status": status,
            "is_open": not is_resolved,
            "candidate": candidate_obj.model_dump() if candidate_obj else None,
            "correlated": correlated_obj.model_dump() if correlated_obj else None,
            "story": story_obj.model_dump() if story_obj else None,
            "evidence": evidence_obj.model_dump() if evidence_obj else None,
            "sop_match": sop_obj.model_dump() if sop_obj else None,
            "guidance": guidance_obj.model_dump() if guidance_obj else None,
            "actions": [a.model_dump() for a in actions]
        }
