"""
Pytest configuration and shared fixtures for SWARM-100 testing.
"""

import os
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Create an isolated temporary SQLite database for testing
_temp_dir = tempfile.mkdtemp(prefix="swarm100_test_")
_test_db_path = Path(_temp_dir) / "test_swarm100.db"
os.environ["SWARM_DB_PATH"] = str(_test_db_path)

from backend.config import settings
settings.db_path = _test_db_path

from backend.agents.registry import init_and_seed
from backend.core.orchestrator import orchestrator
from backend.core.task_queue import TaskQueue
from backend.database import get_connection, get_db
from backend.main import app

# Ensure orchestrator uses test database
orchestrator.queue = TaskQueue(_test_db_path)

@pytest.fixture(autouse=True)
def mock_llm_service_for_sandbox_tests(monkeypatch):
    """
    In the sandbox test environment where direct port 11434 is blocked by local proxy,
    provides deterministic Qwen3 responses with full telemetry for fast, reliable unit tests.
    """
    import json
    from backend.core.llm_service import llm_service, LLMResponse, LLMTelemetry

    async def _sandbox_test_chat(system_prompt, user_message, upstream_context=None, json_mode=False, **kwargs):
        on_token = kwargs.get("on_token")
        if on_token:
            import asyncio
            for word in ["Autonomous ", "workforce ", "verified."]:
                if asyncio.iscoroutinefunction(on_token):
                    await on_token(word)
                else:
                    on_token(word)

        content = f"### [Qwen3 4B Deliverable]\nExecuted for: {user_message[:70]}...\nDeliverable formulated compliant with SWARM-100 specifications."
        if json_mode:
            content = json.dumps({"status": "completed", "score": 88.0, "feedback": "Audited and verified."})
        return LLMResponse(
            content=content,
            telemetry=LLMTelemetry(
                prompt_tokens=35,
                completion_tokens=25,
                total_tokens=60,
                total_latency_ms=145.0,
                tokens_per_second=172.4,
                model="qwen3:4b"
            )
        )

    monkeypatch.setattr(llm_service, "chat", _sandbox_test_chat)

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Ensure test database is migrated and seeded once for test session."""
    init_and_seed(_test_db_path)
    yield
    if _test_db_path.exists():
        try:
            _test_db_path.unlink()
        except Exception:
            pass

@pytest.fixture
def db_conn():
    """Yield a direct sqlite3 connection to the test database."""
    with get_connection(_test_db_path) as conn:
        yield conn

@pytest.fixture
def client():
    """FastAPI TestClient pointing to the test database."""
    def _override_get_db():
        with get_connection(_test_db_path) as conn:
            yield conn

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
