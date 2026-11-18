"""
SWARM-100 Central Tool Registry
Coordinates tool registration, permission verification, approval gating,
isolated execution with timeout enforcement, and immutable SQLite audit logging.
"""

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import settings
from backend.core.tools.base import (
    ApprovalRequiredError,
    BaseTool,
    ExecutionTimeoutError,
    PermissionDeniedError,
    PermissionLevel,
    SecurityBoundaryError,
    ToolContext,
    ToolError,
    ToolNotFoundError,
)
from backend.core.tools.implementations.calculator import CalculatorTool
from backend.core.tools.implementations.csv_processor import CSVProcessorTool
from backend.core.tools.implementations.data_analysis import StructuredDataAnalysisTool
from backend.core.tools.implementations.datetime_tool import DateTimeTool
from backend.core.tools.implementations.document_summarizer import DocumentSummarizerTool
from backend.core.tools.implementations.project_inspector import ProjectInspectorTool
from backend.core.tools.implementations.restricted_code_tester import RestrictedCodeTesterTool
from backend.core.tools.implementations.web_scraper import WebScraperTool
from backend.core.tools.implementations.web_search import WebSearchTool
from backend.core.tools.implementations.workspace_file_creator import WorkspaceFileCreatorTool
from backend.core.tools.implementations.workspace_file_reader import WorkspaceFileReaderTool
from backend.database import get_connection

logger = logging.getLogger("swarm100.tools")

class ToolRegistry:
    def __init__(self, db_path: Optional[Path] = None, workspace_dir: Optional[Path] = None):
        self.db_path = db_path
        self.workspace_dir = workspace_dir or settings.workspace_dir
        self._tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Instantiates and registers all 9 initial general-purpose tools."""
        default_tools = [
            CalculatorTool(),
            DateTimeTool(),
            WorkspaceFileReaderTool(),
            WorkspaceFileCreatorTool(),
            StructuredDataAnalysisTool(),
            CSVProcessorTool(),
            DocumentSummarizerTool(),
            ProjectInspectorTool(),
            RestrictedCodeTesterTool(),
            WebSearchTool(),
            WebScraperTool(),
        ]
        for t in default_tools:
            self.register_tool(t)

    def register_tool(self, tool: BaseTool) -> None:
        """Registers a tool in the active registry."""
        self._tools[tool.id] = tool
        logger.debug(f"Registered tool: [{tool.id}] (permission: {tool.permission_level.value})")

    def unregister_tool(self, tool_id: str) -> None:
        """Unregisters a tool by ID if present."""
        self._tools.pop(tool_id, None)

    def get_tool(self, tool_id: str) -> BaseTool:
        """Retrieves a registered tool by ID or raises ToolNotFoundError."""
        if tool_id not in self._tools:
            raise ToolNotFoundError(f"Tool '{tool_id}' not found in active registry. Available: {list(self._tools.keys())}")
        return self._tools[tool_id]

    def list_tools(self) -> List[Dict[str, Any]]:
        """Returns structured metadata and JSON schemas for all registered tools."""
        return [tool.get_metadata() for tool in self._tools.values()]

    # =========================================================================
    # APPROVAL REQUEST MANAGEMENT
    # =========================================================================

    def create_approval_request(
        self,
        tool_id: str,
        agent_id: str,
        parameters: Dict[str, Any],
        justification: Optional[str] = None,
        task_id: Optional[str] = None,
        goal_id: Optional[str] = None,
    ) -> str:
        """Creates a pending human-in-the-loop / orchestrator approval request in SQLite."""
        tool = self.get_tool(tool_id)
        approval_id = f"appr-{uuid.uuid4().hex[:10]}"
        params_json = json.dumps(parameters, default=str)

        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO tool_approval_requests (
                    id, tool_id, agent_id, task_id, goal_id, permission_level,
                    parameters, justification, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP)
                """,
                (approval_id, tool_id, agent_id, task_id, goal_id, tool.permission_level.value, params_json, justification)
            )
            conn.commit()

        logger.info(f"Created approval request [{approval_id}] for tool '{tool_id}' by agent '{agent_id}'")
        return approval_id

    def resolve_approval_request(
        self,
        approval_id: str,
        approved: bool,
        resolved_by: str = "orchestrator",
        resolution_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Approves or rejects a pending tool approval request."""
        status = "approved" if approved else "rejected"
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM tool_approval_requests WHERE id = ?", (approval_id,)).fetchone()
            if not row:
                raise ValueError(f"Approval request '{approval_id}' not found.")

            conn.execute(
                """
                UPDATE tool_approval_requests
                SET status = ?, resolved_by = ?, resolution_notes = ?, resolved_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, resolved_by, resolution_notes, approval_id)
            )
            conn.commit()

        return {
            "approval_id": approval_id,
            "status": status,
            "resolved_by": resolved_by,
            "resolution_notes": resolution_notes
        }

    def list_pending_approvals(self) -> List[Dict[str, Any]]:
        """Retrieves all pending approval requests awaiting resolution."""
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM tool_approval_requests WHERE status = 'pending' ORDER BY created_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    # =========================================================================
    # TOOL EXECUTION & AUDIT LOGGING
    # =========================================================================

    async def execute_tool(
        self,
        tool_id: str,
        agent_id: str,
        parameters: Dict[str, Any],
        task_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        is_approved: bool = False,
        approved_by: Optional[str] = None,
        justification: Optional[str] = None,
        workspace_override: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Executes a requested tool with comprehensive security checks:
        1. Tool existence check.
        2. Permission and approval verification.
        3. Input schema validation.
        4. Isolated execution with strict timeout enforcement.
        5. Immutable SQLite audit logging.
        """
        tool = self.get_tool(tool_id)
        active_workspace = workspace_override or self.workspace_dir
        start_time = time.perf_counter()
        audit_id = f"audit-{uuid.uuid4().hex[:10]}"
        params_json = json.dumps(parameters, default=str)

        # Rule 1: Approval Gate Enforcement
        if tool.permission_level == PermissionLevel.RESTRICTED_EXECUTION and not is_approved:
            appr_id = self.create_approval_request(
                tool_id=tool_id,
                agent_id=agent_id,
                parameters=parameters,
                justification=justification,
                task_id=task_id,
                goal_id=goal_id
            )
            # Log blocked permission attempt in audit log
            self._write_audit_log(
                audit_id=audit_id,
                tool_id=tool_id,
                agent_id=agent_id,
                task_id=task_id,
                goal_id=goal_id,
                permission_level=tool.permission_level.value,
                input_params=params_json,
                output_result=None,
                status="blocked_permission",
                approved_by=None,
                execution_time_ms=0.0,
                error=f"Execution blocked: Tool requires explicit approval. Created approval request {appr_id}."
            )
            raise ApprovalRequiredError(
                f"Tool '{tool_id}' requires explicit approval before execution. Request logged under ID '{appr_id}'.",
                approval_id=appr_id,
                tool_id=tool_id
            )

        # Rule 2: Input Schema Validation
        try:
            validated_params = tool.input_schema.model_validate(parameters)
        except Exception as e:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            self._write_audit_log(
                audit_id=audit_id,
                tool_id=tool_id,
                agent_id=agent_id,
                task_id=task_id,
                goal_id=goal_id,
                permission_level=tool.permission_level.value,
                input_params=params_json,
                output_result=None,
                status="failed",
                approved_by=approved_by,
                execution_time_ms=elapsed_ms,
                error=f"Schema Validation Error: {e}"
            )
            raise ValueError(f"Invalid input schema for tool '{tool_id}': {e}")

        # Construct execution context
        context = ToolContext(
            agent_id=agent_id,
            goal_id=goal_id,
            task_id=task_id,
            workspace_path=active_workspace,
            is_approved=is_approved,
            approved_by=approved_by,
            justification=justification
        )

        # Rule 3: Timeout-Protected Execution
        try:
            result = await asyncio.wait_for(
                tool.execute(validated_params, context),
                timeout=tool.timeout_seconds
            )
            elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            output_dict = result.model_dump()
            output_json = json.dumps(output_dict, default=str)

            # Record success in audit log
            self._write_audit_log(
                audit_id=audit_id,
                tool_id=tool_id,
                agent_id=agent_id,
                task_id=task_id,
                goal_id=goal_id,
                permission_level=tool.permission_level.value,
                input_params=params_json,
                output_result=output_json,
                status="success",
                approved_by=approved_by if is_approved else "auto",
                execution_time_ms=elapsed_ms,
                error=None
            )

            return {
                "tool_id": tool_id,
                "status": "success",
                "result": output_dict,
                "execution_time_ms": elapsed_ms,
                "audit_id": audit_id
            }

        except asyncio.TimeoutError:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            err_msg = f"Execution exceeded maximum timeout limit of {tool.timeout_seconds} seconds."
            self._write_audit_log(
                audit_id=audit_id,
                tool_id=tool_id,
                agent_id=agent_id,
                task_id=task_id,
                goal_id=goal_id,
                permission_level=tool.permission_level.value,
                input_params=params_json,
                output_result=None,
                status="timeout",
                approved_by=approved_by,
                execution_time_ms=elapsed_ms,
                error=err_msg
            )
            raise ExecutionTimeoutError(err_msg)

        except SecurityBoundaryError as e:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            err_msg = str(e)
            self._write_audit_log(
                audit_id=audit_id,
                tool_id=tool_id,
                agent_id=agent_id,
                task_id=task_id,
                goal_id=goal_id,
                permission_level=tool.permission_level.value,
                input_params=params_json,
                output_result=None,
                status="security_violation",
                approved_by=approved_by,
                execution_time_ms=elapsed_ms,
                error=err_msg
            )
            raise

        except Exception as e:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            err_msg = str(e)
            self._write_audit_log(
                audit_id=audit_id,
                tool_id=tool_id,
                agent_id=agent_id,
                task_id=task_id,
                goal_id=goal_id,
                permission_level=tool.permission_level.value,
                input_params=params_json,
                output_result=None,
                status="failed",
                approved_by=approved_by,
                execution_time_ms=elapsed_ms,
                error=err_msg
            )
            raise

    def _write_audit_log(
        self,
        audit_id: str,
        tool_id: str,
        agent_id: str,
        permission_level: str,
        input_params: str,
        output_result: Optional[str],
        status: str,
        execution_time_ms: float,
        task_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        approved_by: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Writes an immutable audit record to the SQLite tool_audit_logs table."""
        try:
            with get_connection(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO tool_audit_logs (
                        id, tool_id, agent_id, task_id, goal_id, permission_level,
                        input_params, output_result, status, approved_by,
                        execution_time_ms, error, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        audit_id, tool_id, agent_id, task_id, goal_id, permission_level,
                        input_params, output_result, status, approved_by,
                        execution_time_ms, error
                    )
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to persist tool audit log [{audit_id}]: {e}")

    def get_audit_logs(
        self,
        tool_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Queries the tool execution audit logs with optional filters."""
        query = "SELECT * FROM tool_audit_logs"
        clauses = []
        params = []

        if tool_id:
            clauses.append("tool_id = ?")
            params.append(tool_id)
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

        with get_connection(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

# Global tool registry singleton
tool_registry = ToolRegistry()
