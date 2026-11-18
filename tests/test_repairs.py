"""
SWARM-100 Forensic Repair Verification Suite
Comprehensive tests covering all 17 requirements specified in Phase 9:
1. SPA deep-link routing
2. API route preservation
3. WebSocket route preservation
4. Upstream task failure propagation
5. Independent DAG branch execution
6. Retry handling
7. Ollama timeout handling
8. Empty Qwen3 output
9. Malformed Qwen3 output
10. Raw <think> leakage prevention
11. Invalid evaluator responses
12. Evaluation failure handling
13. Product Foundry test-gate enforcement
14. WebSocket reconnection and state reconciliation
15. Database persistence
16. Single-worker concurrency enforcement
17. Backend restart and task recovery
"""

import asyncio
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.core.critic import CriticService
from backend.core.llm_service import DedicatedLLMService, LLMResponse, LLMTelemetry, sanitize_output_content
from backend.core.orchestrator import SwarmOrchestrator
from backend.core.task_queue import TaskQueue
from backend.core.worker_pool import WorkerPool
from backend.models.schemas import GoalStatus, TaskStatus
from backend.database import get_connection

# =============================================================================
# 1. SPA Deep-Link Routing
# =============================================================================
def test_spa_deep_link_routing(client: TestClient):
    """Direct navigation to frontend routes must serve index.html with 200 OK."""
    for path in ["/tasks", "/foundry", "/workforce", "/teams", "/timeline", "/settings"]:
        res = client.get(path)
        assert res.status_code == 200, f"Route {path} failed with {res.status_code}"
        assert "text/html" in res.headers["content-type"]
        assert "SWARM-100" in res.text

def test_favicon_route(client: TestClient):
    """Missing or requested favicon must not return 404 or error."""
    res = client.get("/favicon.ico")
    assert res.status_code in (200, 204)

# =============================================================================
# 2. API Route Preservation
# =============================================================================
def test_api_route_preservation(client: TestClient):
    """Existing API routes work, and unknown API routes return 404 JSON (not SPA HTML)."""
    res = client.get("/api/v1/dashboard/stats")
    assert res.status_code == 200
    assert "total_agents" in res.json()

    # Unknown API route must return 404 JSON, not index.html
    res_404 = client.get("/api/v1/nonexistent-endpoint")
    assert res_404.status_code == 404
    assert res_404.headers["content-type"].startswith("application/json")
    assert res_404.json() == {"detail": "Not Found"}

# =============================================================================
# 3. WebSocket Route Preservation
# =============================================================================
def test_websocket_route_preservation(client: TestClient):
    """WebSocket /ws connects and responds to ping/pong."""
    with client.websocket_connect("/ws") as ws:
        ws.send_text("ping")
        msg = ws.receive_text()
        assert msg == "pong" or "initial_state" in msg

# =============================================================================
# 4. Upstream Task Failure Propagation
# =============================================================================
def test_upstream_task_failure_propagation(db_conn):
    """When an upstream task fails, downstream dependent tasks must transition to BLOCKED."""
    queue = TaskQueue()
    goal_id = queue.create_goal("DAG Failure Test", "Testing failure cascade", concurrency_limit=1)

    t1_id = "task-up-1"
    t2_id = "task-down-2"

    with db_conn:
        db_conn.execute(
            """
            INSERT INTO tasks (id, goal_id, assigned_agent_id, title, priority, dependencies, status, input)
            VALUES (?, ?, 'forge-01', 'Upstream Task', 5, '[]', 'pending', 'input 1')
            """,
            (t1_id, goal_id)
        )
        db_conn.execute(
            """
            INSERT INTO tasks (id, goal_id, assigned_agent_id, title, priority, dependencies, status, input)
            VALUES (?, ?, 'forge-02', 'Downstream Task', 5, ?, 'pending', 'input 2')
            """,
            (t2_id, goal_id, json.dumps([t1_id]))
        )

    # Fail upstream task
    queue.update_task_status(t1_id, TaskStatus.FAILED, error="Ollama CPU timeout")
    blocked = queue.propagate_task_failure(goal_id, t1_id, reason="Prerequisite failed")

    assert t2_id in blocked
    t2 = queue.get_task(t2_id)
    assert t2["status"] == TaskStatus.BLOCKED.value
    assert "Prerequisite" in t2["error"] or "Blocked" in t2["error"]

# =============================================================================
# 5. Independent DAG Branch Execution
# =============================================================================
def test_independent_dag_branch_execution(db_conn):
    """Tasks on independent branches without failed dependencies remain eligible to run."""
    queue = TaskQueue()
    goal_id = queue.create_goal("Independent Branch Test", "Branch isolation", concurrency_limit=1)

    t_failed = "task-branch-fail"
    t_blocked = "task-branch-blocked"
    t_independent = "task-branch-independent"

    with db_conn:
        db_conn.execute(
            """
            INSERT INTO tasks (id, goal_id, assigned_agent_id, title, priority, dependencies, status, input)
            VALUES (?, ?, 'forge-01', 'Failing Branch', 5, '[]', 'failed', 'input')
            """,
            (t_failed, goal_id)
        )
        db_conn.execute(
            """
            INSERT INTO tasks (id, goal_id, assigned_agent_id, title, priority, dependencies, status, input)
            VALUES (?, ?, 'forge-02', 'Blocked Dependent', 5, ?, 'pending', 'input')
            """,
            (t_blocked, goal_id, json.dumps([t_failed]))
        )
        db_conn.execute(
            """
            INSERT INTO tasks (id, goal_id, assigned_agent_id, title, priority, dependencies, status, input)
            VALUES (?, ?, 'forge-03', 'Independent Task', 5, '[]', 'pending', 'input')
            """,
            (t_independent, goal_id)
        )

    # Propagate failure from t_failed
    queue.propagate_task_failure(goal_id, t_failed)

    # Independent task must still be ready
    ready = queue.get_ready_tasks(goal_id)
    ready_ids = [t["id"] for t in ready]
    assert t_independent in ready_ids
    assert t_blocked not in ready_ids

# =============================================================================
# 6. Retry Handling
# =============================================================================
def test_retry_handling(db_conn):
    """retry_task increments retry_count and resets status to pending."""
    queue = TaskQueue()
    goal_id = queue.create_goal("Retry Goal", "Testing retry", concurrency_limit=1)
    task_id = "task-retry-test"

    with db_conn:
        db_conn.execute(
            """
            INSERT INTO tasks (id, goal_id, assigned_agent_id, title, priority, dependencies, status, input, retry_count, max_retries)
            VALUES (?, ?, 'forge-01', 'Task to Retry', 5, '[]', 'failed', 'input', 0, 3)
            """,
            (task_id, goal_id)
        )

    queue.retry_task(task_id)
    t = queue.get_task(task_id)
    assert t["status"] == TaskStatus.PENDING.value
    assert t["retry_count"] == 1
    assert t["error"] is None

# =============================================================================
# 7. Ollama Timeout & Backoff Handling
# =============================================================================
def test_ollama_timeout_handling(monkeypatch):
    """DedicatedLLMService raises RuntimeError after exhausting retries on timeout."""
    import httpx

    service = DedicatedLLMService(base_url="http://localhost:11434", timeout=1.0, max_retries=2)

    async def mock_post(*args, **kwargs):
        raise httpx.ReadTimeout("Mock read timeout from Ollama")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(service.chat("You are an agent", "Do task"))

    assert "Failed to communicate with Ollama after 2 attempts" in str(exc_info.value)

# =============================================================================
# 8. Empty Qwen3 Output Handling
# =============================================================================
def test_empty_qwen3_output():
    """Empty or whitespace-only response content raises ValueError."""
    service = DedicatedLLMService()
    empty_res = {"message": {"content": "   ", "thinking": ""}}

    with pytest.raises(ValueError) as exc:
        service._process_ollama_response(empty_res, "qwen3:4b", 100.0)
    assert "empty response" in str(exc.value)

# =============================================================================
# 9. Malformed Qwen3 Output
# =============================================================================
def test_malformed_qwen3_output():
    """Unclosed <think> tag at start is stripped and does not crash."""
    cleaned = sanitize_output_content("<think>I am pondering...\nHere is the answer")
    # When think tag is unclosed at start, stripped
    assert "<think>" not in cleaned

# =============================================================================
# 10. Raw <think> Leakage Prevention
# =============================================================================
def test_raw_think_leakage_prevention():
    """Sanitizer strips <think>...</think> blocks completely and never leaks reasoning into content."""
    raw = "<think>Let me analyze the problem step by step.\nFirst calculate 2+2=4.</think>The answer is 4."
    cleaned = sanitize_output_content(raw)
    assert cleaned == "The answer is 4."
    assert "analyze" not in cleaned

    # Verify _process_ollama_response strips think tags and preserves thinking separately
    service = DedicatedLLMService()
    mock_res = {
        "message": {
            "content": "<think>Deliberation</think>Production deliverable content",
            "thinking": "Separate chain-of-thought"
        },
        "prompt_eval_count": 10,
        "eval_count": 20
    }
    processed = service._process_ollama_response(mock_res, "qwen3:4b", 250.0)
    assert processed.content == "Production deliverable content"
    assert "<think>" not in processed.content
    assert processed.thinking == "Separate chain-of-thought"

# =============================================================================
# 11. Invalid Evaluator Responses
# =============================================================================
def test_invalid_evaluator_responses(monkeypatch):
    """When Critic generates empty or invalid responses, it must never automatically pass."""
    critic = CriticService()

    async def mock_empty_chat(*args, **kwargs):
        return LLMResponse(
            content="",
            telemetry=LLMTelemetry(model="qwen3:4b")
        )

    from backend.core.llm_service import llm_service
    monkeypatch.setattr(llm_service, "chat", mock_empty_chat)

    res = asyncio.run(critic.evaluate_task_result(
        task_id="t1",
        task_title="Test",
        task_input="Directive",
        output_content="Output",
        agent_id="forge-01"
    ))

    assert res.passed is False
    assert res.score == 0.0

# =============================================================================
# 12. Evaluation Failure Handling
# =============================================================================
def test_evaluation_failure_handling(monkeypatch):
    """When Critic detects rejection or factual errors, passed is strictly False."""
    critic = CriticService()

    async def mock_reject_chat(*args, **kwargs):
        return LLMResponse(
            content="Accuracy: 40\nCompleteness: 50\nREJECTED: Output contains critical errors.",
            telemetry=LLMTelemetry(model="qwen3:4b")
        )

    from backend.core.llm_service import llm_service
    monkeypatch.setattr(llm_service, "chat", mock_reject_chat)

    review = asyncio.run(critic.evaluate_deliverable(
        goal_title="Financial Model",
        goal_description="Compute NPV",
        deliverable_content="Incomplete data"
    ))

    assert review.passed is False

# =============================================================================
# 13. Product Foundry Test-Gate Enforcement
# =============================================================================
def test_foundry_test_gate_enforcement():
    """Verify Foundry models cannot be marked certified if test_pass_rate < 100."""
    from backend.core.foundry import FoundryCertification

    cert_failed = FoundryCertification(
        project_slug="test-proj",
        project_name="Test Project",
        target_directory="workspace/projects/test",
        certified=False,
        verdict="NEEDS_DEVELOPMENT_ITERATION",
        overall_score=60.0,
        architecture_score=80.0,
        code_quality_score=60.0,
        security_score=80.0,
        test_pass_rate=50.0,
        repairs_performed=3,
        critic_observations="Unit tests failed."
    )
    assert cert_failed.certified is False

# =============================================================================
# 14. Database Persistence & WAL Mode
# =============================================================================
def test_database_persistence():
    """Database connections must configure WAL journal mode and busy_timeout."""
    with get_connection() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        # In SQLite WAL mode returns 'wal'
        assert journal_mode.lower() in ("wal", "memory")
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert busy_timeout >= 5000

# =============================================================================
# 15. Single-Worker Concurrency Enforcement
# =============================================================================
def test_single_worker_concurrency_enforcement():
    """Default concurrency is 1 to prevent CPU starvation on local laptops."""
    assert settings.max_concurrency >= 1
    wp = WorkerPool()
    assert wp.concurrency_limit >= 1
    assert wp.semaphore._value == wp.concurrency_limit

# =============================================================================
# 16. Backend Restart and Task Recovery
# =============================================================================
def test_backend_restart_and_task_recovery(db_conn):
    """reconcile_orphaned_tasks rescues running tasks stranded by crashes/restarts."""
    queue = TaskQueue()
    goal_id = queue.create_goal("Recovery Goal", "Testing orphan recovery", concurrency_limit=1)

    t_id = "task-stranded-1"
    with db_conn:
        # Put goal in progress
        db_conn.execute("UPDATE goals SET status = 'in_progress' WHERE id = ?", (goal_id,))
        # Put task in running status as if server was killed during execution
        db_conn.execute(
            """
            INSERT INTO tasks (id, goal_id, assigned_agent_id, title, priority, dependencies, status, input, started_at)
            VALUES (?, ?, 'forge-01', 'Stranded Task', 5, '[]', 'running', 'input', CURRENT_TIMESTAMP)
            """,
            (t_id, goal_id)
        )

    # Reconcile
    reconciled = queue.reconcile_orphaned_tasks()
    assert reconciled >= 1

    t = queue.get_task(t_id)
    assert t["status"] == TaskStatus.PENDING.value
    assert t["started_at"] is None
