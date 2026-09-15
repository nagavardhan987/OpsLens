"""
OpsLens Live Gateway Server
Runs FastAPI on http://0.0.0.0:8000 serving Component 11 orchestrator.
"""

import sys
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI

# Add directory to sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from database import Database
from stream import TagStream
from orchestrator import OpsLensOrchestrator
from api.routes import create_app

db = Database()
stream = TagStream(db_path=db.db_path)
orch = OpsLensOrchestrator(db=db, stream=stream)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await orch.start_streaming()
    try:
        yield
    finally:
        await orch.stop()


app = create_app(orchestrator=orch)
app.router.lifespan_context = lifespan


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
