"""
FastAPI Router: /api/v1/improvement
Endpoints for controlled agent self-improvement:
- Prompt version history tracking
- Propose and objectively benchmark instruction refinements
- Strict security guardrail blocking unauthorized system or orchestrator modifications
"""

import sqlite3
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.core.self_improvement import (
    SecurityRejectionError,
    self_improvement_engine,
)
from backend.database import get_db
from backend.models.schemas import (
    ImprovementProposalOut,
    ImprovementProposalRequest,
    PromptVersionOut,
)

router = APIRouter(prefix="/improvement", tags=["Self-Improvement"])

@router.get("/proposals", summary="List All Self-Improvement Proposals")
def list_improvement_proposals(
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    status: Optional[str] = Query(None, description="Filter by status (accepted, rejected, pending, testing)"),
    limit: int = Query(50, ge=1, le=200, description="Max proposals to return"),
    db: sqlite3.Connection = Depends(get_db),
):
    """Retrieve full history of improvement proposals, comparative benchmarks, and safety verdicts."""
    query = "SELECT * FROM improvement_proposals"
    clauses = []
    params = []
    if agent_id:
        clauses.append("agent_id = ?")
        params.append(agent_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]

@router.get("/versions", response_model=List[PromptVersionOut], summary="List All Active and Superseded Versions")
def list_all_prompt_versions(
    limit: int = Query(50, ge=1, le=200),
    db: sqlite3.Connection = Depends(get_db),
):
    """Retrieve recent prompt versions across the workforce."""
    rows = db.execute(
        "SELECT * FROM agent_prompt_versions ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    return [dict(r) for r in rows]

@router.get("/agents/{agent_id}/versions", response_model=List[PromptVersionOut], summary="Get Agent Prompt Versions")
def get_prompt_version_history(
    agent_id: str,
    db: sqlite3.Connection = Depends(get_db),
):
    """Retrieve full version history of prompt iterations and benchmarks for an agent."""
    agent_row = db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if not agent_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found."
        )

    # Ensure at least version 1 baseline exists
    self_improvement_engine.get_or_create_initial_version(agent_id)
    return self_improvement_engine.get_version_history(agent_id)

@router.post("/agents/{agent_id}/propose", response_model=ImprovementProposalOut, summary="Propose and Evaluate Prompt Improvement")
async def propose_agent_improvement(
    agent_id: str,
    proposal: ImprovementProposalRequest,
    db: sqlite3.Connection = Depends(get_db),
):
    """
    Submit a proposed instruction improvement for an agent:
    1. Enforces security boundary (blocks orchestrator or code alteration attempts).
    2. Runs comparative benchmark against current baseline.
    3. Accepts change only if target metric improves with zero safety regression.
    4. Persists learning record to SQLite memory on acceptance or failure.
    """
    agent_row = db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if not agent_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found."
        )

    try:
        result = await self_improvement_engine.propose_and_evaluate_improvement(
            agent_id=agent_id,
            proposed_prompt=proposal.proposed_prompt,
            rationale=proposal.rationale,
            target_metric=proposal.target_metric,
            iteration=proposal.iteration,
            max_iterations=proposal.max_iterations,
        )
        return result
    except SecurityRejectionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
