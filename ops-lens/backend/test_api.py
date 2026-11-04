"""
OpsLens Backend Verification Script
Verifies all 10 REST endpoints, deterministic calculations, and state transitions.
"""

import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_full_incident_lifecycle():
    print("=== OpsLens Backend Test Suite ===")

    # 1. Reset state
    res = client.post("/api/demo/reset")
    assert res.status_code == 200, f"Reset failed: {res.text}"
    print("✓ [POST /api/demo/reset] Initial reset OK")

    # 2. Check initial normal machine state
    res = client.get("/api/machine")
    assert res.status_code == 200
    m_data = res.json()["data"]
    assert m_data["status"] == "RUNNING"
    assert m_data["parameters"]["valve_04_position"]["value"] == 78.0
    assert m_data["parameters"]["flow_rate"]["value"] == 82.0
    assert m_data["parameters"]["motor_current"]["value"] == 7.8
    assert m_data["parameters"]["discharge_pressure"]["value"] == 4.8
    print("✓ [GET /api/machine] Normal baseline values verified")

    # 3. Check alarms in normal state
    res = client.get("/api/alarms")
    assert res.status_code == 200
    assert res.json()["data"]["active_alarm_count"] == 0
    print("✓ [GET /api/alarms] Zero active alarms in baseline")

    # 4. Start Incident Simulation
    res = client.post("/api/demo/start")
    assert res.status_code == 200
    start_payload = res.json()["data"]
    assert start_payload["incident_active"] is True
    assert len(start_payload["event_story"]["events"]) == 5
    print("✓ [POST /api/demo/start] Full precomputed incident payload received")

    # 5. Check incident machine state
    res = client.get("/api/machine")
    assert res.status_code == 200
    m_inc = res.json()["data"]
    assert m_inc["status"] == "CRITICAL_ALARM"
    assert m_inc["parameters"]["valve_04_position"]["value"] == 43.0
    assert m_inc["parameters"]["flow_rate"]["value"] == 56.0
    assert m_inc["parameters"]["motor_current"]["value"] == 9.2
    assert m_inc["parameters"]["discharge_pressure"]["value"] == 6.9
    print("✓ [GET /api/machine] Incident values verified (43%, 56 L/min, 9.2 A, 6.9 bar)")

    # 6. Check prioritized alarms
    res = client.get("/api/alarms")
    assert res.status_code == 200
    alarm_data = res.json()["data"]
    assert alarm_data["active_alarm_count"] == 1
    assert alarm_data["primary_alarm"]["title"] == "HIGH PRESSURE ALARM"
    assert "Critical event prioritized" in alarm_data["micro_explanation"]
    assert len(alarm_data["related_events"]) == 3
    print("✓ [GET /api/alarms] Alarm prioritization & micro-explanation verified")

    # 7. Check incident summary
    res = client.get("/api/incident")
    assert res.status_code == 200
    inc_data = res.json()["data"]
    assert inc_data["is_incident"] is True
    assert "Pump-02 – High Pressure" in inc_data["incident_name"]
    print("✓ [GET /api/incident] Incident summary & correlation verified")

    # 8. Check Event Story timeline
    res = client.get("/api/event-story")
    assert res.status_code == 200
    story = res.json()["data"]
    assert story["has_story"] is True
    events = story["events"]
    assert len(events) == 5
    assert events[0]["time"] == "14:31" and events[0]["parameter"] == "Valve-04 position"
    assert events[4]["time"] == "14:32" and events[4]["description"] == "HIGH PRESSURE ALARM"
    print("✓ [GET /api/event-story] Event story chronological timeline verified")

    # 9. Check Evidence Engine
    res = client.get("/api/evidence")
    assert res.status_code == 200
    ev_data = res.json()["data"]
    assert ev_data["likely_contributor"] == "Valve-04 restriction"
    assert "Likely contributor based on correlated evidence" in ev_data["attribution_statement"]
    evidence_list = ev_data["supporting_evidence"]
    assert any("decreased by 45%" in e["change"] for e in evidence_list)
    assert any("decreased by 32%" in e["change"] for e in evidence_list)
    assert any("increased by 18%" in e["change"] for e in evidence_list)
    assert any("increased by 44%" in e["change"] for e in evidence_list)
    assert any("occurred before the alarm" in e["change"] for e in evidence_list)
    print("✓ [GET /api/evidence] Evidence engine: -45%, -32%, +18%, +44% verified")

    # 10. Check SOP Retrieval
    res = client.get("/api/sop")
    assert res.status_code == 200
    sop_data = res.json()["data"]
    assert sop_data["has_sop"] is True
    assert sop_data["sop"]["sop_id"] == "HP-P02"
    assert len(sop_data["sop"]["steps"]) == 5
    print("✓ [GET /api/sop] SOP HP-P02 retrieval verified (5 steps)")

    # 11. Record Operator Action
    action_payload = {
        "action_id": "VERIFY_VALVE_04",
        "action_name": "Verify Valve-04 position and condition",
        "notes": "Visual check confirmed 43% mechanical restriction."
    }
    res = client.post("/api/operator-action", json=action_payload)
    assert res.status_code == 200
    act_res = res.json()
    assert act_res["message"] == "Operator action recorded"
    assert act_res["record"]["operator"] == "J. Rivera (Shift 2)"
    print("✓ [POST /api/operator-action] Recorded operator action with 'J. Rivera (Shift 2)'")

    # 12. Check Shift Handover
    res = client.get("/api/handover")
    assert res.status_code == 200
    handover = res.json()["data"]
    assert handover["operator"] == "J. Rivera (Shift 2)"
    assert handover["likely_contributor"] == "Valve-04 restriction"
    assert handover["operator_action"] == "Valve-04 verified"
    assert handover["current_status"] == "Monitoring"
    assert handover["pending_issue"] == "None"
    print("✓ [GET /api/handover] Shift handover summary verified")

    # 13. Test reset back to normal
    res = client.post("/api/demo/reset")
    assert res.status_code == 200
    res = client.get("/api/machine")
    assert res.json()["data"]["status"] == "RUNNING"
    print("✓ [POST /api/demo/reset] Machine reset back to RUNNING state")

    print("\nALL 10 ENDPOINTS & ACCEPTANCE CHECKS PASSED SUCCESSFULLY!\n")


if __name__ == "__main__":
    test_full_incident_lifecycle()
