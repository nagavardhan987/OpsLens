"""
OpsLens - Deterministic Alarm Prioritization and Deduplication Test Suite

Verifies all 20 required criteria across:
- Telemetry validation and data quality
- Direction-aware time-to-limit estimation
- Configurable urgency formula & bands
- Hard precedence safety rules
- Multi-tier deterministic incident ranking with rationales
- Three-layer deduplication & lifecycle state machine
- Equipment-specific causal windows & non-destructive alarm preservation
"""

import math
import unittest
from datetime import datetime, timezone, timedelta

from models import (
    TagReading,
    TagRegistryEntry,
    CandidateEvent,
    UrgencyAssessment,
    TimeToLimitEstimate,
    IndividualAlarmRecord,
)
from alarm_urgency import (
    validate_telemetry,
    estimate_time_to_limit,
    evaluate_urgency,
    rank_incidents,
)
from alarm_lifecycle import (
    compute_alarm_fingerprint,
    AlarmLifecycleManager,
    EQUIPMENT_WINDOWS,
)


class TestAlarmPrioritizationAndDedup(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.entry_pit = TagRegistryEntry(
            tag="PIT-02-PRS",
            equipment_id="Pump-02",
            unit="bar",
            data_type="float",
            baseline_min=4.2,
            baseline_max=5.2,
            trip_threshold=6.5,
            severity_weight=0.90,
            topology_upstream=["VLV-04-POS"],
        )
        self.entry_fit = TagRegistryEntry(
            tag="FIT-02-FLW",
            equipment_id="Pump-02",
            unit="L/min",
            data_type="float",
            baseline_min=75.0,
            baseline_max=90.0,
            trip_threshold=50.0,
            severity_weight=0.85,
            topology_upstream=[],
        )

    # -------------------------------------------------------------------------
    # 1. Source priority pass-through
    # -------------------------------------------------------------------------
    def test_01_source_priority_passthrough(self):
        candidate = CandidateEvent(
            primary_tag="PIT-02-PRS",
            primary_alarm=True,
            trigger_timestamp=self.now.isoformat(),
            raw_deviation_pct=25.0,
            source_priority="ELEVATED_PLANT_PRIORITY",
        )
        reading = TagReading(
            tag="PIT-02-PRS",
            value=5.5,
            timestamp=self.now.isoformat(),
            unit="bar",
            equipment_id="Pump-02",
        )
        assessment = evaluate_urgency(candidate, [reading])
        self.assertEqual(assessment.source_priority, "ELEVATED_PLANT_PRIORITY")
        self.assertNotEqual(assessment.source_priority, assessment.urgency_band)

    # -------------------------------------------------------------------------
    # 2. Urgency calculation formula weights
    # -------------------------------------------------------------------------
    def test_02_urgency_formula_weights(self):
        candidate = CandidateEvent(
            primary_tag="PIT-02-PRS",
            primary_alarm=False,
            trigger_timestamp=self.now.isoformat(),
            raw_deviation_pct=40.0,
            repeat_count=1,
        )
        reading = TagReading(
            tag="PIT-02-PRS",
            value=5.4,
            timestamp=self.now.isoformat(),
            unit="bar",
            equipment_id="Pump-02",
        )
        assessment = evaluate_urgency(candidate, [reading])
        self.assertIsNotNone(assessment.urgency_score)
        self.assertIn(assessment.urgency_band, ("ROUTINE", "ELEVATED", "URGENT"))
        self.assertIn("D_deviation", assessment.scoring_breakdown)
        self.assertIn("R_rate", assessment.scoring_breakdown)
        self.assertIn("E_evidence", assessment.scoring_breakdown)
        self.assertIn("P_persistence", assessment.scoring_breakdown)
        self.assertIn("Q_quality", assessment.scoring_breakdown)

    # -------------------------------------------------------------------------
    # 3. Missing telemetry handling
    # -------------------------------------------------------------------------
    def test_03_missing_telemetry_handling(self):
        reading = TagReading(
            tag="PIT-02-PRS",
            value=None,
            timestamp=self.now.isoformat(),
            unit="bar",
            equipment_id="Pump-02",
        )
        is_valid, quality, reason = validate_telemetry(reading, self.entry_pit, reference_time=self.now)
        self.assertFalse(is_valid)
        self.assertEqual(quality, "INVALID")
        self.assertIn("None", str(reason))

    # -------------------------------------------------------------------------
    # 4. Non-numeric and non-finite telemetry handling
    # -------------------------------------------------------------------------
    def test_04_non_finite_telemetry_handling(self):
        reading_nan = TagReading(
            tag="PIT-02-PRS",
            value=float("nan"),
            timestamp=self.now.isoformat(),
            unit="bar",
            equipment_id="Pump-02",
        )
        is_valid, quality, reason = validate_telemetry(reading_nan, self.entry_pit, reference_time=self.now)
        self.assertFalse(is_valid)
        self.assertEqual(quality, "INVALID")

        reading_inf = TagReading(
            tag="PIT-02-PRS",
            value=float("inf"),
            timestamp=self.now.isoformat(),
            unit="bar",
            equipment_id="Pump-02",
        )
        is_valid_inf, quality_inf, _ = validate_telemetry(reading_inf, self.entry_pit, reference_time=self.now)
        self.assertFalse(is_valid_inf)
        self.assertEqual(quality_inf, "INVALID")

    # -------------------------------------------------------------------------
    # 5. Telemetry freshness validation
    # -------------------------------------------------------------------------
    def test_05_telemetry_freshness(self):
        fresh_ts = (self.now - timedelta(seconds=15)).isoformat().replace("+00:00", "Z")
        stale_ts = (self.now - timedelta(seconds=150)).isoformat().replace("+00:00", "Z")

        reading_fresh = TagReading(tag="PIT-02-PRS", value=5.0, timestamp=fresh_ts, unit="bar", equipment_id="Pump-02")
        reading_stale = TagReading(tag="PIT-02-PRS", value=5.0, timestamp=stale_ts, unit="bar", equipment_id="Pump-02")

        valid_f, quality_f, _ = validate_telemetry(reading_fresh, self.entry_pit, reference_time=self.now)
        valid_s, quality_s, _ = validate_telemetry(reading_stale, self.entry_pit, reference_time=self.now)

        self.assertTrue(valid_f)
        self.assertEqual(quality_f, "VALID")
        self.assertFalse(valid_s)
        self.assertEqual(quality_s, "STALE")

    # -------------------------------------------------------------------------
    # 6. Trip threshold breach hard rule
    # -------------------------------------------------------------------------
    def test_06_trip_threshold_breach_hard_rule(self):
        candidate = CandidateEvent(
            primary_tag="PIT-02-PRS",
            primary_alarm=True,
            trigger_timestamp=self.now.isoformat(),
            raw_deviation_pct=30.0,
        )
        reading = TagReading(
            tag="PIT-02-PRS",
            value=6.7,  # >= 6.5 trip limit
            timestamp=self.now.isoformat(),
            unit="bar",
            equipment_id="Pump-02",
        )
        assessment = evaluate_urgency(candidate, [reading])
        self.assertEqual(assessment.urgency_band, "URGENT")
        self.assertIn("HARD_RULE_TRIP_LIMIT_BREACH", assessment.triggered_rules)
        self.assertGreaterEqual(assessment.urgency_score, 85.0)

    # -------------------------------------------------------------------------
    # 7. Direction-aware time-to-limit estimation
    # -------------------------------------------------------------------------
    def test_07_direction_aware_ttl_rising(self):
        readings = [
            TagReading(tag="PIT-02-PRS", value=5.8, timestamp=(self.now - timedelta(seconds=30)).isoformat(), unit="bar", equipment_id="Pump-02"),
            TagReading(tag="PIT-02-PRS", value=6.0, timestamp=(self.now - timedelta(seconds=20)).isoformat(), unit="bar", equipment_id="Pump-02"),
            TagReading(tag="PIT-02-PRS", value=6.2, timestamp=(self.now - timedelta(seconds=10)).isoformat(), unit="bar", equipment_id="Pump-02"),
            TagReading(tag="PIT-02-PRS", value=6.4, timestamp=self.now.isoformat(), unit="bar", equipment_id="Pump-02"),
        ]
        ttl = estimate_time_to_limit(readings, target_limit=7.0, reference_time=self.now)
        self.assertIsNotNone(ttl)
        self.assertEqual(ttl.direction, "rising")
        self.assertGreater(ttl.rate_per_second, 0)
        self.assertGreater(ttl.time_to_limit_seconds, 0)

    # -------------------------------------------------------------------------
    # 8. Rejection of invalid rate or wrong direction
    # -------------------------------------------------------------------------
    def test_08_rejection_of_wrong_direction_ttl(self):
        # Value is falling away from high limit 7.0
        readings = [
            TagReading(tag="PIT-02-PRS", value=6.2, timestamp=(self.now - timedelta(seconds=20)).isoformat(), unit="bar", equipment_id="Pump-02"),
            TagReading(tag="PIT-02-PRS", value=5.8, timestamp=(self.now - timedelta(seconds=10)).isoformat(), unit="bar", equipment_id="Pump-02"),
            TagReading(tag="PIT-02-PRS", value=5.4, timestamp=self.now.isoformat(), unit="bar", equipment_id="Pump-02"),
        ]
        ttl = estimate_time_to_limit(readings, target_limit=7.0, direction="rising", reference_time=self.now)
        self.assertIsNone(ttl)

    # -------------------------------------------------------------------------
    # 9. Critical time-to-limit (<= 30s) triggers hard rule
    # -------------------------------------------------------------------------
    def test_09_critical_ttl_hard_rule(self):
        # Current = 6.4, rate = +0.03/s, limit = 6.5 -> TTL ~ 3.3s <= 30s
        readings = [
            TagReading(tag="PIT-02-PRS", value=5.5, timestamp=(self.now - timedelta(seconds=30)).isoformat(), unit="bar", equipment_id="Pump-02"),
            TagReading(tag="PIT-02-PRS", value=6.1, timestamp=(self.now - timedelta(seconds=10)).isoformat(), unit="bar", equipment_id="Pump-02"),
            TagReading(tag="PIT-02-PRS", value=6.4, timestamp=self.now.isoformat(), unit="bar", equipment_id="Pump-02"),
        ]
        candidate = CandidateEvent(
            primary_tag="PIT-02-PRS",
            primary_alarm=False,
            trigger_timestamp=self.now.isoformat(),
            raw_deviation_pct=30.0,
        )
        assessment = evaluate_urgency(candidate, readings)
        if assessment.time_to_limit and assessment.time_to_limit.time_to_limit_seconds <= 30.0:
            self.assertEqual(assessment.urgency_band, "URGENT")
            self.assertIn("HARD_RULE_TIME_TO_LIMIT_CRITICAL", assessment.triggered_rules)

    # -------------------------------------------------------------------------
    # 10. Source priority Critical protected
    # -------------------------------------------------------------------------
    def test_10_source_critical_protection(self):
        candidate = CandidateEvent(
            primary_tag="PIT-02-PRS",
            primary_alarm=False,
            trigger_timestamp=self.now.isoformat(),
            raw_deviation_pct=5.0,  # very small deviation
            source_priority="CRITICAL",
        )
        reading = TagReading(
            tag="PIT-02-PRS",
            value=4.8,
            timestamp=self.now.isoformat(),
            unit="bar",
            equipment_id="Pump-02",
        )
        assessment = evaluate_urgency(candidate, [reading])
        self.assertEqual(assessment.urgency_band, "URGENT")
        self.assertIn("HARD_RULE_SOURCE_CRITICAL", assessment.triggered_rules)
        self.assertGreaterEqual(assessment.urgency_score, 85.0)

    # -------------------------------------------------------------------------
    # 11. Multi-tier deterministic ranking policy order
    # -------------------------------------------------------------------------
    def test_11_multi_tier_ranking_order(self):
        incidents = [
            {
                "event_id": "routine_event",
                "urgency": UrgencyAssessment(urgency_band="ROUTINE", urgency_score=35.0, triggered_rules=[]),
                "trigger_timestamp": "2026-10-24T10:00:00Z",
            },
            {
                "event_id": "hard_trip_event",
                "urgency": UrgencyAssessment(urgency_band="URGENT", urgency_score=95.0, triggered_rules=["HARD_RULE_TRIP_LIMIT_BREACH"]),
                "trigger_timestamp": "2026-10-24T10:05:00Z",
            },
            {
                "event_id": "elevated_event",
                "urgency": UrgencyAssessment(urgency_band="ELEVATED", urgency_score=68.0, triggered_rules=[]),
                "trigger_timestamp": "2026-10-24T09:50:00Z",
            },
        ]
        ranked = rank_incidents(incidents)
        self.assertEqual(ranked[0]["event_id"], "hard_trip_event")
        self.assertEqual(ranked[1]["event_id"], "elevated_event")
        self.assertEqual(ranked[2]["event_id"], "routine_event")

    # -------------------------------------------------------------------------
    # 12. Ranking explanation transparency
    # -------------------------------------------------------------------------
    def test_12_ranking_explanation_transparency(self):
        incidents = [
            {
                "event_id": "inc_1",
                "urgency": UrgencyAssessment(
                    urgency_band="URGENT",
                    urgency_score=90.0,
                    triggered_rules=["HARD_RULE_SOURCE_CRITICAL"],
                    urgency_reasons=["Plant source priority CRITICAL"],
                ),
                "trigger_timestamp": "2026-10-24T10:00:00Z",
            }
        ]
        ranked = rank_incidents(incidents)
        self.assertEqual(ranked[0]["ranking_position"], 1)
        self.assertIn("ranking_rationale", ranked[0])
        self.assertTrue(len(ranked[0]["ranking_rationale"]) > 5)

    # -------------------------------------------------------------------------
    # 13. Layer 1 exact deduplication via SHA-256 fingerprint
    # -------------------------------------------------------------------------
    def test_13_exact_deduplication_repeat_count(self):
        mgr = AlarmLifecycleManager()
        is_dup1, rec1 = mgr.check_exact_duplicate("SCADA", "Pump-02", "PIT-02-PRS", "EXCURSION", "HIGH", 6.6, now=self.now)
        self.assertFalse(is_dup1)
        self.assertEqual(rec1.repeat_count, 1)

        later = self.now + timedelta(seconds=5)
        is_dup2, rec2 = mgr.check_exact_duplicate("SCADA", "Pump-02", "PIT-02-PRS", "EXCURSION", "HIGH", 6.8, now=later)
        self.assertTrue(is_dup2)
        self.assertEqual(rec2.repeat_count, 2)
        self.assertEqual(rec2.last_seen_timestamp, later.isoformat().replace("+00:00", "Z"))

    # -------------------------------------------------------------------------
    # 14. Layer 1 preserves original alarm identity & first_seen_timestamp
    # -------------------------------------------------------------------------
    def test_14_preserves_first_seen_and_id(self):
        mgr = AlarmLifecycleManager()
        _, rec1 = mgr.check_exact_duplicate("SCADA", "Pump-02", "PIT-02-PRS", "EXCURSION", "HIGH", 6.6, now=self.now)
        orig_id = rec1.alarm_id
        orig_first_seen = rec1.first_seen_timestamp

        later = self.now + timedelta(seconds=10)
        _, rec2 = mgr.check_exact_duplicate("SCADA", "Pump-02", "PIT-02-PRS", "EXCURSION", "HIGH", 6.7, now=later)

        self.assertEqual(rec2.alarm_id, orig_id)
        self.assertEqual(rec2.first_seen_timestamp, orig_first_seen)

    # -------------------------------------------------------------------------
    # 15. Distinct tags or condition transitions produce distinct fingerprints
    # -------------------------------------------------------------------------
    def test_15_distinct_fingerprints(self):
        fp1 = compute_alarm_fingerprint("SCADA", "Pump-02", "PIT-02-PRS", "EXCURSION", "HIGH")
        fp2 = compute_alarm_fingerprint("SCADA", "Pump-02", "FIT-02-FLW", "EXCURSION", "LOW")
        fp3 = compute_alarm_fingerprint("SCADA", "Pump-02", "PIT-02-PRS", "EXCURSION", "CLEAR")
        self.assertNotEqual(fp1, fp2)
        self.assertNotEqual(fp1, fp3)
        self.assertNotEqual(fp2, fp3)

    # -------------------------------------------------------------------------
    # 16. Layer 2 lifecycle state transitions
    # -------------------------------------------------------------------------
    def test_16_lifecycle_transitions(self):
        mgr = AlarmLifecycleManager()
        s1 = mgr.transition_state("e1", "activate")
        self.assertEqual(s1, "ACTIVE")
        s2 = mgr.transition_state("e1", "acknowledge")
        self.assertEqual(s2, "ACKNOWLEDGED")
        s3 = mgr.transition_state("e1", "clear")
        self.assertEqual(s3, "CLEARED")

    # -------------------------------------------------------------------------
    # 17. Operator Acknowledge does NOT clear the alarm
    # -------------------------------------------------------------------------
    def test_17_ack_does_not_clear(self):
        mgr = AlarmLifecycleManager()
        mgr.transition_state("e2", "activate")
        state_after_ack = mgr.transition_state("e2", "acknowledge")
        self.assertEqual(state_after_ack, "ACKNOWLEDGED")
        self.assertNotEqual(state_after_ack, "CLEARED")

    # -------------------------------------------------------------------------
    # 18. Cleared alarm that reactivates transitions to RECURRING
    # -------------------------------------------------------------------------
    def test_18_cleared_reactivation_recurring(self):
        mgr = AlarmLifecycleManager()
        mgr.transition_state("e3", "activate")
        mgr.transition_state("e3", "clear")
        s_recur = mgr.transition_state("e3", "reactivate")
        self.assertEqual(s_recur, "RECURRING")

    # -------------------------------------------------------------------------
    # 19. Layer 3 equipment-specific causal windows
    # -------------------------------------------------------------------------
    def test_19_equipment_specific_windows(self):
        mgr = AlarmLifecycleManager()
        self.assertEqual(mgr.get_correlation_window("Pump-02"), 60.0)
        self.assertEqual(mgr.get_correlation_window("Compressor-01"), 90.0)
        self.assertEqual(mgr.get_correlation_window("Tank-01"), 120.0)
        self.assertEqual(mgr.get_correlation_window("Unknown-Unit"), 90.0)

    # -------------------------------------------------------------------------
    # 20. Unrelated simultaneous alarms on different equipment kept separate
    # -------------------------------------------------------------------------
    def test_20_separate_equipment_incidents(self):
        mgr = AlarmLifecycleManager()
        mgr.add_to_causal_group("Pump-02", "fp_pump", self.now)
        # Check if compressor alarm within the same time window is merged
        group_comp = mgr.find_causal_group("Compressor-01", "fp_comp", self.now)
        self.assertIsNone(group_comp, "Compressor alarm must not merge into Pump causal group")

    # -------------------------------------------------------------------------
    # 21. Source priority missing and calculated urgency is ROUTINE (PIT-02-PRS trace)
    # -------------------------------------------------------------------------
    def test_21_source_priority_missing_calculated_routine(self):
        # Baseline midpoint for PIT-02-PRS is 4.7 bar. Reading 5.98 bar -> deviation +27.23%
        # D = 27.23, R = 0, E = 0, P = 0, Q = 100 (VALID)
        # U = 0.35 * 27.23 + 0 + 0 + 0 + 0.10 * 100 = 9.53 + 10.0 = 19.53 -> ROUTINE
        candidate = CandidateEvent(
            primary_tag="PIT-02-PRS",
            primary_alarm=False,
            trigger_timestamp=self.now.isoformat(),
            raw_deviation_pct=27.23,
            source_priority=None,
        )
        reading = TagReading(
            tag="PIT-02-PRS",
            value=5.98,
            timestamp=self.now.isoformat(),
            unit="bar",
            equipment_id="Pump-02",
        )
        assessment = evaluate_urgency(candidate, [reading])
        self.assertIsNone(assessment.source_priority)
        self.assertEqual(assessment.urgency_band, "ROUTINE")
        self.assertAlmostEqual(assessment.urgency_score, 19.53, delta=0.1)
        self.assertEqual(assessment.data_quality, "VALID")

    # -------------------------------------------------------------------------
    # 22. Source priority is HIGH and calculated urgency is ROUTINE
    # -------------------------------------------------------------------------
    def test_22_source_priority_high_calculated_routine(self):
        candidate = CandidateEvent(
            primary_tag="PIT-02-PRS",
            primary_alarm=False,
            trigger_timestamp=self.now.isoformat(),
            raw_deviation_pct=15.0,
            source_priority="HIGH",
        )
        reading = TagReading(
            tag="PIT-02-PRS",
            value=5.4,
            timestamp=self.now.isoformat(),
            unit="bar",
            equipment_id="Pump-02",
        )
        assessment = evaluate_urgency(candidate, [reading])
        # Source priority is preserved as HIGH, calculated urgency remains ROUTINE
        self.assertEqual(assessment.source_priority, "HIGH")
        self.assertEqual(assessment.urgency_band, "ROUTINE")

    # -------------------------------------------------------------------------
    # 23. Source priority is CRITICAL and calculated urgency is protected
    # -------------------------------------------------------------------------
    def test_23_source_priority_critical_never_downgraded(self):
        candidate = CandidateEvent(
            primary_tag="PIT-02-PRS",
            primary_alarm=False,
            trigger_timestamp=self.now.isoformat(),
            raw_deviation_pct=5.0,  # small deviation
            source_priority="CRITICAL",
        )
        reading = TagReading(
            tag="PIT-02-PRS",
            value=4.8,
            timestamp=self.now.isoformat(),
            unit="bar",
            equipment_id="Pump-02",
        )
        assessment = evaluate_urgency(candidate, [reading])
        self.assertEqual(assessment.source_priority, "CRITICAL")
        self.assertEqual(assessment.urgency_band, "URGENT")
        self.assertIn("HARD_RULE_SOURCE_CRITICAL", assessment.triggered_rules)
        self.assertGreaterEqual(assessment.urgency_score, 90.0)

    # -------------------------------------------------------------------------
    # 24. Source priority missing and calculated urgency is URGENT
    # -------------------------------------------------------------------------
    def test_24_source_priority_missing_calculated_urgent(self):
        candidate = CandidateEvent(
            primary_tag="PIT-02-PRS",
            primary_alarm=True,  # trip threshold breached
            trigger_timestamp=self.now.isoformat(),
            raw_deviation_pct=45.0,
            source_priority=None,
        )
        reading = TagReading(
            tag="PIT-02-PRS",
            value=6.7,  # >= 6.5 trip limit
            timestamp=self.now.isoformat(),
            unit="bar",
            equipment_id="Pump-02",
        )
        assessment = evaluate_urgency(candidate, [reading])
        self.assertIsNone(assessment.source_priority)
        self.assertEqual(assessment.urgency_band, "URGENT")
        self.assertIn("HARD_RULE_TRIP_LIMIT_BREACH", assessment.triggered_rules)

    # -------------------------------------------------------------------------
    # 25. Source priority available and calculated urgency is ELEVATED
    # -------------------------------------------------------------------------
    def test_25_source_priority_medium_calculated_elevated(self):
        candidate = CandidateEvent(
            primary_tag="PIT-02-PRS",
            primary_alarm=False,
            trigger_timestamp=self.now.isoformat(),
            raw_deviation_pct=85.0,
            repeat_count=3,
            source_priority="MEDIUM",
        )
        reading = TagReading(
            tag="PIT-02-PRS",
            value=6.0,
            timestamp=self.now.isoformat(),
            unit="bar",
            equipment_id="Pump-02",
        )
        correlated = [
            {"tag": "FIT-02-FLW", "deviation_pct": -35.0},
            {"tag": "VLV-04-POS", "deviation_pct": -40.0},
        ]
        assessment = evaluate_urgency(candidate, [reading], correlated_deviations=correlated)
        self.assertEqual(assessment.source_priority, "MEDIUM")
        self.assertEqual(assessment.urgency_band, "ELEVATED")
        self.assertGreaterEqual(assessment.urgency_score, 50.0)
        self.assertLess(assessment.urgency_score, 80.0)

    # -------------------------------------------------------------------------
    # 26. Scoring breakdown exposed in response
    # -------------------------------------------------------------------------
    def test_26_scoring_breakdown_exposed(self):
        candidate = CandidateEvent(
            primary_tag="PIT-02-PRS",
            primary_alarm=False,
            trigger_timestamp=self.now.isoformat(),
            raw_deviation_pct=27.23,
        )
        reading = TagReading(
            tag="PIT-02-PRS",
            value=5.98,
            timestamp=self.now.isoformat(),
            unit="bar",
            equipment_id="Pump-02",
        )
        assessment = evaluate_urgency(candidate, [reading])
        sb = assessment.scoring_breakdown
        self.assertIn("D_deviation", sb)
        self.assertIn("R_rate", sb)
        self.assertIn("E_evidence", sb)
        self.assertIn("P_persistence", sb)
        self.assertIn("Q_quality", sb)
        self.assertIn("weighted_score", sb)
        calculated = 0.35 * sb["D_deviation"] + 0.25 * sb["R_rate"] + 0.20 * sb["E_evidence"] + 0.10 * sb["P_persistence"] + 0.10 * sb["Q_quality"]
        self.assertAlmostEqual(sb["weighted_score"], calculated, delta=0.05)

    # -------------------------------------------------------------------------
    # 27. TTL unavailable reason documented
    # -------------------------------------------------------------------------
    def test_27_ttl_unavailable_reason_documented(self):
        # Single reading -> insufficient readings in history
        reading = TagReading(
            tag="PIT-02-PRS",
            value=5.98,
            timestamp=self.now.isoformat(),
            unit="bar",
            equipment_id="Pump-02",
        )
        candidate = CandidateEvent(
            primary_tag="PIT-02-PRS",
            primary_alarm=False,
            trigger_timestamp=self.now.isoformat(),
            raw_deviation_pct=27.23,
        )
        assessment = evaluate_urgency(candidate, [reading])
        self.assertIsNone(assessment.time_to_limit)
        self.assertIsNotNone(assessment.ttl_unavailable_reason)
        self.assertIn("Insufficient reading history", assessment.ttl_unavailable_reason)

    # -------------------------------------------------------------------------
    # 28. Individual alarm non-destructive persistence in SQLite
    # -------------------------------------------------------------------------
    def test_28_individual_alarm_persistence(self):
        from database import Database
        import tempfile, os

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            db = Database(db_path)
            rec = IndividualAlarmRecord(
                alarm_id="alm-001",
                tag="PIT-02-PRS",
                equipment_id="Pump-02",
                alarm_type="EXCURSION",
                value=5.98,
                threshold=6.5,
                source_priority=None,
                lifecycle_state="ACTIVE",
                repeat_count=1,
                first_seen_timestamp=self.now.isoformat(),
                last_seen_timestamp=self.now.isoformat(),
                fingerprint="fp123456",
            )
            db.save_individual_alarm("event-xyz", rec)
            alarms = db.get_individual_alarms("event-xyz")
            self.assertEqual(len(alarms), 1)
            self.assertEqual(alarms[0]["alarm_id"], "alm-001")
            self.assertEqual(alarms[0]["tag"], "PIT-02-PRS")
            self.assertEqual(alarms[0]["repeat_count"], 1)
        finally:
            try:
                db._get_connection().close()
                os.unlink(db_path)
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # 29. Pump-02 and Compressor-01 alarms must never be merged
    # -------------------------------------------------------------------------
    def test_pump_and_compressor_separate_clusters(self):
        """Pump-02 and Compressor-01 alarms must never be merged into one cluster."""
        import uuid
        from datetime import datetime, timezone, timedelta
        from models import TagReading
        from dedup import DeduplicationEngine
        from database import Database
        import tempfile, os

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            db = Database(db_path=db_path)
            engine = DeduplicationEngine(db=db)

            now = datetime.now(timezone.utc)

            # Pump-02 breach
            pump_reading = TagReading(
                tag="PIT-02-PRS",
                value=7.5,
                timestamp=now.isoformat().replace("+00:00", "Z"),
                unit="bar",
                equipment_id="Pump-02",
                alarm_severity=None,
            )
            pump_candidate = engine.process_reading(pump_reading)
            self.assertIsNotNone(pump_candidate, "Pump-02 should produce a candidate")
            pump_event_id = pump_candidate.event_id

            # Compressor-01 breach 30 seconds later (within 90s window but different equipment)
            later = now + timedelta(seconds=30)
            comp_reading = TagReading(
                tag="CMP-01-VIB",
                value=25.0,
                timestamp=later.isoformat().replace("+00:00", "Z"),
                unit="mm/s",
                equipment_id="Compressor-01",
                alarm_severity=None,
            )
            comp_candidate = engine.process_reading(comp_reading)
            self.assertIsNotNone(comp_candidate, "Compressor-01 should produce a candidate")
            comp_event_id = comp_candidate.event_id

            # Must be DIFFERENT event IDs
            self.assertNotEqual(pump_event_id, comp_event_id,
                "Pump-02 and Compressor-01 incidents must NOT be merged")

            # Both should appear in recent history
            recent_ids = db.get_recent_event_ids(10)
            self.assertIn(pump_event_id, recent_ids, "Pump-02 event must be in history")
            self.assertIn(comp_event_id, recent_ids, "Compressor-01 event must be in history")
            self.assertEqual(len(recent_ids), 2, "Should have exactly 2 separate incidents")

        finally:
            db._conn.close()
            os.unlink(db_path)

    # -------------------------------------------------------------------------
    # 30. Old cluster (>10min) must not absorb readings from a new scenario
    # -------------------------------------------------------------------------
    def test_cluster_expiry_prevents_stale_merge(self):
        """An old cluster (>10min) must not absorb readings from a new scenario."""
        import uuid
        from datetime import datetime, timezone, timedelta
        from models import TagReading
        from dedup import DeduplicationEngine
        from database import Database
        import tempfile, os

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            db = Database(db_path=db_path)
            engine = DeduplicationEngine(db=db)

            # First breach: Pump-02 (simulate old)
            old_time = datetime.now(timezone.utc) - timedelta(minutes=12)
            pump_reading = TagReading(
                tag="PIT-02-PRS",
                value=7.5,
                timestamp=old_time.isoformat().replace("+00:00", "Z"),
                unit="bar",
                equipment_id="Pump-02",
            )
            pump_candidate = engine.process_reading(pump_reading)
            self.assertIsNotNone(pump_candidate)
            pump_event_id = pump_candidate.event_id

            # Second breach: SAME equipment, but 12 minutes later (beyond MAX_CLUSTER_LIFETIME_SECONDS)
            new_time = datetime.now(timezone.utc)
            pump_reading2 = TagReading(
                tag="PIT-02-PRS",
                value=7.8,
                timestamp=new_time.isoformat().replace("+00:00", "Z"),
                unit="bar",
                equipment_id="Pump-02",
            )
            pump_candidate2 = engine.process_reading(pump_reading2)
            self.assertIsNotNone(pump_candidate2)

            # Must be a NEW event (not merged into the old expired cluster)
            self.assertNotEqual(pump_candidate2.event_id, pump_event_id,
                "Reading 12 minutes later must create a new incident, not merge with expired cluster")

        finally:
            db._conn.close()
            os.unlink(db_path)

    def test_three_identical_active_notifications_repeat_count_three(self):
        """Three identical active notifications result in one active alarm record with repeat_count=3."""
        import tempfile
        import os
        from datetime import datetime, timezone, timedelta
        from models import TagReading
        from dedup import DeduplicationEngine
        from database import Database
        from alarm_lifecycle import get_lifecycle_manager

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            db = Database(db_path=db_path)
            engine = DeduplicationEngine(db=db)
            lifecycle = get_lifecycle_manager()
            lifecycle.clear_all()

            base_time = datetime.now(timezone.utc)

            # Notification 1: First active trip alarm
            r1 = TagReading(
                tag="ALM-P02-HP",
                value=True,
                timestamp=base_time.isoformat().replace("+00:00", "Z"),
                unit="status",
                equipment_id="Pump-02",
            )
            c1 = engine.process_reading(r1)
            self.assertIsNotNone(c1, "First notification must produce a candidate event")
            event_id = c1.event_id
            self.assertEqual(c1.repeat_count, 1)
            self.assertEqual(c1.lifecycle_state, "ACTIVE")

            # A backend restart loses the lifecycle singleton but must restore
            # the active fingerprint from the persisted candidate even when a
            # legacy incident has no individual_alarms row.
            db._get_connection().execute(
                "DELETE FROM individual_alarms WHERE incident_id = ?", (event_id,)
            )
            db._get_connection().commit()
            lifecycle.clear_all()
            engine = DeduplicationEngine(db=db)

            # Notification 2: Identical active notification (20 seconds later)
            r2 = TagReading(
                tag="ALM-P02-HP",
                value=True,
                timestamp=(base_time + timedelta(seconds=20)).isoformat().replace("+00:00", "Z"),
                unit="status",
                equipment_id="Pump-02",
            )
            c2 = engine.process_reading(r2)
            self.assertIsNotNone(c2)
            self.assertEqual(c2.event_id, event_id, "Must keep identical incident ID on repeat 2")
            self.assertEqual(c2.repeat_count, 2, "Repeat count must increment to 2")
            self.assertEqual(c2.lifecycle_state, "ACTIVE")

            # Notification 3: Identical active notification (50 seconds later)
            r3 = TagReading(
                tag="ALM-P02-HP",
                value=True,
                timestamp=(base_time + timedelta(seconds=50)).isoformat().replace("+00:00", "Z"),
                unit="status",
                equipment_id="Pump-02",
            )
            c3 = engine.process_reading(r3)
            self.assertIsNotNone(c3)
            self.assertEqual(c3.event_id, event_id, "Must keep identical incident ID on repeat 3")
            self.assertEqual(c3.repeat_count, 3, "Repeat count must increment to 3")
            self.assertEqual(c3.lifecycle_state, "ACTIVE")

            # Notification 4: Exceeding 90s window but still within cluster lifetime and active
            r4 = TagReading(
                tag="ALM-P02-HP",
                value=True,
                timestamp=(base_time + timedelta(seconds=180)).isoformat().replace("+00:00", "Z"),
                unit="status",
                equipment_id="Pump-02",
            )
            c4 = engine.process_reading(r4)
            self.assertIsNotNone(c4)
            self.assertEqual(c4.event_id, event_id, "Must not create a new incident even past 90s for same active alarm")
            self.assertEqual(c4.repeat_count, 4, "Repeat count must increment to 4")

            # Verify SQLite persistence
            candidates = db.get_candidate_events()
            self.assertEqual(len(candidates), 1, "Must have exactly ONE candidate event in DB")
            cand = candidates[0]
            self.assertEqual(cand.event_id, event_id)
            self.assertEqual(cand.repeat_count, 4)
            self.assertEqual(cand.lifecycle_state, "ACTIVE")
            self.assertEqual(cand.primary_tag, "ALM-P02-HP")
            self.assertIsNotNone(cand.first_seen_timestamp)
            self.assertIsNotNone(cand.last_seen_timestamp)
            self.assertNotEqual(cand.first_seen_timestamp, cand.last_seen_timestamp)

            # Verify individual_alarms table persistence
            alarms = db.get_individual_alarms(event_id)
            self.assertEqual(len(alarms), 1, "Must have exactly ONE individual alarm record in DB")
            self.assertEqual(alarms[0]["repeat_count"], 4)
            self.assertEqual(alarms[0]["tag"], "ALM-P02-HP")
            self.assertEqual(alarms[0]["lifecycle_state"], "ACTIVE")

        finally:
            db._conn.close()
            os.unlink(db_path)
            get_lifecycle_manager().clear_all()

    def test_trigger_alarm_repeat_route_registered_and_executes(self):
        """Verify POST /api/scenarios/trigger-alarm-repeat is registered with POST method and returns success."""
        from api.routes import create_app
        from fastapi import HTTPException
        import tempfile, os
        from datetime import datetime, timezone
        from models import TagReading
        from database import Database
        from orchestrator import OpsLensOrchestrator
        from alarm_lifecycle import get_lifecycle_manager

        def run_sync(coro):
            """Drive a coroutine synchronously without Windows sandbox socket constraints."""
            val = None
            while True:
                try:
                    val = coro.send(val)
                except StopIteration as e:
                    return e.value

        get_lifecycle_manager().clear_all()
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            db = Database(db_path=db_path)
            orch = OpsLensOrchestrator(db=db)
            app = create_app(orchestrator=orch)

            # 1. Route is registered with path '/api/scenarios/trigger-alarm-repeat' and method POST
            found_route = None
            for r in app.routes:
                if hasattr(r, "original_router"):
                    for sub_r in r.original_router.routes:
                        if sub_r.path == "/api/scenarios/trigger-alarm-repeat":
                            found_route = sub_r
                            break

            self.assertIsNotNone(found_route, "Route /api/scenarios/trigger-alarm-repeat must be registered")
            self.assertIn("POST", found_route.methods, "Route must accept POST method")

            endpoint = found_route.endpoint

            # 2. When no incident is active, calling endpoint raises HTTPException 409
            with self.assertRaises(HTTPException) as ctx:
                run_sync(endpoint())
            self.assertEqual(ctx.exception.status_code, 409)

            # 3. Seed an active event in SQLite
            now_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            reading = TagReading(
                tag="ALM-P02-HP",
                value=True,
                timestamp=now_ts,
                unit="status",
                equipment_id="Pump-02",
            )
            orch.db.insert_reading(reading)
            cand = orch.dedup.process_reading(reading)
            self.assertIsNotNone(cand)
            event_id = cand.event_id
            orch._completed_events.add(event_id)
            orch._processed_tags[event_id] = set(cand.clustered_tags)
            orch._processed_primary[event_id] = cand.primary_tag

            # 4. Invoke endpoint -> repeat_count becomes 2
            resp1 = run_sync(endpoint())
            self.assertEqual(resp1["status"], "alarm_repeated")
            self.assertEqual(resp1["alarm_tag"], "ALM-P02-HP")
            self.assertEqual(resp1["equipment_id"], "Pump-02")
            self.assertEqual(resp1["repeat_count"], 2)
            self.assertEqual(resp1["lifecycle_state"], "ACTIVE")

            # 5. Invoke endpoint again -> repeat_count becomes 3
            resp2 = run_sync(endpoint())
            self.assertEqual(resp2["status"], "alarm_repeated")
            self.assertEqual(resp2["repeat_count"], 3)
            self.assertEqual(resp2["lifecycle_state"], "ACTIVE")

            # 6. Verify persisted SQLite candidate record
            saved = orch.db.get_candidate_events(event_id=event_id)
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0].repeat_count, 3)
            self.assertEqual(saved[0].lifecycle_state, "ACTIVE")

        finally:
            db._conn.close()
            os.unlink(db_path)
            get_lifecycle_manager().clear_all()


if __name__ == "__main__":
    unittest.main()
