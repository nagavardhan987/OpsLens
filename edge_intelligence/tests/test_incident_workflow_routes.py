"""Focused endpoint tests for operator audit and incident lifecycle actions."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.routes import ActionRequest, MarkUnresolvedRequest, create_app
EVENT_ID = "workflow-event-1"
ALARM_TIME = "2026-10-31T10:00:00Z"


class WorkflowAudit:
    def __init__(self):
        self.actions = []

    def log_action(self, event_id, operator, action_type, notes=None, timestamp=None):
        action = SimpleNamespace(
            event_id=event_id, operator=operator, action_type=action_type,
            notes=notes, timestamp=timestamp or "2026-10-31T10:02:00Z",
            model_dump=lambda: {
                "event_id": event_id, "operator": operator, "action_type": action_type,
                "notes": notes, "timestamp": timestamp or "2026-10-31T10:02:00Z",
            },
        )
        self.actions.append(action)
        return action


class WorkflowOrchestrator:
    def __init__(self, latest_reading=None):
        self.db = SimpleNamespace(get_latest_reading=lambda _tag: latest_reading)
        self.audit = WorkflowAudit()

    def get_full_event(self, event_id):
        if event_id != EVENT_ID:
            return None
        return {"event_id": event_id, "story": {"steps": [{"tag": "ALM-P02-HP", "timestamp": ALARM_TIME}]}}

    def _equipment_for(self, _tag):
        return "Pump-02"


def endpoint_for(app, path):
    # Newer FastAPI versions retain included routers as deferred _IncludedRouter
    # entries until route matching. Inspect the source router in that case.
    routes = []
    for route in app.routes:
        routes.append(route)
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            routes.extend(original_router.routes)
    normalized = path.removeprefix("/api")
    return next(route.endpoint for route in routes if getattr(route, "path", None) in (path, normalized))


def run_sync_endpoint(coroutine):
    """Run these no-await endpoint handlers without opening Windows asyncio sockets."""
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("Expected a synchronous endpoint handler with no await points")


class TestIncidentWorkflowRoutes(unittest.TestCase):
    def test_mark_unresolved_writes_audited_transition_and_returns_open_status(self):
        orch = WorkflowOrchestrator()
        app = create_app(orchestrator=orch)
        handler = endpoint_for(app, "/api/incidents/{event_id}/unresolved")
        result = run_sync_endpoint(handler(EVENT_ID, MarkUnresolvedRequest(
            operator="operator-7", reason="Waiting for maintenance inspection.", timestamp="2026-10-31T10:03:00Z",
        )))
        self.assertEqual(result["status"], "UNRESOLVED")
        self.assertTrue(result["is_open"])
        self.assertEqual(result["event_id"], EVENT_ID)
        self.assertEqual(result["action"]["action_type"], "MARK_UNRESOLVED")
        self.assertEqual(result["action"]["notes"], "Waiting for maintenance inspection.")
        self.assertEqual(result["action"]["operator"], "operator-7")
        self.assertEqual(result["action"]["timestamp"], "2026-10-31T10:03:00Z")

    def test_mark_unresolved_accepts_missing_note_but_rejects_unknown_incident(self):
        orch = WorkflowOrchestrator()
        app = create_app(orchestrator=orch)
        handler = endpoint_for(app, "/api/incidents/{event_id}/unresolved")
        result = run_sync_endpoint(handler(EVENT_ID, MarkUnresolvedRequest(operator="operator-7")))
        self.assertIsNone(result["action"]["notes"])
        with self.assertRaises(Exception) as error:
            run_sync_endpoint(handler("missing-event", MarkUnresolvedRequest(operator="operator-7")))
        self.assertEqual(getattr(error.exception, "status_code", None), 404)

    def test_resolve_requires_later_source_clear_then_operator_confirmation(self):
        active = SimpleNamespace(tag="ALM-P02-HP", equipment_id="Pump-02", value=True, timestamp="2026-10-31T10:01:00Z")
        orch = WorkflowOrchestrator(latest_reading=active)
        app = create_app(orchestrator=orch)
        handler = endpoint_for(app, "/api/actions")
        request = ActionRequest(event_id=EVENT_ID, operator="operator-7", action_type="RESOLVE", notes="Confirmed clear")
        with self.assertRaises(Exception) as active_error:
            run_sync_endpoint(handler(request))
        self.assertEqual(getattr(active_error.exception, "status_code", None), 400)
        self.assertEqual(orch.audit.actions, [])

        stale_clear = SimpleNamespace(tag="ALM-P02-HP", equipment_id="Pump-02", value=False, timestamp=ALARM_TIME)
        orch.db.get_latest_reading = lambda _tag: stale_clear
        with self.assertRaises(Exception) as stale_error:
            run_sync_endpoint(handler(request))
        self.assertEqual(getattr(stale_error.exception, "status_code", None), 400)
        self.assertEqual(orch.audit.actions, [])

        later_clear = SimpleNamespace(tag="ALM-P02-HP", equipment_id="Pump-02", value=False, timestamp="2026-10-31T10:04:00Z")
        orch.db.get_latest_reading = lambda _tag: later_clear
        result = run_sync_endpoint(handler(request))
        self.assertEqual(result["action_type"], "RESOLVE")
        self.assertEqual(len(orch.audit.actions), 1)


if __name__ == "__main__":
    unittest.main()
