"""
Tests for OpsLens Synthetic Telemetry Generator and Incident Archetypes
"""

import unittest
import asyncio
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone

from models import TagReading
from tag_registry import TAG_REGISTRY
from database import Database
from generator import SyntheticDataGenerator, BaselineNoiseEngine


class TestSyntheticDataGenerator(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_opslens.db"
        self.db = Database(db_path=self.db_path)
        self.generator = SyntheticDataGenerator(
            db=self.db,
            sample_interval=2.0,
            start_time=datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)
        )

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # 1. Baseline Noise & Write-Through SQLite Tests
    # -------------------------------------------------------------------------

    def test_baseline_noise_bounds_and_variance(self):
        """
        Requirement 2: Oscillates within baseline_min/max with realistic random walk
        noise (not flat jitter).
        """
        engine = BaselineNoiseEngine(TAG_REGISTRY)
        collected_values = {tag: [] for tag in TAG_REGISTRY if TAG_REGISTRY[tag].data_type == "float"}

        # Run 120 steps (~4 minutes of simulated plant telemetry)
        for _ in range(120):
            step_vals = engine.step(dt=2.0)
            for tag, val in step_vals.items():
                collected_values[tag].append(val)
                entry = TAG_REGISTRY[tag]
                self.assertTrue(
                    entry.baseline_min <= val <= entry.baseline_max,
                    f"Tag {tag} exceeded nominal bounds: val={val}, min={entry.baseline_min}, max={entry.baseline_max}"
                )

        # Verify values are dynamic (non-zero variance) rather than static flat
        for tag, vals in collected_values.items():
            unique_vals = set(vals)
            self.assertGreater(
                len(unique_vals), 5,
                f"Tag {tag} had too few unique values ({len(unique_vals)}); lacked random walk."
            )

    def test_sqlite_write_through(self):
        """
        Requirement 5: Push each TagReading write-through to shared SQLite table.
        """
        self.assertEqual(self.db.get_count(), 0)
        readings = self.generator.advance_step()

        # Total tags per sample interval must equal total tags in registry
        self.assertEqual(len(readings), len(TAG_REGISTRY))
        self.assertEqual(self.db.get_count(), len(TAG_REGISTRY))

        # Check contract fields of persisted rows
        for r in readings:
            self.assertIsInstance(r, TagReading)
            row = self.db.get_latest_reading(r.tag)
            self.assertIsNotNone(row)
            self.assertEqual(row.tag, r.tag)
            self.assertEqual(row.unit, r.unit)
            self.assertEqual(row.equipment_id, r.equipment_id)
            self.assertEqual(row.timestamp, r.timestamp)

    # -------------------------------------------------------------------------
    # 2. Scenario Archetype State Machine Tests
    # -------------------------------------------------------------------------

    def test_scenario_a_valve_restriction_cascade(self):
        """
        Requirement 3a: Valve restriction cascade
        (valve down -> flow down -> current up -> pressure up -> alarm), ~60-90s.
        """
        readings = list(self.generator.run_scenario("valve_restriction_cascade", speed_multiplier=float("inf")))
        self.assertGreater(len(readings), 0)

        # Retrieve all readings from DB for Pump-02 tags
        vlv_readings = self.db.get_readings(tag="VLV-04-POS")
        flw_readings = self.db.get_readings(tag="FIT-02-FLW")
        cur_readings = self.db.get_readings(tag="MOT-02-CUR")
        prs_readings = self.db.get_readings(tag="PIT-02-PRS")
        alm_readings = self.db.get_readings(tag="ALM-P02-HP")

        # Check start vs end values
        start_vlv = float(vlv_readings[0].value)
        end_vlv = float(vlv_readings[-1].value)
        self.assertGreaterEqual(start_vlv, 70.0)
        self.assertEqual(end_vlv, 43.0)  # Dropped ~45%

        start_flw = float(flw_readings[0].value)
        end_flw = float(flw_readings[-1].value)
        self.assertGreaterEqual(start_flw, 75.0)
        self.assertEqual(end_flw, 56.0)  # Dropped ~32%

        start_cur = float(cur_readings[0].value)
        end_cur = float(cur_readings[-1].value)
        self.assertLessEqual(start_cur, 8.2)
        self.assertEqual(end_cur, 9.2)   # Surged ~18%

        start_prs = float(prs_readings[0].value)
        end_prs = float(prs_readings[-1].value)
        self.assertLessEqual(start_prs, 5.2)
        self.assertEqual(end_prs, 6.9)   # Surged ~44%

        # Alarm must have tripped True
        tripped_alarms = [r for r in alm_readings if r.value is True]
        self.assertGreater(len(tripped_alarms), 0, "ALM-P02-HP must trip True during valve cascade")

        # Compressor tags must remain nominal throughout Scenario A
        cmp_vib_readings = self.db.get_readings(tag="CMP-01-VIB")
        for r in cmp_vib_readings:
            self.assertTrue(
                TAG_REGISTRY["CMP-01-VIB"].baseline_min <= float(r.value) <= TAG_REGISTRY["CMP-01-VIB"].baseline_max
            )

    def test_scenario_b_bearing_wear_isolation(self):
        """
        Requirement 3b & Acceptance Criteria:
        Bearing wear (vibration/current slow rise, no valve involvement) -
        unrelated tag on different equipment (Pump-02) MUST NOT correlate.
        """
        self.generator.reset(clear_db=True)
        list(self.generator.run_scenario("bearing_wear", speed_multiplier=float("inf")))

        # Verify Compressor-01 excursions
        vib_readings = self.db.get_readings(tag="CMP-01-VIB")
        self.assertGreaterEqual(float(vib_readings[-1].value), 7.0)  # Exceeded trip threshold
        alm_vb_readings = self.db.get_readings(tag="ALM-C01-VB")
        tripped = [r for r in alm_vb_readings if r.value is True]
        self.assertGreater(len(tripped), 0)

        # Acceptance Criteria Check: Pump-02 tags MUST stay strictly within nominal baselines!
        for p_tag in ["VLV-04-POS", "FIT-02-FLW", "MOT-02-CUR", "PIT-02-PRS"]:
            readings = self.db.get_readings(tag=p_tag)
            entry = TAG_REGISTRY[p_tag]
            for r in readings:
                val = float(r.value)
                self.assertTrue(
                    entry.baseline_min <= val <= entry.baseline_max,
                    f"Isolation breach: Pump-02 tag {p_tag} deviated to {val} during Compressor-01 bearing wear!"
                )

    def test_scenario_c_seal_leak_signature(self):
        """
        Requirement 3c: Seal leak (flow down AND pressure down together -
        different signature than valve restriction where pressure surges).
        """
        self.generator.reset(clear_db=True)
        list(self.generator.run_scenario("seal_leak", speed_multiplier=float("inf")))

        flw_readings = self.db.get_readings(tag="FIT-02-FLW")
        prs_readings = self.db.get_readings(tag="PIT-02-PRS")
        vlv_readings = self.db.get_readings(tag="VLV-04-POS")
        alm_readings = self.db.get_readings(tag="ALM-P02-HP")

        # Flow and pressure must drop together
        end_flw = float(flw_readings[-1].value)
        end_prs = float(prs_readings[-1].value)
        self.assertLess(end_flw, 50.0)   # Low flow trip condition
        self.assertLess(end_prs, 3.0)    # Pressure plunged (4.8 -> 2.1 bar)

        # Valve must stay nominal!
        vlv_entry = TAG_REGISTRY["VLV-04-POS"]
        for r in vlv_readings:
            self.assertTrue(vlv_entry.baseline_min <= float(r.value) <= vlv_entry.baseline_max)

        # High pressure alarm must NOT trip
        for r in alm_readings:
            self.assertFalse(r.value)

    def test_scenario_d_sensor_fault_non_correlation(self):
        """
        Requirement 3d & Acceptance Criteria:
        Sensor fault / false positive: a single tag spikes with NO correlated
        deviations on any topologically-linked tag.
        """
        self.generator.reset(clear_db=True)
        list(self.generator.run_scenario("sensor_fault", speed_multiplier=float("inf")))

        prs_readings = self.db.get_readings(tag="PIT-02-PRS")
        prs_values = [float(r.value) for r in prs_readings]
        # PIT-02-PRS must have spiked above nominal max (5.2 bar)
        self.assertGreaterEqual(max(prs_values), 7.0)

        # Topologically linked tags: FIT-02-FLW, MOT-02-CUR, VLV-04-POS
        # MUST HAVE ZERO OUT-OF-BASELINE DEVIATIONS
        for linked_tag in ["FIT-02-FLW", "MOT-02-CUR", "VLV-04-POS"]:
            linked_readings = self.db.get_readings(tag=linked_tag)
            entry = TAG_REGISTRY[linked_tag]
            for r in linked_readings:
                val = float(r.value)
                self.assertTrue(
                    entry.baseline_min <= val <= entry.baseline_max,
                    f"Tag {linked_tag} falsely deviated during isolated sensor fault on PIT-02-PRS: {val}"
                )

    # -------------------------------------------------------------------------
    # 3. Continuous Non-Overlapping Timeline & Reset Tests
    # -------------------------------------------------------------------------

    def test_back_to_back_runs_continuous_timeline(self):
        """
        Acceptance Criteria:
        All 4 scenarios must be runnable back-to-back without process restart,
        with the SQLite table correctly reflecting a continuous, non-overlapping timeline.
        """
        self.generator.reset(clear_db=True, start_time=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc))

        scenarios = ["valve_restriction", "bearing_wear", "seal_leak", "sensor_fault"]
        for sc_id in scenarios:
            list(self.generator.run_scenario(sc_id, speed_multiplier=float("inf")))

        # Query all readings ordered by ID
        all_readings = self.db.get_readings(order_desc=False)
        self.assertGreater(len(all_readings), 0)

        # Check timestamp monotonicity
        timestamps = [r.timestamp for r in all_readings]
        for i in range(1, len(timestamps)):
            t_prev = datetime.fromisoformat(timestamps[i - 1].replace("Z", "+00:00"))
            t_curr = datetime.fromisoformat(timestamps[i].replace("Z", "+00:00"))
            self.assertGreaterEqual(t_curr, t_prev, f"Non-monotonic timestamp: {t_prev} -> {t_curr}")

        # Verify exact 2.0s time steps across the entire multi-scenario sequence
        distinct_timestamps = sorted(list(set(timestamps)))
        for i in range(1, len(distinct_timestamps)):
            dt_prev = datetime.fromisoformat(distinct_timestamps[i - 1].replace("Z", "+00:00"))
            dt_curr = datetime.fromisoformat(distinct_timestamps[i].replace("Z", "+00:00"))
            delta = (dt_curr - dt_prev).total_seconds()
            self.assertAlmostEqual(delta, 2.0, places=2, msg=f"Discontinuous step: {delta}s instead of 2.0s")

    def test_async_generator_streaming(self):
        """Test async generator interface."""
        async def run_async():
            self.generator.reset(clear_db=True)
            count = 0
            async for reading in self.generator.run_scenario_async("sensor_fault", speed_multiplier=float("inf")):
                self.assertIsInstance(reading, TagReading)
                count += 1
            self.assertGreater(count, 0)
            self.assertEqual(self.db.get_count(), count)

        asyncio.run(run_async())


if __name__ == "__main__":
    unittest.main()
