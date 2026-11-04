"""Measure OpsLens AI latency: old assistant path vs new streamed diagnosis.

Two modes:

  python tools/benchmark_ai.py live [--api http://127.0.0.1:8001] [--scenarios all]
      Needs the backend running with OPSLENS_LLM_PROVIDER=ollama and Ollama
      serving qwen2.5:3b. For each scenario it starts the run, waits for the
      incident, then times:
        * BEFORE  POST /api/assistant/ask  "Why did this alarm happen?"
                  (non-streamed: the operator sees nothing until it finishes)
        * AFTER   GET  /api/events/{id}/diagnosis/stream
                  (time to first token, time to complete, cached repeat)
      Results are printed and written to benchmark_results.json.

  python tools/benchmark_ai.py capture
      No model needed. Runs each scenario in-process against a fake Ollama that
      records the requests, and reports how many model calls each path makes,
      prompt size (characters, ~tokens) and generation budget. This is what
      can be measured without the real model; it is NOT a latency figure.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

QUESTION = "Why did this alarm happen?"


# ------------------------------------------------------------------ live mode

def live(api: str, scenarios: list[str], speed: float) -> None:
    import requests

    out = []
    health = requests.get(f"{api}/api/copilot/ollama", timeout=10).json()
    print(f"Ollama: reachable={health.get('reachable')} model={health.get('model')} "
          f"installed={health.get('model_installed')} selected={health.get('ollama_selected')}")
    if not health.get("ollama_selected"):
        print("WARNING: backend is not using Ollama (set OPSLENS_LLM_PROVIDER=ollama). Results will be fallback timings.")
    for sid in scenarios:
        r = requests.post(f"{api}/api/scenarios/run", json={"scenario_id": sid, "speed_multiplier": speed}, timeout=10)
        if r.status_code != 200:
            print(sid, "could not start:", r.text)
            continue
        status = {}
        for _ in range(600):
            status = requests.get(f"{api}/api/scenarios/status", timeout=10).json()
            if status.get("status") not in ("running",):
                break
            time.sleep(0.5)
        eid = status.get("event_id")
        if not eid:
            print(sid, "no incident:", status.get("status"))
            continue

        t0 = time.perf_counter()
        ask = requests.post(f"{api}/api/assistant/ask", json={"event_id": eid, "question": QUESTION}, timeout=300)
        before_total = (time.perf_counter() - t0) * 1000
        ask_json = ask.json() if ask.ok else {}

        def stream_once():
            t = time.perf_counter()
            first = None
            done = {}
            with requests.get(f"{api}/api/events/{eid}/diagnosis/stream", stream=True, timeout=300) as resp:
                event = None
                for line in resp.iter_lines(decode_unicode=True):
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: "):
                        if event == "token" and first is None:
                            first = (time.perf_counter() - t) * 1000
                        if event == "done":
                            done = json.loads(line[6:])
            return first, (time.perf_counter() - t) * 1000, done

        ttft, total, done = stream_once()
        _, cached_total, _ = stream_once()
        row = {
            "scenario": sid, "event_id": eid,
            "before_assistant_ask_ms": round(before_total, 0),
            "before_llm_used": ask_json.get("llm_used"), "before_fallback_used": ask_json.get("fallback_used"),
            "after_time_to_first_token_ms": round(ttft, 0) if ttft else None,
            "after_total_ms": round(total, 0), "after_cached_ms": round(cached_total, 0),
            "after_engine": done.get("engine"), "after_fallback_reason": done.get("fallback_reason"),
            "after_server_latency": done.get("latency"),
        }
        out.append(row)
        print(json.dumps(row))
        requests.post(f"{api}/api/scenarios/corrective-action", timeout=60)
    Path("benchmark_results.json").write_text(json.dumps(out, indent=2))
    print("written benchmark_results.json")


# --------------------------------------------------------------- capture mode

def capture(scenarios: list[str]) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from unittest.mock import patch

    captured = []

    class Fake(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"models": [{"name": "qwen2.5:3b"}]}).encode())

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            captured.append((self.path, payload))
            # An unusable reply: both paths then fall back, which is fine here;
            # only the requests are being measured.
            self.send_response(500)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"

    def size(path, payload):
        if path.endswith("/api/chat"):
            text = "".join(m["content"] for m in payload["messages"])
        else:
            text = payload.get("prompt") or json.dumps(payload.get("messages", ""))
        return len(text)

    async def run():
        from alarm_lifecycle import get_lifecycle_manager
        from database import Database
        from datetime import datetime, timedelta, timezone
        from orchestrator import OpsLensOrchestrator
        from generator import SyntheticDataGenerator
        import ai_diagnosis
        import httpx
        from api.routes import create_app

        rows = []
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                "OPSLENS_LLM_PROVIDER": "ollama", "EDGE_LLM_URL": url, "OPSLENS_OLLAMA_TIMEOUT": "5",
                "OPSLENS_ASSISTANT_CACHE_TTL": "0"}):
            get_lifecycle_manager().clear_all()
            db = Database(db_path=Path(tmp) / "b.db")
            orch = OpsLensOrchestrator(db=db)
            app = create_app(orchestrator=orch)
            start = datetime.now(timezone.utc) - timedelta(hours=3)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=60) as c:
                for i, sid in enumerate(scenarios):
                    before_ids = {e.event_id for e in db.get_candidate_events()}
                    gen = SyntheticDataGenerator(db=db, sample_interval=2.0, start_time=start + timedelta(minutes=20 * i))
                    async for r in gen.run_scenario_async(sid, speed_multiplier=float("inf")):
                        await orch.process_reading(r)
                    while orch._in_flight_tasks:
                        await asyncio.gather(*list(orch._in_flight_tasks.values()), return_exceptions=True)
                    new = [e for e in db.get_candidate_events() if e.event_id not in before_ids]
                    for e in new:
                        await orch.process_candidate_event(e)
                    while orch._in_flight_tasks:
                        await asyncio.gather(*list(orch._in_flight_tasks.values()), return_exceptions=True)
                    eid = new[0].event_id
                    captured.clear()
                    await c.post("/api/assistant/ask", json={"event_id": eid, "question": QUESTION})
                    old = list(captured)
                    captured.clear()
                    ai_diagnosis.CACHE.clear()
                    await c.get(f"/api/events/{eid}/diagnosis")
                    new_calls = list(captured)
                    rows.append({
                        "scenario": sid,
                        "before_model_calls": len(old),
                        "before_prompt_chars": [size(p, q) for p, q in old],
                        "before_endpoint": sorted({p for p, _ in old}),
                        "before_num_predict": [q.get("options", {}).get("num_predict") for _, q in old],
                        "before_streamed_to_operator": False,
                        "after_model_calls": len(new_calls),
                        "after_prompt_chars": [size(p, q) for p, q in new_calls],
                        "after_endpoint": sorted({p for p, _ in new_calls}),
                        "after_num_predict": [q.get("options", {}).get("num_predict") for _, q in new_calls],
                        "after_streamed_to_operator": True,
                    })
                    print(json.dumps(rows[-1]))
            await orch.stop()
        return rows

    rows = asyncio.run(run())
    server.shutdown()
    Path("benchmark_capture.json").write_text(json.dumps(rows, indent=2))


def main():
    import incident_catalog as catalog
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["live", "capture"])
    ap.add_argument("--api", default="http://127.0.0.1:8001")
    ap.add_argument("--scenarios", default="all")
    ap.add_argument("--speed", type=float, default=20.0)
    a = ap.parse_args()
    ids = [s.scenario_id for s in catalog.SCENARIOS] if a.scenarios == "all" else a.scenarios.split(",")
    if a.mode == "live":
        live(a.api.rstrip("/"), ids, a.speed)
    else:
        capture(ids)


if __name__ == "__main__":
    main()
