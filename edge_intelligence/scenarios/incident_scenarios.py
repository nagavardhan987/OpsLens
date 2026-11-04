"""
OpsLens - The six Scenario Lab incidents, driven by incident_catalog.

Each run has three periods:
  * normal operation  - tags follow the generator's baseline noise inside
                        their normal range (no overrides);
  * abnormal period   - each measurement ramps (smoothstep) from its value at
                        ramp start to the exact incident value; trips latch
                        when their limit is reached, statuses change, and
                        simulated PLC alarm inputs follow the limits;
  * recovery (only after "Run simulated corrective action") - values ramp to
                        the exact "after fix" values and alarm inputs clear
                        when their source returns inside the limit.

All readings are SIMULATED. Nothing here talks to a PLC.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import incident_catalog as catalog
from scenarios.base import BaseScenario


def _crossed(value: float, threshold: float, direction: str) -> bool:
    return value >= threshold if direction == "high" else value <= threshold


class CatalogScenario(BaseScenario):
    def __init__(self, scenario_id: str):
        spec = catalog.SCENARIO_BY_ID[scenario_id]
        super().__init__(
            scenario_id=spec.scenario_id,
            name=spec.name,
            description=spec.summary,
            duration_seconds=catalog.SCENARIO_DURATION_S,
            target_equipment=spec.equipment_id,
            expected_correlations=catalog.scenario_tags(spec),
            expected_non_correlations=[
                tag for other in catalog.SCENARIOS if other.scenario_id != spec.scenario_id
                for tag in catalog.scenario_tags(other) if tag not in catalog.scenario_tags(spec)
            ],
        )
        self.spec = spec
        self.equipment_scope = frozenset(catalog.PLANT_EQUIPMENT)
        self._ramp_start_values: Dict[str, float] = {}
        self._trip_latched_at: Dict[str, float] = {}
        self._last_values: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    def _alarm_bits(self, values: Dict[str, Any], tripped: Dict[str, bool]) -> Dict[str, bool]:
        bits: Dict[str, bool] = {}
        for sig in self.spec.signals:
            value = values.get(sig.tag)
            for lim in sig.limits:
                if lim.alarm_tag:
                    bits[lim.alarm_tag] = bool(isinstance(value, (int, float)) and _crossed(float(value), lim.value, lim.direction))
        return bits

    def _status_values(self, elapsed: float, tripped: Dict[str, bool]) -> Dict[str, bool]:
        values = {}
        for st in self.spec.statuses:
            changed = (st.change_at is not None and elapsed >= st.change_at) or \
                      (st.change_when is not None and tripped.get(st.change_when, False))
            values[st.tag] = st.incident if changed else st.normal
        return values

    def get_tag_values(self, elapsed_seconds: float, nominal_values: Dict[str, float]) -> Dict[str, Any]:
        t = elapsed_seconds
        values: Dict[str, Any] = {}
        for sig in self.spec.signals:
            start, end = sig.ramp
            if end <= start:
                continue  # step/zero signals are handled after trips are evaluated
            if t < start:
                continue  # normal period: generator baseline noise
            if sig.tag not in self._ramp_start_values:
                lo, hi = sig.noise_band or sig.normal
                midpoint = ((lo or 0.0) + (hi if hi is not None else (lo or 0.0))) / 2.0
                self._ramp_start_values[sig.tag] = float(nominal_values.get(sig.tag, midpoint))
            progress = min(1.0, (t - start) / (end - start))
            values[sig.tag] = round(self.smooth_transition(self._ramp_start_values[sig.tag], sig.incident, progress), 3)

        # Trips latch when their measurement reaches the limit.
        for trip in self.spec.trips:
            value = values.get(trip.tag)
            if trip.trip_id not in self._trip_latched_at and isinstance(value, (int, float)) \
                    and _crossed(float(value), trip.threshold, trip.direction):
                self._trip_latched_at[trip.trip_id] = t
        tripped = {trip_id: True for trip_id in self._trip_latched_at}

        for sig in self.spec.signals:
            if sig.peak_then_zero_on and sig.peak_then_zero_on in self._trip_latched_at \
                    and t > self._trip_latched_at[sig.peak_then_zero_on]:
                values[sig.tag] = 0.0
            if sig.step_on and sig.step_on in self._trip_latched_at:
                values[sig.tag] = float(sig.incident)

        values.update(self._status_values(t, tripped))
        values.update(self._alarm_bits({**nominal_values, **values}, tripped))
        self._last_values = {**self._last_values, **values}
        return values

    # ------------------------------------------------------------------
    def get_recovery_values(self, recovery_elapsed: float, nominal_values: Dict[str, float]) -> Dict[str, Any]:
        """Simulated corrective action: ramp to the incident map's 'after fix' values."""
        progress = min(1.0, recovery_elapsed / catalog.RECOVERY_DURATION_S)
        values: Dict[str, Any] = {}
        for sig in self.spec.signals:
            start_value = self._last_values.get(sig.tag)
            if not isinstance(start_value, (int, float)) or isinstance(start_value, bool):
                start_value = nominal_values.get(sig.tag, sig.after)
            values[sig.tag] = round(self.smooth_transition(float(start_value), sig.after, progress), 3)
        for st in self.spec.statuses:
            # Equipment is restored (and trips reset) only once the recovery is complete.
            values[st.tag] = st.after if progress >= 1.0 else self._last_values.get(st.tag, st.incident)
        values.update(self._alarm_bits(values, {}))
        for st in self.spec.statuses:
            if st.kind == "fault":
                values[st.tag] = st.after if progress >= 1.0 else True
        return values

    def recovery_complete(self, recovery_elapsed: float) -> bool:
        return recovery_elapsed >= catalog.RECOVERY_DURATION_S

    def get_ground_truth(self) -> Dict[str, Any]:
        return {**super().get_ground_truth(), **catalog.scenario_summary(self.spec)}


def factory(scenario_id: str):
    def _make() -> CatalogScenario:
        return CatalogScenario(scenario_id)
    _make.__name__ = f"CatalogScenario[{scenario_id}]"
    return _make
