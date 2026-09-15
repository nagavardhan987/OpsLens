"""
OpsLens - Deduplication & Time-Window Clustering Engine (Component 3)

Implements topological time-window clustering to suppress alarm floods:
Groups multiple breaches occurring on the same equipment or topologically linked
equipment within a 90-second window into ONE unified CandidateEvent.
"""

import uuid
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Any, AsyncIterator
from dataclasses import dataclass, field

from models import TagReading, CandidateEvent, to_iso_utc
from registry_loader import RegistryLoader, get_registry_loader
from prioritizer import PrioritizationEngine, DeviationAssessment
from database import Database, DEFAULT_DB_PATH
from stream import TagStream


@dataclass
class ActiveCluster:
    """Internal representation of an evolving event cluster."""
    event_id: str
    equipment_id: str
    trigger_timestamp: datetime
    last_breach_timestamp: datetime
    primary_tag: str
    primary_alarm: bool
    raw_deviation_pct: float
    clustered_tags: List[str] = field(default_factory=list)
    tag_assessments: Dict[str, DeviationAssessment] = field(default_factory=dict)

    def to_candidate_event(self) -> CandidateEvent:
        """Convert to strict CandidateEvent schema."""
        return CandidateEvent(
            event_id=self.event_id,
            primary_tag=self.primary_tag,
            primary_alarm=self.primary_alarm,
            trigger_timestamp=to_iso_utc(self.trigger_timestamp),
            raw_deviation_pct=self.raw_deviation_pct,
            clustered_tags=list(self.clustered_tags)
        )


class DeduplicationEngine:
    """
    Topological time-window clustering and deduplication engine.
    Suppresses alarm floods and persists CandidateEvent objects into SQLite.
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        prioritizer: Optional[PrioritizationEngine] = None,
        registry_loader: Optional[RegistryLoader] = None,
        cluster_window_seconds: float = 90.0
    ):
        self.db = db if db is not None else Database()
        self.prioritizer = prioritizer if prioritizer is not None else PrioritizationEngine()
        self.loader = registry_loader if registry_loader is not None else get_registry_loader()
        self.cluster_window_seconds = cluster_window_seconds

        # Active in-flight clusters: event_id -> ActiveCluster
        self._active_clusters: Dict[str, ActiveCluster] = {}
        self._load_active_clusters_from_db()

    def _load_active_clusters_from_db(self) -> None:
        """Hydrate active in-flight clusters from candidate_events table in SQLite on startup."""
        try:
            conn = self.db._get_connection()
            query = """
                SELECT event_id, primary_tag, primary_alarm, trigger_timestamp,
                       raw_deviation_pct, clustered_tags, equipment_id, updated_at
                FROM candidate_events
                WHERE status = 'OPEN'
            """
            cursor = conn.execute(query)
            rows = cursor.fetchall()
            for row in rows:
                eid = row["event_id"]
                trig_dt = self._parse_timestamp(row["trigger_timestamp"])
                upd_dt = self._parse_timestamp(row["updated_at"]) if row["updated_at"] else trig_dt
                clustered = json.loads(row["clustered_tags"])

                cluster = ActiveCluster(
                    event_id=eid,
                    equipment_id=row["equipment_id"],
                    trigger_timestamp=trig_dt,
                    last_breach_timestamp=trig_dt,
                    primary_tag=row["primary_tag"],
                    primary_alarm=bool(row["primary_alarm"]),
                    raw_deviation_pct=float(row["raw_deviation_pct"]),
                    clustered_tags=clustered,
                    tag_assessments={}
                )
                self._active_clusters[eid] = cluster
        except Exception:
            pass

    def _parse_timestamp(self, ts_str: str) -> datetime:
        """Parse ISO8601 UTC timestamp string to datetime."""
        clean = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _are_topologically_linked(self, tag1: str, tag2: str) -> bool:
        """Check if two tags share an upstream or downstream causal connection in the DAG."""
        if tag1 == tag2:
            return True
        up1 = set(self.loader.get_upstream(tag1, recursive=True))
        if tag2 in up1:
            return True
        up2 = set(self.loader.get_upstream(tag2, recursive=True))
        if tag1 in up2:
            return True
        return False

    def _find_matching_cluster(
        self,
        equipment_id: str,
        tag: str,
        breach_time: datetime
    ) -> Optional[ActiveCluster]:
        """
        Search for an existing active cluster that matches either:
        1. The same equipment_id within the cluster window.
        2. Or a topologically linked tag within the cluster window.
        """
        for cluster in self._active_clusters.values():
            # Check time window relative to cluster's last breach or trigger
            delta_sec = abs((breach_time - cluster.last_breach_timestamp).total_seconds())
            if delta_sec > self.cluster_window_seconds:
                continue

            # Check equipment match
            if cluster.equipment_id == equipment_id:
                return cluster

            # Check topological link with any existing tag in cluster
            for existing_tag in cluster.clustered_tags:
                if self._are_topologically_linked(tag, existing_tag):
                    return cluster

        return None

    def _update_cluster_primary(self, cluster: ActiveCluster) -> None:
        """
        Elect the primary tag and primary_alarm status for the cluster:
        - Any explicit alarm tag elevates primary_alarm = True.
        - Primary tag is selected by:
          1. Trip alarm status (alarms take priority).
          2. Tag severity_weight from TagRegistryEntry (highest severity wins).
          3. Magnitude of deviation percentage (largest deviation wins).
        """
        best_tag: Optional[str] = None
        best_alarm = False
        best_severity = -1.0
        best_deviation_mag = -1.0

        for t_name, assessment in cluster.tag_assessments.items():
            entry = assessment.entry
            is_alarm = assessment.is_trip_alarm
            sev = entry.severity_weight
            dev_mag = abs(assessment.deviation_pct)

            # Compare priority score
            if best_tag is None:
                best_tag = t_name
                best_alarm = is_alarm
                best_severity = sev
                best_deviation_mag = dev_mag
                continue

            # Rule 1: Trip alarms beat non-alarms
            if is_alarm and not best_alarm:
                best_tag = t_name
                best_alarm = True
                best_severity = sev
                best_deviation_mag = dev_mag
            elif is_alarm == best_alarm:
                # Rule 2: Higher severity weight wins
                if sev > best_severity:
                    best_tag = t_name
                    best_severity = sev
                    best_deviation_mag = dev_mag
                elif abs(sev - best_severity) < 1e-4:
                    # Rule 3: Larger deviation magnitude wins
                    if dev_mag > best_deviation_mag:
                        best_tag = t_name
                        best_deviation_mag = dev_mag

        if best_tag is not None:
            cluster.primary_tag = best_tag
            cluster.primary_alarm = best_alarm
            cluster.raw_deviation_pct = cluster.tag_assessments[best_tag].deviation_pct
            cluster.trigger_timestamp = self._parse_timestamp(
                cluster.tag_assessments[best_tag].reading.timestamp
            )

    def process_reading(self, reading: TagReading) -> Optional[CandidateEvent]:
        """
        Process a single TagReading:
        1. Evaluate for deviation & breach.
        2. If breach, cluster into an existing or new CandidateEvent.
        3. Persist CandidateEvent write-through to SQLite.
        Returns the updated CandidateEvent if a breach occurred, else None.
        """
        assessment = self.prioritizer.evaluate_reading(reading)
        if not assessment.is_breach:
            return None

        breach_time = self._parse_timestamp(reading.timestamp)
        cluster = self._find_matching_cluster(reading.equipment_id, reading.tag, breach_time)

        if cluster is not None:
            # Merge into existing cluster
            if reading.tag not in cluster.clustered_tags:
                cluster.clustered_tags.append(reading.tag)

            cluster.last_breach_timestamp = breach_time
            cluster.tag_assessments[reading.tag] = assessment
            self._update_cluster_primary(cluster)

        else:
            # Spawn a new cluster
            new_id = str(uuid.uuid4())
            cluster = ActiveCluster(
                event_id=new_id,
                equipment_id=reading.equipment_id,
                trigger_timestamp=breach_time,
                last_breach_timestamp=breach_time,
                primary_tag=reading.tag,
                primary_alarm=assessment.is_trip_alarm,
                raw_deviation_pct=assessment.deviation_pct,
                clustered_tags=[reading.tag],
                tag_assessments={reading.tag: assessment}
            )
            self._active_clusters[new_id] = cluster

        candidate_event = cluster.to_candidate_event()

        # Write-through to SQLite candidate_events table
        self.db.save_candidate_event(candidate_event, equipment_id=cluster.equipment_id)

        return candidate_event

    def get_candidate_events(self) -> List[CandidateEvent]:
        """Retrieve all CandidateEvents persisted in SQLite."""
        return self.db.get_candidate_events()

    def clear(self) -> None:
        """Clear memory clusters and SQLite candidate_events table."""
        self._active_clusters.clear()
        self.db.clear_candidate_events()

    async def process_stream(
        self,
        stream: TagStream,
        max_events: Optional[int] = None
    ) -> AsyncIterator[CandidateEvent]:
        """
        Consume real-time TagStream and yield CandidateEvents as they evolve.
        """
        event_count = 0
        async for reading in stream.subscribe():
            candidate = self.process_reading(reading)
            if candidate is not None:
                yield candidate
                event_count += 1
                if max_events is not None and event_count >= max_events:
                    break
