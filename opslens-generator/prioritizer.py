"""
OpsLens - Prioritization Engine (Component 3)

Evaluates incoming TagReadings against dynamic TagRegistryEntry specifications.
Computes percentage deviations from dynamic baseline midpoints and flags
alarm-worthy breaches without using any hardcoded thresholds.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, Union
from models import TagReading, TagRegistryEntry
from registry_loader import RegistryLoader, get_registry_loader


@dataclass
class DeviationAssessment:
    """Evaluated telemetry reading with dynamic deviation and breach status."""
    reading: TagReading
    entry: TagRegistryEntry
    midpoint: float
    deviation_pct: float
    is_breach: bool
    is_trip_alarm: bool
    breach_reason: Optional[str] = None


class PrioritizationEngine:
    """
    Decoupled prioritization engine that evaluates incoming telemetry readings
    strictly using metadata from the TagRegistryEntry.
    """

    def __init__(
        self,
        registry_loader: Optional[RegistryLoader] = None,
        base_severity_tolerance_pct: float = 12.0
    ):
        self.loader = registry_loader if registry_loader is not None else get_registry_loader()
        self.base_tolerance_pct = base_severity_tolerance_pct

    def compute_midpoint(self, entry: TagRegistryEntry) -> float:
        """Calculate dynamic operating midpoint from baseline bounds."""
        if entry.data_type == "float":
            return (entry.baseline_min + entry.baseline_max) / 2.0
        return 0.0

    def compute_deviation_pct(self, reading: TagReading, entry: TagRegistryEntry) -> float:
        """
        Compute percentage deviation:
        deviation_pct = (value - baseline_midpoint) / baseline_midpoint * 100.0
        Signed float representation (e.g. -44.9).
        """
        if entry.data_type == "bool":
            # Boolean alarms: 100.0 if True/tripped, else 0.0
            is_active = (
                reading.value is True
                or reading.value in [1.0, 1, "true", "True"]
            )
            return 100.0 if is_active else 0.0

        if entry.data_type == "float":
            midpoint = self.compute_midpoint(entry)
            if abs(midpoint) < 1e-6:
                return 0.0
            val = float(reading.value)
            dev = ((val - midpoint) / midpoint) * 100.0
            return round(dev, 2)

        return 0.0

    def evaluate_reading(self, reading: TagReading) -> DeviationAssessment:
        """
        Assess an incoming TagReading for baseline deviation and alarm-worthiness.
        Checks:
        1. Explicit trip_threshold breach (directional).
        2. Dynamic deviation magnitude scaled by severity_weight.
        """
        entry = self.loader.get_tag(reading.tag)
        midpoint = self.compute_midpoint(entry)
        dev_pct = self.compute_deviation_pct(reading, entry)

        is_breach = False
        is_trip_alarm = False
        reason = None

        # ---------------------------------------------------------------------
        # 1. Check Explicit Trip Threshold
        # ---------------------------------------------------------------------
        if entry.data_type == "bool":
            is_true = reading.value is True or reading.value in [1.0, 1, "true", "True"]
            if is_true:
                is_breach = True
                is_trip_alarm = True
                reason = "Discrete trip alarm annunciated (True)"
        elif entry.trip_threshold is not None:
            num_val = float(reading.value)
            if entry.trip_threshold > entry.baseline_max:
                # High limit trip (e.g. PIT-02 > 6.5, CMP-01-VIB > 7.0)
                if num_val >= entry.trip_threshold:
                    is_breach = True
                    is_trip_alarm = True
                    reason = f"Exceeded high trip threshold ({num_val} >= {entry.trip_threshold})"
            elif entry.trip_threshold < entry.baseline_min:
                # Low limit trip (e.g. FIT-02 flow < 50.0)
                if num_val <= entry.trip_threshold:
                    is_breach = True
                    is_trip_alarm = True
                    reason = f"Breached low trip threshold ({num_val} <= {entry.trip_threshold})"

        # ---------------------------------------------------------------------
        # 2. Check Baseline Bounds Excursion & Severity-Scaled Deviation
        # ---------------------------------------------------------------------
        if not is_breach and entry.data_type == "float":
            num_val = float(reading.value)
            is_outside_baseline = (
                num_val < entry.baseline_min or num_val > entry.baseline_max
            )

            # Dynamic allowable threshold scaled inversely with severity_weight:
            # Higher severity weight -> lower allowable deviation tolerance
            # e.g., severity 0.90 -> threshold ~7.8%; severity 0.50 -> threshold ~10.5%
            scaled_tolerance = self.base_tolerance_pct * (1.2 - 0.4 * entry.severity_weight)

            if is_outside_baseline and abs(dev_pct) >= scaled_tolerance:
                is_breach = True
                is_trip_alarm = False
                direction = "high" if dev_pct > 0 else "low"
                reason = (
                    f"Baseline excursion ({num_val} outside [{entry.baseline_min}, {entry.baseline_max}], "
                    f"deviation: {dev_pct:+.1f}% exceeds tolerance {scaled_tolerance:.1f}%)"
                )

        return DeviationAssessment(
            reading=reading,
            entry=entry,
            midpoint=midpoint,
            deviation_pct=dev_pct,
            is_breach=is_breach,
            is_trip_alarm=is_trip_alarm,
            breach_reason=reason
        )
