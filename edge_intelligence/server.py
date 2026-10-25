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
    try:
        yield
    finally:
        await orch.stop()


app = create_app(orchestrator=orch)
app.router.lifespan_context = lifespan


if __name__ == "__main__":
    host = os.getenv("OPSLENS_HOST", "0.0.0.0")
    port = int(os.getenv("OPSLENS_PORT", "8001"))
    print(f"Starting OpsLens Gateway Server on http://{host}:{port}...")
    uvicorn.run(app, host=host, port=port)
