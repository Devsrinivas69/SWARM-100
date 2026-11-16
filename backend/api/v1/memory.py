"""
FastAPI Router: /api/v1/memory
Endpoints for inspecting the 3 persistent memory layers:
1. Agent Memory: Individual agent lessons, experiences, and failure warnings
2. Project Memory: Goal context, architectural decisions, and accumulated deliverables
3. Global Knowledge: Reusable verified approaches and cross-agent best practices
"""

import sqlite3
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.core.memory import memory_service
from backend.database import get_db
from backend.models.schemas import (
    AgentMemoryOut,
    GlobalKnowledgeOut,
    ProjectMemoryOut,
)

router = APIRouter(prefix="/memory", tags=["Memory"])

@router.get("/recent", response_model=List[AgentMemoryOut], summary="Get Recent Memories Across All Agents")
def get_recent_agent_memories(
    memory_type: Optional[str] = Query(None, description="Filter by memory type"),
    limit: int = Query(50, ge=1, le=200, description="Max memories to return"),
    db: sqlite3.Connection = Depends(get_db),
):
    """Retrieve recent experiential memories across all agents for the Memory dashboard."""
    query = "SELECT * FROM agent_memories"
    params = []
    if memory_type:
        query += " WHERE memory_type = ?"
        params.append(memory_type)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]

@router.get("/agents/{agent_id}", response_model=List[AgentMemoryOut], summary="Get Agent Memories")
def get_agent_memories(
    agent_id: str,
    memory_type: Optional[str] = Query(None, description="Filter by memory type (e.g. successful_approach, failure_pattern, task_experience, lesson_learned)"),
    limit: int = Query(20, ge=1, le=100, description="Max memories to return"),
    db: sqlite3.Connection = Depends(get_db),
):
    """Retrieve persisted experiential memories and learned lessons for an individual agent."""
    # Verify agent exists
    agent_row = db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if not agent_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found."
        )

    return memory_service.get_agent_memories(agent_id=agent_id, memory_type=memory_type, limit=limit)

@router.get("/projects/{goal_id}", response_model=List[ProjectMemoryOut], summary="Get Project Memories")
def get_project_memories(
    goal_id: str,
    category: Optional[str] = Query(None, description="Filter by category (e.g. decision, task_output, context, constraint)"),
    db: sqlite3.Connection = Depends(get_db),
):
    """Retrieve accumulated project context, architectural decisions, and task deliverables for a goal."""
    goal_row = db.execute("SELECT id FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if not goal_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Goal '{goal_id}' not found."
        )

    return memory_service.get_project_memories(goal_id=goal_id, category=category)

@router.get("/global", response_model=List[GlobalKnowledgeOut], summary="Get Global Knowledge")
def get_global_knowledge(
    domain: Optional[str] = Query(None, description="Domain or discipline filter"),
    pattern_type: Optional[str] = Query(None, description="Filter by pattern type (e.g. verified_lesson, successful_approach, known_failure_pattern, best_practice)"),
    limit: int = Query(20, ge=1, le=100, description="Max records to return"),
):
    """Retrieve cross-agent verified lessons, organizational best practices, and known anti-patterns."""
    return memory_service.get_global_knowledge(domain=domain, pattern_type=pattern_type, limit=limit)

@router.get("/context", summary="Synthesize Context for Task")
def get_synthesized_task_context(
    agent_id: str = Query(..., description="Target agent ID"),
    goal_id: str = Query(..., description="Target goal ID"),
    task_title: str = Query(..., description="Task title"),
    task_type: str = Query("General", description="Task classification type"),
):
    """Retrieve the multi-layer synthesized context injected into an agent before task execution."""
    context = memory_service.retrieve_context_for_task(
        agent_id=agent_id,
        goal_id=goal_id,
        task_title=task_title,
        task_type=task_type
    )
    return {
        "agent_id": agent_id,
        "goal_id": goal_id,
        "task_title": task_title,
        "task_type": task_type,
        "synthesized_context": context,
    }
