"""
OpsLens - Scenario Data: Pump-02 High Pressure Incident
Contains normal baselines, incident targets, timeline steps, and SOP details.
"""

from typing import Dict, Any, List

NORMAL_MACHINE_STATE: Dict[str, Any] = {
    "machine_id": "PUMP-02",
    "name": "Feed Water Injection Pump 02",
    "status": "RUNNING",
    "status_color": "green",
    "health_index": 98,
    "mode": "AUTOMATIC",
    "last_updated": "14:30:00",
    "parameters": {
        "valve_04_position": {
            "name": "Valve-04 Position",
            "tag": "VLV-04-POS",
            "value": 78.0,
            "unit": "%",
            "normal_range": [70.0, 85.0],
            "status": "NORMAL",
            "trend": "STABLE"
        },
        "flow_rate": {
            "name": "Discharge Flow Rate",
            "tag": "FIT-02-FLW",
            "value": 82.0,
            "unit": "L/min",
            "normal_range": [75.0, 90.0],
            "status": "NORMAL",
            "trend": "STABLE"
        },
        "motor_current": {
            "name": "Drive Motor Current",
            "tag": "MOT-02-CUR",
            "value": 7.8,
            "unit": "A",
            "normal_range": [7.0, 8.2],
            "status": "NORMAL",
            "trend": "STABLE"
        },
        "discharge_pressure": {
            "name": "Discharge Line Pressure",
            "tag": "PIT-02-PRS",
            "value": 4.8,
            "unit": "bar",
            "normal_range": [4.2, 5.2],
            "status": "NORMAL",
            "trend": "STABLE"
        }
    }
}

INCIDENT_MACHINE_STATE: Dict[str, Any] = {
    "machine_id": "PUMP-02",
    "name": "Feed Water Injection Pump 02",
    "status": "CRITICAL_ALARM",
    "status_color": "red",
    "health_index": 41,
    "mode": "AUTOMATIC",
    "last_updated": "14:32:00",
    "parameters": {
        "valve_04_position": {
            "name": "Valve-04 Position",
            "tag": "VLV-04-POS",
            "value": 43.0,
            "unit": "%",
            "normal_range": [70.0, 85.0],
            "status": "DEVIATED",
            "trend": "DOWN",
            "delta_percent": -45
        },
        "flow_rate": {
            "name": "Discharge Flow Rate",
            "tag": "FIT-02-FLW",
            "value": 56.0,
            "unit": "L/min",
            "normal_range": [75.0, 90.0],
            "status": "LOW",
            "trend": "DOWN",
            "delta_percent": -32
        },
        "motor_current": {
            "name": "Drive Motor Current",
            "tag": "MOT-02-CUR",
            "value": 9.2,
            "unit": "A",
            "normal_range": [7.0, 8.2],
            "status": "HIGH",
            "trend": "UP",
            "delta_percent": 18
        },
        "discharge_pressure": {
            "name": "Discharge Line Pressure",
            "tag": "PIT-02-PRS",
            "value": 6.9,
            "unit": "bar",
            "normal_range": [4.2, 5.2],
            "status": "CRITICAL_HIGH",
            "trend": "UP",
            "delta_percent": 44
        }
    }
}

TIMELINE_EVENTS: List[Dict[str, Any]] = [
    {
        "id": "evt-01",
        "time": "14:31",
        "relative_sec": 0,
        "parameter": "Valve-04 position",
        "tag": "VLV-04-POS",
        "description": "Valve-04 position restricted",
        "detail": "78% → 43%",
        "from_val": 78.0,
        "to_val": 43.0,
        "unit": "%",
        "type": "PROCESS_DEVIATION",
        "severity": "WARNING",
        "tag_color": "amber",
        "precedes_alarm": True
    },
    {
        "id": "evt-02",
        "time": "14:32",
        "relative_sec": 4,
        "parameter": "Flow rate",
        "tag": "FIT-02-FLW",
        "description": "Discharge flow drop detected",
        "detail": "82 → 56 L/min",
        "from_val": 82.0,
        "to_val": 56.0,
        "unit": "L/min",
        "type": "PROCESS_DEVIATION",
        "severity": "WARNING",
        "tag_color": "amber",
        "precedes_alarm": True
    },
    {
        "id": "evt-03",
        "time": "14:32",
        "relative_sec": 6,
        "parameter": "Motor current",
        "tag": "MOT-02-CUR",
        "description": "Drive motor current increase (hydraulic backpressure)",
        "detail": "7.8 → 9.2 A",
        "from_val": 7.8,
        "to_val": 9.2,
        "unit": "A",
        "type": "PROCESS_DEVIATION",
        "severity": "WARNING",
        "tag_color": "amber",
        "precedes_alarm": True
    },
    {
        "id": "evt-04",
        "time": "14:32",
        "relative_sec": 8,
        "parameter": "Discharge pressure",
        "tag": "PIT-02-PRS",
        "description": "Discharge line pressure surge",
        "detail": "4.8 → 6.9 bar",
        "from_val": 4.8,
        "to_val": 6.9,
        "unit": "bar",
        "type": "THRESHOLD_BREACH",
        "severity": "CRITICAL",
        "tag_color": "red",
        "precedes_alarm": True
    },
    {
        "id": "evt-05",
        "time": "14:32",
        "relative_sec": 10,
        "parameter": "ALARM ANNUNCIATOR",
        "tag": "ALM-P02-HP",
        "description": "HIGH PRESSURE ALARM",
        "detail": "Pressure 6.9 bar exceeds trip limit 6.0 bar",
        "from_val": None,
        "to_val": 6.9,
        "unit": "bar",
        "type": "CRITICAL_ALARM",
        "severity": "CRITICAL",
        "tag_color": "red",
        "precedes_alarm": False
    }
]

EVIDENCE_PAYLOAD: Dict[str, Any] = {
    "likely_contributor": "Valve-04 restriction",
    "attribution_statement": "Likely contributor based on correlated evidence.",
    "confidence_rating": "HIGH",
    "correlation_chain": "Valve-04 restriction → Flow reduction → Motor load surge → Pressure spike → Trip alarm",
    "supporting_evidence": [
        {
            "id": "ev-1",
            "metric": "Valve-04 position",
            "change": "decreased by 45%",
            "exact_numbers": "78% → 43%",
            "formula": "(78 - 43) / 78 = -44.9%",
            "verified": True
        },
        {
            "id": "ev-2",
            "metric": "Discharge flow",
            "change": "decreased by 32%",
            "exact_numbers": "82 → 56 L/min",
            "formula": "(82 - 56) / 82 = -31.7%",
            "verified": True
        },
        {
            "id": "ev-3",
            "metric": "Drive motor current",
            "change": "increased by 18%",
            "exact_numbers": "7.8 → 9.2 A",
            "formula": "(9.2 - 7.8) / 7.8 = +17.9%",
            "verified": True
        },
        {
            "id": "ev-4",
            "metric": "Line discharge pressure",
            "change": "increased by 44%",
            "exact_numbers": "4.8 → 6.9 bar",
            "formula": "(6.9 - 4.8) / 4.8 = +43.8%",
            "verified": True
        },
        {
            "id": "ev-5",
            "metric": "Temporal sequence",
            "change": "Valve deviation occurred before the alarm",
            "exact_numbers": "14:31 (Valve) vs 14:32 (Alarm)",
            "formula": "Causal lead time = 60 seconds",
            "verified": True
        }
    ]
}

SOP_HP_P02: Dict[str, Any] = {
    "sop_id": "HP-P02",
    "title": "High Pressure Response Procedure",
    "system": "Pump-02 Feed Water Line",
    "revision": "v2.4",
    "keywords": ["high pressure", "pump", "valve", "restriction", "pump-02", "valve-04", "pit-02"],
    "summary": "Verify Valve-04 position and Pump-02 operating condition.",
    "effective_limit": "6.0 bar max operating pressure",
    "steps": [
        {
            "step_number": 1,
            "instruction": "Verify pressure reading.",
            "detail": "Cross-check transmitter PIT-02-PRS against backup local gauge PI-02B to rule out instrumentation failure.",
            "safety_note": "Do not enter containment valve pit if line is hammering."
        },
        {
            "step_number": 2,
            "instruction": "Check Valve-04 position.",
            "detail": "Inspect actuator control signal and mechanical indicator on Valve-04 (VLV-04-POS). Verify if positioner commanded reduction to 43% or physical blockage exists.",
            "safety_note": "Ensure bypass line is isolated before manual jog."
        },
        {
            "step_number": 3,
            "instruction": "Verify Pump-02 operating condition.",
            "detail": "Check motor current (MOT-02-CUR), casing vibration, and bearing temperatures. Inspect for cavitation or excessive recirculation backpressure.",
            "safety_note": "High motor current (9.2 A) approaching thermal overload limit (10.0 A)."
        },
        {
            "step_number": 4,
            "instruction": "If pressure remains above the limit, follow the applicable shutdown procedure.",
            "detail": "If pressure does not normalize below 5.2 bar within 120 seconds of valve trim, trip Pump-02 via emergency stop push button or DCS permissive sequence.",
            "safety_note": "Overpressure protection burst disc threshold is 8.0 bar."
        },
        {
            "step_number": 5,
            "instruction": "Escalate to maintenance if valve malfunction is suspected.",
            "detail": "Contact mechanical maintenance dispatch (Ext. 4410) and log work order for actuator recalibration or trim debris clearance.",
            "safety_note": "Complete shift handover log entry before shift change."
        }
    ]
}

NEXT_BEST_ACTIONS: List[Dict[str, Any]] = [
    {
        "priority": 1,
        "action": "Verify Valve-04 position and condition",
        "description": "Inspect actuator air supply and stem position to relieve discharge restriction.",
        "target_component": "Valve-04"
    },
    {
        "priority": 2,
        "action": "Review Pump-02 operating status",
        "description": "Monitor drive motor current (9.2 A) and bearing vibration under backpressure.",
        "target_component": "Pump-02"
    },
    {
        "priority": 3,
        "action": "Follow HP-P02 SOP",
        "description": "Adhere to the 5-step emergency response procedure if pressure exceeds 6.0 bar.",
        "target_component": "SOP HP-P02"
    }
]

FIXED_OPERATOR: str = "J. Rivera (Shift 2)"
