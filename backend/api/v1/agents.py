"""
FastAPI Router: /api/v1/agents
Endpoints to list, inspect, and update agent status and performance.
"""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.agents.registry import (
    count_agents,
    get_agent_by_id,
    get_all_agents,
    update_agent_score,
    update_agent_status,
)
from backend.database import get_db
from backend.models.schemas import (
    AgentCountResponse,
    AgentOut,
    AgentScoreUpdate,
    AgentStatusUpdate,
    PaginatedAgents,
)

router = APIRouter(prefix="/agents", tags=["Agents"])

@router.get("", response_model=PaginatedAgents, summary="List registered agents")
def list_agents(
    team_id: Optional[int] = Query(None, ge=1, le=10, description="Filter by team ID (1-10)"),
    status: Optional[str] = Query(None, description="Filter by operational status (idle, busy, error, paused, retired)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    db: sqlite3.Connection = Depends(get_db),
):
    """Retrieve a paginated list of SWARM-100 agents with optional team and status filters."""
    return get_all_agents(db, team_id=team_id, status=status, page=page, page_size=page_size)

@router.get("/count", response_model=AgentCountResponse, summary="Get total agent count")
def get_agent_count(db: sqlite3.Connection = Depends(get_db)):
    """Return the total number of registered agents and verify against expected 100."""
    total = count_agents(db)
    return {
        "total_agents": total,
        "expected": 100,
        "ok": total == 100,
    }

@router.get("/{agent_id}", response_model=AgentOut, summary="Inspect an agent by ID")
def inspect_agent(agent_id: str, db: sqlite3.Connection = Depends(get_db)):
    """Retrieve full agent details including role, capabilities, memory key, and system instructions."""
    agent = get_agent_by_id(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found in registry."
        )
    return agent

@router.patch("/{agent_id}/status", summary="Update agent operational status")
def change_agent_status(
    agent_id: str,
    payload: AgentStatusUpdate,
    db: sqlite3.Connection = Depends(get_db),
):
    """Update an agent's operational status (e.g. idle, busy, error, paused, retired)."""
    try:
        updated = update_agent_status(db, agent_id, payload.status)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found in registry."
        )

    agent = get_agent_by_id(db, agent_id)
    return {
        "agent_id": agent_id,
        "status": agent["status"],
        "message": f"Agent '{agent_id}' status updated to '{agent['status']}'."
    }

@router.patch("/{agent_id}/score", summary="Update agent performance score and task count")
def change_agent_score(
    agent_id: str,
    payload: AgentScoreUpdate,
    db: sqlite3.Connection = Depends(get_db),
):
    """Update an agent's performance score (0.0 - 100.0) and optionally increment task count."""
    try:
        updated = update_agent_score(
            db,
            agent_id,
            payload.performance_score,
            payload.task_count
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found in registry."
        )

    agent = get_agent_by_id(db, agent_id)
    return {
        "agent_id": agent_id,
        "performance_score": agent["performance_score"],
        "task_count": agent["task_count"],
        "message": f"Agent '{agent_id}' performance updated."
    }
