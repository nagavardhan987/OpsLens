"""Interpret configured alarm priority without changing the source priority."""
from typing import Optional, Dict, Any


class AlarmPriorityInterpreter:
    """Pass through HMI priority and attach a non-ranking context explanation.

    OpsLens has no authority or plant-specific policy for reordering approved
    alarm priorities. Context is informational only and never changes the
    configured source severity.
    """

    @staticmethod
    def interpret(source_severity: Optional[str], related_signal_count: int = 0) -> Dict[str, Any]:
        source = str(source_severity).strip() if source_severity is not None else ""
        source = source or "not supplied"
        context = (f"{related_signal_count} related signal deviations observed"
                   if related_signal_count > 0 else "No related signal deviations supplied")
        return {
            "source_severity": source,
            "display_priority": source,
            "priority_basis": "configured source priority" if source != "not supplied" else "not supplied by source",
            "context": context,
            "priority_overridden": False,
        }
