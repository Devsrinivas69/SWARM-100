"""
FastAPI Router: /api/v1/goals and /api/v1/tasks
Endpoints for submitting goals, executing worker pools, monitoring progress,
and issuing pause, resume, cancel, and retry commands.
"""

from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from backend.core.orchestrator import orchestrator
from backend.models.schemas import GoalCreate, GoalOut, GoalSummary, TaskOut

router = APIRouter(tags=["Orchestration"])

# -----------------------------------------------------------------------------
# GOALS ENDPOINTS
# -----------------------------------------------------------------------------

@router.post("/goals", status_code=status.HTTP_201_CREATED, summary="Submit natural-language goal")
def submit_goal(payload: GoalCreate):
    """
    Accepts arbitrary natural language goals, classifies the domain, builds
    a structured DAG of independent and dependent subtasks, and assigns specialist agents.
    """
    res = orchestrator.submit_goal(
        title=payload.title,
        description=payload.description,
        concurrency_limit=payload.concurrency_limit
    )
    return res

@router.get("/goals", summary="List goals")
def list_goals(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    """Lists submitted goals with progress stats."""
    return orchestrator.queue.list_goals(page=page, page_size=page_size)

@router.get("/goals/{goal_id}", response_model=GoalOut, summary="Inspect goal status and subtasks")
def get_goal_status(goal_id: str):
    """Inspects a goal's full state, subtasks, outputs, and QA reviews."""
    goal = orchestrator.queue.get_goal(goal_id)
    if not goal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Goal '{goal_id}' not found."
        )
    return goal

@router.post("/goals/{goal_id}/run", summary="Execute goal via worker pool")
async def run_goal(goal_id: str):
    """
    Runs the asynchronous worker pool for a goal through to synthesis and critic verification.
    """
    goal = orchestrator.queue.get_goal(goal_id)
    if not goal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Goal '{goal_id}' not found."
        )

    result = await orchestrator.run_goal(goal_id)
    return result

@router.post("/goals/{goal_id}/pause", summary="Pause goal execution")
def pause_goal(goal_id: str):
    ok = orchestrator.pause_goal(goal_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not pause goal '{goal_id}'."
        )
    return {"goal_id": goal_id, "status": "paused"}

@router.post("/goals/{goal_id}/resume", summary="Resume paused goal")
def resume_goal(goal_id: str):
    ok = orchestrator.resume_goal(goal_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not resume goal '{goal_id}'."
        )
    return {"goal_id": goal_id, "status": "in_progress"}

@router.post("/goals/{goal_id}/cancel", summary="Cancel running goal")
def cancel_goal(goal_id: str):
    ok = orchestrator.cancel_goal(goal_id)
    return {"goal_id": goal_id, "status": "cancelled"}

# -----------------------------------------------------------------------------
# TASKS ENDPOINTS
# -----------------------------------------------------------------------------

@router.get("/tasks", response_model=List[TaskOut], summary="List all tasks")
def list_tasks(
    status: Optional[str] = Query(None, description="Filter by status (pending, assigned, running, reviewing, completed, failed, blocked, cancelled)"),
    goal_id: Optional[str] = Query(None, description="Filter by goal ID"),
    agent_id: Optional[str] = Query(None, description="Filter by assigned agent ID"),
    limit: int = Query(100, ge=1, le=500, description="Max tasks to return")
):
    """Retrieves tasks across all goals for the Task Board and Execution Timeline."""
    return orchestrator.queue.list_tasks(status=status, goal_id=goal_id, agent_id=agent_id, limit=limit)

@router.get("/tasks/{task_id}", response_model=TaskOut, summary="Inspect specific task")
def get_task(task_id: str):
    task = orchestrator.queue.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found."
        )
    return task

@router.post("/tasks/{task_id}/retry", summary="Retry a failed task")
def retry_task(task_id: str):
    task = orchestrator.queue.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found."
        )
    ok = orchestrator.retry_task(task_id)
    return {"task_id": task_id, "status": "pending", "retried": ok}
