"""
FastAPI Router: /api/v1/llm
Endpoints for verifying local Ollama connectivity and executing real model inferences.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.core.llm_service import llm_service
from backend.models.schemas import ConfigDict

router = APIRouter(prefix="/llm", tags=["LLM Engine"])

class ModelExecutionRequest(BaseModel):
    system_prompt: Optional[str] = Field(
        default="You are an autonomous AI workforce architect evaluating systems.",
        description="System prompt defining agent persona and constraints."
    )
    prompt: Optional[str] = Field(
        default="State the 3 core architectural principles of autonomous multi-agent workforces. Answer in concise bullet points.",
        description="User task directive."
    )
    model: Optional[str] = Field(
        default=None,
        description="Optional model override (defaults to configured model e.g. qwen3:4b)."
    )
    json_mode: bool = Field(
        default=False,
        description="Enforce structured JSON output mode from Ollama."
    )

class ModelExecutionResponse(BaseModel):
    success: bool
    model: str
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_latency_ms: float
    tokens_per_second: float

@router.get("/connection", summary="Test connection to local Ollama API")
async def test_ollama_connection():
    """
    Probes the local Ollama daemon (http://localhost:11434/api/tags)
    and verifies that the target model (qwen3:4b) is installed and accessible.
    """
    res = await llm_service.check_connection()
    return res

@router.post("/test", response_model=ModelExecutionResponse, summary="Execute live inference on Ollama")
async def execute_model_test(payload: Optional[ModelExecutionRequest] = None):
    """
    Executes a real test inference on the local Ollama instance (qwen3:4b),
    verifying token generation, context processing, and telemetry collection.
    """
    req = payload or ModelExecutionRequest()
    try:
        response = await llm_service.chat(
            system_prompt=req.system_prompt or "You are an autonomous specialist agent.",
            user_message=req.prompt or "Hello",
            model=req.model,
            json_mode=req.json_mode
        )

        return ModelExecutionResponse(
            success=True,
            model=response.telemetry.model or llm_service.model,
            content=response.content,
            prompt_tokens=response.telemetry.prompt_tokens,
            completion_tokens=response.telemetry.completion_tokens,
            total_tokens=response.telemetry.total_tokens,
            total_latency_ms=response.telemetry.total_latency_ms,
            tokens_per_second=response.telemetry.tokens_per_second
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ollama execution failed: {type(e).__name__} - {str(e)}"
        )
