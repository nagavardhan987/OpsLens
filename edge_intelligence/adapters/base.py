"""
OpsLens - BaseAdapter Abstract Interface

All telemetry source adapters (OPC UA, MQTT, REST, Simulator) must implement
this interface. The OpsLens Intelligence Core consumes only the common
TagReading model — it is completely HMI and protocol agnostic.

SAFETY: All adapters are READ-ONLY. No write operations to industrial equipment.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional, Dict, Any
from models import TagReading


class BaseAdapter(ABC):
    """Abstract telemetry source adapter."""

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to the telemetry source."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Cleanly disconnect."""
        ...

    @abstractmethod
    async def stream_readings(self) -> AsyncGenerator[TagReading, None]:
        """
        Async generator yielding TagReading objects from the source.
        Must normalize all data to the common TagReading model.
        SAFETY: Read-only. Must NEVER write to industrial equipment.
        """
        ...

    @abstractmethod
    def status(self) -> Dict[str, Any]:
        """Return adapter health and connection status."""
        ...

    @property
    @abstractmethod
    def adapter_type(self) -> str:
        """Return adapter type string: simulator | opcua | mqtt | rest"""
        ...
