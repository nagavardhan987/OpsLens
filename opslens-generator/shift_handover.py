"""
OpsLens - Shift Handover Compiler (Component 10)

Compiles a comprehensive, traceable HandoverSummary across an operational shift window.
Performs real queries against SQLite tables (event_stories, candidate_events,
operator_actions) without hardcoding or state mutation.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from models import HandoverSummary, OperatorAction, EventStory, Evidence, SopMatch, Guidance
from database import Database

logger = logging.getLogger("opslens.handover")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class ShiftHandoverCompiler:
    """
    Compiles shift handover summaries from persistent SQLite stores.
    Guarantees pure read/query operations with zero state mutation.
    """

    def __init__(self, db: Optional[Database] = None):
        self.db = db if db is not None else Database()

    def compile_handover(
        self,
        shift_start: str,
        shift_end: str
    ) -> HandoverSummary:
        """
        Query all events and operator actions within [shift_start, shift_end].
        Computes open_events as events in the window lacking a RESOLVE action.

        Args:
            shift_start: ISO8601 UTC timestamp of shift beginning.
            shift_end: ISO8601 UTC timestamp of shift conclusion.

        Returns:
            HandoverSummary adhering to the shared system contract.
        """
        if not shift_start or not shift_end:
            raise ValueError("shift_start and shift_end must be non-empty ISO8601 strings.")

        if shift_start > shift_end:
            raise ValueError(
                f"Invalid shift window: shift_start ({shift_start}) is after shift_end ({shift_end})."
            )

        # 1. Query events in the shift window
        event_ids = self.db.get_events_in_window(shift_start, shift_end)

        # 2. Query operator actions in the shift window
        actions = self.db.get_actions_in_window(shift_start, shift_end)

        # 3. Determine open events: events in this window with no RESOLVE action
        open_event_ids: List[str] = []
        for eid in event_ids:
            if not self.db.is_event_resolved(eid):
                open_event_ids.append(eid)

        logger.info(
            f"[Handover] Compiled shift window [{shift_start} -> {shift_end}]: "
            f"{len(event_ids)} total events, {len(actions)} actions, {len(open_event_ids)} open events."
        )

        return HandoverSummary(
            shift_start=shift_start,
            shift_end=shift_end,
            events=event_ids,
            actions=actions,
            open_events=open_event_ids
        )

    def get_event_drilldown(self, event_id: str) -> Dict[str, Any]:
        """
        Drill down into an event listed in HandoverSummary to inspect its
        full timeline, root-cause evidence, SOP match, guidance, and actions.
        """
        stories = self.db.get_event_stories(event_id=event_id)
        evidence = self.db.get_evidence(event_id=event_id)
        sop_matches = self.db.get_sop_matches(event_id=event_id)
        guidance = self.db.get_guidance(event_id=event_id)
        actions = self.db.get_operator_actions(event_id=event_id)

        return {
            "event_id": event_id,
            "story": stories[0] if stories else None,
            "evidence": evidence[0] if evidence else None,
            "sop_match": sop_matches[0] if sop_matches else None,
            "guidance": guidance[0] if guidance else None,
            "actions": actions
        }


# -----------------------------------------------------------------------------
# Module-level convenience functions
# -----------------------------------------------------------------------------

_default_compiler = ShiftHandoverCompiler()


def compile_handover(
    shift_start: str,
    shift_end: str,
    db: Optional[Database] = None
) -> HandoverSummary:
    """Convenience function to compile a shift handover summary."""
    compiler = ShiftHandoverCompiler(db=db) if db else _default_compiler
    return compiler.compile_handover(shift_start, shift_end)


def get_event_drilldown(
    event_id: str,
    db: Optional[Database] = None
) -> Dict[str, Any]:
    """Convenience function to drill into event details."""
    compiler = ShiftHandoverCompiler(db=db) if db else _default_compiler
    return compiler.get_event_drilldown(event_id)
