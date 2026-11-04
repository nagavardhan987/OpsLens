"""
OpsLens - Continuous Industrial Synthetic Data Generator

Generates realistic telemetry streams for industrial assets using:
1. Discretized Ornstein-Uhlenbeck mean-reverting random walk for nominal baseline noise.
2. Dynamic state machines for 4 incident archetypes.
3. Write-through persistence into SQLite table `tag_readings`.
4. Continuous, monotonically advancing timeline across back-to-back runs.
5. Both sync generator and async generator streaming interfaces.
"""

import time
import math
import random
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Generator, AsyncGenerator, Optional, List, Any, Union

from models import TagReading, to_iso_utc
from tag_registry import TAG_REGISTRY, TagRegistryEntry, get_all_tags
from database import Database, DEFAULT_DB_PATH
from scenarios import get_scenario, BaseScenario


class BaselineNoiseEngine:
    """
    Simulates continuous physical sensor readings with inertial memory using
    discretized Ornstein-Uhlenbeck (OU) mean-reverting stochastic process.
    """

    def __init__(self, registry: Dict[str, TagRegistryEntry], theta: float = 0.25):
        self.registry = registry
        self.theta = theta  # Mean-reversion speed
        self.values: Dict[str, float] = {}
        self.reset()

    def reset(self) -> None:
        """Initialize all continuous values to the exact baseline midpoint."""
        for tag, entry in self.registry.items():
            if entry.data_type == "float":
                # Start at midpoint
                midpoint = (entry.baseline_min + entry.baseline_max) / 2.0
                self.values[tag] = midpoint
            else:
                self.values[tag] = entry.baseline_min

    def step(self, dt: float = 2.0) -> Dict[str, float]:
        """
        Advance one step of the OU process:
        dx = theta * (mu - x) * dt + sigma * sqrt(dt) * N(0, 1)
        """
        for tag, entry in self.registry.items():
            if entry.data_type != "float":
                continue

            current_val = self.values.get(tag, (entry.baseline_min + entry.baseline_max) / 2.0)
            midpoint = (entry.baseline_min + entry.baseline_max) / 2.0
            span = entry.baseline_max - entry.baseline_min

            # Volatility tuned to ~8% of normal span per sample
            sigma = span * 0.08

            # Drift + diffusion
            drift = self.theta * (midpoint - current_val) * dt
            diffusion = sigma * math.sqrt(dt) * random.gauss(0.0, 1.0)
            next_val = current_val + drift + diffusion

            # Soft reflecting barrier at baseline bounds
            margin = span * 0.02
            min_bound = entry.baseline_min + margin
            max_bound = entry.baseline_max - margin

            if next_val < min_bound:
                next_val = min_bound + abs(min_bound - next_val) * 0.5
            elif next_val > max_bound:
                next_val = max_bound - abs(next_val - max_bound) * 0.5

            self.values[tag] = round(next_val, 2)

        return {tag: self.values[tag] for tag, entry in self.registry.items() if entry.data_type == "float"}


class SyntheticDataGenerator:
    """
    OpsLens Synthetic Telemetry Generator.
    Produces real-time TagReading objects and pushes them write-through to SQLite.
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        sample_interval: float = 2.0,
        start_time: Optional[datetime] = None
    ):
        self.db = db if db is not None else Database()
        self.sample_interval = sample_interval
        self.noise_engine = BaselineNoiseEngine(TAG_REGISTRY)

        # Timeline tracking
        if start_time is None:
            self.sim_clock = datetime.now(timezone.utc)
        else:
            self.sim_clock = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)

        self.current_scenario: Optional[BaseScenario] = None
        self.scenario_elapsed: float = 0.0

    def reset(self, clear_db: bool = True, start_time: Optional[datetime] = None) -> None:
        """
        Reset generator state back to nominal baseline.
        Optionally clears the SQLite table and restarts the timeline.
        """
        self.noise_engine.reset()
        self.current_scenario = None
        self.scenario_elapsed = 0.0

        if start_time is not None:
            self.sim_clock = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)

        if clear_db:
            self.db.clear_readings()

    def advance_step(self) -> List[TagReading]:
        """
        Compute one complete sample interval across all registered tags,
        apply active scenario state machine modifications, commit write-through
        to SQLite, and advance the simulation clock.
        """
        # 1. Compute baseline nominal noise
        nominal_values = self.noise_engine.step(dt=self.sample_interval)

        # 2. Query scenario state machine if active
        overrides: Dict[str, Any] = {}
        if self.current_scenario is not None:
            overrides = self.current_scenario.get_tag_values(
                self.scenario_elapsed,
                nominal_values
            )
            self.scenario_elapsed += self.sample_interval

        # 3. Build TagReading objects for all tags
        ts_str = to_iso_utc(self.sim_clock)
        readings: List[TagReading] = []

        for tag_name in get_all_tags():
            entry = TAG_REGISTRY[tag_name]

            if tag_name in overrides:
                val = overrides[tag_name]
            elif entry.data_type == "bool":
                val = False
            elif entry.data_type == "float":
                val = nominal_values.get(tag_name, (entry.baseline_min + entry.baseline_max) / 2.0)
            else:
                val = "NORMAL"

            reading = TagReading(
                tag=tag_name,
                value=val,
                timestamp=ts_str,
                unit=entry.unit,
                equipment_id=entry.equipment_id
            )
            readings.append(reading)

        # 4. Write-through to SQLite
        for r in readings:
            self.db.insert_reading(r)

        # 5. Advance clock by sample interval
        self.sim_clock += timedelta(seconds=self.sample_interval)

        return readings

    def run_scenario(
        self,
        scenario_id: str,
        speed_multiplier: float = 1.0,
        start_time: Optional[datetime] = None
    ) -> Generator[TagReading, None, None]:
        """
        Synchronous generator yielding TagReading items for the selected scenario.
        Write-through persistence to SQLite occurs on each sample step.

        :param scenario_id: One of 'valve_restriction', 'bearing_wear', 'seal_leak', 'sensor_fault'
        :param speed_multiplier: 1.0 = real-time, 10.0 = 10x speed, float('inf') = instant
        :param start_time: Optional starting anchor time (defaults to continuous self.sim_clock)
        """
        if start_time is not None:
            self.sim_clock = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)

        scenario = get_scenario(scenario_id)
        self.current_scenario = scenario
        self.scenario_elapsed = 0.0

        sleep_delay = 0.0
        if speed_multiplier > 0 and not math.isinf(speed_multiplier):
            sleep_delay = self.sample_interval / speed_multiplier

        while not scenario.is_complete(self.scenario_elapsed):
            step_readings = self.advance_step()
            for reading in step_readings:
                yield reading

            if sleep_delay > 0:
                time.sleep(sleep_delay)

        self.current_scenario = None

    async def run_scenario_async(
        self,
        scenario_id: str,
        speed_multiplier: float = 1.0,
        start_time: Optional[datetime] = None
    ) -> AsyncGenerator[TagReading, None]:
        """
        Asynchronous generator yielding TagReading items for in-process async loops.
        """
        if start_time is not None:
            self.sim_clock = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)

        scenario = get_scenario(scenario_id)
        self.current_scenario = scenario
        self.scenario_elapsed = 0.0

        sleep_delay = 0.0
        if speed_multiplier > 0 and not math.isinf(speed_multiplier):
            sleep_delay = self.sample_interval / speed_multiplier

        while not scenario.is_complete(self.scenario_elapsed):
            step_readings = self.advance_step()
            for reading in step_readings:
                yield reading

            if sleep_delay > 0:
                await asyncio.sleep(sleep_delay)

        self.current_scenario = None

    def stream_nominal(
        self,
        duration_seconds: float,
        speed_multiplier: float = 1.0
    ) -> Generator[TagReading, None, None]:
        """Stream nominal baseline noise for a specified duration."""
        self.current_scenario = None
        self.scenario_elapsed = 0.0
        elapsed = 0.0

        sleep_delay = 0.0
        if speed_multiplier > 0 and not math.isinf(speed_multiplier):
            sleep_delay = self.sample_interval / speed_multiplier

        while elapsed < duration_seconds:
            step_readings = self.advance_step()
            for reading in step_readings:
                yield reading
            elapsed += self.sample_interval

            if sleep_delay > 0:
                time.sleep(sleep_delay)
