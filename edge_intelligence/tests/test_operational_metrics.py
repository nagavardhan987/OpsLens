"""
Tests for OpsLens Operational Metrics calculations.

Covers:
- Zero resolved incidents: MTTR and MTTR reduction are unavailable (null).
- One resolved incident: MTTR matches its actual recorded duration.
- Multiple resolved incidents: MTTR is the arithmetic mean of valid durations.
- Unresolved incidents are excluded from MTTR.
- Invalid timestamps and negative durations are excluded.
- Baseline missing or zero: MTTR reduction is unavailable.
- New incidents update counts.
- Resolving an incident updates open/resolved counts and MTTR.
- Repeated alarms update the appropriate repeat counter without creating duplicate incidents.
- Scope parameter distinguishes session-wide vs selected incident metrics.
- Context assembly latency reflects recorded measurements and remains separate from the target SLA.
"""

import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

from api.routes import create_app
from database import Database
from dedup import DeduplicationEngine
from models import TagReading, OperatorAction
from orchestrator import OpsLensOrchestrator
from alarm_lifecycle import get_lifecycle_manager


def run_sync(coro):
    """Drive a coroutine synchronously without event loop dependency."""
    val = None
    while True:
        try:
            val = coro.send(val)
        except StopIteration as e:
            return e.value


class TestOperationalMetrics(unittest.TestCase):
    def setUp(self):
        get_lifecycle_manager().clear_all()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_metrics.db")
        self.db = Database(db_path=self.db_path)
        self.orch = OpsLensOrchestrator(db=self.db)
        self.app = create_app(orchestrator=self.orch)
        self.dedup = DeduplicationEngine(db=self.db)

        # Locate /api/metrics/impact endpoint
        self.metrics_endpoint = None
        for r in self.app.routes:
            if hasattr(r, "original_router"):
                for sub_r in r.original_router.routes:
                    if sub_r.path == "/api/metrics/impact":
                        self.metrics_endpoint = sub_r.endpoint
                        break
        self.assertIsNotNone(self.metrics_endpoint, "Route /api/metrics/impact must be registered")

    def tearDown(self):
        self.db._conn.close()
        self.tmp_dir.cleanup()
        get_lifecycle_manager().clear_all()

    def _create_incident(self, tag="ALM-P02-HP", equipment="Pump-02", minutes_ago=30):
        trigger_dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        reading = TagReading(
            tag=tag,
            value=True,
            timestamp=trigger_dt.isoformat().replace("+00:00", "Z"),
            unit="status",
            equipment_id=equipment,
        )
        self.db.insert_reading(reading)
        candidate = self.dedup.process_reading(reading)
        self.assertIsNotNone(candidate)
        return candidate.event_id, trigger_dt

    def _resolve_incident(self, event_id, trigger_dt, duration_minutes=15.0):
        resolve_dt = trigger_dt + timedelta(minutes=duration_minutes)
        resolve_ts = resolve_dt.isoformat().replace("+00:00", "Z")
        action = OperatorAction(
            event_id=event_id,
            operator="Operator 1",
            action_type="RESOLVE",
            notes="Resolved during test",
            timestamp=resolve_ts,
        )
        self.db.save_operator_action(action)

    def test_zero_resolved_incidents_mttr_and_reduction_are_none(self):
        """When zero resolved incidents exist, MTTR and MTTR reduction must return None/null."""
        # 1 open incident
        self._create_incident()

        res = run_sync(self.metrics_endpoint(scope="session", event_id=None, baseline_mttr=45.0))
        self.assertEqual(res["total_incidents"], 1)
        self.assertEqual(res["open_incidents"], 1)
        self.assertEqual(res["resolved_incidents"], 0)
        self.assertEqual(res["valid_samples_count"], 0)
        self.assertIsNone(res["avg_mttr_minutes"], "MTTR must be None when no resolved incidents exist")
        self.assertIsNone(res["mttr_reduction_pct"], "MTTR reduction must be None when MTTR is unavailable")
        self.assertEqual(res["baseline_mttr_minutes"], 45.0)

    def test_one_resolved_incident_mttr_matches_recorded_duration(self):
        """With one resolved incident, MTTR equals its exact recorded duration."""
        eid, trigger_dt = self._create_incident(minutes_ago=20)
        self._resolve_incident(eid, trigger_dt, duration_minutes=12.5)

        res = run_sync(self.metrics_endpoint(scope="session", event_id=None, baseline_mttr=45.0))
        self.assertEqual(res["total_incidents"], 1)
        self.assertEqual(res["open_incidents"], 0)
        self.assertEqual(res["resolved_incidents"], 1)
        self.assertEqual(res["valid_samples_count"], 1)
        self.assertEqual(res["avg_mttr_minutes"], 12.5)
        # Reduction: ((45 - 12.5) / 45) * 100 = 72.2%
        expected_reduction = round(((45.0 - 12.5) / 45.0) * 100, 1)
        self.assertEqual(res["mttr_reduction_pct"], expected_reduction)

    def test_multiple_resolved_incidents_mttr_is_arithmetic_mean(self):
        """With multiple resolved incidents, MTTR is the arithmetic mean of valid durations."""
        eid1, t1 = self._create_incident(tag="ALM-P02-HP", equipment="Pump-02", minutes_ago=60)
        self._resolve_incident(eid1, t1, duration_minutes=10.0)

        eid2, t2 = self._create_incident(tag="ALM-C01-VB", equipment="Compressor-01", minutes_ago=40)
        self._resolve_incident(eid2, t2, duration_minutes=20.0)

        res = run_sync(self.metrics_endpoint(scope="session", event_id=None, baseline_mttr=45.0))
        self.assertEqual(res["total_incidents"], 2)
        self.assertEqual(res["open_incidents"], 0)
        self.assertEqual(res["resolved_incidents"], 2)
        self.assertEqual(res["valid_samples_count"], 2)
        # Mean of 10.0 and 20.0 is 15.0
        self.assertEqual(res["avg_mttr_minutes"], 15.0)
        # Reduction: ((45 - 15) / 45) * 100 = 66.7%
        expected_reduction = round(((45.0 - 15.0) / 45.0) * 100, 1)
        self.assertEqual(res["mttr_reduction_pct"], expected_reduction)

    def test_unresolved_incidents_are_excluded_from_mttr(self):
        """Unresolved incidents update total and open counts but do not dilute MTTR calculation."""
        eid1, t1 = self._create_incident(tag="ALM-P02-HP", equipment="Pump-02", minutes_ago=50)
        self._resolve_incident(eid1, t1, duration_minutes=16.0)

        # Create 2 unresolved incidents
        self._create_incident(tag="ALM-C01-VB", equipment="Compressor-01", minutes_ago=25)
        self._create_incident(tag="PIT-02-PRS", equipment="Pump-02", minutes_ago=10)

        res = run_sync(self.metrics_endpoint(scope="session", event_id=None, baseline_mttr=45.0))
        self.assertEqual(res["total_incidents"], 3)
        self.assertEqual(res["open_incidents"], 2)
        self.assertEqual(res["resolved_incidents"], 1)
        self.assertEqual(res["valid_samples_count"], 1)
        self.assertEqual(res["avg_mttr_minutes"], 16.0)

    def test_invalid_timestamps_and_negative_durations_excluded(self):
        """Resolution actions with negative duration (resolution before trigger) are excluded from MTTR."""
        eid, trigger_dt = self._create_incident(minutes_ago=20)
        # Resolution timestamp earlier than trigger timestamp (negative duration)
        self._resolve_incident(eid, trigger_dt, duration_minutes=-5.0)

        res = run_sync(self.metrics_endpoint(scope="session", event_id=None, baseline_mttr=45.0))
        self.assertEqual(res["total_incidents"], 1)
        self.assertEqual(res["valid_samples_count"], 0, "Negative duration must be excluded from valid samples")
        self.assertIsNone(res["avg_mttr_minutes"])
        self.assertIsNone(res["mttr_reduction_pct"])

    def test_baseline_missing_or_zero_disables_mttr_reduction(self):
        """When baseline is 0 or negative, MTTR reduction percentage returns None."""
        eid, trigger_dt = self._create_incident(minutes_ago=20)
        self._resolve_incident(eid, trigger_dt, duration_minutes=10.0)

        res_zero = run_sync(self.metrics_endpoint(scope="session", event_id=None, baseline_mttr=0.0))
        self.assertEqual(res_zero["avg_mttr_minutes"], 10.0)
        self.assertIsNone(res_zero["mttr_reduction_pct"], "Reduction must be None when baseline is 0")
        self.assertIsNone(res_zero["baseline_mttr_minutes"])

    def test_unconfigured_baseline_is_unavailable_by_default(self):
        eid, trigger_dt = self._create_incident(minutes_ago=20)
        self._resolve_incident(eid, trigger_dt, duration_minutes=10.0)

        res = run_sync(self.metrics_endpoint(scope="session", event_id=None))
        self.assertEqual(res["avg_mttr_minutes"], 10.0)
        self.assertIsNone(res["baseline_mttr_minutes"])
        self.assertIsNone(res["mttr_reduction_pct"])

    def test_repeated_alarms_do_not_create_duplicate_incidents(self):
        """Repeated alarms on same active incident increment repeat count without inflating incident count."""
        eid, trigger_dt = self._create_incident(tag="ALM-P02-HP", equipment="Pump-02", minutes_ago=10)

        # Trigger same alarm again 3 times with progressive timestamps
        for i in range(1, 4):
            reading = TagReading(
                tag="ALM-P02-HP",
                value=True,
                timestamp=(trigger_dt + timedelta(seconds=i * 15)).isoformat().replace("+00:00", "Z"),
                unit="status",
                equipment_id="Pump-02",
            )
            self.db.insert_reading(reading)
            self.dedup.process_reading(reading)

        res = run_sync(self.metrics_endpoint(scope="session", event_id=None, baseline_mttr=45.0))
        self.assertEqual(res["total_incidents"], 1, "Repeats must not create duplicate incidents")
        self.assertEqual(res["open_incidents"], 1)

        # Verify candidate event has repeat_count of 4
        candidates = self.db.get_candidate_events(event_id=eid)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].repeat_count, 4)

    def test_scope_selected_incident_vs_session(self):
        """Selected scope calculates metrics for the specific incident only."""
        eid1, t1 = self._create_incident(tag="ALM-P02-HP", equipment="Pump-02", minutes_ago=40)
        self._resolve_incident(eid1, t1, duration_minutes=8.0)

        eid2, t2 = self._create_incident(tag="ALM-C01-VB", equipment="Compressor-01", minutes_ago=20)
        # eid2 is left open

        # Session scope
        res_session = run_sync(self.metrics_endpoint(scope="session", event_id=None, baseline_mttr=45.0))
        self.assertEqual(res_session["total_incidents"], 2)
        self.assertEqual(res_session["resolved_incidents"], 1)
        self.assertEqual(res_session["open_incidents"], 1)

        # Selected scope: resolved incident
        res_eid1 = run_sync(self.metrics_endpoint(scope="selected", event_id=eid1, baseline_mttr=45.0))
        self.assertEqual(res_eid1["scope"], "selected")
        self.assertEqual(res_eid1["selected_event_id"], eid1)
        self.assertEqual(res_eid1["total_incidents"], 1)
        self.assertEqual(res_eid1["resolved_incidents"], 1)
        self.assertEqual(res_eid1["open_incidents"], 0)
        self.assertEqual(res_eid1["avg_mttr_minutes"], 8.0)

        # Selected scope: open incident
        res_eid2 = run_sync(self.metrics_endpoint(scope="selected", event_id=eid2, baseline_mttr=45.0))
        self.assertEqual(res_eid2["scope"], "selected")
        self.assertEqual(res_eid2["selected_event_id"], eid2)
        self.assertEqual(res_eid2["total_incidents"], 1)
        self.assertEqual(res_eid2["resolved_incidents"], 0)
        self.assertEqual(res_eid2["open_incidents"], 1)
        self.assertIsNone(res_eid2["avg_mttr_minutes"])

    def test_context_assembly_latency_separate_from_target_sla(self):
        """Context assembly target (< 2000 ms) remains static SLA, while stats reflect actual measurements."""
        res = run_sync(self.metrics_endpoint(scope="session", event_id=None, baseline_mttr=45.0))
        self.assertEqual(res["context_assembly_target_ms"], 2000)
        self.assertEqual(res["context_assembly_stats"]["sample_count"], 0)
        self.assertIsNone(res["context_assembly_stats"]["avg_ms"])


if __name__ == "__main__":
    unittest.main()
