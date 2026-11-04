"""
OpsLens - Base Scenario State Machine

Provides the abstract base class for all incident archetypes.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class BaseScenario(ABC):
    """
    Abstract state machine interface for an incident archetype.
    Calculates dynamic value deviations as a function of elapsed simulation time.
    """

    def __init__(
        self,
        scenario_id: str,
        name: str,
        description: str,
        duration_seconds: float,
        target_equipment: str,
        expected_correlations: List[str],
        expected_non_correlations: List[str],
    ):
        self.scenario_id = scenario_id
        self.name = name
        self.description = description
        self.duration_seconds = duration_seconds
        self.target_equipment = target_equipment
        self.expected_correlations = expected_correlations
        self.expected_non_correlations = expected_non_correlations

    @abstractmethod
    def get_tag_values(
        self,
        elapsed_seconds: float,
        nominal_values: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Compute overrides or modified tag values at the given elapsed time.
        Any tag not returned will use its nominal random walk baseline value.
        """
        pass

    def is_complete(self, elapsed_seconds: float) -> bool:
        """Check if scenario reached its configured duration."""
        return elapsed_seconds >= self.duration_seconds

    def get_ground_truth(self) -> Dict[str, Any]:
        """Return ground-truth metadata for downstream validation."""
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "description": self.description,
            "duration_seconds": self.duration_seconds,
            "target_equipment": self.target_equipment,
            "expected_correlations": list(self.expected_correlations),
            "expected_non_correlations": list(self.expected_non_correlations),
        }

    @staticmethod
    def smooth_transition(start_val: float, end_val: float, progress: float) -> float:
        """Smooth cubic Hermite interpolation between start_val and end_val for progress in [0, 1]."""
        p = max(0.0, min(1.0, progress))
        # Hermite smoothstep: 3*p^2 - 2*p^3
        smooth_p = p * p * (3.0 - 2.0 * p)
        return start_val + (end_val - start_val) * smooth_p
