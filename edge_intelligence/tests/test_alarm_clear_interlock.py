import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api.routes import _is_clear_alarm_reading


class TestAlarmClearInterlock(unittest.TestCase):
    alarm_time = "2026-10-27T07:00:00Z"

    def reading(self, value, timestamp="2026-10-27T07:01:00Z", tag="ALM-P02-HP", equipment_id="Pump-02"):
        return SimpleNamespace(value=value, timestamp=timestamp, tag=tag, equipment_id=equipment_id)

    def test_active_alarm_is_not_a_clear(self):
        self.assertFalse(_is_clear_alarm_reading(self.reading(True), "ALM-P02-HP", self.alarm_time, "Pump-02"))

    def test_stale_clear_reading_cannot_clear_newer_alarm(self):
        self.assertFalse(_is_clear_alarm_reading(self.reading(False, "2026-10-27T06:59:59Z"), "ALM-P02-HP", self.alarm_time, "Pump-02"))

    def test_clear_sample_for_wrong_tag_or_equipment_is_rejected(self):
        self.assertFalse(_is_clear_alarm_reading(self.reading(False, tag="ALM-OTHER"), "ALM-P02-HP", self.alarm_time, "Pump-02"))
        self.assertFalse(_is_clear_alarm_reading(self.reading(False, equipment_id="Pump-03"), "ALM-P02-HP", self.alarm_time, "Pump-02"))

    def test_later_clear_sample_for_matching_source_is_accepted(self):
        self.assertTrue(_is_clear_alarm_reading(self.reading(False), "ALM-P02-HP", self.alarm_time, "Pump-02"))

    def test_clear_sample_must_be_newer_than_recovery_start(self):
        recovery_started = "2026-10-27T07:02:00Z"
        self.assertFalse(_is_clear_alarm_reading(
            self.reading(False, "2026-10-27T07:01:59Z"),
            "ALM-P02-HP", self.alarm_time, "Pump-02", minimum_timestamp=recovery_started,
        ))
        self.assertTrue(_is_clear_alarm_reading(
            self.reading(False, "2026-10-27T07:02:01Z"),
            "ALM-P02-HP", self.alarm_time, "Pump-02", minimum_timestamp=recovery_started,
        ))


if __name__ == "__main__":
    unittest.main()
