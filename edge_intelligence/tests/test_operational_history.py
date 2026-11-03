import sys
import tempfile
import unittest
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import Database
from models import EventStory, IndividualAlarmRecord, OperatorAction
from operational_history import (build_handover_summary, configured_shift_window,
                                 generate_shift_narrative, list_alarm_history)

class OperationalHistoryTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / ".test-tmp"
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.db = Database(Path(self.temp.name) / 'history.db')
        self.event = 'incident-1'
        self.db.save_event_story(EventStory(event_id=self.event, steps=[{"step_number": 1, "tag": "ALM-P02-HP", "timestamp": "2026-11-01T10:00:00Z", "description": "High pressure alarm"}], causal_label='High pressure'))
        self.alarm = IndividualAlarmRecord(alarm_id='alarm-1', tag='ALM-P02-HP', equipment_id='Pump-02', value=True, source_priority='P1', first_seen_timestamp='2026-11-01T10:00:00Z', last_seen_timestamp='2026-11-01T10:00:00Z', fingerprint='fp')
        self.db.save_individual_alarm(self.event, self.alarm)
        self.db.record_alarm_occurrence(self.event, self.alarm, 'simulated', 'VALID')

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_repeated_occurrences_are_retained_and_aggregated(self):
        repeat = self.alarm.model_copy(update={'last_seen_timestamp': '2026-11-01T10:02:00Z', 'value': True, 'repeat_count': 2})
        self.db.save_individual_alarm(self.event, repeat)
        self.db.record_alarm_occurrence(self.event, repeat, 'simulated', 'VALID')
        row = list_alarm_history(self.db)[0]
        self.assertEqual(row['repeat_count'], 2)
        self.assertEqual([o['occurred_at'] for o in row['occurrences']], ['2026-11-01T10:00:00Z', '2026-11-01T10:02:00Z'])

    def test_acknowledgement_does_not_resolve_alarm_or_incident(self):
        action = OperatorAction(action_id='a1', event_id=self.event, operator='Ada', action_type='ACKNOWLEDGE', timestamp='2026-11-01T10:01:00Z')
        self.db.save_operator_action(action)
        self.db.record_alarm_transition('alarm-1', self.event, 'ACKNOWLEDGED', 'Ada', action.timestamp)
        row = list_alarm_history(self.db)[0]
        self.assertEqual(row['status'], 'ACKNOWLEDGED')
        self.assertEqual(len(list_alarm_history(self.db, {'status': 'ACTIVE'})), 1)
        self.assertEqual(list_alarm_history(self.db, {'status': 'UNACKNOWLEDGED'}), [])
        self.assertEqual(self.db.get_event_status(self.event), 'ACKNOWLEDGED')
        self.assertIn(self.event, self.db.get_open_event_ids())

    def test_return_to_normal_is_not_resolution(self):
        self.db.record_alarm_transition('alarm-1', self.event, 'RETURNED_TO_NORMAL', 'System telemetry', '2026-11-01T10:03:00Z')
        row = list_alarm_history(self.db)[0]
        self.assertEqual(row['status'], 'RETURNED_TO_NORMAL')
        self.assertFalse(self.db.is_event_resolved(self.event))
        self.assertIn(self.event, self.db.get_open_event_ids())

    def test_resolution_is_distinct_and_historical_alarm_is_retained(self):
        self.db.save_operator_action(OperatorAction(action_id='resolve-1', event_id=self.event, operator='Bo', action_type='RESOLVE', timestamp='2026-11-01T10:05:00Z'))
        row = list_alarm_history(self.db)[0]
        self.assertEqual(row['status'], 'RESOLVED')
        self.assertEqual(row['resolved_by'], 'Bo')
        self.assertEqual(len(row['occurrences']), 1)
        self.assertEqual(self.db.get_event_status(self.event), 'RESOLVED')
        self.assertNotIn(self.event, self.db.get_open_event_ids())

    def test_ack_after_resolution_does_not_reopen_incident(self):
        self.db.save_operator_action(OperatorAction(action_id='resolve-2', event_id=self.event, operator='Ada', action_type='RESOLVE', timestamp='2026-11-01T10:05:00Z'))
        self.db.save_operator_action(OperatorAction(action_id='ack-late', event_id=self.event, operator='Bo', action_type='ACKNOWLEDGE', timestamp='2026-11-01T10:06:00Z'))
        self.assertTrue(self.db.is_event_resolved(self.event))
        self.assertNotIn(self.event, self.db.get_open_event_ids())

    def test_unresolved_incident_carries_across_shift_window(self):
        action = OperatorAction(action_id='unresolved-1', event_id=self.event, operator='Ada', action_type='MARK_UNRESOLVED', timestamp='2026-11-01T18:00:00Z', notes='Carry forward')
        self.db.save_operator_action(action)
        summary = build_handover_summary(self.db, '2026-11-01T18:00:00Z', '2026-11-02T06:00:00Z')
        self.assertEqual(summary['unresolved_incidents'], [{'incident_id': self.event, 'status': 'UNRESOLVED'}])
        self.assertIn(self.event, self.db.get_open_event_ids())

    def test_handover_history_filters_and_multiple_operators(self):
        for hid, shift, operator, when in [('h-day', 'Day', 'Ada', '2026-11-01T18:00:00Z'), ('h-night', 'Night', 'Bo', '2026-11-02T06:00:00Z')]:
            self.db.save_shift_handover({'handover_id': hid, 'shift_date': when[:10], 'shift_name': shift,
                'shift_start': when, 'shift_end': when, 'outgoing_operator': operator,
                'submitted_at': when, 'summary': {'incident_id': self.event}, 'entries': []})
        self.assertEqual(len(self.db.list_shift_handovers({'operator': 'Ada'})), 1)
        self.assertEqual(len(self.db.list_shift_handovers({'shift': 'Night'})), 1)
        self.assertEqual(len(self.db.list_shift_handovers({'date': '2026-11-02'})), 1)

    def test_handover_comments_are_audit_only(self):
        record = {'handover_id': 'h-comment', 'shift_date': '2026-11-01', 'shift_name': 'Day', 'shift_start': '2026-11-01T06:00:00Z', 'shift_end': '2026-11-01T18:00:00Z', 'outgoing_operator': 'Ada', 'submitted_at': '2026-11-01T18:00:00Z', 'summary': {}, 'entries': []}
        self.db.save_shift_handover(record)
        response = self.db.save_handover_item_response('h-comment', 'open-alarms:alarm-1', 'Bo', 'Check motor noise.', False, '2026-11-01T18:05:00Z')
        self.assertFalse(response['acknowledged'])
        self.assertEqual(len(self.db.get_handover_item_responses('h-comment')), 1)
        self.assertFalse(self.db.is_event_resolved(self.event))

    def test_handover_summary_marks_missing_operational_sources(self):
        summary = build_handover_summary(self.db, '2026-11-01T09:00:00Z', '2026-11-01T12:00:00Z')
        self.assertEqual(summary['open_alarms'][0]['alarm_id'], 'ALM-P02-HP')
        self.assertEqual(summary['equipment_out_of_service']['status'], 'Unavailable')
        self.assertEqual(summary['chemical_and_polymer_stock']['status'], 'Unavailable')

    def test_handover_narrative_uses_recorded_alarm_and_unresolved_incident(self):
        summary = build_handover_summary(self.db, '2026-11-01T09:00:00Z', '2026-11-01T12:00:00Z')
        narrative = generate_shift_narrative(summary)
        self.assertIn('ALM-P02-HP', narrative['text'])
        self.assertIn(self.event, narrative['text'])
        self.assertEqual(narrative['source'], 'deterministic')

    def test_no_alarm_shift_summary_is_explicit(self):
        summary = {'events_in_shift': [], 'actions_in_shift': [], 'open_alarms': [],
                   'unacknowledged_alarms': [], 'unresolved_incidents': [],
                   'abnormal_sensor_readings': {'items': []}}
        narrative = generate_shift_narrative(summary)
        self.assertIn('Open alarms: 0', narrative['text'])
        self.assertIn('Unresolved incidents carried forward: 0', narrative['text'])

    def test_local_llm_summary_success_is_labeled_and_grounded(self):
        summary = {'open_alarms': [{'alarm_id': 'ALM-P02-HP', 'equipment': 'Pump-02', 'status': 'ACTIVE'}],
                   'unacknowledged_alarms': [], 'unresolved_incidents': [], 'events_in_shift': [], 'actions_in_shift': [],
                   'abnormal_sensor_readings': {'items': []}}
        response = generate_shift_narrative(summary, lambda prompt, timeout: 'ALM-P02-HP remains active on Pump-02.', 'ollama')
        self.assertEqual(response['source'], 'AI-generated (local model)')
        self.assertIn('ALM-P02-HP', response['text'])

    def test_local_llm_failure_returns_deterministic_fallback(self):
        def fail(_prompt, timeout):
            raise TimeoutError('model timeout')
        response = generate_shift_narrative({'open_alarms': [], 'unacknowledged_alarms': [],
            'unresolved_incidents': [], 'events_in_shift': [], 'actions_in_shift': [],
            'abnormal_sensor_readings': {'items': []}}, fail, 'ollama')
        self.assertEqual(response['source'], 'deterministic')
        self.assertEqual(response['status'], 'fallback')
        self.assertIn('notice', response)

    def test_local_llm_ungrounded_output_is_rejected(self):
        summary = {'open_alarms': [], 'unacknowledged_alarms': [], 'unresolved_incidents': [],
                   'events_in_shift': [], 'actions_in_shift': [], 'abnormal_sensor_readings': {'items': []}}
        response = generate_shift_narrative(summary, lambda prompt, timeout: 'Pump-02 pressure is 999 bar.', 'ollama')
        self.assertEqual(response['source'], 'deterministic')
        self.assertEqual(response['status'], 'fallback')

    def test_remote_provider_never_receives_incident_records(self):
        def unexpected(_prompt, timeout):
            self.fail('external provider should not be called for shift summaries')
        response = generate_shift_narrative({'open_alarms': [], 'unacknowledged_alarms': [],
            'unresolved_incidents': [], 'events_in_shift': [], 'actions_in_shift': [],
            'abnormal_sensor_readings': {'items': []}}, unexpected, 'groq')
        self.assertEqual(response['source'], 'deterministic')

    def test_ollama_nonlocal_endpoint_never_receives_incident_records(self):
        def unexpected(_prompt, timeout):
            self.fail('non-local endpoint should not receive handover records')
        with patch.dict(os.environ, {'EDGE_LLM_URL': 'https://example.invalid'}):
            response = generate_shift_narrative({'open_alarms': [], 'unacknowledged_alarms': [],
                'unresolved_incidents': [], 'events_in_shift': [], 'actions_in_shift': [],
                'abnormal_sensor_readings': {'items': []}}, unexpected, 'ollama')
        self.assertEqual(response['source'], 'deterministic')

    def test_unconfigured_shift_timing_is_not_assumed(self):
        with patch.dict(os.environ, {'OPSLENS_SHIFT_START': '', 'OPSLENS_SHIFT_END': ''}, clear=False):
            self.assertIsNone(configured_shift_window(datetime(2026, 11, 2, 10, tzinfo=timezone.utc)))

    def test_overnight_shift_window_uses_previous_calendar_day(self):
        with patch.dict(os.environ, {'OPSLENS_SHIFT_START': '18:00', 'OPSLENS_SHIFT_END': '06:00', 'OPSLENS_SHIFT_NAME': 'Night'}):
            window = configured_shift_window(datetime(2026, 11, 2, 2, tzinfo=timezone.utc))
        self.assertEqual(window['name'], 'Night')
        self.assertEqual(window['date'], '2026-11-01')
        self.assertIn('2026-11-01T18:00:00', window['start'])
        self.assertIn('2026-11-02T06:00:00', window['end'])

    def test_handover_receipt_is_separate_from_incident_status(self):
        record = {'handover_id': 'h1', 'shift_date': '2026-11-01', 'shift_name': 'Day', 'shift_start': '2026-11-01T06:00:00+05:30', 'shift_end': '2026-11-01T18:00:00+05:30', 'outgoing_operator': 'Ada', 'submitted_at': '2026-11-01T18:00:00Z', 'summary': {}, 'entries': []}
        self.db.save_shift_handover(record)
        self.assertTrue(self.db.confirm_shift_handover('h1', 'Bo', 'Bo', '2026-11-01T18:20:00Z', True, True))
        received = self.db.get_shift_handover('h1')
        self.assertEqual(received['status'], 'RECEIVED')
        self.assertTrue(received['face_to_face_confirmed'])
        self.assertTrue(received['walkthrough_confirmed'])
        self.assertFalse(self.db.is_event_resolved(self.event))


if __name__ == '__main__':
    unittest.main()
