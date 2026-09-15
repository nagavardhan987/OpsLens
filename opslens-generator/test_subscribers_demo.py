"""
OpsLens Component 2 Verification Script: Multi-Subscriber Pub-Sub & Window Query

Demonstrates:
1. Two independent subscribers running concurrently on TagStream.
2. Subscriber 1 (Prioritization Engine) subscribes at t=0s.
3. Subscriber 2 (Live Dashboard) subscribes late at t=16s (staggered join).
4. Zero duplicates, zero dropped rows, and independent consumption.
5. get_window() lookback query across the baseline -> incident transition boundary.

Usage:
    python test_subscribers_demo.py --speed 10.0
"""

import sys
import asyncio
import argparse
from datetime import datetime, timezone, timedelta
from typing import List

from models import TagReading
from database import Database
from generator import SyntheticDataGenerator
from stream import TagStream
from registry_loader import get_registry_loader


def print_banner():
    print("=" * 82)
    print(" OpsLens Component 2: Ingestion & Pub-Sub Decoupling Verification")
    print("=" * 82)


async def run_pubsub_demo(speed_multiplier: float = 10.0):
    print_banner()
    db = Database()
    print("Clearing SQLite tag_readings table for fresh scenario run...")
    db.clear_readings()

    loader = get_registry_loader()
    print(f"Registry loaded: {len(loader.all_tags())} tags across equipment units: {loader.all_equipment()}")

    start_sim_time = datetime(2026, 9, 11, 14, 30, 0, tzinfo=timezone.utc)
    generator = SyntheticDataGenerator(
        db=db,
        sample_interval=2.0,
        start_time=start_sim_time
    )
    stream = TagStream(db_path=db.db_path, poll_interval_seconds=0.05)

    sub1_readings: List[TagReading] = []
    sub2_readings: List[TagReading] = []

    scenario_finished = asyncio.Event()

    # Subscriber 1: Prioritization Engine (subscribes at t=0s)
    async def sub1_worker():
        print("[SUB-1 Prioritization] Connected. Listening from t=0s...")
        async for reading in stream.subscribe(from_latest=True):
            sub1_readings.append(reading)
            if reading.tag in ["VLV-04-POS", "PIT-02-PRS", "ALM-P02-HP"]:
                print(
                    f"  [SUB-1 Pri-Engine] {reading.timestamp[11:19]} | "
                    f"{reading.tag:<11} = {str(reading.value):<6} {reading.unit:<5} "
                    f"({reading.equipment_id})"
                )

    # Subscriber 2: Live HMI Dashboard (staggered connect at t=16s / step 8)
    async def sub2_worker():
        delay = 16.0 / speed_multiplier
        await asyncio.sleep(delay)

        print("\n" + "-" * 82)
        print(f"[SUB-2 Dashboard] Connected LATE at elapsed ~16s (delayed join). Listening for NEW rows...")
        print("-" * 82)

        async for reading in stream.subscribe(from_latest=True):
            sub2_readings.append(reading)
            if reading.tag in ["VLV-04-POS", "FIT-02-FLW", "ALM-P02-HP"]:
                print(
                    f"  [SUB-2 Dashboard ] {reading.timestamp[11:19]} | "
                    f"{reading.tag:<11} = {str(reading.value):<6} {reading.unit:<5} "
                    f"({reading.equipment_id})"
                )

    # Generator runner: runs Scenario A (Valve Restriction Cascade)
    async def generator_worker():
        print(f"\n[GENERATOR] Starting Scenario A ('valve_restriction_cascade') at {speed_multiplier}x speed...")
        async for _ in generator.run_scenario_async("valve_restriction_cascade", speed_multiplier=speed_multiplier):
            pass
        print("[GENERATOR] Scenario A execution complete.")

    # Launch concurrent tasks
    s1_task = asyncio.create_task(sub1_worker())
    s2_task = asyncio.create_task(sub2_worker())
    
    # Allow subscriber 1 to register first
    await asyncio.sleep(0.05)
    gen_task = asyncio.create_task(generator_worker())

    await gen_task

    # Wait until all committed DB rows are delivered to subscriber 1
    total_db_rows = db.get_count()
    timeout = asyncio.get_event_loop().time() + 3.0
    while len(sub1_readings) < total_db_rows and asyncio.get_event_loop().time() < timeout:
        await asyncio.sleep(0.05)

    # Allow subscriber 2 to catch up on its queue
    await asyncio.sleep(0.2)

    s1_task.cancel()
    s2_task.cancel()
    await stream.close()

    # -------------------------------------------------------------------------
    # Verification & Ground Truth Audit
    # -------------------------------------------------------------------------
    total_db_rows = db.get_count()
    print("\n" + "=" * 82)
    print(" VERIFICATION AUDIT RESULTS")
    print("=" * 82)
    print(f"Total Rows Committed to SQLite `tag_readings`: {total_db_rows}")
    print(f"Total Rows Received by Subscriber 1 (t=0s):     {len(sub1_readings)}")
    print(f"Total Rows Received by Subscriber 2 (t=16s):    {len(sub2_readings)}")

    # Duplicates check
    s1_keys = [(r.tag, r.timestamp) for r in sub1_readings]
    s2_keys = [(r.tag, r.timestamp) for r in sub2_readings]
    s1_dup_count = len(s1_keys) - len(set(s1_keys))
    s2_dup_count = len(s2_keys) - len(set(s2_keys))

    print(f"Subscriber 1 Duplicate Rows:                    {s1_dup_count}")
    print(f"Subscriber 2 Duplicate Rows:                    {s2_dup_count}")

    # Independence check: Subscriber 2 must have fewer rows than Subscriber 1 because it joined late
    assert len(sub1_readings) == total_db_rows, (
        f"Subscriber 1 missed rows! Received {len(sub1_readings)} vs DB {total_db_rows}"
    )
    assert len(sub2_readings) < len(sub1_readings), (
        f"Subscriber 2 should have joined late and received fewer rows than Subscriber 1!"
    )
    assert s1_dup_count == 0, "Subscriber 1 received duplicate readings!"
    assert s2_dup_count == 0, "Subscriber 2 received duplicate readings!"

    print("\n[PUB-SUB SUCCESS] Both subscribers consumed independently without drops or duplicates.")

    # -------------------------------------------------------------------------
    # Lookback Query get_window() Verification
    # -------------------------------------------------------------------------
    print("\n" + "=" * 82)
    print(" LOOKBACK WINDOW QUERY VERIFICATION (get_window)")
    print("=" * 82)
    # Query window spanning nominal -> incident boundary (14:30:10 to 14:30:36)
    window_start = start_sim_time + timedelta(seconds=10)
    window_end = start_sim_time + timedelta(seconds=36)
    print(f"Querying Pump-02 window from {window_start.isoformat()} to {window_end.isoformat()}...")

    window_results = await stream.get_window(
        equipment_id="Pump-02",
        start=window_start,
        end=window_end,
        tags=["VLV-04-POS", "FIT-02-FLW", "PIT-02-PRS"]
    )

    print(f"Total readings returned for window: {len(window_results)}\n")
    print(f"{'Timestamp':<28} | {'Tag':<12} | {'Value':<10} | {'Unit':<8} | {'Equipment'}")
    print("-" * 75)
    for r in window_results[:12]:  # Print first 12 for clean inspection
        print(f"{r.timestamp:<28} | {r.tag:<12} | {str(r.value):<10} | {r.unit:<8} | {r.equipment_id}")
    print(f"... [{len(window_results) - 12} additional rows in transition window]")

    # Verify boundary transition in lookback window
    vlv_window = [r for r in window_results if r.tag == "VLV-04-POS"]
    vlv_start_val = float(vlv_window[0].value)
    vlv_end_val = float(vlv_window[-1].value)

    print("-" * 75)
    print(f"Boundary verification: VLV-04-POS at start of window: {vlv_start_val}%")
    print(f"Boundary verification: VLV-04-POS at end of window:   {vlv_end_val}%")
    assert vlv_start_val > 70.0, f"Expected nominal valve start, got {vlv_start_val}"
    assert vlv_end_val == 43.0, f"Expected throttled valve end, got {vlv_end_val}"

    print("\n[LOOKBACK SUCCESS] get_window() accurately retrieved transition boundary data.")
    print("=" * 82)


def main():
    parser = argparse.ArgumentParser(description="OpsLens Component 2 Multi-Subscriber Verification")
    parser.add_argument("--speed", type=float, default=10.0, help="Simulation speed multiplier (default: 10.0)")
    args = parser.parse_args()

    asyncio.run(run_pubsub_demo(speed_multiplier=args.speed))


if __name__ == "__main__":
    main()
