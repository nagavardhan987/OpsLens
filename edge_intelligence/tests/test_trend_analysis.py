import unittest

from trend_analysis import summarize_readings


def readings(values, times=None, tag="FIT-02-FLW"):
    times = times or [f"2026-10-16T09:{minute:02d}:00Z" for minute in range(len(values))]
    return [{"tag": tag, "value": value, "timestamp": stamp, "unit": "L/min", "equipment_id": "Pump-02"}
            for value, stamp in zip(values, times)]


class TestTrendAnalysis(unittest.TestCase):
    def test_rising_and_chronological_timestamped_changes(self):
        result = summarize_readings(readings([10, 15, 20]), "2026-10-16T10:00:00Z")[0]
        self.assertEqual(result["first_observed"]["value"], 10)
        self.assertEqual(result["last_observed"]["value"], 20)
        self.assertEqual(result["minimum"]["value"], 10)
        self.assertEqual(result["maximum"]["value"], 20)
        self.assertEqual(result["absolute_change"], 10)
        self.assertEqual(result["percentage_change"], 100)
        self.assertEqual([change["timestamp"] for change in result["important_changes"]],
                         ["2026-10-16T09:01:00Z", "2026-10-16T09:02:00Z"])
        self.assertTrue(all(change["chronology"] == "before_alarm" for change in result["important_changes"]))

    def test_falling_flat_and_zero_baseline(self):
        falling = summarize_readings(readings([20, 10]))[0]
        self.assertEqual(falling["absolute_change"], -10)
        self.assertEqual(falling["percentage_change"], -50)
        flat = summarize_readings(readings([4, 4, 4]))[0]
        self.assertEqual(flat["change_count"], 0)
        self.assertEqual(flat["absolute_change"], 0)
        zero = summarize_readings(readings([0, 5]))[0]
        self.assertIsNone(zero["percentage_change"])
        self.assertIsNone(zero["important_changes"][0]["percentage_change"])

    def test_empty_invalid_and_conflicting_duplicate_timestamp(self):
        self.assertEqual(summarize_readings([]), [])
        invalid = summarize_readings(readings([None, "bad", float("nan"), True]))[0]
        self.assertEqual(invalid["reading_count"], 0)
        self.assertEqual(invalid["invalid_reading_count"], 1)
        self.assertEqual(invalid["non_numeric_reading_count"], 3)
        same_time = "2026-10-16T09:00:00Z"
        duplicate = summarize_readings(readings([1, 1, 2, 3], [same_time, same_time, same_time,
                                                                    "2026-10-16T09:01:00Z"]))[0]
        self.assertEqual(duplicate["duplicate_records_ignored"], 1)
        self.assertEqual(duplicate["ambiguous_timestamp_count"], 1)
        self.assertEqual(duplicate["first_observed"]["value"], 3)
        self.assertEqual(duplicate["missing_data"].startswith("Conflicting"), True)

    def test_gap_indicator_is_explicitly_cadence_heuristic(self):
        result = summarize_readings(readings([1, 2, 3], [
            "2026-10-16T09:00:00Z", "2026-10-16T09:00:02Z", "2026-10-16T09:00:20Z"
        ]))[0]
        self.assertEqual(result["gap_count"], 1)
        self.assertIn("not proof of missing samples", result["gap_detection"])

    def test_window_coverage_does_not_claim_unobserved_period(self):
        result = summarize_readings(readings([1, 2], [
            "2026-10-16T09:59:00Z", "2026-10-16T10:00:00Z"
        ]), "2026-10-16T10:00:00Z", window_start="2026-10-16T09:30:00Z")[0]
        self.assertEqual(result["observed_coverage_seconds"], 60)
        self.assertEqual(result["leading_unobserved_seconds"], 1740)
        self.assertIn("no numeric reading was recorded during the first 1740 seconds", result["coverage_note"])


if __name__ == "__main__":
    unittest.main()
