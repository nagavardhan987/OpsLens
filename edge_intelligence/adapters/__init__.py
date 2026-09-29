"""OpsLens Adapters package — HMI-agnostic telemetry ingestion layer."""
from .base import BaseAdapter
from .simulator_adapter import SimulatorAdapter

__all__ = ["BaseAdapter", "SimulatorAdapter"]
