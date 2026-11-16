"""
FastAPI Router: /api/v1/tools
Endpoints for:
- Discovering registered tools and schemas
- Executing tools through the central orchestrator
- Inspecting pending approval requests and approving/rejecting them
- Reviewing immutable tool audit records
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.core.orchestrator import orchestrator
from backend.core.tools.base import (
    ApprovalRequiredError,
    ExecutionTimeoutError,
    PermissionDeniedError,
    SecurityBoundaryError,
    ToolError,
    ToolNotFoundError,
)
from backend.core.tools.registry import tool_registry

router = APIRouter(prefix="/tools", tags=["Tools"])

# =============================================================================
# SCHEMAS
# =============================================================================

class ToolExecutionRequest(BaseModel):
    agent_id: str = Field(..., description="The requesting specialist agent ID")
    parameters: Dict[str, Any] = Field(..., description="Tool input parameters compliant with tool's input schema")
    task_id: Optional[str] = Field(None, description="Active task ID")
    goal_id: Optional[str] = Field(None, description="Active goal ID")
    is_approved: bool = Field(False, description="Whether approval has been granted")
    approved_by: Optional[str] = Field(None, description="Approver identifier (e.g. 'orchestrator', 'user')")
    justification: Optional[str] = Field(None, description="Rationale for tool invocation")

class ToolApprovalResolution(BaseModel):
    approved: bool = Field(..., description="True to approve, False to reject")
    resolved_by: str = Field("orchestrator", description="Identifier of the resolving authority")
    resolution_notes: Optional[str] = Field(None, description="Notes or reasoning regarding resolution")

# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("", summary="List Registered Tools")
def list_tools():
    """Returns metadata, descriptions, schemas, and permission levels for all registered tools."""
    return tool_registry.list_tools()

@router.get("/approvals/pending", summary="List Pending Approval Requests")
def list_pending_approvals():
    """Lists tool invocations that are currently blocked waiting for orchestrator or human approval."""
    return tool_registry.list_pending_approvals()

@router.post("/approvals/{approval_id}/resolve", summary="Resolve Approval Request")
def resolve_approval(approval_id: str, resolution: ToolApprovalResolution):
    """Approves or rejects a pending tool approval request."""
    try:
        return tool_registry.resolve_approval_request(
            approval_id=approval_id,
            approved=resolution.approved,
            resolved_by=resolution.resolved_by,
            resolution_notes=resolution.resolution_notes
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.get("/audit", summary="Get Tool Execution Audit Logs")
def get_audit_logs(
    tool_id: Optional[str] = Query(None, description="Filter by tool ID"),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (success, failed, blocked_permission, timeout, security_violation)"),
    limit: int = Query(50, ge=1, le=500, description="Max audit entries to retrieve"),
):
    """Queries immutable audit logs detailing every tool invocation, security check, and execution duration."""
    return tool_registry.get_audit_logs(
        tool_id=tool_id,
        agent_id=agent_id,
        status=status_filter,
        limit=limit
    )

@router.get("/{tool_id}", summary="Inspect Tool by ID")
def inspect_tool(tool_id: str):
    """Inspects a specific tool's permission level, description, and input/output JSON schemas."""
    try:
        tool = tool_registry.get_tool(tool_id)
        return tool.get_metadata()
    except ToolNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.post("/{tool_id}/execute", summary="Request Tool Execution via Orchestrator")
async def execute_tool(tool_id: str, req: ToolExecutionRequest):
    """
    Agents request tool execution through the central orchestrator.
    Enforces permission verification, approval gating, sandbox containment, and audit logging.
    """
    try:
        result = await orchestrator.request_tool_execution(
            agent_id=req.agent_id,
            tool_id=tool_id,
            parameters=req.parameters,
            task_id=req.task_id,
            goal_id=req.goal_id,
            is_approved=req.is_approved,
            approved_by=req.approved_by,
            justification=req.justification,
        )
        return result

    except ApprovalRequiredError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "ApprovalRequired",
                "message": str(e),
                "approval_id": e.approval_id,
                "tool_id": e.tool_id
            }
        )
    except SecurityBoundaryError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "SecurityBoundaryViolation",
                "message": str(e)
            }
        )
    except ExecutionTimeoutError as e:
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail={
                "error": "ExecutionTimeout",
                "message": str(e)
            }
        )
    except ToolNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Tool execution failed: {str(e)}"
        )
