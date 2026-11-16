"""
FastAPI Router: /api/v1/teams
Endpoints to list and inspect teams and their 10 specialist agents.
"""

import sqlite3
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from backend.agents.registry import get_all_teams, get_team_agents, get_team_by_id
from backend.database import get_db
from backend.models.schemas import TeamOut, TeamWithAgents

router = APIRouter(prefix="/teams", tags=["Teams"])

@router.get("", response_model=List[TeamOut], summary="List all 10 teams")
def list_teams(db: sqlite3.Connection = Depends(get_db)):
    """Retrieve all 10 SWARM-100 teams along with their active agent counts."""
    return get_all_teams(db)

@router.get("/{team_id}", response_model=TeamWithAgents, summary="Inspect team with agents")
def inspect_team(team_id: int, db: sqlite3.Connection = Depends(get_db)):
    """Retrieve team details and all 10 specialist agents belonging to this team."""
    team = get_team_by_id(db, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team {team_id} not found."
        )

    agents = get_team_agents(db, team_id)
    result = dict(team)
    result["agents"] = agents
    return result
