"""
OpsLens Synthetic Telemetry Generator - Live Demo CLI

Usage:
    python run_demo.py --list
    python run_demo.py --scenario valve_restriction --speed 5.0
    python run_demo.py --scenario bearing_wear --speed 10.0
    python run_demo.py --scenario seal_leak --speed 5.0
    python run_demo.py --scenario sensor_fault --speed 5.0
    python run_demo.py --all --speed 20.0
"""

import sys
import argparse
from datetime import datetime, timezone

from tag_registry import TAG_REGISTRY, get_all_equipment_ids
from database import Database
from generator import SyntheticDataGenerator
from scenarios import list_available_scenarios


def print_banner():
    print("=" * 78)
    print(" OpsLens Industrial Telemetry Stream Generator -- Edge Engine Foundation")
    print("=" * 78)


def print_scenarios():
    print_banner()
    print("Available Scenarios:")
    for sc in list_available_scenarios():
        print(f"\n  * ID:          {sc['scenario_id']}")
        print(f"    Name:        {sc['name']}")
        print(f"    Target:      {sc['target_equipment']}")
        print(f"    Duration:    {sc['duration_seconds']}s")
        print(f"    Description: {sc['description']}")
        print(f"    Correlated:  {', '.join(sc['expected_correlations'])}")
        print(f"    Unrelated:   {', '.join(sc['expected_non_correlations'])}")
    print("\n" + "=" * 78)


def run_cli():
    parser = argparse.ArgumentParser(description="OpsLens Synthetic Telemetry Stream Generator")
    parser.add_argument("--scenario", type=str, default="valve_restriction", help="Scenario ID to execute")
    parser.add_argument("--speed", type=float, default=5.0, help="Simulation speed multiplier (default 5.0)")
    parser.add_argument("--list", action="store_true", help="List registered scenarios and exit")
    parser.add_argument("--all", action="store_true", help="Run all 4 scenarios back-to-back")
    parser.add_argument("--reset-db", action="store_true", help="Clear sqlite database before starting")

    args = parser.parse_args()

    if args.list:
        print_scenarios()
        return

    print_banner()
    db = Database()
    if args.reset_db:
        print("Clearing SQLite tag_readings table...")
        db.clear_readings()

    generator = SyntheticDataGenerator(db=db, sample_interval=2.0)

    target_scenarios = (
        ["valve_restriction", "bearing_wear", "seal_leak", "sensor_fault"]
        if args.all
        else [args.scenario]
    )

    for sc_id in target_scenarios:
        print(f"\n[STREAM START] Running scenario: '{sc_id}' (Speed: {args.speed}x)")
        step_idx = 0
        current_step_readings = []

        for reading in generator.run_scenario(sc_id, speed_multiplier=args.speed):
            current_step_readings.append(reading)
            if len(current_step_readings) == len(TAG_REGISTRY):
                step_idx += 1
                # Format a compact status line for key tags
                lookup = {r.tag: r.value for r in current_step_readings}
                ts = current_step_readings[0].timestamp
                print(
                    f"[{ts}] Step {step_idx:02d} | "
                    f"VLV: {lookup.get('VLV-04-POS', 0.0):>5}% | "
                    f"FLW: {lookup.get('FIT-02-FLW', 0.0):>5} L/m | "
                    f"PRS: {lookup.get('PIT-02-PRS', 0.0):>4} bar | "
                    f"CUR: {lookup.get('MOT-02-CUR', 0.0):>4} A | "
                    f"HP_ALM: {lookup.get('ALM-P02-HP', False)} | "
                    f"CMP_VIB: {lookup.get('CMP-01-VIB', 0.0):>4} mm/s | "
                    f"VB_ALM: {lookup.get('ALM-C01-VB', False)}"
                )
                current_step_readings = []

        print(f"[STREAM END] Completed scenario '{sc_id}'. Total SQLite rows: {db.get_count()}")

    print("\n" + "=" * 78)
    print(f"SUCCESS: Continuous telemetry stream stored in: {db.db_path}")
    print("=" * 78)


if __name__ == "__main__":
    run_cli()
