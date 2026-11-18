from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict

# =============================================================================
# ENUMS
# =============================================================================

class TaskStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"

class GoalStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"

# =============================================================================
# AGENT & TEAM SCHEMAS
# =============================================================================

class TeamBase(BaseModel):
    id: int
    name: str
    domain: str
    description: str

class TeamOut(TeamBase):
    created_at: str | datetime
    agent_count: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)

class AgentBase(BaseModel):
    id: str
    team_id: int
    name: str
    role: str
    capabilities: List[str]
    memory_key: str
    status: str
    performance_score: float
    task_count: int

class AgentSummary(AgentBase):
    model_config = ConfigDict(from_attributes=True)

class AgentOut(AgentBase):
    system_prompt: str
    created_at: str | datetime
    updated_at: str | datetime
    model_config = ConfigDict(from_attributes=True)

class AgentStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(idle|busy|error|paused|retired)$")

class AgentScoreUpdate(BaseModel):
    performance_score: float = Field(..., ge=0.0, le=100.0)
    task_count: Optional[int] = Field(None, ge=0)

class PaginatedAgents(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[AgentSummary]

class TeamWithAgents(TeamOut):
    agents: List[AgentSummary]

class AgentCountResponse(BaseModel):
    total_agents: int
    expected: int
    ok: bool

# =============================================================================
# TASK & ORCHESTRATION SCHEMAS
# =============================================================================

class TaskPlanItem(BaseModel):
    """A subtask proposed during goal planning."""
    title: str
    task_type: str
    required_capabilities: List[str] = []
    assigned_agent_id: str
    priority: int = 5
    dependencies: List[str] = []
    input: str

class GoalAnalysis(BaseModel):
    """The structured understanding and decomposed plan for a goal."""
    goal_summary: str
    task_type: str
    required_capabilities: List[str] = []
    subtasks: List[TaskPlanItem] = []

class TaskCreate(BaseModel):
    goal_id: str
    parent_task_id: Optional[str] = None
    assigned_agent_id: str
    title: str
    priority: int = Field(5, ge=1, le=10)
    dependencies: List[str] = []
    input: str

class TaskOut(BaseModel):
    id: str
    goal_id: str
    parent_task_id: Optional[str] = None
    assigned_agent_id: str
    title: str
    priority: int
    dependencies: List[str] = []
    status: str
    input: str
    output: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: str | datetime
    started_at: Optional[str | datetime] = None
    completed_at: Optional[str | datetime] = None
    updated_at: Optional[str | datetime] = None
    tokens_used: int = 0
    latency_ms: float = 0.0
    review_score: Optional[float] = None
    review_feedback: Optional[str] = None
    critic_id: Optional[str] = None
    dimensions: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class GoalCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=500)
    description: str = Field(..., min_length=5, max_length=10000)
    concurrency_limit: int = Field(1, ge=1, le=20, description="Concurrency limit for execution pool (default 1)")
    workforce_density: Optional[str] = Field(
        "adaptive",
        description="Workforce density mode: 'adaptive', 'focused' (3-5), 'balanced' (10-15), 'comprehensive' (20-30), or 'full_swarm' (up to 100 agents across all 10 teams)"
    )

class GoalSummary(BaseModel):
    id: str
    title: str
    task_type: str
    status: str
    concurrency_limit: int
    total_tasks: int = 0
    completed_tasks: int = 0
    review_score: Optional[float] = None
    created_at: str | datetime
    completed_at: Optional[str | datetime] = None
    model_config = ConfigDict(from_attributes=True)

class GoalOut(BaseModel):
    id: str
    title: str
    description: str
    task_type: str
    required_capabilities: List[str] = []
    status: str
    concurrency_limit: int
    final_output: Optional[str] = None
    review_feedback: Optional[str] = None
    review_score: Optional[float] = None
    error: Optional[str] = None
    created_at: str | datetime
    completed_at: Optional[str | datetime] = None
    tasks: List[TaskOut] = []
    model_config = ConfigDict(from_attributes=True)

class ReviewResult(BaseModel):
    score: float = Field(..., ge=0.0, le=100.0)
    feedback: str
    passed: bool
    critic_agent_id: str
    dimensions: Dict[str, float] = {}

# =============================================================================
# PERSISTENT MEMORY SCHEMAS
# =============================================================================

class AgentMemoryOut(BaseModel):
    id: str
    agent_id: str
    memory_type: str
    task_id: Optional[str] = None
    goal_id: Optional[str] = None
    summary: str
    content: str
    score: Optional[float] = None
    importance: float = 1.0
    access_count: int = 0
    created_at: str | datetime
    model_config = ConfigDict(from_attributes=True)

class ProjectMemoryOut(BaseModel):
    id: str
    goal_id: str
    key: str
    category: str
    content: str
    created_by_task_id: Optional[str] = None
    created_at: str | datetime
    model_config = ConfigDict(from_attributes=True)

class GlobalKnowledgeOut(BaseModel):
    id: str
    pattern_type: str
    domain: str
    title: str
    content: str
    evidence: Optional[str] = None
    confidence_score: float = 85.0
    usage_count: int = 0
    created_at: str | datetime
    updated_at: str | datetime
    model_config = ConfigDict(from_attributes=True)

# =============================================================================
# CONTROLLED SELF-IMPROVEMENT SCHEMAS
# =============================================================================

class PromptVersionOut(BaseModel):
    id: str
    agent_id: str
    version: int
    prompt_text: str
    change_rationale: Optional[str] = None
    proposed_by: str
    benchmark_score: Optional[float] = None
    status: str
    created_at: str | datetime
    model_config = ConfigDict(from_attributes=True)

class ImprovementProposalRequest(BaseModel):
    proposed_prompt: str = Field(..., min_length=20, max_length=10000, description="The refined prompt proposed by or for the agent")
    rationale: str = Field(..., min_length=10, max_length=1000, description="Why this change improves quality and domain precision")
    target_metric: str = Field("accuracy", description="Target metric being optimized (e.g. accuracy, completeness, logic)")
    iteration: int = Field(1, ge=1, description="Current optimization iteration")
    max_iterations: int = Field(3, ge=1, le=10, description="Maximum permitted self-improvement iterations")

class ImprovementProposalOut(BaseModel):
    accepted: bool
    status: str
    new_version: Optional[int] = None
    current_version: Optional[int] = None
    baseline_score: Optional[float] = None
    new_score: Optional[float] = None
    test_score: Optional[float] = None
    delta: Optional[float] = None
    safety_passed: Optional[bool] = None
    verdict: str

