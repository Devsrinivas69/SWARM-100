"""
SWARM-100 Backend Application
FastAPI entrypoint with lifecycle hooks, auto-seeding, and CORS configuration.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.agents.registry import init_and_seed
from backend.api.v1.router import router as api_v1_router
from backend.config import settings
from backend.core.websocket_manager import ws_manager

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("swarm100")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing SWARM-100 SQLite registry...")
    init_and_seed()
    logger.info("SWARM-100 Registry ready: 10 teams and 100 specialist agents seeded.")
    yield
    logger.info("SWARM-100 shutting down.")

app = FastAPI(
    title="SWARM-100 Autonomous Workforce API",
    description="General-purpose autonomous multi-agent AI workforce registry and orchestrator API.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Central API v1 router
app.include_router(api_v1_router)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time bi-directional event stream for dashboard clients."""
    await ws_manager.connect(websocket)
    try:
        while True:
            text = await websocket.receive_text()
            if text == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as e:
        logger.debug(f"WebSocket connection error: {e}")
        await ws_manager.disconnect(websocket)

@app.get("/health", tags=["System"], summary="System health probe")
def health_check():
    return {
        "status": "healthy",
        "service": "SWARM-100",
        "version": "0.1.0",
        "database": str(settings.db_path)
    }

# Mount static frontend dashboard at root URL
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

