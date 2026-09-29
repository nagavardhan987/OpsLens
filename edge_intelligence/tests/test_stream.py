"""
Tests for OpsLens Ingestion & Pub-Sub Decoupling Layer (Component 2)
"""

import unittest
import asyncio
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

from models import TagReading
from tag_registry import TAG_REGISTRY
from database import Database
from generator import SyntheticDataGenerator
from registry_loader import RegistryLoader, get_registry_loader
from stream import TagStream


class TestRegistryLoader(unittest.TestCase):

    def setUp(self):
        self.loader = get_registry_loader()

    def test_lookup_tag(self):
        entry = self.loader.get_tag("VLV-04-POS")
        self.assertEqual(entry.tag, "VLV-04-POS")
        self.assertEqual(entry.equipment_id, "Pump-02")
        self.assertEqual(entry.unit, "%")

        with self.assertRaises(KeyError):
            self.loader.get_tag("NON_EXISTENT_TAG")

    def test_equipment_lookups(self):
        pump_tags = self.loader.get_equipment_tags("Pump-02")
        self.assertEqual(len(pump_tags), 5)
        names = self.loader.get_equipment_tag_names("Pump-02")
        self.assertIn("PIT-02-PRS", names)

    def test_topology_helpers(self):
        upstream = self.loader.get_upstream("ALM-P02-HP", recursive=True)
        self.assertIn("PIT-02-PRS", upstream)
        self.assertIn("FIT-02-FLW", upstream)
        self.assertIn("VLV-04-POS", upstream)

        dist = self.loader.get_topology_distance("VLV-04-POS", "ALM-P02-HP")
        self.assertIsNotNone(dist)
        self.assertGreaterEqual(dist, 2)

    def test_thresholds_and_baselines(self):
        b_min, b_max = self.loader.get_baseline_range("PIT-02-PRS")
        self.assertEqual(b_min, 4.2)
        self.assertEqual(b_max, 5.2)

        trip = self.loader.get_trip_threshold("PIT-02-PRS")
        self.assertEqual(trip, 6.5)

        weight = self.loader.get_severity_weight("PIT-02-PRS")
        self.assertEqual(weight, 0.15)


class TestTagStream(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_stream_opslens.db"
        self.db = Database(db_path=self.db_path)
        self.generator = SyntheticDataGenerator(
            db=self.db,
            sample_interval=2.0,
            start_time=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc)
        )
        self.stream = TagStream(
            db_path=self.db_path,
            poll_interval_seconds=0.05  # Fast 50ms polling for unit test
        )

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_multiple_concurrent_subscribers(self):
        """
        Requirement 2: Multiple concurrent subscribers (prioritization engine and
        live dashboard feed) independently receive the same stream without cross-blocking.
        """
        async def run_test():
            sub1_received: list[TagReading] = []
            sub2_received: list[TagReading] = []

            # Background consumer 1 (fast consumer)
            async def consumer_1():
                async for reading in self.stream.subscribe():
                    sub1_received.append(reading)
                    if len(sub1_received) >= 33:  # 3 sample steps * 11 tags
                        break

            # Background consumer 2 (slow consumer with artificial processing delay)
            async def consumer_2():
                async for reading in self.stream.subscribe():
                    sub2_received.append(reading)
                    # Artificially slow processing (2ms) to test non-blocking fanout
                    await asyncio.sleep(0.002)
                    if len(sub2_received) >= 33:
                        break

            c1_task = asyncio.create_task(consumer_1())
            c2_task = asyncio.create_task(consumer_2())

            # Give broker loop 50ms to initialize
            await asyncio.sleep(0.05)

            # Generator produces 3 sample steps (33 readings)
            for _ in range(3):
                self.generator.advance_step()
                await asyncio.sleep(0.08)

            await asyncio.wait_for(asyncio.gather(c1_task, c2_task), timeout=5.0)

            self.assertEqual(len(sub1_received), 33)
            self.assertEqual(len(sub2_received), 33)

            # Ensure both subscribers received the exact same tags in chronological order
            sub1_tags = [r.tag for r in sub1_received]
            sub2_tags = [r.tag for r in sub2_received]
            self.assertEqual(sub1_tags, sub2_tags)

            await self.stream.close()

        asyncio.run(run_test())

    def test_staggered_subscribers(self):
        """
        Acceptance Criteria:
        Two independent subscribers started at different times each receive the
        full set of readings generated after their own subscribe() call, correctly,
        with no duplicates or drops.
        """
        async def run_test():
            sub1_received: list[TagReading] = []
            sub2_received: list[TagReading] = []

            # 1. Subscriber 1 joins at the beginning
            async def consumer_1():
                async for reading in self.stream.subscribe(from_latest=True):
                    sub1_received.append(reading)
                    if len(sub1_received) >= 44:  # 4 steps * 11 tags = 44 readings
                        break

            c1_task = asyncio.create_task(consumer_1())
            await asyncio.sleep(0.05)

            # Step 1 and Step 2 produced (22 readings)
            for _ in range(2):
                self.generator.advance_step()
                await asyncio.sleep(0.08)

            # Wait until Subscriber 1 has processed initial 22 readings
            while len(sub1_received) < 22:
                await asyncio.sleep(0.02)

            self.assertEqual(len(sub1_received), 22)

            # 2. Subscriber 2 joins late (after 22 readings already in DB)
            async def consumer_2():
                async for reading in self.stream.subscribe(from_latest=True):
                    sub2_received.append(reading)
                    if len(sub2_received) >= 22:  # Should receive only steps 3 & 4 (22 readings)
                        break

            c2_task = asyncio.create_task(consumer_2())
            await asyncio.sleep(0.05)

            # Step 3 and Step 4 produced (22 more readings)
            for _ in range(2):
                self.generator.advance_step()
                await asyncio.sleep(0.08)

            await asyncio.wait_for(asyncio.gather(c1_task, c2_task), timeout=5.0)

            # Subscriber 1 must have all 44 readings
            self.assertEqual(len(sub1_received), 44)
            # Subscriber 2 must have received only the 22 readings generated after its join
            self.assertEqual(len(sub2_received), 22)

            # Verify no duplicates in either subscriber
            sub1_keys = [(r.tag, r.timestamp) for r in sub1_received]
            self.assertEqual(len(sub1_keys), len(set(sub1_keys)), "Subscriber 1 had duplicates!")

            sub2_keys = [(r.tag, r.timestamp) for r in sub2_received]
            self.assertEqual(len(sub2_keys), len(set(sub2_keys)), "Subscriber 2 had duplicates!")

            # Verify that Subscriber 2's readings match the second half of Subscriber 1's readings
            self.assertEqual(sub1_received[22:], sub2_received)

            await self.stream.close()

        asyncio.run(run_test())

    def test_get_window_boundary(self):
        """
        Acceptance Criteria:
        get_window() returns correct results for a query spanning a scenario
        transition boundary (baseline -> incident).
        """
        async def run_test():
            # Run valve_restriction scenario instantly into the database
            # Generator start time: 2026-09-11 10:00:00 UTC
            # Cascade:
            # 0s - 10s: baseline (nominal)
            # 10s - 28s: valve drops
            # 18s - 38s: flow drops
            # 28s - 48s: current surges
            # 36s - 58s: pressure surges
            # 52s+: alarm trips
            list(self.generator.run_scenario("valve_restriction", speed_multiplier=float("inf")))

            base_time = datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc)
            # Query window spanning baseline (t+6s) into incident (t+34s)
            start_window = base_time + timedelta(seconds=6)
            end_window = base_time + timedelta(seconds=34)

            # 1. Query all Pump-02 readings across this window
            window_readings = await self.stream.get_window(
                equipment_id="Pump-02",
                start=start_window,
                end=end_window
            )
            self.assertGreater(len(window_readings), 0)

            # Check that all returned readings belong to Pump-02 and fall within [start, end]
            for r in window_readings:
                self.assertEqual(r.equipment_id, "Pump-02")
                r_ts = datetime.fromisoformat(r.timestamp.replace("Z", "+00:00"))
                self.assertTrue(start_window <= r_ts <= end_window)

            # 2. Verify tag filtering on specific tags
            vlv_prs_readings = await self.stream.get_window(
                equipment_id="Pump-02",
                start=start_window,
                end=end_window,
                tags=["VLV-04-POS", "PIT-02-PRS"]
            )
            self.assertGreater(len(vlv_prs_readings), 0)
            for r in vlv_prs_readings:
                self.assertIn(r.tag, ["VLV-04-POS", "PIT-02-PRS"])

            # Verify transition boundary dynamics in window:
            # At start of window (t=6s), VLV is nominal (> 70%)
            vlv_readings = [r for r in vlv_prs_readings if r.tag == "VLV-04-POS"]
            self.assertGreater(float(vlv_readings[0].value), 70.0)
            # By t=34s, VLV has dropped to 43.0%
            self.assertEqual(float(vlv_readings[-1].value), 43.0)

            await self.stream.close()

        asyncio.run(run_test())

    def test_high_load_no_drops(self):
        """
        Stress test: simulates high-frequency ingestion and verifies zero drops or duplicates.
        """
        async def run_test():
            received: list[TagReading] = []
            target_count = 110  # 10 sample steps * 11 tags

            async def consumer():
                async for reading in self.stream.subscribe():
                    received.append(reading)
                    if len(received) >= target_count:
                        break

            c_task = asyncio.create_task(consumer())
            await asyncio.sleep(0.05)

            # Rapidly produce 10 sample steps
            for _ in range(10):
                self.generator.advance_step()

            await asyncio.wait_for(c_task, timeout=5.0)
            self.assertEqual(len(received), target_count)

            # Verify zero duplicate rows
            keys = [(r.tag, r.timestamp) for r in received]
            self.assertEqual(len(keys), len(set(keys)))

            await self.stream.close()

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
