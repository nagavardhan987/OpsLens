"""
OpsLens - Scenario Registry & Factory
"""

from typing import Dict, Type, List, Any
from scenarios.base import BaseScenario
from scenarios.valve_restriction import ValveRestrictionScenario
from scenarios.bearing_wear import BearingWearScenario
from scenarios.seal_leak import SealLeakScenario
from scenarios.sensor_fault import SensorFaultScenario
from scenarios.tank_overflow import TankOverflowScenario
from scenarios.compressor_overspeed import CompressorOverspeedScenario
from scenarios.pump_cavitation import PumpCavitationScenario
from scenarios.wet_well_high_level import WetWellHighLevelScenario
from scenarios.screen_differential_pressure import ScreenDifferentialPressureScenario
from scenarios.low_do_ammonia_rise import LowDOAmmoniaRiseScenario
from scenarios.filters_uv_disinfection_failure import FiltersUvDisinfectionFailureScenario
from scenarios.ras_pump_failure import RaspumpFailureScenario
from scenarios.filter_sensor_fault import FilterSensorFaultScenario
from scenarios.biological_foam import BiologicalFoamScenario
from scenarios.biogas_holder_pressure import BiogasHolderPressureScenario
from scenarios.centrifuge_capture import CentrifugeCaptureScenario
from scenarios.monitoring_due import MonitoringDueScenario


SCENARIO_REGISTRY: Dict[str, Type[BaseScenario]] = {
    # Wastewater scenarios appear first so the primary demo is in its intended domain.
    "wet_well_high_level": WetWellHighLevelScenario,
    "screen_differential_pressure": ScreenDifferentialPressureScenario,
    "low_do_ammonia_rise": LowDOAmmoniaRiseScenario,
    "filters_uv_disinfection_failure": FiltersUvDisinfectionFailureScenario,
    "ras_pump_failure": RaspumpFailureScenario,
    "filter_sensor_fault": FilterSensorFaultScenario,
    "biological_foam": BiologicalFoamScenario,
    "biogas_holder_pressure": BiogasHolderPressureScenario,
    "centrifuge_capture": CentrifugeCaptureScenario,
    "monitoring_due": MonitoringDueScenario,

    # --- Original 4 ---
    "valve_restriction":         ValveRestrictionScenario,
    "valve_restriction_cascade": ValveRestrictionScenario,
    "scenario_a":                ValveRestrictionScenario,

    "bearing_wear":              BearingWearScenario,
    "scenario_b":                BearingWearScenario,

    "seal_leak":                 SealLeakScenario,
    "scenario_c":                SealLeakScenario,

    "sensor_fault":              SensorFaultScenario,
    "scenario_d":                SensorFaultScenario,

    # --- New 3 ---
    "tank_overflow":             TankOverflowScenario,
    "scenario_e":                TankOverflowScenario,

    "compressor_overspeed":      CompressorOverspeedScenario,
    "scenario_f":                CompressorOverspeedScenario,

    "pump_cavitation":           PumpCavitationScenario,
    "scenario_g":                PumpCavitationScenario,
}


def get_scenario(scenario_id: str) -> BaseScenario:
    """Instantiate a scenario state machine by name or alias."""
    norm_id = scenario_id.lower().strip()
    if norm_id not in SCENARIO_REGISTRY:
        valid_ids = sorted(list(set(SCENARIO_REGISTRY.keys())))
        raise ValueError(
            f"Unknown scenario_id '{scenario_id}'. Available scenarios: {valid_ids}"
        )
    return SCENARIO_REGISTRY[norm_id]()


def list_available_scenarios() -> List[Dict[str, Any]]:
    """Return summary metadata for all distinct registered scenarios."""
    seen_classes = set()
    summaries = []
    for s_cls in SCENARIO_REGISTRY.values():
        if s_cls not in seen_classes:
            seen_classes.add(s_cls)
            instance = s_cls()
            summaries.append(instance.get_ground_truth())
    return summaries


PRIMARY_DEMO_SCENARIOS = [
    ("wet_well_high_level", "Lift Station — Wet-Well High-High Level", "WITH MATCHING SOP", "SOP-LFT-001", "Lift Station High-High Level and Pump Clog Response"),
    ("screen_differential_pressure", "Inlet Works — Screen Differential Pressure High", "WITH MATCHING SOP", "SOP-INL-001", "Bar Screen Operation and Blockage Response"),
    ("biological_foam", "Aeration Tank — Biological Foam", "WITH MATCHING SOP", "SOP-BIO-001", "Activated Sludge Foam Control"),
    ("ras_pump_failure", "RAS Pump Failure — Sludge Blanket High", "WITH MATCHING SOP", "SOP-BIO-002", "RAS Pump Failure and Sludge Blanket Control"),
    ("biogas_holder_pressure", "Biogas System — High Holder Pressure / CHP Trip", "WITH MATCHING SOP", "SOP-GAS-001", "Biogas Holder High Pressure, CHP Trip and Flare Operation"),
    ("centrifuge_capture", "Dewatering Centrifuge — Low Solids Capture / High Centrate Ammonia", "WITH MATCHING SOP", "SOP-SLD-001", "Dewatering Centrifuge Operation and Centrate Recycle Control"),
    ("monitoring_due", "Process Monitoring — Sampling / Calibration Due", "WITH MATCHING SOP", "SOP-LAB-001", "Process Sampling and Monitoring Schedule"),
    ("valve_restriction", "Pump-02 — Valve Restriction", "WITHOUT SPECIFIC EQUIPMENT-FAILURE SOP", None, None),
    ("bearing_wear", "Compressor-01 — Bearing Wear", "WITHOUT SPECIFIC EQUIPMENT-FAILURE SOP", None, None),
    ("filter_sensor_fault", "Filter-01 — Sensor Fault", "WITHOUT SPECIFIC EQUIPMENT-FAILURE SOP", None, None),
]


def list_primary_demo_scenarios() -> List[Dict[str, Any]]:
    """Return exactly the ten curated primary demonstration scenarios."""
    result = []
    for scenario_id, name, group, sop_id, sop_title in PRIMARY_DEMO_SCENARIOS:
        scenario = get_scenario(scenario_id)
        equipment_by_id = {
            "wet_well_high_level": "LiftStation-01", "screen_differential_pressure": "InletWorks-01",
            "biological_foam": "AerationBasin-01", "ras_pump_failure": "RASSystem-01",
            "biogas_holder_pressure": "BiogasSystem-01", "centrifuge_capture": "DewateringCentrifuge-01",
            "monitoring_due": "ProcessMonitoring-01", "bearing_wear": "Compressor-01",
            "valve_restriction": "Pump-02", "filter_sensor_fault": "Filter-01",
        }
        alarm_by_id = {
            "wet_well_high_level": "ALM-WW-101-HH", "screen_differential_pressure": "ALM-SCR-110-DP",
            "biological_foam": "ALM-AER-201-FOAM", "ras_pump_failure": "ALM-SLB-201-HIGH",
            "biogas_holder_pressure": "ALM-GAS-601-HIGH", "centrifuge_capture": "ALM-SLD-701-CAPTURE",
            "monitoring_due": "ALM-LAB-901-DUE", "bearing_wear": "ALM-C01-VB",
            "valve_restriction": "ALM-P02-HP", "filter_sensor_fault": "ALM-FLT-401-SENSOR",
        }
        result.append({
            **scenario.get_ground_truth(),
            "scenario_id": scenario_id,
            "name": name,
            "equipment_id": equipment_by_id.get(scenario_id),
            "alarm_id": alarm_by_id.get(scenario_id),
            "demo_group": group,
            "sop_available": bool(sop_id),
            "sop_id": sop_id,
            "sop_title": sop_title,
            "sop_approval_status": "Draft for review — not approved" if sop_id else "No directly applicable equipment-failure SOP retrieved",
            "source_status": "SIMULATED",
        })
    return result
