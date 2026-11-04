import sqlite3
import tempfile
import unittest
from pathlib import Path

from database import Database
from models import TagReading


class PlcReadingProvenanceTests(unittest.TestCase):
    def test_sqlite_round_trip_keeps_source_quality_and_connection_for_live_and_simulated(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            db = Database(Path(directory) / "provenance.sqlite")
            live = TagReading(
                tag="MOT-02-CUR", value=7.5, timestamp="2026-10-30T10:00:00Z", unit="A",
                equipment_id="Pump-02", received_timestamp="2026-10-30T10:00:01Z",
                data_quality="VALID", data_source="live_plc", connection_status="connected",
            )
            simulated = TagReading(
                tag="MOT-02-CUR", value=8.0, timestamp="2026-10-30T10:00:02Z", unit="A",
                equipment_id="Pump-02", received_timestamp="2026-10-30T10:00:02Z",
                data_quality="VALID", data_source="simulated", connection_status="simulation",
            )
            db.insert_readings_batch([live, simulated])
            readings = db.get_readings(tag="MOT-02-CUR")
            self.assertEqual([item.data_source for item in readings], ["live_plc", "simulated"])
            self.assertEqual(readings[0].timestamp, live.timestamp)
            self.assertEqual(readings[0].received_timestamp, live.received_timestamp)
            self.assertEqual(readings[0].data_quality, "VALID")
            self.assertEqual(readings[0].connection_status, "connected")
            self.assertEqual(db.get_latest_reading("MOT-02-CUR").data_source, "simulated")
            context_readings = db.get_context_readings(
                equipment_id="Pump-02", tags=["MOT-02-CUR"],
                start_time="2026-10-30T09:59:00Z", end_time="2026-10-30T10:01:00Z")
            self.assertEqual(context_readings[0]["data_source"], "live_plc")
            self.assertEqual(context_readings[0]["received_timestamp"], live.received_timestamp)
            db._conn.close()

    def test_additive_migration_preserves_existing_sqlite_readings(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            path = Path(directory) / "legacy.sqlite"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE tag_readings (id INTEGER PRIMARY KEY, tag TEXT, value REAL, value_raw TEXT, timestamp TEXT, unit TEXT, equipment_id TEXT)")
            connection.execute("INSERT INTO tag_readings VALUES (1, 'MOT-02-CUR', 7.5, '7.5', '2026-10-30T10:00:00Z', 'A', 'Pump-02')")
            connection.commit()
            connection.close()
            db = Database(path)
            reading = db.get_latest_reading("MOT-02-CUR")
            self.assertEqual(reading.value, 7.5)
            self.assertEqual(reading.data_source, "unknown")
            self.assertEqual(reading.timestamp, "2026-10-30T10:00:00Z")
            db._conn.close()


if __name__ == "__main__":
    unittest.main()
