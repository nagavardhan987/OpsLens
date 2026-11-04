"""
OpsLens - AI-Powered Runtime Copilot for Industrial HMI
Backend Application Server (FastAPI + Uvicorn)
Schneider Electric Innovation Marathon MVP
"""

import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router

app = FastAPI(
    title="OpsLens - Industrial HMI Runtime Copilot API",
    description="Edge Intelligence REST API for Schneider Electric EcoStruxure Operator Terminal Expert",
    version="1.0.0"
)

# CORS Middleware for local Vite frontend dev server (port 5173 -> 8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root():
    return {
        "service": "OpsLens Edge Intelligence Runtime",
        "system": "EcoStruxure HMI Copilot",
        "status": "ONLINE",
        "edge_platform": "Edge IPC (Industrial PC)",
        "target_hmi": "EcoStruxure Operator Terminal Expert",
        "version": "1.0.0",
        "endpoints": [
            "/api/machine",
            "/api/alarms",
            "/api/incident",
            "/api/event-story",
            "/api/evidence",
            "/api/sop",
            "/api/operator-action",
            "/api/handover",
            "/api/demo/start",
            "/api/demo/reset"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
