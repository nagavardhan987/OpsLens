"""
OpsLens - Orchestrator & API Acceptance Verification (Component 11)

Verifies:
1. Concurrent Overlapping Events: Fire scenarios (a) and (b) within 10 seconds of each other
   and verify BOTH produce complete, independent, non-interleaved records across all tables.
2. Process Kill & Restart Idempotency: Kill and restart orchestrator process mid-scenario and
   verify zero duplicate or corrupted records in SQLite on restart.
3. FastAPI REST & SSE Verification: Verify get_full_event, get_open_events, log_action,
   compile_handover, and SSE stream endpoints.
"""

import os
import sys
import uuid
import unittest
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from fastapi.testclient import TestClient

from models import TagReading, CandidateEvent, EventStory, OperatorAction, HandoverSummary
from database import Database
from stream import TagStream
from generator import SyntheticDataGenerator
from orchestrator import OpsLensOrchestrator
from api.routes import create_app


class TestOrchestratorAcceptance(unittest.TestCase):
    """Component 11 Acceptance Tests."""

    def setUp(self):
        self.test_db_path = "test_orchestrator_ops.db"
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        self.db = Database(self.test_db_path)
        self.stream = TagStream(db_path=self.test_db_path)
        self.orchestrator = OpsLensOrchestrator(db=self.db, stream=self.stream)
        self.app = create_app(orchestrator=self.orchestrator)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_concurrent_overlapping_events_acceptance(self):
        """
        Acceptance Criterion 1:
        Fire scenarios (a) and (b) within 10 seconds of each other and verify
        BOTH produce complete, independent, non-interleaved records across all tables
        (e.g. scenario (b)'s SopMatch never references scenario (a)'s event_id).
        """
        async def run_concurrent():
            # Start streaming orchestrator
            await self.orchestrator.start_streaming()

            # Generate Scenario A (Valve Restriction) at T0
            time_a = datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc)
            gen_a = SyntheticDataGenerator(db=self.db, sample_interval=2.0, start_time=time_a)
            readings_a = list(gen_a.run_scenario("valve_restriction_cascade", speed_multiplier=float("inf")))

            # Generate Scenario B (Bearing Wear) fired 5 seconds later (within 10s)
            time_b = datetime(2026, 9, 11, 10, 0, 5, tzinfo=timezone.utc)
            gen_b = SyntheticDataGenerator(db=self.db, sample_interval=2.0, start_time=time_b)
            readings_b = list(gen_b.run_scenario("bearing_wear", speed_multiplier=float("inf")))

            # Interleave / feed readings concurrently into orchestrator
            # (Simulates live concurrent sensor packet arrival)
            max_len = max(len(readings_a), len(readings_b))
            for i in range(max_len):
                if i < len(readings_a):
                    await self.orchestrator.process_reading(readings_a[i])
                if i < len(readings_b):
                    await self.orchestrator.process_reading(readings_b[i])

            # Wait for all concurrent event pipeline workers to complete
            if self.orchestrator._in_flight_tasks:
                await asyncio.gather(*self.orchestrator._in_flight_tasks.values(), return_exceptions=True)

            await self.orchestrator.stop()

            # Verification across all tables
            candidates = self.db.get_candidate_events()
            self.assertEqual(len(candidates), 2, f"Expected 2 candidate events, got {len(candidates)}")
            event_a_id = [c.event_id for c in candidates if "VLV-04-POS" in c.clustered_tags or c.primary_tag == "VLV-04-POS"][0]
            event_b_id = [c.event_id for c in candidates if "CMP-01-VIB" in c.clustered_tags or c.primary_tag == "CMP-01-VIB"][0]

            self.assertNotEqual(event_a_id, event_b_id)

            # 1. Correlated Events
            corr_a = self.db.get_correlated_events(event_id=event_a_id)
            corr_b = self.db.get_correlated_events(event_id=event_b_id)
            self.assertEqual(len(corr_a), 1)
            self.assertEqual(len(corr_b), 1)

            # 2. Event Stories
            story_a = self.db.get_event_stories(event_id=event_a_id)
            story_b = self.db.get_event_stories(event_id=event_b_id)
            self.assertEqual(len(story_a), 1)
            self.assertEqual(len(story_b), 1)
            self.assertNotEqual(story_a[0].causal_label, story_b[0].causal_label)

            # 3. Evidence
            ev_a = self.db.get_evidence(event_id=event_a_id)
            ev_b = self.db.get_evidence(event_id=event_b_id)
            self.assertEqual(len(ev_a), 1)
            self.assertEqual(len(ev_b), 1)
            self.assertEqual(ev_a[0].likely_contributor_tag, "VLV-04-POS")
            self.assertEqual(ev_b[0].likely_contributor_tag, "CMP-01-VIB")

            # 4. SOP Matches: Strict isolation and non-interleaving
            sop_a = self.db.get_sop_matches(event_id=event_a_id)
            sop_b = self.db.get_sop_matches(event_id=event_b_id)
            self.assertEqual(len(sop_a), 1)
            self.assertEqual(len(sop_b), 1)
            self.assertEqual(sop_a[0].event_id, event_a_id)
            self.assertEqual(sop_b[0].event_id, event_b_id)
            self.assertEqual(sop_a[0].sop_id, "SOP-P02-VLV-01")
            self.assertEqual(sop_b[0].sop_id, "SOP-C01-BRG-01")
            self.assertNotEqual(sop_a[0].sop_id, sop_b[0].sop_id)

            # 5. Guidance
            guid_a = self.db.get_guidance(event_id=event_a_id)
            guid_b = self.db.get_guidance(event_id=event_b_id)
            self.assertEqual(len(guid_a), 1)
            self.assertEqual(len(guid_b), 1)
            self.assertEqual(guid_a[0].cited_sop_id, "SOP-P02-VLV-01")
            self.assertEqual(guid_b[0].cited_sop_id, "SOP-C01-BRG-01")

            # 6. Unified get_full_event
            full_a = self.orchestrator.get_full_event(event_a_id)
            full_b = self.orchestrator.get_full_event(event_b_id)
            self.assertIsNotNone(full_a)
            self.assertIsNotNone(full_b)
            self.assertEqual(full_a["event_id"], event_a_id)
            self.assertEqual(full_b["event_id"], event_b_id)
            self.assertEqual(full_a["sop_match"]["sop_id"], "SOP-P02-VLV-01")
            self.assertEqual(full_b["sop_match"]["sop_id"], "SOP-C01-BRG-01")

        asyncio.run(run_concurrent())

    def test_kill_and_restart_idempotency_acceptance(self):
        """
        Acceptance Criterion 2:
        Kill and restart the orchestrator process mid-scenario and verify no
        duplicate/corrupted records are created on restart (idempotency check against SQLite).
        """
        async def run_restart_test():
            # 1. Run Scenario A halfway on first orchestrator
            time_a = datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc)
            gen = SyntheticDataGenerator(db=self.db, sample_interval=2.0, start_time=time_a)
            all_readings = list(gen.run_scenario("valve_restriction_cascade", speed_multiplier=float("inf")))
            halfway = len(all_readings) // 2

            # Feed first half of readings
            for r in all_readings[:halfway]:
                await self.orchestrator.process_reading(r)

            if self.orchestrator._in_flight_tasks:
                await asyncio.gather(*self.orchestrator._in_flight_tasks.values(), return_exceptions=True)

            # Checkpoint counts before kill
            candidates_before = self.db.get_candidate_events()
            self.assertEqual(len(candidates_before), 1)
            event_id = candidates_before[0].event_id

            # Simulate killing process: stop orchestrator and discard in-memory instance
            await self.orchestrator.stop()
            del self.orchestrator

            # 2. Restart orchestrator on the EXACT same SQLite database
            orch_restarted = OpsLensOrchestrator(db=self.db, stream=self.stream)

            # Feed remaining readings through the restarted orchestrator
            for r in all_readings[halfway:]:
                await orch_restarted.process_reading(r)

            if orch_restarted._in_flight_tasks:
                await asyncio.gather(*orch_restarted._in_flight_tasks.values(), return_exceptions=True)

            await orch_restarted.stop()

            # 3. Verify zero duplicates across all tables (Idempotency check)
            self.assertEqual(len(self.db.get_candidate_events(event_id=event_id)), 1)
            self.assertEqual(len(self.db.get_correlated_events(event_id=event_id)), 1)
            self.assertEqual(len(self.db.get_event_stories(event_id=event_id)), 1)
            self.assertEqual(len(self.db.get_evidence(event_id=event_id)), 1)
            self.assertEqual(len(self.db.get_sop_matches(event_id=event_id)), 1)
            self.assertEqual(len(self.db.get_guidance(event_id=event_id)), 1)

            # Total table row counts must be exactly 1 each
            self.assertEqual(len(self.db.get_candidate_events()), 1)
            self.assertEqual(len(self.db.get_correlated_events()), 1)
            self.assertEqual(len(self.db.get_event_stories()), 1)
            self.assertEqual(len(self.db.get_evidence()), 1)
            self.assertEqual(len(self.db.get_sop_matches()), 1)
            self.assertEqual(len(self.db.get_guidance()), 1)

        asyncio.run(run_restart_test())

    def test_fastapi_rest_and_streaming_endpoints(self):
        """
        Requirement 4: Expose REST endpoints wrapping: get_full_event, get_open_events,
        log_action, compile_handover, plus a live event feed.
        """
        # Populate an event in DB
        event_id = str(uuid.uuid4())
        self.db.save_candidate_event(
            CandidateEvent(
                event_id=event_id,
                primary_tag="VLV-04-POS",
                primary_alarm=True,
                trigger_timestamp="2026-09-11T10:00:00Z",
                raw_deviation_pct=-44.9,
                clustered_tags=["VLV-04-POS"]
            ),
            equipment_id="Pump-02"
        )
        self.db.save_event_story(
            EventStory(
                event_id=event_id,
                steps=[{"step_number": 1, "tag": "VLV-04-POS", "timestamp": "2026-09-11T10:00:00Z", "description": "d", "value_before": 100.0, "value_after": 55.1}],
                causal_label="Valve Throttling"
            )
        )

        # 1. GET /api/events/{event_id}
        res = self.client.get(f"/api/events/{event_id}")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["event_id"], event_id)
        self.assertEqual(data["status"], "OPEN")

        # 404 on missing event
        res404 = self.client.get(f"/api/events/{uuid.uuid4()}")
        self.assertEqual(res404.status_code, 404)

        # 2. GET /api/events/open
        res_open = self.client.get("/api/events/open")
        self.assertEqual(res_open.status_code, 200)
        self.assertIn(event_id, res_open.json()["open_events"])

        # 3. POST /api/actions - valid action
        action_payload = {
            "event_id": event_id,
            "operator": "operator_jane",
            "action_type": "ACKNOWLEDGE",
            "notes": "Acknowledged from dashboard"
        }
        res_action = self.client.post("/api/actions", json=action_payload)
        self.assertEqual(res_action.status_code, 200)
        self.assertEqual(res_action.json()["action_type"], "ACKNOWLEDGE")

        # POST /api/actions - rejected PLC command
        unsafe_payload = {
            "event_id": event_id,
            "operator": "malicious",
            "action_type": "SET_VALVE_POS",
            "notes": "Machine command"
        }
        res_unsafe = self.client.post("/api/actions", json=unsafe_payload)
        self.assertEqual(res_unsafe.status_code, 400)

        # 4. POST /api/handover
        handover_payload = {
            "shift_start": "2026-09-11T09:00:00Z",
            "shift_end": "2026-09-11T11:00:00Z"
        }
        res_handover = self.client.post("/api/handover", json=handover_payload)
        self.assertEqual(res_handover.status_code, 200)
        self.assertIn(event_id, res_handover.json()["events"])

        # 5. GET /api/events/stream SSE connection test
        with self.client.stream("GET", "/api/events/stream?max_events=0") as response:
            self.assertEqual(response.status_code, 200)
            # Read first chunk
            for line in response.iter_lines():
                if line:
                    self.assertTrue("event:" in line or "data:" in line or "connected" in line)
                    break


if __name__ == "__main__":
    unittest.main()
