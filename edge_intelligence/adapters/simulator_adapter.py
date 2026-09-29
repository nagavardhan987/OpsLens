"""
OpsLens - SimulatorAdapter

Wraps the existing SyntheticDataGenerator and TagStream.
This is the adapter used for demo and testing.
Keeps all Pump-02 scenarios working without modification.
"""
import sys
import asyncio
import logging
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .base import BaseAdapter
from models import TagReading
from database import Database
from stream import TagStream
from generator import SyntheticDataGenerator

logger = logging.getLogger("opslens.adapter.simulator")


class SimulatorAdapter(BaseAdapter):
    """
    Synthetic telemetry adapter for demo and testing.
    Generates realistic industrial sensor data for the Pump-02 scenario.
    READ-ONLY: Cannot write to any equipment.
    """

    def __init__(self, db: Optional[Database] = None, sample_interval: float = 2.0):
        self.db = db or Database()
        self.stream = TagStream(db_path=self.db.db_path)
        self.generator = SyntheticDataGenerator(db=self.db, sample_interval=sample_interval)
        self._connected = False

    async def connect(self) -> bool:
        self._connected = True
        logger.info("[SimulatorAdapter] Connected (synthetic telemetry)")
        return True

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("[SimulatorAdapter] Disconnected")

    async def stream_readings(self) -> AsyncGenerator[TagReading, None]:
        async for reading in self.stream.subscribe():
            yield reading

    async def run_scenario(self, scenario_id: str, speed: float = 10.0):
        """Run a named scenario (e.g. valve_restriction) through the generator."""
        async for reading in self.generator.run_scenario_async(scenario_id, speed_multiplier=speed):
            yield reading

    def status(self) -> Dict[str, Any]:
        return {
            "adapter": "simulator",
            "connected": self._connected,
            "source": "SyntheticDataGenerator",
            "note": "Generates realistic Pump-02 / Compressor-01 telemetry for demo",
        }

    @property
    def adapter_type(self) -> str:
        return "simulator"
