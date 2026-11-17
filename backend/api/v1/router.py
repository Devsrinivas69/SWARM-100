"""
API v1 Central Router
"""

from fastapi import APIRouter
from backend.api.v1.agents import router as agents_router
from backend.api.v1.teams import router as teams_router
from backend.api.v1.orchestrator import router as orchestrator_router
from backend.api.v1.llm import router as llm_router
from backend.api.v1.memory import router as memory_router
from backend.api.v1.improvement import router as improvement_router
from backend.api.v1.tools import router as tools_router
from backend.api.v1.dashboard import router as dashboard_router
from backend.api.v1.foundry import router as foundry_router

router = APIRouter(prefix="/api/v1")
router.include_router(agents_router)
router.include_router(teams_router)
router.include_router(orchestrator_router)
router.include_router(llm_router)
router.include_router(memory_router)
router.include_router(improvement_router)
router.include_router(tools_router)
router.include_router(dashboard_router)
router.include_router(foundry_router)



