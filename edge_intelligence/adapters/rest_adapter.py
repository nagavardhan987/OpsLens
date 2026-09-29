"""
OpsLens - REST Polling Adapter

Polls an external REST endpoint for telemetry data.
Maps JSON response to TagReading model.
Configuration:
  REST_TELEMETRY_URL  e.g. http://scada-server:8080/api/tags
  REST_POLL_INTERVAL  seconds between polls (default 2.0)
  REST_AUTH_TOKEN     Bearer token if required

SAFETY: READ-ONLY. Only polls for data, never writes.
"""
import os
import logging
import asyncio
from typing import AsyncGenerator, Dict, Any, List
from .base import BaseAdapter

logger = logging.getLogger("opslens.adapter.rest")

REST_URL = os.environ.get("REST_TELEMETRY_URL", "http://localhost:9090/api/tags")
REST_POLL_INTERVAL = float(os.environ.get("REST_POLL_INTERVAL", "2.0"))
REST_AUTH_TOKEN = os.environ.get("REST_AUTH_TOKEN", None)


class RESTAdapter(BaseAdapter):
    """
    REST polling adapter. Fetches telemetry from any HTTP JSON endpoint.
    READ-ONLY: Never POSTs control commands.
    """

    def __init__(self):
        self._connected = False
        self._session = None

    async def connect(self) -> bool:
        try:
            import httpx
            self._session = httpx.AsyncClient(
                headers={"Authorization": f"Bearer {REST_AUTH_TOKEN}"} if REST_AUTH_TOKEN else {},
                timeout=5.0
            )
            self._connected = True
            logger.info(f"[RESTAdapter] Configured to poll {REST_URL}")
            return True
        except ImportError:
            logger.warning("[RESTAdapter] httpx not installed.")
            return False

    async def disconnect(self) -> None:
        if self._session:
            await self._session.aclose()
        self._connected = False

    async def stream_readings(self) -> AsyncGenerator:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from models import TagReading, current_iso_utc
        from tag_registry import TAG_REGISTRY

        while self._connected:
            try:
                resp = await self._session.get(REST_URL)
                if resp.status_code == 200:
                    readings: List[Dict] = resp.json()
                    if isinstance(readings, dict):
                        readings = readings.get("readings", readings.get("tags", [readings]))
                    for item in readings:
                        tag = item.get("tag") or item.get("tag_id")
                        value = item.get("value")
                        if tag and value is not None:
                            reg = TAG_REGISTRY.get(tag)
                            yield TagReading(
                                tag=tag,
                                value=value,
                                timestamp=item.get("timestamp", current_iso_utc()),
                                unit=reg.unit if reg else item.get("unit", ""),
                                equipment_id=reg.equipment_id if reg else item.get("equipment_id", "UNKNOWN"),
                            )
            except Exception as e:
                logger.debug(f"[RESTAdapter] Poll error: {e}")
            await asyncio.sleep(REST_POLL_INTERVAL)

    def status(self) -> Dict[str, Any]:
        return {
            "adapter": "rest",
            "connected": self._connected,
            "endpoint": REST_URL,
            "poll_interval_s": REST_POLL_INTERVAL,
            "read_only": True,
        }

    @property
    def adapter_type(self) -> str:
        return "rest"
