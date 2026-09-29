"""
OpsLens - OPC UA Adapter

OpsLens acts as an OPC UA CLIENT (never server).
Connects to an OPC UA server (e.g. Schneider Electric EcoStruxure, Siemens, ABB).

SAFETY: READ-ONLY. All write/control operations are DISABLED.
The adapter may only read tag values from the OPC UA server.

Configuration via environment variables:
  OPCUA_ENDPOINT       e.g. opc.tcp://192.168.1.100:4840
  OPCUA_SECURITY_MODE  None | Sign | SignAndEncrypt (default: None)
  OPCUA_USERNAME       (optional)
  OPCUA_PASSWORD       (optional)
  OPCUA_NAMESPACE      e.g. 2
  OPCUA_TAG_MAPPING    path to JSON file mapping OpsLens tag names to OPC UA NodeIds

Tag mapping JSON format:
  {
    "VLV-04-POS":  "ns=2;s=Pump02.ValvePosition",
    "FIT-02-FLW":  "ns=2;s=Pump02.FlowRate",
    ...
  }

Gracefully disabled if asyncua is not installed.
"""
import os
import json
import logging
import asyncio
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, Optional
from datetime import datetime, timezone

from .base import BaseAdapter

logger = logging.getLogger("opslens.adapter.opcua")

OPCUA_ENDPOINT = os.environ.get("OPCUA_ENDPOINT", "opc.tcp://localhost:4840")
OPCUA_USERNAME = os.environ.get("OPCUA_USERNAME", None)
OPCUA_PASSWORD = os.environ.get("OPCUA_PASSWORD", None)
OPCUA_NAMESPACE = int(os.environ.get("OPCUA_NAMESPACE", "2"))
OPCUA_TAG_MAPPING_PATH = os.environ.get("OPCUA_TAG_MAPPING", None)
OPCUA_POLL_INTERVAL = float(os.environ.get("OPCUA_POLL_INTERVAL", "1.0"))

# Default tag mapping (override with OPCUA_TAG_MAPPING env file)
DEFAULT_TAG_MAPPING = {
    "VLV-04-POS": f"ns={OPCUA_NAMESPACE};s=Pump02.ValvePosition",
    "FIT-02-FLW": f"ns={OPCUA_NAMESPACE};s=Pump02.FlowRate",
    "MOT-02-CUR": f"ns={OPCUA_NAMESPACE};s=Pump02.MotorCurrent",
    "PIT-02-PRS": f"ns={OPCUA_NAMESPACE};s=Pump02.DischargePressure",
    "ALM-P02-HP": f"ns={OPCUA_NAMESPACE};s=Pump02.HighPressureAlarm",
}


class OPCUAAdapter(BaseAdapter):
    """
    OPC UA Client Adapter for OpsLens.
    Reads industrial tag data from any OPC UA server.
    NEVER writes to the OPC UA server or industrial equipment.
    """

    def __init__(self):
        self._client = None
        self._connected = False
        self._tag_mapping = self._load_tag_mapping()

    def _load_tag_mapping(self) -> Dict[str, str]:
        if OPCUA_TAG_MAPPING_PATH and Path(OPCUA_TAG_MAPPING_PATH).exists():
            with open(OPCUA_TAG_MAPPING_PATH, encoding="utf-8") as f:
                return json.load(f)
        return DEFAULT_TAG_MAPPING

    async def connect(self) -> bool:
        try:
            from asyncua import Client
            self._client = Client(url=OPCUA_ENDPOINT)
            if OPCUA_USERNAME:
                self._client.set_user(OPCUA_USERNAME)
                self._client.set_password(OPCUA_PASSWORD or "")
            await self._client.connect()
            self._connected = True
            logger.info(f"[OPCUAAdapter] Connected to {OPCUA_ENDPOINT}")
            return True
        except ImportError:
            logger.warning("[OPCUAAdapter] asyncua not installed. Run: pip install asyncua")
            return False
        except Exception as e:
            logger.error(f"[OPCUAAdapter] Connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        if self._client and self._connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._connected = False

    async def stream_readings(self):
        """
        Poll OPC UA server at OPCUA_POLL_INTERVAL seconds.
        Yields TagReading for each configured tag.
        READ-ONLY: Never writes to OPC UA nodes.
        """
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from models import TagReading, current_iso_utc
        from tag_registry import TAG_REGISTRY

        while self._connected:
            for tag_name, node_id in self._tag_mapping.items():
                try:
                    node = self._client.get_node(node_id)
                    value = await node.read_value()
                    reg = TAG_REGISTRY.get(tag_name)
                    yield TagReading(
                        tag=tag_name,
                        value=value,
                        timestamp=current_iso_utc(),
                        unit=reg.unit if reg else "",
                        equipment_id=reg.equipment_id if reg else "UNKNOWN",
                    )
                except Exception as e:
                    logger.debug(f"[OPCUAAdapter] Failed to read {tag_name}: {e}")
            await asyncio.sleep(OPCUA_POLL_INTERVAL)

    def status(self) -> Dict[str, Any]:
        return {
            "adapter": "opcua",
            "connected": self._connected,
            "endpoint": OPCUA_ENDPOINT,
            "tags_configured": len(self._tag_mapping),
            "read_only": True,
            "write_disabled": True,
        }

    @property
    def adapter_type(self) -> str:
        return "opcua"
