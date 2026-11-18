"""
SWARM-100 Backend Application
FastAPI entrypoint with lifecycle hooks, auto-seeding, and CORS configuration.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.agents.registry import init_and_seed
from backend.api.v1.router import router as api_v1_router
from backend.config import settings
from backend.core.orchestrator import orchestrator
from backend.core.task_queue import TaskQueue
from backend.core.websocket_manager import ws_manager
from backend.database import get_connection

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
    tq = TaskQueue()
    reconciled = tq.reconcile_orphaned_tasks()
    if reconciled > 0:
        logger.info(f"Reconciled {reconciled} orphaned/interrupted tasks from previous run.")

    # Automatically resume execution for any in-progress goals
    with get_connection(tq.db_path) as conn:
        active_goals = conn.execute(
            "SELECT id, title FROM goals WHERE status = 'in_progress'"
        ).fetchall()
        for g in active_goals:
            logger.info(f"Auto-resuming in-progress goal '{g['title']}' ({g['id']})...")
            orchestrator.start_goal_execution(g["id"])

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

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serves favicon.ico if present, otherwise returns empty 204."""
    fav_file = FRONTEND_DIR / "favicon.ico"
    if fav_file.is_file():
        return FileResponse(fav_file)
    return Response(status_code=204)

@app.get("/", include_in_schema=False)
async def serve_root():
    """Serves the dashboard index.html at root."""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="Dashboard index.html not found")

@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa_or_static(full_path: str):
    """
    Serves static frontend assets or falls back to index.html for client-side SPA routing.
    Guards API routes and health endpoints from being swallowed.
    """
    # Safeguard: Never swallow API, WebSocket, or system endpoints
    if full_path.startswith("api/") or full_path == "health" or full_path.startswith("ws"):
        raise HTTPException(status_code=404, detail="Not Found")

    # Check if this points to an existing file in the frontend directory
    candidate_file = (FRONTEND_DIR / full_path).resolve()
    try:
        candidate_file.relative_to(FRONTEND_DIR.resolve())
        if candidate_file.is_file():
            return FileResponse(candidate_file)
    except ValueError:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Fall back to index.html for SPA routes (e.g. /tasks, /foundry, /workforce)
    index_file = FRONTEND_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)

    raise HTTPException(status_code=404, detail="Frontend index.html not found")

