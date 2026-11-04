"""
OpsLens - Alarm Lifecycle Manager (Phase 3)

Three-layer alarm deduplication and lifecycle state machine:

Layer 1: Exact event deduplication via stable SHA-256 fingerprint.
         - Increments repeat_count and last_seen_timestamp on repeats.
         - Preserves first_seen_timestamp and original alarm identity.

Layer 2: Lifecycle state machine.
         - States: NEW → ACTIVE → ACKNOWLEDGED / CLEARED → RECURRING
         - Acknowledgment does NOT automatically clear alarm.
         - Cleared alarms that re-trigger become RECURRING.

Layer 3: Causal incident grouping with equipment-specific windows.
         - Pump-02: 60s, Compressor-01: 90s, Tank-01: 120s, default: 90s
         - Keeps causally unrelated simultaneous alarms separate.
         - Never suppresses a new independent URGENT alarm.
         - All individual alarms preserved as IndividualAlarmRecord.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from models import IndividualAlarmRecord, current_iso_utc

logger = logging.getLogger("opslens.alarm_lifecycle")

# Equipment-specific correlation windows (seconds)
EQUIPMENT_WINDOWS: Dict[str, float] = {
    "Pump-02": 60.0,
    "Compressor-01": 90.0,
    "Tank-01": 120.0,
}
DEFAULT_WINDOW = 90.0


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def compute_alarm_fingerprint(
    source_system: str,
    equipment_id: str,
    tag: str,
    alarm_type: str,
    state_transition: str,
) -> str:
    """
    Compute a stable SHA-256 fingerprint for exact event deduplication.
    Distinct tags or distinct condition transitions are never merged.
    """
    payload = f"{source_system}|{equipment_id}|{tag}|{alarm_type}|{state_transition}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class AlarmLifecycleManager:
    """
    Manages the full alarm lifecycle through three deduplication layers.
    Thread-safe for single-threaded asyncio event loop use.
    """

    def __init__(self) -> None:
        # Layer 1: fingerprint → IndividualAlarmRecord (active/recent)
        self._active_fingerprints: Dict[str, IndividualAlarmRecord] = {}
        # Layer 2: event_id → lifecycle state
        self._lifecycle_states: Dict[str, str] = {}
        # Layer 3: equipment_id → list of (fingerprint, timestamp)
        self._equipment_groups: Dict[str, List[Tuple[str, datetime]]] = {}
        # Fingerprints whose source input returned to normal (False) after
        # activation. The next True reading is a real re-activation.
        self._returned_to_normal: Set[str] = set()

    def mark_returned_to_normal(self, tag: str, timestamp: Optional[str] = None) -> int:
        """Record that an alarm input returned to normal. Does not clear or
        acknowledge anything; the next activation counts as a repeat.

        A FALSE sample older than the latest TRUE sample (out-of-order delivery,
        e.g. the same readings arriving via the API and the SQLite stream) is
        not a return to normal and is ignored."""
        count = 0
        when = _parse_iso(timestamp) if timestamp else None
        for fingerprint, record in self._active_fingerprints.items():
            if when is not None:
                last_seen = _parse_iso(record.last_seen_timestamp)
                if last_seen is not None and when <= last_seen:
                    continue
            if record.tag == tag and fingerprint not in self._returned_to_normal:
                self._returned_to_normal.add(fingerprint)
                count += 1
        return count

    # -------------------------------------------------------------------------
    # Layer 1 — Exact deduplication
    # -------------------------------------------------------------------------

    def check_exact_duplicate(
        self,
        source_system: str,
        equipment_id: str,
        tag: str,
        alarm_type: str,
        state_transition: str,
        value,
        threshold: Optional[float] = None,
        source_priority: Optional[str] = None,
        now: Optional[datetime] = None,
        count_repeat: bool = True,
    ) -> Tuple[bool, IndividualAlarmRecord]:
        """
        Check whether this alarm is an exact repeat of a known active alarm.

        Returns (is_duplicate: bool, record: IndividualAlarmRecord).
        - If duplicate: updates last_seen on the existing record. repeat_count is
          incremented only for a genuine re-annunciation: the alarm input
          returned to normal and became active again, or the source explicitly
          re-sent the notification (count_repeat=True). Periodic samples of an
          alarm that simply stays active are NOT repeats; callers feeding polled
          samples pass count_repeat=False.
        - If new: creates a new IndividualAlarmRecord and registers it.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        fingerprint = compute_alarm_fingerprint(
            source_system, equipment_id, tag, alarm_type, state_transition
        )

        if fingerprint in self._active_fingerprints:
            existing = self._active_fingerprints[fingerprint]
            reactivated = fingerprint in self._returned_to_normal
            if reactivated or count_repeat:
                existing.repeat_count += 1
                self._returned_to_normal.discard(fingerprint)
            existing.last_seen_timestamp = now.isoformat().replace("+00:00", "Z")
            # Update value (process value may have changed even if alarm condition same)
            existing.value = value
            logger.debug(
                f"[Lifecycle] Exact duplicate: {tag} fingerprint={fingerprint[:8]} "
                f"repeat_count={existing.repeat_count}"
            )
            return True, existing

        # New alarm
        now_str = now.isoformat().replace("+00:00", "Z")
        initial_state = "ACTIVE" if state_transition in ("ACTIVE", "HIGH", "TRIP") else "NEW"
        record = IndividualAlarmRecord(
            tag=tag,
            equipment_id=equipment_id,
            alarm_type=alarm_type,
            value=value,
            threshold=threshold,
            source_priority=source_priority,
            lifecycle_state=initial_state,
            repeat_count=1,
            first_seen_timestamp=now_str,
            last_seen_timestamp=now_str,
            fingerprint=fingerprint,
        )
        self._active_fingerprints[fingerprint] = record
        return False, record

    def forget_fingerprint(self, fingerprint: str) -> None:
        """Drop an active fingerprint so the next occurrence starts a new record.
        Used when a recurrence belongs to a different incident than the record."""
        self._active_fingerprints.pop(fingerprint, None)
        self._returned_to_normal.discard(fingerprint)

    def register_fingerprint(self, fingerprint: str, record: IndividualAlarmRecord) -> None:
        """Register a fingerprint manually (for records created externally)."""
        self._active_fingerprints[fingerprint] = record

    def get_record(self, fingerprint: str) -> Optional[IndividualAlarmRecord]:
        """Retrieve an active record by fingerprint."""
        return self._active_fingerprints.get(fingerprint)

    # -------------------------------------------------------------------------
    # Layer 2 — Lifecycle state machine
    # -------------------------------------------------------------------------

    def transition_state(
        self,
        event_id: str,
        action: str,
        fingerprint: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> str:
        """
        Transition the lifecycle state of an alarm/event.

        action: "activate" | "acknowledge" | "clear" | "reactivate"

        Returns the new state string.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        current = self._lifecycle_states.get(event_id, "NEW")

        if action == "activate":
            if current in ("NEW", ""):
                new_state = "ACTIVE"
            elif current == "CLEARED":
                new_state = "RECURRING"
            else:
                new_state = current  # already ACTIVE / ACKNOWLEDGED

        elif action == "acknowledge":
            # ACK ≠ clear. Alarm may still be active.
            if current in ("NEW", "ACTIVE", "RECURRING"):
                new_state = "ACKNOWLEDGED"
            else:
                new_state = current

        elif action == "clear":
            new_state = "CLEARED"
            # Remove from active fingerprints
            if fingerprint and fingerprint in self._active_fingerprints:
                record = self._active_fingerprints[fingerprint]
                record.lifecycle_state = "CLEARED"
                record.cleared_timestamp = now.isoformat().replace("+00:00", "Z")
                del self._active_fingerprints[fingerprint]

        elif action == "reactivate":
            # Alarm cleared but now seen again — RECURRING
            new_state = "RECURRING"

        else:
            new_state = current

        self._lifecycle_states[event_id] = new_state
        if fingerprint and fingerprint in self._active_fingerprints:
            self._active_fingerprints[fingerprint].lifecycle_state = new_state
            if action == "acknowledge":
                now_str = now.isoformat().replace("+00:00", "Z")
                self._active_fingerprints[fingerprint].acknowledged_timestamp = now_str

        logger.debug(
            f"[Lifecycle] event={event_id} {current} --{action}--> {new_state}"
        )
        return new_state

    def get_state(self, event_id: str) -> str:
        """Return current lifecycle state for an event."""
        return self._lifecycle_states.get(event_id, "NEW")

    # -------------------------------------------------------------------------
    # Layer 3 — Causal incident grouping
    # -------------------------------------------------------------------------

    def get_correlation_window(self, equipment_id: str) -> float:
        """Return equipment-specific correlation window in seconds."""
        return EQUIPMENT_WINDOWS.get(equipment_id, DEFAULT_WINDOW)

    def find_causal_group(
        self,
        equipment_id: str,
        fingerprint: str,
        alarm_timestamp: datetime,
    ) -> Optional[str]:
        """
        Search for an existing causal group for this equipment within the
        correlation window. Returns the group key (first fingerprint in group)
        or None if no matching group found.

        Independent simultaneous alarms on different equipment are NOT grouped.
        """
        window = self.get_correlation_window(equipment_id)
        group_key = equipment_id  # group by equipment

        if group_key not in self._equipment_groups:
            return None

        # Check if any alarm in the group is within the window
        group = self._equipment_groups[group_key]
        for fp, ts in group:
            age = abs((alarm_timestamp - ts).total_seconds())
            if age <= window:
                return group_key

        return None

    def add_to_causal_group(
        self,
        equipment_id: str,
        fingerprint: str,
        alarm_timestamp: datetime,
    ) -> str:
        """
        Add an alarm to a causal group for its equipment.
        Returns the group key.
        """
        group_key = equipment_id
        if group_key not in self._equipment_groups:
            self._equipment_groups[group_key] = []
        self._equipment_groups[group_key].append((fingerprint, alarm_timestamp))
        return group_key

    def get_group_alarms(self, equipment_id: str) -> List[IndividualAlarmRecord]:
        """Get all active individual alarm records for an equipment group."""
        group = self._equipment_groups.get(equipment_id, [])
        records = []
        for fp, _ in group:
            record = self._active_fingerprints.get(fp)
            if record:
                records.append(record)
        return records

    def purge_expired_groups(self, now: Optional[datetime] = None) -> None:
        """Remove stale group entries beyond 3x their correlation window (cleanup)."""
        if now is None:
            now = datetime.now(timezone.utc)
        for equip_id in list(self._equipment_groups.keys()):
            window = self.get_correlation_window(equip_id) * 3
            self._equipment_groups[equip_id] = [
                (fp, ts)
                for fp, ts in self._equipment_groups[equip_id]
                if (now - ts).total_seconds() <= window
            ]
            if not self._equipment_groups[equip_id]:
                del self._equipment_groups[equip_id]

    def clear_all(self) -> None:
        """Reset all lifecycle state (test/reinit use only)."""
        self._active_fingerprints.clear()
        self._lifecycle_states.clear()
        self._equipment_groups.clear()
        self._returned_to_normal.clear()


# Singleton instance for the running server process
_lifecycle_manager: Optional[AlarmLifecycleManager] = None


def get_lifecycle_manager() -> AlarmLifecycleManager:
    """Return the process-level singleton AlarmLifecycleManager."""
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = AlarmLifecycleManager()
    return _lifecycle_manager
