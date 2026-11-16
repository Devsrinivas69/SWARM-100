"""
End-to-End Test Suite for SWARM-100 Central Multi-Agent Orchestrator
Tests all 12 orchestrator steps:
1. Understand natural-language goal
2. Classify task type
3. Identify required capabilities
4. Create structured task plan
5. Divide into independent and dependent subtasks
6. Assign each subtask to suitable specialist agents (from 100 agents)
7. Add tasks to persistent SQLite queue
8. Execute tasks through asynchronous worker pool (concurrency limit)
9. Track dependencies and failures (never silently discard failed tasks)
10. Combine completed outputs
11. Request independent reviews from Team 9 Critic (ARGUS)
12. Return final result
Also tests Pause, Resume, Cancel, and Retry control operations.
"""

import asyncio
import pytest
from fastapi.testclient import TestClient

from backend.core.matcher import match_agent_for_task
from backend.core.orchestrator import orchestrator
from backend.core.planner import classify_task_type, create_task_plan, extract_required_capabilities
from backend.core.task_queue import TaskQueue
from backend.core.worker_pool import WorkerPool
from backend.models.schemas import GoalStatus, TaskStatus

# =============================================================================
# 1. GOAL UNDERSTANDING & CLASSIFICATION TESTS
# =============================================================================

class TestGoalPlanningAndClassification:
    def test_classify_software_development_goal(self):
        text = "Build a distributed REST API with FastAPI and SQLite database"
        task_type = classify_task_type(text, title=text)
        assert task_type == "Software Development"

        caps = extract_required_capabilities(text, task_type)
        assert "software_architecture" in caps
        assert "programming" in caps

    def test_classify_data_analysis_goal(self):
        text = "Clean the customer dataset, run hypothesis tests, and build an analytics chart"
        task_type = classify_task_type(text, title=text)
        assert task_type == "Data Analysis"

        caps = extract_required_capabilities(text, task_type)
        assert "data_cleaning" in caps
        assert "statistics" in caps

    def test_classify_research_goal(self):
        text = "Conduct deep web research on competitor pricing and gather literature evidence"
        task_type = classify_task_type(text, title=text)
        assert task_type == "Research"

        caps = extract_required_capabilities(text, task_type)
        assert "web_research" in caps

    def test_classify_business_strategy_goal(self):
        text = "Calculate TAM, SAM, and SOM for our SaaS product and formulate a pricing model"
        task_type = classify_task_type(text, title=text)
        assert task_type == "Business Strategy"

    def test_task_plan_has_independent_and_dependent_subtasks(self):
        title = "Develop an E-Commerce Backend Service"
        desc = "Design system architecture, threat model, API interfaces, and business logic."
        plan = create_task_plan(title, desc)

        assert plan.task_type == "Software Development"
        assert len(plan.subtasks) >= 3

        # Subtasks with empty dependencies are independent (Phase 1)
        independent_tasks = [t for t in plan.subtasks if len(t.dependencies) == 0]
        assert len(independent_tasks) >= 1, "Must have independent initial tasks"

        # Subtasks with dependencies are dependent (Phase 2+)
        dependent_tasks = [t for t in plan.subtasks if len(t.dependencies) > 0]
        assert len(dependent_tasks) >= 1, "Must have dependent subsequent tasks"

        # Verify assigned agents are valid IDs from the 100 agents
        from backend.agents.definitions import AGENTS
        valid_ids = {a["id"] for a in AGENTS}
        for task in plan.subtasks:
            assert task.assigned_agent_id in valid_ids, f"Invalid agent {task.assigned_agent_id}"

# =============================================================================
# 2. PERSISTENT QUEUE & DEPENDENCY RESOLUTION TESTS
# =============================================================================

class TestPersistentQueue:
    def test_enqueue_goal_and_tasks(self, db_conn):
        queue = orchestrator.queue
        title = "Conduct Competitive Intelligence on Cloud Storage Providers"
        desc = "Research pricing, features, security compliance, and synthesize findings."

        plan = create_task_plan(title, desc)
        goal_id = queue.create_goal(title, desc, concurrency_limit=2)
        task_ids = queue.populate_goal_plan(goal_id, plan)

        assert len(task_ids) == len(plan.subtasks)

        # Inspect goal in SQLite
        goal = queue.get_goal(goal_id)
        assert goal is not None
        assert goal["title"] == title
        assert goal["status"] == GoalStatus.IN_PROGRESS.value
        assert len(goal["tasks"]) == len(task_ids)

        # Initial ready tasks should ONLY be independent tasks (0 dependencies)
        ready = queue.get_ready_tasks(goal_id)
        assert len(ready) >= 1
        for r in ready:
            assert len(r["dependencies"]) == 0

    def test_dependent_tasks_become_ready_only_after_upstream_completes(self, db_conn):
        queue = orchestrator.queue
        goal_id = queue.create_goal("Test Pipeline", "Test dependency unblocking", concurrency_limit=1)

        # Manually create task A (independent) and task B (dependent on A)
        with db_conn:
            db_conn.execute(
                """
                INSERT INTO tasks (id, goal_id, assigned_agent_id, title, priority, dependencies, status, input)
                VALUES ('task-upstream-1', ?, 'forge-01', 'Upstream Task', 5, '[]', 'pending', 'input 1'),
                       ('task-downstream-1', ?, 'forge-02', 'Downstream Task', 5, '["task-upstream-1"]', 'pending', 'input 2')
                """,
                (goal_id, goal_id)
            )

        # Only upstream should be ready
        ready = queue.get_ready_tasks(goal_id)
        ready_ids = [t["id"] for t in ready]
        assert "task-upstream-1" in ready_ids
        assert "task-downstream-1" not in ready_ids

        # Mark upstream task completed
        queue.update_task_status("task-upstream-1", TaskStatus.COMPLETED, output="Upstream result")

        # Now downstream task must be ready
        ready_after = queue.get_ready_tasks(goal_id)
        ready_after_ids = [t["id"] for t in ready_after]
        assert "task-downstream-1" in ready_after_ids

# =============================================================================
# 3. WORKER POOL & CONCURRENCY TESTS
# =============================================================================

class TestWorkerPoolExecution:
    def test_worker_executes_task_and_updates_agent_status(self, db_conn):
        queue = orchestrator.queue
        worker_pool = WorkerPool(concurrency_limit=1, task_queue=queue)

        goal_id = queue.create_goal("Unit Test Goal", "Execution testing", concurrency_limit=1)
        task = {
            "id": "task-worker-test",
            "goal_id": goal_id,
            "assigned_agent_id": "stratos-01",
            "title": "Define Project Scope",
            "dependencies": [],
            "input": "Clarify project objectives and boundaries."
        }

        with db_conn:
            db_conn.execute(
                """
                INSERT INTO tasks (id, goal_id, assigned_agent_id, title, priority, dependencies, status, input)
                VALUES (?, ?, ?, ?, 5, '[]', 'pending', ?)
                """,
                (task["id"], goal_id, task["assigned_agent_id"], task["title"], task["input"])
            )

        result = asyncio.run(worker_pool.execute_task(task))
        assert result["status"] == "completed"
        assert len(result["output"]) > 20

        # Verify task completed in SQLite
        db_task = queue.get_task(task["id"])
        assert db_task["status"] == TaskStatus.COMPLETED.value
        assert db_task["output"] is not None
        assert db_task["started_at"] is not None
        assert db_task["completed_at"] is not None

    def test_failed_task_is_never_silently_discarded(self, db_conn, monkeypatch):
        queue = orchestrator.queue
        worker_pool = WorkerPool(concurrency_limit=1, task_queue=queue)

        goal_id = queue.create_goal("Failure Goal", "Testing failure logging", concurrency_limit=1)
        task = {
            "id": "task-fail-test",
            "goal_id": goal_id,
            "assigned_agent_id": "forge-01",
            "title": "Faulty Task",
            "dependencies": [],
            "input": "Should trigger error handling."
        }

        with db_conn:
            db_conn.execute(
                """
                INSERT INTO tasks (id, goal_id, assigned_agent_id, title, priority, dependencies, status, input)
                VALUES (?, ?, ?, ?, 5, '[]', 'pending', ?)
                """,
                (task["id"], goal_id, task["assigned_agent_id"], task["title"], task["input"])
            )

        # Force an execution error to verify it is caught and recorded
        from backend.core.llm_service import llm_service
        async def mock_fail(*args, **kwargs):
            raise ConnectionResetError("Simulated LLM network socket timeout")

        monkeypatch.setattr(llm_service, "chat", mock_fail)

        # Worker pool captures failure and records it in DB
        res = asyncio.run(worker_pool.execute_task(task))
        assert res["status"] == "failed"
        assert "ConnectionResetError" in res["error"]

        # Check task in DB: Never silently discarded, status=failed, error details preserved
        db_task = queue.get_task(task["id"])
        assert db_task is not None
        assert db_task["status"] == TaskStatus.FAILED.value
        assert "ConnectionResetError" in db_task["error"]
        assert db_task["completed_at"] is not None

# =============================================================================
# 4. FULL ORCHESTRATION PIPELINE TESTS (12 STEPS)
# =============================================================================

class TestFullOrchestrationPipeline:
    def test_full_pipeline_from_goal_to_critic_review(self):
        title = "Formulate a Go-To-Market Pricing Strategy for SaaS"
        desc = "Analyze target buyer personas, model tiered pricing, and estimate customer acquisition cost payback."

        # Step 1-7: Submit Goal
        submit_res = orchestrator.submit_goal(title, desc, concurrency_limit=2)
        goal_id = submit_res["goal_id"]
        assert goal_id.startswith("goal-")
        assert submit_res["task_type"] == "Business Strategy"
        assert submit_res["task_count"] >= 3

        # Step 8-12: Run Goal through Worker Pool, Combine Outputs, and Review
        run_res = asyncio.run(orchestrator.run_goal(goal_id))

        assert run_res["status"] == "completed"
        assert run_res["review_score"] >= 70.0
        assert "ARGUS-01" in run_res["review_feedback"]
        assert len(run_res["final_output"]) > 100

        # Verify final goal in SQLite
        goal = orchestrator.queue.get_goal(goal_id)
        assert goal["status"] == "completed"
        assert goal["final_output"] is not None
        assert goal["review_score"] is not None
        assert goal["completed_at"] is not None

        # Verify all subtasks are completed with outputs
        for task in goal["tasks"]:
            assert task["status"] == "completed"
            assert task["output"] is not None
            assert task["completed_at"] is not None

# =============================================================================
# 5. CONTROL OPERATIONS: PAUSE, RESUME, CANCEL, RETRY
# =============================================================================

class TestControlOperations:
    def test_pause_and_resume_goal(self):
        queue = orchestrator.queue
        goal_id = queue.create_goal("Pausable Goal", "Testing pause resume", concurrency_limit=1)

        # Pause
        assert orchestrator.pause_goal(goal_id)
        goal = queue.get_goal(goal_id)
        assert goal["status"] == "paused"

        # Resume
        assert orchestrator.resume_goal(goal_id)
        goal = queue.get_goal(goal_id)
        assert goal["status"] == "in_progress"

    def test_cancel_goal_cancels_subtasks(self, db_conn):
        queue = orchestrator.queue
        goal_id = queue.create_goal("Cancellable Goal", "Testing cancellation", concurrency_limit=1)

        with db_conn:
            db_conn.execute(
                """
                INSERT INTO tasks (id, goal_id, assigned_agent_id, title, priority, dependencies, status, input)
                VALUES ('task-cancel-1', ?, 'forge-01', 'Subtask 1', 5, '[]', 'pending', 'input 1'),
                       ('task-cancel-2', ?, 'forge-02', 'Subtask 2', 5, '[]', 'running', 'input 2')
                """,
                (goal_id, goal_id)
            )

        assert orchestrator.cancel_goal(goal_id)
        goal = queue.get_goal(goal_id)
        assert goal["status"] == "cancelled"

        t1 = queue.get_task("task-cancel-1")
        t2 = queue.get_task("task-cancel-2")
        assert t1["status"] == "cancelled"
        assert t2["status"] == "cancelled"

    def test_retry_failed_task(self, db_conn):
        queue = orchestrator.queue
        goal_id = queue.create_goal("Retryable Goal", "Testing retries", concurrency_limit=1)

        with db_conn:
            db_conn.execute(
                """
                INSERT INTO tasks (id, goal_id, assigned_agent_id, title, priority, dependencies, status, input, error, retry_count)
                VALUES ('task-retry-1', ?, 'forge-01', 'Task with error', 5, '[]', 'failed', 'input', 'Timeout error', 0)
                """,
                (goal_id,)
            )

        # Retry task
        assert orchestrator.retry_task("task-retry-1")
        task = queue.get_task("task-retry-1")
        assert task["status"] == "pending"
        assert task["error"] is None
        assert task["retry_count"] == 1

# =============================================================================
# 6. REST API ENDPOINTS TESTS
# =============================================================================

class TestOrchestratorAPI:
    def test_api_submit_goal(self, client: TestClient):
        response = client.post(
            "/api/v1/goals",
            json={
                "title": "Design a Distributed Microservices Architecture",
                "description": "Specify service boundaries, communication protocols, and architectural patterns.",
                "concurrency_limit": 1
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert "goal_id" in data
        assert data["task_type"] == "Software Development"
        assert data["task_count"] >= 3

    def test_api_inspect_goal(self, client: TestClient):
        # Create a goal
        sub_res = client.post(
            "/api/v1/goals",
            json={
                "title": "Perform Statistical Trend Forecasting",
                "description": "Analyze dataset metrics, clean anomalies, and compute confidence intervals.",
                "concurrency_limit": 1
            }
        )
        goal_id = sub_res.json()["goal_id"]

        get_res = client.get(f"/api/v1/goals/{goal_id}")
        assert get_res.status_code == 200
        data = get_res.json()
        assert data["id"] == goal_id
        assert data["task_type"] == "Data Analysis"
        assert len(data["tasks"]) >= 3

    def test_api_run_goal_e2e(self, client: TestClient):
        sub_res = client.post(
            "/api/v1/goals",
            json={
                "title": "Investigate AI Agent Workforce Coordination Frameworks",
                "description": "Research academic literature, compare agent architectures, and synthesize findings.",
                "concurrency_limit": 2
            }
        )
        goal_id = sub_res.json()["goal_id"]

        # Run through API
        run_res = client.post(f"/api/v1/goals/{goal_id}/run")
        assert run_res.status_code == 200
        data = run_res.json()
        assert data["status"] == "completed"
        assert data["review_score"] >= 70.0
        assert "ARGUS" in data["review_feedback"]

    def test_api_pause_and_resume(self, client: TestClient):
        sub_res = client.post(
            "/api/v1/goals",
            json={"title": "Test Pausing", "description": "Goal to be paused", "concurrency_limit": 1}
        )
        goal_id = sub_res.json()["goal_id"]

        # Pause
        pause_res = client.post(f"/api/v1/goals/{goal_id}/pause")
        assert pause_res.status_code == 200
        assert pause_res.json()["status"] == "paused"

        # Resume
        resume_res = client.post(f"/api/v1/goals/{goal_id}/resume")
        assert resume_res.status_code == 200
        assert resume_res.json()["status"] == "in_progress"

    def test_api_cancel_goal(self, client: TestClient):
        sub_res = client.post(
            "/api/v1/goals",
            json={"title": "Test Cancelling", "description": "Goal to be cancelled", "concurrency_limit": 1}
        )
        goal_id = sub_res.json()["goal_id"]

        cancel_res = client.post(f"/api/v1/goals/{goal_id}/cancel")
        assert cancel_res.status_code == 200
        assert cancel_res.json()["status"] == "cancelled"

    def test_api_retry_task(self, client: TestClient, db_conn):
        sub_res = client.post(
            "/api/v1/goals",
            json={"title": "Test Retry API", "description": "Goal with failing task", "concurrency_limit": 1}
        )
        goal_id = sub_res.json()["goal_id"]
        goal = client.get(f"/api/v1/goals/{goal_id}").json()
        target_task_id = goal["tasks"][0]["id"]

        # Manually fail the task in DB
        with db_conn:
            db_conn.execute(
                "UPDATE tasks SET status = 'failed', error = 'Network drop' WHERE id = ?",
                (target_task_id,)
            )

        # Retry via API
        retry_res = client.post(f"/api/v1/tasks/{target_task_id}/retry")
        assert retry_res.status_code == 200
        assert retry_res.json()["retried"] is True

        # Inspect task
        task_res = client.get(f"/api/v1/tasks/{target_task_id}")
        assert task_res.json()["status"] == "pending"
        assert task_res.json()["error"] is None
        assert task_res.json()["retry_count"] == 1
