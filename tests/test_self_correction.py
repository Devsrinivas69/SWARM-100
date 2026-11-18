"""
Tests for SWARM-100 Critic Self-Correction Loop
Verifies automated revision cycles upon critic defect detection.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from backend.core.critic import TaskEvaluationResult
from backend.core.llm_service import LLMResponse, LLMTelemetry
from backend.core.task_queue import TaskQueue
from backend.core.worker_pool import WorkerPool
from backend.models.schemas import TaskStatus


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
class TestCriticSelfCorrectionLoop:
    async def test_task_passes_first_try_no_correction_needed(self, db_conn):
        queue = TaskQueue()
        pool = WorkerPool(concurrency_limit=1, task_queue=queue)

        goal_id = queue.create_goal("Test Goal", "Self correction test", concurrency_limit=1)
        task = {
            "id": "t-pass-first",
            "goal_id": goal_id,
            "assigned_agent_id": "stratos-01",
            "title": "Clean Task",
            "dependencies": [],
            "input": "Execute pristine strategic plan."
        }
        with db_conn:
            db_conn.execute(
                "INSERT INTO tasks (id, goal_id, assigned_agent_id, title, priority, dependencies, status, input) VALUES (?, ?, ?, ?, 5, '[]', 'pending', ?)",
                (task["id"], goal_id, task["assigned_agent_id"], task["title"], task["input"])
            )

        initial_eval = TaskEvaluationResult(
            task_id=task["id"],
            agent_id=task["assigned_agent_id"],
            critic_id="argus-06",
            score=88.0,
            passed=True,
            factual_errors=[],
            missing_requirements=[],
            weak_reasoning=[],
            critic_feedback="High quality deliverable."
        )

        with patch("backend.core.worker_pool.react_engine.execute_react_task", new_callable=AsyncMock) as mock_react, \
             patch("backend.core.worker_pool.critic_service.evaluate_task_result", new_callable=AsyncMock) as mock_critic:

            mock_react.return_value = (
                "Pristine strategic output deliverable.",
                [],
                {"total_tokens": 120, "total_latency_ms": 200.0}
            )
            mock_critic.return_value = initial_eval

            res = await pool.execute_task(task)

            assert res["status"] == "completed"
            assert res["evaluation"]["score"] == 88.0
            assert mock_critic.call_count == 1  # Only 1 evaluation, no correction needed

    async def test_task_triggers_self_correction_and_passes(self, db_conn):
        queue = TaskQueue()
        pool = WorkerPool(concurrency_limit=1, task_queue=queue)

        goal_id = queue.create_goal("Test Goal Correction", "Self correction trigger", concurrency_limit=1)
        task = {
            "id": "t-correct-success",
            "goal_id": goal_id,
            "assigned_agent_id": "venture-02",
            "title": "Market Sizing Analysis",
            "dependencies": [],
            "input": "Analyze market size with verified Bengaluru figures."
        }
        with db_conn:
            db_conn.execute(
                "INSERT INTO tasks (id, goal_id, assigned_agent_id, title, priority, dependencies, status, input) VALUES (?, ?, ?, ?, 5, '[]', 'pending', ?)",
                (task["id"], goal_id, task["assigned_agent_id"], task["title"], task["input"])
            )

        # First evaluation: fails with score 55.0
        failing_eval = TaskEvaluationResult(
            task_id=task["id"],
            agent_id=task["assigned_agent_id"],
            critic_id="argus-06",
            score=55.0,
            passed=False,
            factual_errors=["Missing population density numbers"],
            missing_requirements=["Missing price elasticity analysis"],
            weak_reasoning=["Assumption on auto fares unverified"],
            critic_feedback="Market sizing draft is incomplete and lacks empirical density benchmarks."
        )

        # Second evaluation after correction: passes with score 86.0
        passing_eval = TaskEvaluationResult(
            task_id=task["id"],
            agent_id=task["assigned_agent_id"],
            critic_id="argus-06",
            score=86.0,
            passed=True,
            factual_errors=[],
            missing_requirements=[],
            weak_reasoning=[],
            critic_feedback="Thorough revision. All density metrics and competitor pricing verified."
        )

        with patch("backend.core.worker_pool.react_engine.execute_react_task", new_callable=AsyncMock) as mock_react, \
             patch("backend.core.worker_pool.critic_service.evaluate_task_result", new_callable=AsyncMock) as mock_critic, \
             patch("backend.core.worker_pool.llm_service.chat", new_callable=AsyncMock) as mock_chat:

            mock_react.return_value = (
                "Initial flawed market report.",
                [],
                {"total_tokens": 100, "total_latency_ms": 150.0}
            )
            mock_critic.side_effect = [failing_eval, passing_eval]
            mock_chat.return_value = LLMResponse(
                content="Revised market report with verified density figures for Indiranagar and Whitefield.",
                telemetry=LLMTelemetry(total_tokens=150, total_latency_ms=250.0)
            )

            res = await pool.execute_task(task)

            assert res["status"] == "completed"
            assert res["evaluation"]["score"] == 86.0
            assert mock_critic.call_count == 2  # Evaluated twice (initial + post-revision)
            assert "Revised market report" in res["output"]
