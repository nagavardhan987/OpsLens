"""
OpsLens - Context Correlation Engine (Component 4)

Enriches CandidateEvents into CorrelatedEvents by querying the lookback window
via TagStream.get_window(), evaluating dynamic deviations, scoring plausibility
using causal topology graph distance and temporal precedence, and persisting
CorrelatedEvents to SQLite table `correlated_events`.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Any
from models import CandidateEvent, CorrelatedEvent, CorrelatedDeviation, TagReading, to_iso_utc
from registry_loader import RegistryLoader, get_registry_loader
from topology import TopologyGraph
from database import Database, DEFAULT_DB_PATH
from stream import TagStream


class CorrelationEngine:
    """
    Context correlation engine for OpsLens.
    Reconstructs causal upstream context without hardcoded assumptions.
    """

    def __init__(
        self,
        stream: Optional[TagStream] = None,
        db: Optional[Database] = None,
        registry_loader: Optional[RegistryLoader] = None,
        topology_graph: Optional[TopologyGraph] = None,
        noise_threshold_pct: float = 5.0,
        lookback_seconds: float = 120.0,
        max_topology_depth: int = 3
    ):
        self.db = db if db is not None else Database()
        self.stream = stream if stream is not None else TagStream(db_path=self.db.db_path)
        self.loader = registry_loader if registry_loader is not None else get_registry_loader()
        self.topology = topology_graph if topology_graph is not None else TopologyGraph(self.loader)
        self.noise_threshold_pct = noise_threshold_pct
        self.lookback_seconds = lookback_seconds
        self.max_topology_depth = max_topology_depth

    def _parse_timestamp(self, ts_str: str) -> datetime:
        clean = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def compute_tag_deviation(self, reading: TagReading) -> float:
        """Compute deviation percentage vs baseline midpoint for a tag reading."""
        entry = self.loader.get_tag(reading.tag)
        if entry.data_type == "bool":
            is_active = (
                reading.value is True
                or reading.value in [1.0, 1, "true", "True"]
            )
            return 100.0 if is_active else 0.0

        if entry.data_type == "float":
            midpoint = (entry.baseline_min + entry.baseline_max) / 2.0
            if abs(midpoint) < 1e-6:
                return 0.0
            val = float(reading.value)
            dev = ((val - midpoint) / midpoint) * 100.0
            return round(dev, 2)

        return 0.0

    async def correlate_event(self, candidate: CandidateEvent,
                              temporal_context: Optional[Dict[str, Any]] = None,
                              graph_context: Optional[List[str]] = None) -> CorrelatedEvent:
        """
        Enrich a CandidateEvent into a CorrelatedEvent:
        1. Look back [trigger_timestamp - 120s, trigger_timestamp] across equipment tags
           and reachable upstream topology tags.
        2. Detect deviation onset and temporal precedence for each tag.
        3. Filter by noise_threshold (>= 5%) and topology_distance (<= 3).
        4. Sort correlated_deviations by precedence (earliest onset first).
        5. Persist CorrelatedEvent to SQLite table `correlated_events`.
        """
        trigger_dt = self._parse_timestamp(candidate.trigger_timestamp)
        start_dt = trigger_dt - timedelta(seconds=self.lookback_seconds)
        end_dt = trigger_dt + timedelta(seconds=self.lookback_seconds)

        primary_entry = self.loader.get_tag(candidate.primary_tag)
        equipment_id = primary_entry.equipment_id

        # 1. Identify all target candidate tags to evaluate:
        # ALL tags on the same equipment_id PLUS any tag in upstream topology reachable up to depth 3
        equip_tags = set(self.loader.get_equipment_tag_names(equipment_id))
        if temporal_context:
            equip_tags.update(item.get("tag") for item in temporal_context.get("telemetry", []) if item.get("tag"))
        upstream_nodes = self.topology.get_upstream_nodes(candidate.primary_tag, max_depth=self.max_topology_depth)
        target_tags = equip_tags.union(set(upstream_nodes.keys()))

        # Query window readings via TagStream.get_window()
        # Note: If upstream tags span another equipment unit, query equipment_id
        window_readings = await self.stream.get_window(
            equipment_id=equipment_id,
            start=start_dt,
            end=end_dt,
            tags=list(target_tags)
        )

        # Group readings by tag chronologically
        tag_readings_map: Dict[str, List[TagReading]] = {t: [] for t in target_tags}
        for r in window_readings:
            if r.tag in tag_readings_map:
                tag_readings_map[r.tag].append(r)

        correlated_devs: List[CorrelatedDeviation] = []

        # 2. Evaluate each target tag for correlation
        for tag, readings in tag_readings_map.items():
            # Exclude the primary_tag itself from correlated_deviations
            if tag == candidate.primary_tag:
                continue

            if not readings:
                continue

            entry = self.loader.get_tag(tag)
            onset_timestamp: Optional[str] = None
            deviation_at_primary: Optional[float] = None

            # Detect onset: earliest sample where reading departs from normal baseline bounds
            for r in readings:
                dev = self.compute_tag_deviation(r)
                is_excursion = False
                if entry.data_type == "bool":
                    is_excursion = (r.value is True or r.value in [1.0, 1, "true", "True"])
                elif entry.data_type == "float":
                    val = float(r.value)
                    is_outside = (val < entry.baseline_min or val > entry.baseline_max)
                    if is_outside and abs(dev) >= self.noise_threshold_pct:
                        is_excursion = True

                if is_excursion and onset_timestamp is None:
                    onset_timestamp = r.timestamp

            if onset_timestamp is None:
                # Tag never departed from nominal baseline bounds
                continue

            # Deviation at primary trigger: take the reading closest to trigger_timestamp
            closest_reading = min(
                readings,
                key=lambda r: abs((self._parse_timestamp(r.timestamp) - trigger_dt).total_seconds())
            )
            deviation_at_primary = self.compute_tag_deviation(closest_reading)

            # Check topology distance
            dist = self.topology.get_distance(
                candidate.primary_tag,
                tag,
                max_depth=self.max_topology_depth
            )

            # Filtering Criteria:
            # 1. deviation_pct magnitude >= noise_threshold (default 5%)
            # 2. topology_distance <= 3 (and not None)
            if dist is None or dist > self.max_topology_depth:
                continue

            if abs(deviation_at_primary) < self.noise_threshold_pct:
                continue

            # Precedence check: does onset timestamp occur before primary trigger timestamp?
            onset_dt = self._parse_timestamp(onset_timestamp)
            precedes = (onset_dt < trigger_dt)

            correlated_devs.append(
                CorrelatedDeviation(
                    tag=tag,
                    deviation_pct=deviation_at_primary,
                    timestamp=onset_timestamp,
                    precedes_primary=precedes,
                    topology_distance=dist
                )
            )

        # 3. Sort correlated_deviations by precedence (earliest onset timestamp first)
        correlated_devs.sort(key=lambda d: self._parse_timestamp(d.timestamp))

        # 4. Construct CorrelatedEvent
        correlated_event = CorrelatedEvent(
            event_id=candidate.event_id,
            primary_tag=candidate.primary_tag,
            primary_alarm=candidate.primary_alarm,
            trigger_timestamp=candidate.trigger_timestamp,
            raw_deviation_pct=candidate.raw_deviation_pct,
            clustered_tags=list(candidate.clustered_tags),
            correlated_deviations=correlated_devs,
            temporal_context=temporal_context or {},
            graph_context=graph_context or [],
        )

        # 5. Write-through to SQLite table correlated_events
        self.db.save_correlated_event(correlated_event, equipment_id=equipment_id)

        return correlated_event

    async def correlate_candidate_events(
        self,
        candidate_events: List[CandidateEvent]
    ) -> List[CorrelatedEvent]:
        """Correlate a batch of CandidateEvents."""
        results = []
        for candidate in candidate_events:
            corr = await self.correlate_event(candidate)
            results.append(corr)
        return results
