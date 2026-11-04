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


SCENARIO_REGISTRY: Dict[str, Type[BaseScenario]] = {
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
