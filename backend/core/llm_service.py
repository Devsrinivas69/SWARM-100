"""
SWARM-100 Dedicated LLM Service
Async HTTP client for Ollama API (qwen3:4b) with retry handling, context window management,
token/latency telemetry tracking, structured JSON mode, and single-concurrency inference lock.
"""

import asyncio
import json
import logging
import re
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

def sanitize_output_content(text: str) -> str:
    """
    Strips raw <think>...</think> reasoning tags to keep deliverables clean.
    If the model generation was truncated while inside think tags (common with reasoning models
    on smaller token budgets), safely extracts the inner analysis so the task never crashes.
    """
    if not text or not text.strip():
        return ""
    # Check if there is content outside closed <think> blocks
    cleaned = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE).strip()
    if cleaned:
        # Strip any stray tags
        cleaned = re.sub(r'</?think>', '', cleaned, flags=re.IGNORECASE).strip()
        if cleaned:
            return cleaned

    # Safe extraction fallback: if all generation was inside <think>, extract the inner text
    inner_text = re.sub(r'</?think>', '', text, flags=re.IGNORECASE).strip()
    return inner_text

class LLMResponse(BaseModel):
    content: str
    telemetry: LLMTelemetry
    thinking: Optional[str] = None
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
        sys_content = system_prompt.strip()
        sys_tokens = self.estimate_tokens(sys_content)
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
            {"role": "system", "content": sys_content},
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
        timeout: Optional[float] = None,
        connect_timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        inference_concurrency: Optional[int] = None
    ):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = timeout if timeout is not None else settings.ollama_timeout
        self.connect_timeout = connect_timeout if connect_timeout is not None else settings.ollama_connect_timeout
        self.max_retries = max_retries if max_retries is not None else settings.ollama_max_retries
        self.context_mgr = ContextManager(max_context_tokens=settings.max_context_tokens, max_output_tokens=2048)
        self.inference_concurrency = max(1, inference_concurrency if inference_concurrency is not None else settings.max_concurrency)
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
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
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
        max_tokens: Optional[int] = None,
        on_token: Optional[Any] = None,
        purpose: Optional[str] = None,
        provider: Optional[str] = None
    ) -> LLMResponse:
        """
        Executes an inference request through the active provider (Ollama, Groq, Gemini, or OpenAI)
        with automatic fallback, token streaming, and telemetry tracking.
        """
        active_provider = (provider or settings.llm_provider).lower()
        tokens_budget = max_tokens if max_tokens is not None else settings.default_max_tokens
        messages = self.context_mgr.prepare_messages(
            system_prompt=system_prompt,
            user_message=user_message,
            upstream_context=upstream_context
        )

        api_messages = [dict(m) for m in messages]
        if api_messages and api_messages[0]["role"] == "system":
            api_messages[0]["content"] += "\n\nCRITICAL OPERATIONAL RULE: Output your specialist findings and deliverables directly in structured Markdown. Do NOT output <think> or </think> tags. Provide your direct analysis immediately."

        # 1. Cloud routing (Groq, Gemini, OpenAI)
        if active_provider == "groq" and settings.groq_api_key:
            try:
                return await self._send_groq(api_messages, model=model, temperature=temperature, max_tokens=tokens_budget, on_token=on_token)
            except Exception as e:
                logger.warning(f"Groq provider failed ({e}); falling back to local Ollama...")

        elif active_provider == "gemini" and settings.gemini_api_key:
            try:
                return await self._send_gemini(api_messages, model=model, temperature=temperature, max_tokens=tokens_budget, on_token=on_token)
            except Exception as e:
                logger.warning(f"Gemini provider failed ({e}); falling back to local Ollama...")

        elif active_provider == "openai" and settings.openai_api_key:
            try:
                return await self._send_openai(api_messages, model=model, temperature=temperature, max_tokens=tokens_budget, on_token=on_token)
            except Exception as e:
                logger.warning(f"OpenAI provider failed ({e}); falling back to local Ollama...")

        elif active_provider == "hybrid":
            # In hybrid mode: Critic reviews burst to cloud for ultra-fast response if key exists
            if purpose == "critic" and (settings.groq_api_key or settings.gemini_api_key):
                if settings.groq_api_key:
                    try:
                        return await self._send_groq(api_messages, model=model, temperature=temperature, max_tokens=tokens_budget, on_token=on_token)
                    except Exception as e:
                        logger.warning(f"Hybrid Groq critic failed ({e}); falling back to local Ollama...")
                elif settings.gemini_api_key:
                    try:
                        return await self._send_gemini(api_messages, model=model, temperature=temperature, max_tokens=tokens_budget, on_token=on_token)
                    except Exception as e:
                        logger.warning(f"Hybrid Gemini critic failed ({e}); falling back to local Ollama...")

        # 2. Local Ollama execution (Shared inference lock)
        selected_model = model or self.model
        options: Dict[str, Any] = {
            "temperature": temperature,
            "num_ctx": settings.max_context_tokens
        }
        if tokens_budget:
            options["num_predict"] = tokens_budget

        payload: Dict[str, Any] = {
            "model": selected_model,
            "messages": api_messages,
            "stream": on_token is not None,
            "options": options
        }

        if json_mode:
            payload["format"] = "json"

        async with self.semaphore:
            logger.debug(f"Acquired inference slot for model {selected_model}")
            return await self._send_with_retries(payload, custom_timeout=custom_timeout, on_token=on_token)

    async def _send_groq(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        on_token: Optional[Any] = None
    ) -> LLMResponse:
        """Executes high-throughput inference on Groq Cloud API."""
        api_key = settings.groq_api_key
        target_model = model or settings.groq_model
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or settings.default_max_tokens,
            "stream": on_token is not None
        }

        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=40.0) as client:
            if on_token:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    resp.raise_for_status()
                    chunks = []
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            d = json.loads(data_str)
                            delta = d["choices"][0]["delta"].get("content", "")
                            if delta:
                                chunks.append(delta)
                                if asyncio.iscoroutinefunction(on_token):
                                    await on_token(delta)
                                else:
                                    on_token(delta)
                        except Exception:
                            pass
                    content = sanitize_output_content("".join(chunks))
                    latency = (time.perf_counter() - start) * 1000.0
                    return LLMResponse(
                        content=content,
                        telemetry=LLMTelemetry(
                            completion_tokens=len(chunks),
                            total_tokens=len(chunks) + 50,
                            total_latency_ms=round(latency, 2),
                            model=target_model
                        )
                    )
            else:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = sanitize_output_content(data["choices"][0]["message"]["content"])
                latency = (time.perf_counter() - start) * 1000.0
                usage = data.get("usage", {})
                return LLMResponse(
                    content=content,
                    telemetry=LLMTelemetry(
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        total_tokens=usage.get("total_tokens", 0),
                        total_latency_ms=round(latency, 2),
                        model=target_model
                    )
                )

    async def _send_gemini(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        on_token: Optional[Any] = None
    ) -> LLMResponse:
        """Executes inference on Google Gemini API."""
        api_key = settings.gemini_api_key
        target_model = model or settings.gemini_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent?key={api_key}"

        # Convert chat messages to Gemini contents format
        contents = []
        for m in messages:
            role = "user" if m["role"] in ("user", "system") else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens or settings.default_max_tokens
            }
        }

        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            raw_text = ""
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                raw_text = "".join(p.get("text", "") for p in parts)

            content = sanitize_output_content(raw_text)
            if on_token and content:
                if asyncio.iscoroutinefunction(on_token):
                    await on_token(content)
                else:
                    on_token(content)

            latency = (time.perf_counter() - start) * 1000.0
            usage = data.get("usageMetadata", {})
            return LLMResponse(
                content=content,
                telemetry=LLMTelemetry(
                    prompt_tokens=usage.get("promptTokenCount", 0),
                    completion_tokens=usage.get("candidatesTokenCount", 0),
                    total_tokens=usage.get("totalTokenCount", 0),
                    total_latency_ms=round(latency, 2),
                    model=target_model
                )
            )

    async def _send_openai(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        on_token: Optional[Any] = None
    ) -> LLMResponse:
        """Executes inference on OpenAI / OpenRouter compatible API."""
        api_key = settings.openai_api_key
        target_model = model or settings.openai_model
        url = f"{settings.openai_base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or settings.default_max_tokens,
            "stream": False
        }

        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = sanitize_output_content(data["choices"][0]["message"]["content"])
            if on_token and content:
                if asyncio.iscoroutinefunction(on_token):
                    await on_token(content)
                else:
                    on_token(content)

            latency = (time.perf_counter() - start) * 1000.0
            usage = data.get("usage", {})
            return LLMResponse(
                content=content,
                telemetry=LLMTelemetry(
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    total_latency_ms=round(latency, 2),
                    model=target_model
                )
            )

    async def _send_with_retries(
        self,
        payload: Dict[str, Any],
        custom_timeout: Optional[float] = None,
        on_token: Optional[Any] = None
    ) -> LLMResponse:
        """Executes HTTP request with exponential backoff retry handling, streaming support, and separate connect/read timeouts."""
        read_timeout = custom_timeout or self.timeout
        connect_timeout = self.connect_timeout
        timeout_config = httpx.Timeout(read_timeout, connect=connect_timeout, read=read_timeout, write=30.0)
        url = f"{self.base_url}/api/chat"
        last_exception = None

        for attempt in range(1, self.max_retries + 1):
            start_time = time.perf_counter()
            try:
                logger.info(f"Ollama request attempt {attempt}/{self.max_retries} to {url} [model={payload['model']}, stream={payload.get('stream', False)}]")
                async with httpx.AsyncClient(timeout=timeout_config, trust_env=False) as client:
                    if on_token and payload.get("stream", False):
                        async with client.stream("POST", url, json=payload) as stream_resp:
                            if stream_resp.status_code != 200:
                                err_text = await stream_resp.aread()
                                err_msg = f"Ollama HTTP {stream_resp.status_code}: {err_text.decode('utf-8', errors='replace')}"
                                logger.error(err_msg)
                                raise httpx.HTTPStatusError(err_msg, request=stream_resp.request, response=stream_resp)

                            collected_tokens = []
                            final_res = {}
                            async for line in stream_resp.aiter_lines():
                                if not line or not line.strip():
                                    continue
                                try:
                                    chunk = json.loads(line)
                                except Exception:
                                    continue

                                token = chunk.get("message", {}).get("content", "")
                                if token:
                                    collected_tokens.append(token)
                                    if asyncio.iscoroutinefunction(on_token):
                                        await on_token(token)
                                    else:
                                        on_token(token)

                                if chunk.get("done"):
                                    final_res = chunk

                            total_latency_ms = (time.perf_counter() - start_time) * 1000.0
                            final_res["message"] = {"content": "".join(collected_tokens)}
                            return self._process_ollama_response(final_res, payload["model"], total_latency_ms)

                    else:
                        response = await client.post(url, json=payload)
                        total_latency_ms = (time.perf_counter() - start_time) * 1000.0

                        if response.status_code == 200:
                            res_json = response.json()
                            return self._process_ollama_response(res_json, payload["model"], total_latency_ms)

                        err_msg = f"Ollama HTTP {response.status_code}: {response.text}"
                        logger.error(err_msg)
                        if response.status_code in (404, 400):
                            raise RuntimeError(f"Ollama error: {response.text}")

                        raise httpx.HTTPStatusError(err_msg, request=response.request, response=response)

            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError, ValueError) as exc:
                last_exception = exc
                logger.warning(f"Ollama call failed on attempt {attempt}/{self.max_retries}: {type(exc).__name__} - {exc}")
                if attempt < self.max_retries:
                    if isinstance(exc, ValueError) and "options" in payload:
                        cur_pred = payload["options"].get("num_predict", 1536)
                        payload["options"]["num_predict"] = min(4096, cur_pred + 512)
                        logger.info(f"Expanded token budget to {payload['options']['num_predict']} for retry attempt {attempt + 1}")

                    backoff = min(8.0, (2 ** (attempt - 1)) * 1.5)
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
        raw_content = message.get("content", "")
        thinking = message.get("thinking", "").strip()

        # Sanitize deliverable content: strip reasoning tags if they leaked into content
        content = sanitize_output_content(raw_content)

        # Fallback: If Ollama segregated output into the thinking channel (common with Qwen3
        # reasoning mode on constrained CPU token budgets), extract the structured analysis from thinking
        if not content and thinking:
            logger.info("Deliverable content empty; extracting structured analysis from Ollama thinking channel.")
            content = sanitize_output_content(thinking)

        # Validation: Ensure we have actual generated content
        if not content:
            raise ValueError("Ollama returned empty response content and empty thinking tokens.")

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
            thinking=thinking if thinking else None,
            raw_response=res_json,
            parsed_json=parsed_json
        )

    def get_active_provider_info(self) -> Dict[str, Any]:
        """Returns details on the current LLM provider routing state."""
        return {
            "active_provider": settings.llm_provider,
            "ollama": {
                "base_url": self.base_url,
                "model": self.model,
                "concurrency": self.inference_concurrency
            },
            "groq": {
                "configured": bool(settings.groq_api_key),
                "model": settings.groq_model
            },
            "gemini": {
                "configured": bool(settings.gemini_api_key),
                "model": settings.gemini_model
            },
            "openai": {
                "configured": bool(settings.openai_api_key),
                "model": settings.openai_model
            },
            "features": {
                "token_streaming": settings.enable_token_streaming,
                "react_tools": settings.enable_react_tools,
                "critic_retries": settings.max_critic_retries
            }
        }


# Global dedicated LLM service singleton
llm_service = DedicatedLLMService()
