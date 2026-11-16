"""
SWARM-100 Dedicated LLM Service
Async HTTP client for Ollama API (qwen3:4b) with retry handling, context window management,
token/latency telemetry tracking, structured JSON mode, and single-concurrency inference lock.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar
import httpx
from pydantic import BaseModel, Field

from backend.config import settings

logger = logging.getLogger("swarm100.llm")

T = TypeVar("T", bound=BaseModel)

class LLMTelemetry(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    load_duration_ms: float = 0.0
    eval_duration_ms: float = 0.0
    tokens_per_second: float = 0.0
    model: str = ""

class LLMResponse(BaseModel):
    content: str
    telemetry: LLMTelemetry
    raw_response: Dict[str, Any] = Field(default_factory=dict)
    parsed_json: Optional[Dict[str, Any]] = None

class ContextManager:
    """
    Manages context window budgets for local models (e.g. Qwen3 4B).
    Guards against context overflow by budgeting tokens between system instructions,
    task directives, and upstream dependency context.
    """
    def __init__(self, max_context_tokens: int = 8192, max_output_tokens: int = 2048):
        self.max_context_tokens = max_context_tokens
        self.max_output_tokens = max_output_tokens
        self.max_input_tokens = max_context_tokens - max_output_tokens

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Heuristic token estimate (~3.5 - 4 chars per token for English/Code)."""
        if not text:
            return 0
        return max(1, len(text) // 4)

    def prepare_messages(
        self,
        system_prompt: str,
        user_message: str,
        upstream_context: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """
        Assembles messages while enforcing context limits.
        Prioritizes:
        1. System prompt (immutable agent identity)
        2. Immediate user task prompt
        3. Upstream dependency context (truncated if necessary)
        """
        sys_tokens = self.estimate_tokens(system_prompt)
        user_tokens = self.estimate_tokens(user_message)
        available_for_context = self.max_input_tokens - (sys_tokens + user_tokens)

        final_user_content = user_message
        if upstream_context and available_for_context > 100:
            up_tokens = self.estimate_tokens(upstream_context)
            if up_tokens > available_for_context:
                # Truncate upstream context from the middle or end
                chars_allowed = available_for_context * 4
                truncated_context = upstream_context[:chars_allowed] + "\n...[Context truncated to fit context budget]..."
                final_user_content = f"{user_message}\n\n[Prerequisite Context]:\n{truncated_context}"
            else:
                final_user_content = f"{user_message}\n\n[Prerequisite Context]:\n{upstream_context}"
        elif upstream_context:
            logger.warning("Context budget exceeded; omitting upstream context to protect task directives.")

        return [
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": final_user_content.strip()}
        ]

class DedicatedLLMService:
    """
    Production-grade Async Ollama Client for SWARM-100:
    - Shared inference engine with concurrency initially limited to one.
    - Full telemetry extraction (tokens, latency, throughput).
    - Configurable timeout and exponential-backoff retries.
    - Robust JSON schema enforcement.
    """
    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 300.0,
        max_retries: int = 3,
        inference_concurrency: int = 1
    ):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = timeout
        self.max_retries = max_retries
        self.context_mgr = ContextManager(max_context_tokens=4096, max_output_tokens=1024)
        self.inference_concurrency = inference_concurrency
        self._inference_semaphore: Optional[asyncio.Semaphore] = None

    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._inference_semaphore is None:
            self._inference_semaphore = asyncio.Semaphore(self.inference_concurrency)
        return self._inference_semaphore

    async def check_connection(self) -> Dict[str, Any]:
        """
        Tests connection to the local Ollama API endpoint.
        Returns health status, latency, and available models.
        """
        start_time = time.perf_counter()
        url = f"{self.base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                latency_ms = (time.perf_counter() - start_time) * 1000.0

                if response.status_code == 200:
                    data = response.json()
                    models = [m.get("name") for m in data.get("models", [])]
                    model_found = any(self.model in m for m in models)
                    return {
                        "status": "connected",
                        "endpoint": self.base_url,
                        "latency_ms": round(latency_ms, 2),
                        "configured_model": self.model,
                        "model_available": model_found,
                        "available_models": models
                    }
                else:
                    return {
                        "status": "error",
                        "endpoint": self.base_url,
                        "status_code": response.status_code,
                        "detail": response.text.strip(),
                        "configured_model": self.model,
                        "latency_ms": round(latency_ms, 2)
                    }
        except httpx.ConnectError as e:
            return {
                "status": "unreachable",
                "endpoint": self.base_url,
                "configured_model": self.model,
                "error": f"Connection refused at {self.base_url}. Ensure Ollama is running (`ollama serve`).",
                "detail": str(e)
            }
        except Exception as e:
            return {
                "status": "failed",
                "endpoint": self.base_url,
                "configured_model": self.model,
                "error": type(e).__name__,
                "detail": str(e)
            }

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        upstream_context: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.2,
        model: Optional[str] = None,
        custom_timeout: Optional[float] = None,
        max_tokens: Optional[int] = 768
    ) -> LLMResponse:
        """
        Executes an inference request through the shared inference engine.
        Locks concurrency to 1 to prevent resource thrashing on local hardware.
        """
        selected_model = model or self.model
        messages = self.context_mgr.prepare_messages(
            system_prompt=system_prompt,
            user_message=user_message,
            upstream_context=upstream_context
        )

        options: Dict[str, Any] = {
            "temperature": temperature,
            "num_ctx": 4096
        }
        if max_tokens:
            options["num_predict"] = max_tokens

        payload: Dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "stream": False,
            "options": options
        }

        if json_mode:
            payload["format"] = "json"

        # Acquire shared inference engine lock
        async with self.semaphore:
            logger.debug(f"Acquired inference slot for model {selected_model}")
            return await self._send_with_retries(payload, custom_timeout=custom_timeout)

    async def _send_with_retries(
        self,
        payload: Dict[str, Any],
        custom_timeout: Optional[float] = None
    ) -> LLMResponse:
        """Executes HTTP request with exponential backoff retry handling."""
        timeout_val = custom_timeout or self.timeout
        timeout_config = httpx.Timeout(timeout_val, connect=20.0, read=timeout_val, write=30.0)
        url = f"{self.base_url}/api/chat"
        last_exception = None

        for attempt in range(1, self.max_retries + 1):
            start_time = time.perf_counter()
            try:
                logger.info(f"Ollama request attempt {attempt}/{self.max_retries} to {url} [model={payload['model']}]")
                async with httpx.AsyncClient(timeout=timeout_config) as client:
                    response = await client.post(url, json=payload)
                    total_latency_ms = (time.perf_counter() - start_time) * 1000.0

                    if response.status_code == 200:
                        res_json = response.json()
                        return self._process_ollama_response(res_json, payload["model"], total_latency_ms)

                    # HTTP Error from Ollama
                    err_msg = f"Ollama HTTP {response.status_code}: {response.text}"
                    logger.error(err_msg)
                    if response.status_code in (404, 400):
                        # Client error (e.g. model not found) - do not retry
                        raise RuntimeError(f"Ollama error: {response.text}")

                    raise httpx.HTTPStatusError(err_msg, request=response.request, response=response)

            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                last_exception = exc
                logger.warning(f"Ollama call failed on attempt {attempt}/{self.max_retries}: {type(exc).__name__} - {exc}")
                if attempt < self.max_retries:
                    backoff = (2 ** (attempt - 1)) * 1.5
                    logger.info(f"Retrying in {backoff:.1f}s...")
                    await asyncio.sleep(backoff)
            except Exception as exc:
                last_exception = exc
                logger.error(f"Unexpected error calling Ollama: {exc}")
                raise

        raise RuntimeError(f"Failed to communicate with Ollama after {self.max_retries} attempts. Last error: {last_exception}")

    def _process_ollama_response(
        self,
        res_json: Dict[str, Any],
        model_name: str,
        total_latency_ms: float
    ) -> LLMResponse:
        """Parses and validates Ollama response and extracts full token/latency telemetry."""
        message = res_json.get("message", {})
        content = message.get("content", "").strip()
        thinking = message.get("thinking", "").strip()

        # For reasoning models (e.g. Qwen 3) in Ollama, thinking holds the generated reasoning
        # if the token limit is reached during the thinking phase or content is empty.
        if not content and thinking:
            content = thinking

        # Response validation
        if not content:
            raise ValueError("Ollama returned an empty response content.")

        # Extract telemetry
        prompt_tokens = res_json.get("prompt_eval_count", 0)
        eval_tokens = res_json.get("eval_count", 0)
        total_tokens = prompt_tokens + eval_tokens

        # Duration fields from Ollama are in nanoseconds
        load_duration_ms = res_json.get("load_duration", 0) / 1_000_000.0
        eval_duration_ms = res_json.get("eval_duration", 0) / 1_000_000.0

        eval_seconds = eval_duration_ms / 1000.0
        tps = (eval_tokens / eval_seconds) if eval_seconds > 0 else 0.0

        telemetry = LLMTelemetry(
            prompt_tokens=prompt_tokens,
            completion_tokens=eval_tokens,
            total_tokens=total_tokens,
            total_latency_ms=round(total_latency_ms, 2),
            load_duration_ms=round(load_duration_ms, 2),
            eval_duration_ms=round(eval_duration_ms, 2),
            tokens_per_second=round(tps, 2),
            model=model_name
        )

        # Parse JSON if structured output requested
        parsed_json = None
        if content.startswith("{") and content.endswith("}"):
            try:
                parsed_json = json.loads(content)
            except Exception:
                pass

        logger.info(
            f"Ollama execution complete: {eval_tokens} tokens generated in {total_latency_ms:.1f}ms "
            f"({tps:.1f} t/s, prompt_tokens={prompt_tokens})"
        )

        return LLMResponse(
            content=content,
            telemetry=telemetry,
            raw_response=res_json,
            parsed_json=parsed_json
        )

# Global dedicated LLM service singleton
llm_service = DedicatedLLMService()
