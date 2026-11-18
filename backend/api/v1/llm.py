"""
FastAPI Router: /api/v1/llm
Endpoints for verifying local Ollama connectivity and executing real model inferences.
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.config import settings
from backend.core.llm_service import llm_service
from backend.models.schemas import ConfigDict

router = APIRouter(prefix="/llm", tags=["LLM Engine"])

class LLMConfigRequest(BaseModel):
    provider: Optional[str] = Field(None, description="Active LLM provider: 'ollama', 'groq', 'gemini', 'openai', or 'hybrid'")
    groq_api_key: Optional[str] = Field(None, description="Groq API key")
    groq_model: Optional[str] = Field(None, description="Groq model (e.g. llama-3.3-70b-versatile)")
    gemini_api_key: Optional[str] = Field(None, description="Google Gemini API key")
    gemini_model: Optional[str] = Field(None, description="Gemini model (e.g. gemini-2.0-flash)")
    openai_api_key: Optional[str] = Field(None, description="OpenAI API key")
    openai_model: Optional[str] = Field(None, description="OpenAI model (e.g. gpt-4o-mini)")
    enable_token_streaming: Optional[bool] = Field(None, description="Toggle WebSocket token streaming")
    enable_react_tools: Optional[bool] = Field(None, description="Toggle autonomous ReAct tool loop")
    max_critic_retries: Optional[int] = Field(None, description="Maximum critic self-correction retries")

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


@router.get("/providers", summary="Get LLM provider state and model routing info")
async def get_providers():
    """Returns current active provider and available cloud burst integrations."""
    return llm_service.get_active_provider_info()


@router.post("/config", summary="Configure hybrid LLM routing and advanced features")
async def configure_llm_settings(payload: LLMConfigRequest):
    """Updates active provider and configuration in runtime settings."""
    if payload.provider:
        valid_providers = ("ollama", "groq", "gemini", "openai", "hybrid")
        if payload.provider.lower() not in valid_providers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid provider '{payload.provider}'. Must be one of: {valid_providers}"
            )
        settings.llm_provider = payload.provider.lower()

    if payload.groq_api_key is not None:
        settings.groq_api_key = payload.groq_api_key.strip()
    if payload.groq_model:
        settings.groq_model = payload.groq_model.strip()

    if payload.gemini_api_key is not None:
        settings.gemini_api_key = payload.gemini_api_key.strip()
    if payload.gemini_model:
        settings.gemini_model = payload.gemini_model.strip()

    if payload.openai_api_key is not None:
        settings.openai_api_key = payload.openai_api_key.strip()
    if payload.openai_model:
        settings.openai_model = payload.openai_model.strip()

    if payload.enable_token_streaming is not None:
        settings.enable_token_streaming = payload.enable_token_streaming

    if payload.enable_react_tools is not None:
        settings.enable_react_tools = payload.enable_react_tools

    if payload.max_critic_retries is not None:
        settings.max_critic_retries = max(0, min(5, payload.max_critic_retries))

    return {
        "status": "updated",
        "configuration": llm_service.get_active_provider_info()
    }
