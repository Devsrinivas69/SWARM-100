"""
Test Suite for SWARM-100 Dedicated LLM Service
Tests:
- Async HTTP communication & error handling
- Configurable model selection
- Context size management & truncation safeguards
- Token and latency telemetry tracking
- Single-concurrency shared inference lock
- Structured JSON output parsing
- API connection probe and model execution endpoints
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from backend.core.llm_service import ContextManager, DedicatedLLMService, LLMResponse, LLMTelemetry

# =============================================================================
# 1. CONTEXT SIZE MANAGEMENT TESTS
# =============================================================================

class TestContextManager:
    def test_token_estimation(self):
        cm = ContextManager()
        text = "Hello world! This is a test of token estimation."
        tokens = cm.estimate_tokens(text)
        assert tokens > 0
        assert tokens == len(text) // 4

    def test_prepare_messages_without_upstream(self):
        cm = ContextManager(max_context_tokens=1000)
        messages = cm.prepare_messages(
            system_prompt="You are a research specialist.",
            user_message="Find data on global solar energy."
        )
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a research specialist."
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Find data on global solar energy."

    def test_prepare_messages_with_upstream_within_budget(self):
        cm = ContextManager(max_context_tokens=4000)
        messages = cm.prepare_messages(
            system_prompt="You are an analyst.",
            user_message="Analyze the solar trends.",
            upstream_context="Solar energy grew by 24% year over year in 2025."
        )
        assert len(messages) == 2
        assert "Prerequisite Context" in messages[1]["content"]
        assert "Solar energy grew by 24%" in messages[1]["content"]

    def test_context_truncation_when_exceeding_budget(self):
        # Set artificially small context budget to trigger context guard
        cm = ContextManager(max_context_tokens=300, max_output_tokens=100)
        massive_context = "Data point alpha beta gamma delta. " * 500 # ~17,500 chars

        messages = cm.prepare_messages(
            system_prompt="System prompt.",
            user_message="Core task directive.",
            upstream_context=massive_context
        )
        assert len(messages) == 2
        user_content = messages[1]["content"]
        assert "Context truncated to fit context budget" in user_content
        # Ensure total message length is bounded
        assert len(user_content) < len(massive_context)

# =============================================================================
# 2. TELEMETRY & INFERENCE ENGINE TESTS
# =============================================================================

class TestDedicatedLLMService:
    def test_telemetry_calculation_from_ollama_response(self):
        service = DedicatedLLMService(model="qwen3:4b")

        mock_ollama_json = {
            "model": "qwen3:4b",
            "message": {
                "role": "assistant",
                "content": "Autonomous agents require clear role boundaries and shared goals."
            },
            "prompt_eval_count": 45,
            "eval_count": 20,
            "load_duration": 500_000_000,    # 500 ms in ns
            "eval_duration": 1_000_000_000,  # 1000 ms in ns
            "total_duration": 1_600_000_000
        }

        resp = service._process_ollama_response(
            res_json=mock_ollama_json,
            model_name="qwen3:4b",
            total_latency_ms=1600.0
        )

        assert resp.content == "Autonomous agents require clear role boundaries and shared goals."
        assert resp.telemetry.prompt_tokens == 45
        assert resp.telemetry.completion_tokens == 20
        assert resp.telemetry.total_tokens == 65
        assert resp.telemetry.load_duration_ms == 500.0
        assert resp.telemetry.eval_duration_ms == 1000.0
        assert resp.telemetry.tokens_per_second == 20.0
        assert resp.telemetry.model == "qwen3:4b"

    def test_structured_json_parsing(self):
        service = DedicatedLLMService(model="qwen3:4b")
        mock_json_content = '{"verdict": "pass", "score": 92.5, "issues": []}'

        mock_ollama_json = {
            "model": "qwen3:4b",
            "message": {"role": "assistant", "content": mock_json_content},
            "prompt_eval_count": 30,
            "eval_count": 15,
            "eval_duration": 500_000_000
        }

        resp = service._process_ollama_response(mock_ollama_json, "qwen3:4b", 500.0)
        assert resp.parsed_json is not None
        assert resp.parsed_json["verdict"] == "pass"
        assert resp.parsed_json["score"] == 92.5

    def test_empty_response_validation_raises_error(self):
        service = DedicatedLLMService()
        mock_empty_json = {
            "model": "qwen3:4b",
            "message": {"role": "assistant", "content": "   "}
        }
        with pytest.raises(ValueError):
            service._process_ollama_response(mock_empty_json, "qwen3:4b", 100.0)

    def test_single_concurrency_semaphore_lock(self):
        service = DedicatedLLMService(inference_concurrency=1)
        sem = service.semaphore
        assert sem._value == 1

        # Simulate lock acquisition
        async def mock_call():
            async with service.semaphore:
                assert service.semaphore._value == 0
                await asyncio.sleep(0.01)

        asyncio.run(mock_call())
        assert service.semaphore._value == 1

# =============================================================================
# 3. FASTAPI LLM ENDPOINTS TESTS
# =============================================================================

class TestLLMEndpoints:
    def test_connection_endpoint(self, client: TestClient):
        response = client.get("/api/v1/llm/connection")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "endpoint" in data
        assert "configured_model" in data
        assert data["configured_model"] == "qwen3:4b"

    def test_model_test_endpoint_with_mocked_ollama(self, client: TestClient, monkeypatch):
        from backend.core.llm_service import llm_service

        # Mock an actual Ollama response
        async def mock_chat(*args, **kwargs):
            return LLMResponse(
                content="1. Separation of concerns\n2. Decentralized specialization\n3. Verification feedback loops",
                telemetry=LLMTelemetry(
                    prompt_tokens=25,
                    completion_tokens=18,
                    total_tokens=43,
                    total_latency_ms=320.5,
                    tokens_per_second=56.1,
                    model="qwen3:4b"
                )
            )

        monkeypatch.setattr(llm_service, "chat", mock_chat)

        response = client.post(
            "/api/v1/llm/test",
            json={
                "system_prompt": "You are a test reviewer.",
                "prompt": "List 3 principles."
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["model"] == "qwen3:4b"
        assert "Separation of concerns" in data["content"]
        assert data["prompt_tokens"] == 25
        assert data["completion_tokens"] == 18
        assert data["total_tokens"] == 43
        assert data["total_latency_ms"] == 320.5
        assert data["tokens_per_second"] == 56.1
