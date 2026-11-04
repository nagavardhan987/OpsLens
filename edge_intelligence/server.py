"""
OpsLens Live Gateway Server
Runs FastAPI on http://0.0.0.0:8000 serving Component 11 orchestrator.
"""

import sys
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
import os
import uvicorn
from fastapi import FastAPI
from env_loader import load_env_file

# Add directory to sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# Load this backend's local settings before importing modules that read the
# environment. Existing process variables win over values in the local file.
load_env_file(root_dir / ".env")

from database import Database
from stream import TagStream
from orchestrator import OpsLensOrchestrator
from api.routes import create_app

db = Database()
stream = TagStream(db_path=db.db_path)
orch = OpsLensOrchestrator(db=db, stream=stream)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Readings already stored in SQLite have already contributed to persisted
    # incidents. Replaying them on every server restart inflates repeat counts
    # and reruns the full event pipeline; subscribe only to rows added after
    # this process starts.
    await orch.start_streaming(from_latest=True)
    if os.getenv("OPSLENS_LLM_PROVIDER", "").strip().lower() == "ollama" and \
            os.getenv("OPSLENS_OLLAMA_WARMUP", "true").strip().lower() in ("1", "true", "yes"):
        # Load the local model in the background so the operator's first
        # question is not spent on a cold start. Startup never waits for it.
        from edge_slm import ollama_health, warm_up_ollama

        def _warm():
            health = ollama_health()
            if health["reachable"] and health["model_installed"]:
                print(f"[OpsLens] Warming up Ollama model {health['model']} ...", flush=True)
                print(f"[OpsLens] Ollama warm-up: {warm_up_ollama()}", flush=True)
            else:
                print(f"[OpsLens] Ollama not ready ({health['error']}). Deterministic answers remain available.", flush=True)

        asyncio.get_running_loop().run_in_executor(None, _warm)
    plc_adapter = app.state.opcua_adapter
    plc_task = None
    if plc_adapter.config.enabled and plc_adapter.configured:
        async def ingest_plc_readings():
            async for reading in plc_adapter.stream_readings():
                # PLC readings enter the same write-through store and incident pipeline.
                orch.db.insert_reading(reading)
        plc_task = asyncio.create_task(ingest_plc_readings(), name="opslens-plc-opcua-ingestion")
    try:
        yield
    finally:
        if plc_task and not plc_task.done():
            plc_task.cancel()
            try:
                await plc_task
            except asyncio.CancelledError:
                pass
        await plc_adapter.disconnect()
        await orch.stop()


app = create_app(orchestrator=orch)
app.router.lifespan_context = lifespan


if __name__ == "__main__":
    host = os.getenv("OPSLENS_HOST", "0.0.0.0")
    port = int(os.getenv("OPSLENS_PORT", "8001"))
    print(f"Starting OpsLens Gateway Server on http://{host}:{port}...")
    uvicorn.run(app, host=host, port=port)
