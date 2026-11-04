"""
OpsLens - Frontend Repointing End-to-End Verification Test

Verifies:
1. REST API endpoints match frontend client contracts (/api/scenarios, /api/status, /api/events/{id}, /api/actions, /api/handover).
2. Acceptance Criterion: Firing Scenario B live produces demonstrably different dashboard content
   (different causal_label, SOP, evidence) than Scenario A with no frontend code changes.
3. Operator Action Verification: Operator action buttons call /api/actions with real event_id and
   safety interlock rejects prohibited machine commands.
4. Shift Handover Verification: Real handover compilation from event and action records.
"""

import os
import sys
import uuid
import unittest
import asyncio
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from database import Database
from stream import TagStream
from generator import SyntheticDataGenerator
from orchestrator import OpsLensOrchestrator
from api.routes import create_app


class TestFrontendRepoint(unittest.TestCase):
    def setUp(self):
        self.test_db_path = "test_frontend_repoint.db"
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
            try:
                os.remove(self.test_db_path)
            except Exception:
                pass

    def test_frontend_endpoints_and_scenario_contrast(self):
        """
        Acceptance Test:
        Verify Scenario A and Scenario B produce distinct content for:
        - causal_label (EventStory)
        - likely_contributor_tag (Evidence)
        - sop_id & sop_title (RelevantSop)
        - candidate & guidance (AlarmPrioritization / NextBestAction)
        """
        async def run_test():
            await self.orchestrator.start_streaming()

            # 1. Verify API Scenarios & Status
            res_sc = self.client.get("/api/scenarios")
            self.assertEqual(res_sc.status_code, 200)
            sc_data = res_sc.json()
            self.assertIn("scenarios", sc_data)
            scenario_ids = [s["scenario_id"] for s in sc_data["scenarios"]]
            self.assertIn("valve_restriction_cascade", scenario_ids)
            self.assertIn("bearing_wear", scenario_ids)

            res_st = self.client.get("/api/status")
            self.assertEqual(res_st.status_code, 200)
            self.assertIn(res_st.json()["status"].upper(), ["ONLINE", "NOMINAL"])

            # 2. Fire Scenario A: Valve Restriction Cascade
            t0 = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)
            gen_a = SyntheticDataGenerator(db=self.db, sample_interval=2.0, start_time=t0)
            readings_a = list(gen_a.run_scenario("valve_restriction_cascade", speed_multiplier=float("inf")))
            for r in readings_a:
                await self.orchestrator.process_reading(r)

            while self.orchestrator._in_flight_tasks:
                await asyncio.gather(*list(self.orchestrator._in_flight_tasks.values()), return_exceptions=True)

            candidates_a = self.db.get_candidate_events()
            self.assertGreater(len(candidates_a), 0, "Scenario A must generate a candidate event")
            event_a_id = candidates_a[0].event_id

            # Query Scenario A full event via REST
            res_event_a = self.client.get(f"/api/events/{event_a_id}")
            self.assertEqual(res_event_a.status_code, 200)
            full_a = res_event_a.json()

            # Verify Scenario A schemas mapped directly to contract
            self.assertEqual(full_a["event_id"], event_a_id)
            self.assertTrue("valve" in full_a["story"]["causal_label"].lower())
            self.assertEqual(full_a["evidence"]["likely_contributor_tag"], "VLV-04-POS")
            self.assertIn(full_a["evidence"]["confidence_label"], ["LOW", "MEDIUM", "HIGH"])
            self.assertEqual(full_a["sop_match"]["sop_id"], "SOP-P02-VLV-01")
            self.assertTrue("valve" in full_a["sop_match"]["sop_title"].lower())
            self.assertGreater(len(full_a["sop_match"]["steps"]), 0)
            self.assertGreater(len(full_a["guidance"]["next_best_actions"]), 0)

            # 3. Fire Scenario B: Bearing Wear
            t1 = datetime(2026, 9, 11, 12, 5, 0, tzinfo=timezone.utc)
            gen_b = SyntheticDataGenerator(db=self.db, sample_interval=2.0, start_time=t1)
            readings_b = list(gen_b.run_scenario("bearing_wear", speed_multiplier=float("inf")))
            for r in readings_b:
                await self.orchestrator.process_reading(r)

            while self.orchestrator._in_flight_tasks:
                await asyncio.gather(*list(self.orchestrator._in_flight_tasks.values()), return_exceptions=True)

            candidates_b = self.db.get_candidate_events()
            event_b_candidates = [c for c in candidates_b if c.event_id != event_a_id]
            self.assertGreater(len(event_b_candidates), 0, "Scenario B must generate a candidate event")
            event_b_id = event_b_candidates[0].event_id

            # Query Scenario B full event via REST
            res_event_b = self.client.get(f"/api/events/{event_b_id}")
            self.assertEqual(res_event_b.status_code, 200)
            full_b = res_event_b.json()

            # Verify Scenario B schemas mapped directly to contract
            self.assertEqual(full_b["event_id"], event_b_id)
            self.assertIn("bearing", full_b["story"]["causal_label"].lower())
            self.assertEqual(full_b["evidence"]["likely_contributor_tag"], "CMP-01-VIB")
            self.assertEqual(full_b["sop_match"]["sop_id"], "SOP-C01-BRG-01")
            self.assertIn("Bearing", full_b["sop_match"]["sop_title"])

            # 4. Acceptance Criterion: Contrast Check
            self.assertNotEqual(full_a["story"]["causal_label"], full_b["story"]["causal_label"])
            self.assertNotEqual(full_a["evidence"]["likely_contributor_tag"], full_b["evidence"]["likely_contributor_tag"])
            self.assertNotEqual(full_a["sop_match"]["sop_id"], full_b["sop_match"]["sop_id"])
            self.assertNotEqual(full_a["sop_match"]["sop_title"], full_b["sop_match"]["sop_title"])

            # 5. Operator Action Logging against real event_id
            # Permitted action
            res_action = self.client.post("/api/actions", json={
                "event_id": event_a_id,
                "operator": "J. Rivera (Shift 2)",
                "action_type": "VERIFY",
                "timestamp": "2026-09-11T12:02:00Z",
                "notes": "Verified Valve-04 physical position"
            })
            self.assertEqual(res_action.status_code, 200)
            act_json = res_action.json()
            self.assertEqual(act_json["action_type"], "VERIFY")
            self.assertEqual(act_json["event_id"], event_a_id)

            # Prohibited machine command must be rejected (400 Bad Request)
            res_bad_action = self.client.post("/api/actions", json={
                "event_id": event_a_id,
                "operator": "J. Rivera (Shift 2)",
                "action_type": "SET_VALVE_POSITION",
                "notes": "Automated actuator drive"
            })
            self.assertEqual(res_bad_action.status_code, 400)

            # Resolve event action
            res_resolve = self.client.post("/api/actions", json={
                "event_id": event_a_id,
                "operator": "J. Rivera (Shift 2)",
                "action_type": "RESOLVE",
                "timestamp": "2026-09-11T12:04:00Z",
                "notes": "Incident mitigated and resolved"
            })
            self.assertEqual(res_resolve.status_code, 200)

            # 6. Shift Handover Ledger Verification
            res_handover = self.client.post("/api/handover", json={
                "shift_start": "2026-09-11T00:00:00Z",
                "shift_end": "2026-09-11T23:59:59Z"
            })
            self.assertEqual(res_handover.status_code, 200)
            ho_json = res_handover.json()
            self.assertIn("events", ho_json)
            self.assertIn("actions", ho_json)
            self.assertIn("open_events", ho_json)
            self.assertGreaterEqual(len(ho_json["actions"]), 2)
            self.assertEqual(len(ho_json["events"]), 2)
            self.assertIn(event_b_id, ho_json["open_events"])
            self.assertNotIn(event_a_id, ho_json["open_events"])

            await self.orchestrator.stop()

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
