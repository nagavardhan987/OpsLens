"""
OpsLens - Operator Action Audit Layer (Component 9)

Records and audits human operator interventions against specific incident events.
Enforces:
1. Event Integrity: Rejects actions for non-existent events (prevents orphaned actions).
2. Cardinal Safety Constraint: Strictly prohibits machine/PLC commands via an explicit
   allowlist of human decision action types.
3. Event Isolation: Strict foreign-key association preventing action cross-contamination.
4. Open Event Tracking: Identifies events pending resolution or acknowledgment.
"""

import uuid
import logging
from typing import Optional, List, Set
from models import OperatorAction, current_iso_utc
from database import Database

logger = logging.getLogger("opslens.audit")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Cardinal Safety Constraint: ONLY human decision / workflow actions permitted.
# Any PLC / DCS / SCADA setpoint or machine actuation commands are strictly forbidden.
ALLOWED_ACTION_TYPES: Set[str] = {
    "ACKNOWLEDGE",
    "ACKNOWLEDGED",
    "VERIFY",
    "VERIFIED",
    "INSPECT",
    "INSPECTED",
    "RESOLVE",
    "RESOLVED",
    "ESCALATE",
    "ESCALATED",
    "INVESTIGATE",
    "INVESTIGATING",
    "ANNOTATE",
}


class OperatorActionAudit:
    """
    Audit manager for operator actions and interventions.
    """

    def __init__(self, db: Optional[Database] = None):
        self.db = db if db is not None else Database()

    def log_action(
        self,
        event_id: str,
        operator: str,
        action_type: str,
        notes: Optional[str] = None,
        timestamp: Optional[str] = None
    ) -> OperatorAction:
        """
        Record an operator intervention against a specific event.

        Raises:
            ValueError: If action_type is not in ALLOWED_ACTION_TYPES (safety violation),
                        or if event_id does not exist in event_stories (orphan violation).
        """
        if not action_type or not isinstance(action_type, str):
            raise ValueError("action_type must be a non-empty string.")

        normalized_action = action_type.strip().upper()

        # 1. Cardinal Safety Constraint: Allowlist enforcement
        if normalized_action not in ALLOWED_ACTION_TYPES:
            raise ValueError(
                f"Invalid action_type '{action_type}'. Cardinal Safety Constraint: "
                f"Machine/PLC actuator commands are strictly forbidden. "
                f"Permitted operator action types: {sorted(list(ALLOWED_ACTION_TYPES))}."
            )

        # 2. Event Integrity: Orphan action prevention
        if not self.db.event_story_exists(event_id):
            raise ValueError(
                f"Invalid event_id '{event_id}': Event does not exist in event_stories. "
                f"Orphaned operator actions are strictly prohibited."
            )

        # 3. Construct OperatorAction
        ts = timestamp if timestamp else current_iso_utc()
        action = OperatorAction(
            action_id=str(uuid.uuid4()),
            event_id=event_id,
            operator=operator.strip() if operator else "anonymous",
            action_type=normalized_action,
            timestamp=ts,
            notes=notes.strip() if notes else None
        )

        # 4. Persist to SQLite
        self.db.save_operator_action(action)
        logger.info(
            f"[Audit] Operator '{action.operator}' logged action '{action.action_type}' "
            f"for event {event_id} (action_id={action.action_id})"
        )
        return action

    def get_actions_for_event(self, event_id: str) -> List[OperatorAction]:
        """
        Retrieve all recorded operator actions for a specific event.
        Guarantees event-level isolation.
        """
        return self.db.get_operator_actions(event_id=event_id)

    def get_open_events(self) -> List[str]:
        """
        Retrieve all event_ids from event_stories that have not yet been
        ACKNOWLEDGED or RESOLVED.
        """
        return self.db.get_open_event_ids()


# -----------------------------------------------------------------------------
# Module-level convenience functions
# -----------------------------------------------------------------------------

_default_audit = OperatorActionAudit()


def log_action(
    event_id: str,
    operator: str,
    action_type: str,
    notes: Optional[str] = None,
    timestamp: Optional[str] = None,
    db: Optional[Database] = None
) -> OperatorAction:
    """Convenience function to log an operator action."""
    audit = OperatorActionAudit(db=db) if db else _default_audit
    return audit.log_action(event_id, operator, action_type, notes, timestamp)


def get_actions_for_event(event_id: str, db: Optional[Database] = None) -> List[OperatorAction]:
    """Convenience function to retrieve actions for a specific event."""
    audit = OperatorActionAudit(db=db) if db else _default_audit
    return audit.get_actions_for_event(event_id)


def get_open_events(db: Optional[Database] = None) -> List[str]:
    """Convenience function to retrieve open events."""
    audit = OperatorActionAudit(db=db) if db else _default_audit
    return audit.get_open_events()
