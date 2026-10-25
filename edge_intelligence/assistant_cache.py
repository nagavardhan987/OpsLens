"""Short-lived cache for identical, versioned incident Q&A.

Live sensor state is part of the cache key, so a later reading cannot reuse an
older answer as if it described the current alarm.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any, Dict, Optional

_LOCK = threading.Lock()
_STORE: Dict[str, tuple[float, Dict[str, Any]]] = {}


def ttl_seconds() -> float:
    return float(os.environ.get("OPSLENS_ASSISTANT_CACHE_TTL", "120"))


def _now() -> float:
    return time.monotonic()


def context_fingerprint(event: Dict[str, Any], context: Optional[Dict[str, Any]]) -> str:
    context = context or {}
    readings = context.get("readings") or []
    last = readings[-1] if readings else {}
    payload = {
        "event_id": event.get("event_id"),
        "window": context.get("window"),
        "reading_count": len(readings),
        "last_reading": {
            "tag": last.get("tag"),
            "timestamp": last.get("timestamp_utc") or last.get("timestamp"),
            "value": last.get("value"),
        },
        "action_count": len(context.get("operator_actions") or []),
        "related_count": len(context.get("related_events") or []),
        "sop_id": (event.get("sop_match") or {}).get("sop_id"),
        "alarm_state": (context.get("selected_event") or {}).get("alarm_state"),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def cache_key(event_id: str, question: str, fingerprint: str, conversation_tail: str = "") -> str:
    material = f"{event_id}|{question.strip().lower()}|{fingerprint}|{conversation_tail}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def question_is_volatile(question: str) -> bool:
    text = question.lower()
    return any(token in text for token in (
        "today", "now", "current", "live", "happened", "earlier today", "this shift"
    ))


def get(key: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        item = _STORE.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < _now():
            _STORE.pop(key, None)
            return None
        return dict(value)


def put(key: str, value: Dict[str, Any]) -> None:
    with _LOCK:
        _STORE[key] = (_now() + ttl_seconds(), dict(value))


def invalidate_event(event_id: str) -> None:
    prefix_marker = event_id
    with _LOCK:
        # Keys are hashes, so drop everything; demo cache is small.
        _STORE.clear()
    _ = prefix_marker


def clear() -> None:
    with _LOCK:
        _STORE.clear()
