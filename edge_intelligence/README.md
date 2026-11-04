# OpsLens Synthetic Telemetry Stream Generator

The continuous, real-time industrial telemetry generator foundation for **OpsLens** (Edge AI Copilot for Industrial HMI).

## Architecture & System Contract

All components adhere strictly to the OpsLens shared system contracts:
- `TagReading`: `{ "tag": str, "value": float|bool|str, "timestamp": ISO8601 str, "unit": str, "equipment_id": str }`
- `TagRegistryEntry`: `{ "tag": str, "equipment_id": str, "unit": str, "data_type": "float"|"bool"|"string", "baseline_min": float, "baseline_max": float, "trip_threshold": float|null, "severity_weight": float (0-1), "topology_upstream": [tag names this tag causally depends on] }`
- Shared SQLite write-through storage (`tag_readings` table with WAL mode and indices)
- Timestamps in ISO8601 UTC format.
- Percentages as signed floats (e.g., `-44.9`).

## Directory Structure

```
opslens-generator/
├── models.py                # Strict system contract Pydantic models
├── tag_registry.py          # 11 industrial tags across 3 units + DAG helpers
├── database.py              # Shared SQLite write-through engine with WAL mode
├── generator.py             # OU random walk noise + state machines + streaming
├── scenarios.md             # Ground-truth specifications for downstream engines
├── run_demo.py              # Interactive streaming CLI
├── scenarios/
│   ├── __init__.py          # Scenario registry & factory
│   ├── base.py              # Base state machine class
│   ├── valve_restriction.py # Archetype A: Valve restriction cascade (~75s)
│   ├── bearing_wear.py      # Archetype B: Compressor bearing wear (~80s)
│   ├── seal_leak.py         # Archetype C: Seal leak concurrent drop (~60s)
│   └── sensor_fault.py      # Archetype D: Sensor fault / false positive (~40s)
└── tests/
    ├── test_registry.py     # Registry schema & topology DAG tests
    └── test_generator.py    # Noise, state machines, isolation, timeline tests
```

## Running Tests

```powershell
python -m pytest tests/ -v
```

## Running the Live Demo

List scenarios:
```powershell
python run_demo.py --list
```

Run a specific scenario at 5x speed:
```powershell
python run_demo.py --scenario valve_restriction --speed 5.0
```

Run all 4 scenarios back-to-back:
```powershell
python run_demo.py --all --speed 20.0
```
