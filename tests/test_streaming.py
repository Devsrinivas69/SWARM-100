"""
Tests for SWARM-100 Live Token Streaming and TokenStreamBuffer
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from backend.core.llm_service import LLMResponse, LLMTelemetry, llm_service
from backend.core.worker_pool import TokenStreamBuffer


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
class TestTokenStreaming:
    async def test_token_stream_buffer_aggregates_and_flushes(self):
        emitted_events = []

        with patch("backend.core.worker_pool.ws_manager.emit_event") as mock_emit:
            mock_emit.side_effect = lambda ev, data: emitted_events.append((ev, data))

            buffer = TokenStreamBuffer(
                task_id="t-stream-1",
                agent_id="recon-01",
                goal_id="g-stream-1",
                flush_interval=1.0  # High interval to test count trigger
            )

            # Add 6 tokens -> triggers flush on count >= 6
            tokens = ["Hello", " ", "world", " ", "from", " "]
            for t in tokens:
                await buffer.add_token(t)

            assert len(emitted_events) == 1
            ev_name, ev_data = emitted_events[0]
            assert ev_name == "token_stream"
            assert ev_data["task_id"] == "t-stream-1"
            assert ev_data["token"] == "Hello world from "

            # Add remaining token and manual flush
            await buffer.add_token("SWARM-100!")
            await buffer.flush()

            assert len(emitted_events) == 2
            assert emitted_events[1][1]["token"] == "SWARM-100!"

    async def test_chat_dispatches_tokens_to_callback(self):
        received_tokens = []

        async def token_collector(t: str):
            received_tokens.append(t)

        mock_chunks = [
            '{"message": {"content": "Autonomous "}, "done": false}\n',
            '{"message": {"content": "workforce "}, "done": false}\n',
            '{"message": {"content": "verified."}, "done": true, "eval_count": 3, "eval_duration": 100000000}\n'
        ]

        class MockStreamResponse:
            status_code = 200
            request = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def aiter_lines(self):
                for c in mock_chunks:
                    yield c

        res = await llm_service.chat(
            system_prompt="System",
            user_message="Hello",
            on_token=token_collector
        )

        assert "".join(received_tokens) == "Autonomous workforce verified."
        assert res.telemetry.total_tokens == 60
