import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

from api.routes import create_app
from database import Database
from dedup import DeduplicationEngine
from models import TagReading


class _Audit:
    def __init__(self, event_id):
        self.event_id = event_id

    def get_open_events(self):
        return [self.event_id]


class _Orchestrator:
    """Small real-database harness around the production dedup engine."""

    def __init__(self, db, engine, event_id):
        self.db = db
        self.engine = engine
        self.event_id = event_id
        self.audit = _Audit(event_id)

    def _equipment_for(self, tag):
        return "Pump-02" if tag == "ALM-P02-HP" else "Unknown"

    def get_full_event(self, event_id):
        if event_id != self.event_id:
            return None
        candidates = self.db.get_candidate_events(event_id=event_id)
        if not candidates:
            return None
        return {
            "event_id": event_id,
            "candidate": candidates[0].model_dump(mode="json"),
            "story": {"steps": [{"tag": "ALM-P02-HP", "description": "High pressure trip"}]},
        }

    async def process_reading(self, reading):
        return self.engine.process_reading(reading)


class TestRepeatAlarmApi(unittest.IsolatedAsyncioTestCase):
    async def test_two_repeats_update_the_existing_active_alarm_to_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(db_path=Path(tmp) / "repeat.db")
            engine = DeduplicationEngine(db=db)
            initial_time = datetime.now(timezone.utc) - timedelta(seconds=2)
            initial = TagReading(
                tag="ALM-P02-HP",
                value=True,
                timestamp=initial_time.isoformat().replace("+00:00", "Z"),
                unit="status",
                equipment_id="Pump-02",
            )
            db.insert_reading(initial)
            first = engine.process_reading(initial)
            self.assertIsNotNone(first)
            self.assertEqual(first.repeat_count, 1)
            event_id = first.event_id

            app = create_app(orchestrator=_Orchestrator(db, engine, event_id))
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://opslens.test") as client:
                for expected_count in (2, 3):
                    response = await client.post("/api/scenarios/trigger-alarm-repeat")
                    self.assertEqual(response.status_code, 200, response.text)
                    payload = response.json()
                    self.assertEqual(payload["event_id"], event_id)
                    self.assertEqual(payload["repeat_count"], expected_count)
                    self.assertEqual(payload["lifecycle_state"], "ACTIVE")

            stored = db.get_candidate_events(event_id=event_id)
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0].repeat_count, 3)
            self.assertEqual(stored[0].lifecycle_state, "ACTIVE")
            alarms = db.get_individual_alarms(event_id)
            self.assertEqual(len(alarms), 1)
            self.assertEqual(alarms[0]["repeat_count"], 3)
            self.assertNotEqual(alarms[0]["last_seen_timestamp"], initial.timestamp)
            db._get_connection().close()


if __name__ == "__main__":
    unittest.main()
