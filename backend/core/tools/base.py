"""
SWARM-100 Base Tool Architecture
Defines:
- Permission levels (SAFE, WORKSPACE_READ, WORKSPACE_WRITE, RESTRICTED_EXECUTION)
- Tool invocation context (agent, task, goal, workspace boundaries, approval tokens)
- Abstract base class for all general-purpose tools with schema validation
- Specialized security exceptions
"""

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# PERMISSION LEVELS
# =============================================================================

class PermissionLevel(str, Enum):
    SAFE = "SAFE"                             # Non-destructive pure computation (auto-approved)
    WORKSPACE_READ = "WORKSPACE_READ"         # Read-only operations strictly confined to approved workspace
    WORKSPACE_WRITE = "WORKSPACE_WRITE"       # Non-destructive file creation inside approved workspace
    RESTRICTED_EXECUTION = "RESTRICTED_EXEC"  # Code testing or dynamic execution: STRICTLY requires approval!

# =============================================================================
# EXCEPTIONS
# =============================================================================

class ToolError(Exception):
    """Base exception for all tool operations."""
    pass

class ToolNotFoundError(ToolError):
    """Raised when an unrecognised tool ID is requested."""
    pass

class PermissionDeniedError(ToolError):
    """Raised when an agent attempts an unauthorized tool execution."""
    pass

class ApprovalRequiredError(ToolError):
    """Raised when a tool requires explicit orchestrator or user approval before running."""
    def __init__(self, message: str, approval_id: Optional[str] = None, tool_id: Optional[str] = None):
        super().__init__(message)
        self.approval_id = approval_id
        self.tool_id = tool_id

class SecurityBoundaryError(ToolError):
    """Raised when a tool operation attempts to breach sandbox or workspace boundaries."""
    pass

class ExecutionTimeoutError(ToolError):
    """Raised when a tool exceeds its configured execution timeout limit."""
    pass

# =============================================================================
# TOOL CONTEXT & BASE CLASS
# =============================================================================

class ToolContext(BaseModel):
    agent_id: str = Field(..., description="The requesting specialist agent ID")
    goal_id: Optional[str] = Field(None, description="Active goal ID")
    task_id: Optional[str] = Field(None, description="Active task ID")
    workspace_path: Path = Field(..., description="Root directory of the approved workspace")
    is_approved: bool = Field(False, description="Whether explicit approval has been granted")
    approved_by: Optional[str] = Field(None, description="Identity of approver (e.g. 'orchestrator', 'user')")
    justification: Optional[str] = Field(None, description="Reasoning provided for the tool request")

    model_config = ConfigDict(arbitrary_types_allowed=True)

class BaseTool(ABC):
    """Abstract base class for all SWARM-100 tools."""
    id: str
    name: str
    description: str
    permission_level: PermissionLevel
    timeout_seconds: float = 10.0
    input_schema: Type[BaseModel]
    output_schema: Type[BaseModel]

    @abstractmethod
    async def execute(self, params: BaseModel, context: ToolContext) -> BaseModel:
        """Executes the tool logic within the validated security context."""
        pass

    def get_metadata(self) -> Dict[str, Any]:
        """Returns structured metadata including JSON schemas for tool documentation and LLM injection."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "permission_level": self.permission_level.value,
            "timeout_seconds": self.timeout_seconds,
            "input_schema": self.input_schema.model_json_schema(),
            "output_schema": self.output_schema.model_json_schema(),
        }
