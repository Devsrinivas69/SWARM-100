"""
Tests for SWARM-100 Autonomous ReAct Loop Engine
Verifies tool parsing, catalog formatting, iterative execution, and fallback.
"""

import pytest
from unittest.mock import AsyncMock, patch

from backend.core.llm_service import LLMResponse, LLMTelemetry
from backend.core.react_loop import (
    ReActEngine,
    extract_final_answer,
    format_tool_catalog,
    parse_action_and_input,
    react_engine
)


class TestReActParsing:
    def test_format_tool_catalog_includes_safe_tools(self):
        catalog = format_tool_catalog()
        assert "calculator" in catalog
        assert "web_search" in catalog
        assert "restricted_code_tester" not in catalog  # Restricted tools excluded

    def test_parse_action_and_input_standard(self):
        text = """
        Thought: I need to calculate the fare.
        Action: calculator
        Action Input: {"expression": "25 * 4"}
        """
        parsed = parse_action_and_input(text)
        assert parsed is not None
        tool_id, params = parsed
        assert tool_id == "calculator"
        assert params == {"expression": "25 * 4"}

    def test_parse_action_and_input_no_action(self):
        text = "Here is the direct analysis without any tool action."
        parsed = parse_action_and_input(text)
        assert parsed is None

    def test_parse_action_and_input_dirty_json(self):
        text = """
        Thought: I should search for metro stations.
        Action: web_search
        Action Input: {"query": "Indiranagar Metro Bengaluru"}
        """
        parsed = parse_action_and_input(text)
        assert parsed is not None
        tool_id, params = parsed
        assert tool_id == "web_search"
        assert "Indiranagar" in params.get("query", "")

    def test_extract_final_answer_with_explicit_tag(self):
        text = """
        Thought: All data gathered.
        Final Answer:
        # Bengaluru Metro Analysis
        The optimal feeder route connects Indiranagar with Domlur.
        """
        ans = extract_final_answer(text)
        assert ans.startswith("# Bengaluru Metro Analysis")
        assert "Domlur" in ans
        assert "Final Answer:" not in ans

    def test_extract_final_answer_without_tag(self):
        text = "This is a direct report deliverable."
        ans = extract_final_answer(text)
        assert ans == "This is a direct report deliverable."


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
class TestReActEngineExecution:
    async def test_react_engine_direct_answer_turn_1(self):
        """When LLM produces deliverable without tool call, finishes in 1 turn."""
        mock_response = LLMResponse(
            content="Direct market analysis report.",
            telemetry=LLMTelemetry(prompt_tokens=50, completion_tokens=100, total_tokens=150, total_latency_ms=200.0)
        )

        with patch("backend.core.react_loop.llm_service.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = mock_response

            deliverable, tools, tele = await react_engine.execute_react_task(
                agent_id="stratos-01",
                system_prompt="You are a strategist.",
                task_title="Market Strategy",
                task_directives="Directives",
                task_id="t-1",
                goal_id="g-1"
            )

            assert deliverable == "Direct market analysis report."
            assert len(tools) == 0
            assert tele["turns_used"] == 1
            assert tele["total_tokens"] == 150

    async def test_react_engine_executes_tool_and_synthesizes_final_answer(self):
        """When LLM calls a tool in Turn 1 and provides Final Answer in Turn 2."""
        turn_1_resp = LLMResponse(
            content="Thought: Let me calculate total revenue.\nAction: calculator\nAction Input: {\"expression\": \"500000 * 0.15\"}",
            telemetry=LLMTelemetry(total_tokens=100, total_latency_ms=150.0)
        )
        turn_2_resp = LLMResponse(
            content="Thought: Calculation done.\nFinal Answer:\nProjected monthly revenue is ₹75,000.",
            telemetry=LLMTelemetry(total_tokens=120, total_latency_ms=180.0)
        )

        with patch("backend.core.react_loop.llm_service.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [turn_1_resp, turn_2_resp]

            deliverable, tools, tele = await react_engine.execute_react_task(
                agent_id="venture-03",
                system_prompt="You are a financial analyst.",
                task_title="Financial Model",
                task_directives="Calculate margins",
                task_id=None,
                goal_id=None
            )

            assert "75,000" in deliverable
            assert len(tools) == 1
            assert tools[0]["tool_id"] == "calculator"
            assert tools[0]["success"] is True
            assert tele["total_tokens"] == 220

    async def test_react_engine_executes_web_search(self):
        """Verify web_search works within autonomous ReAct loop."""
        turn_1_resp = LLMResponse(
            content="Thought: Let me search for Bengaluru metro details.\nAction: web_search\nAction Input: {\"query\": \"Namma Metro Purple Line\"}",
            telemetry=LLMTelemetry(total_tokens=80, total_latency_ms=100.0)
        )
        turn_2_resp = LLMResponse(
            content="Thought: Information retrieved.\nFinal Answer:\nThe Purple line connects Whitefield to Challaghatta.",
            telemetry=LLMTelemetry(total_tokens=100, total_latency_ms=120.0)
        )
        with patch("backend.core.react_loop.llm_service.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [turn_1_resp, turn_2_resp]
            deliverable, tools, tele = await react_engine.execute_react_task(
                agent_id="recon-01",
                system_prompt="You are a research specialist.",
                task_title="Metro Research",
                task_directives="Find metro lines",
                task_id=None,
                goal_id=None
            )
            assert "Purple line" in deliverable
            assert len(tools) == 1
            assert tools[0]["tool_id"] == "web_search"
            assert tools[0]["success"] is True
            assert tele["tools_count"] == 1
