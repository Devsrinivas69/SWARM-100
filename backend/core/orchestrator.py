"""
SWARM-100 Central Multi-Agent Orchestrator
Coordinates the 12-step autonomous workforce lifecycle from natural-language goal
to verified final delivery.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from backend.core.critic import critic_service
from backend.core.planner import create_task_plan
from backend.core.task_queue import TaskQueue
from backend.core.tools.registry import tool_registry
from backend.core.websocket_manager import ws_manager
from backend.core.worker_pool import WorkerPool
from backend.database import get_connection
from backend.models.schemas import GoalAnalysis, GoalOut, GoalStatus, TaskStatus

logger = logging.getLogger(__name__)

class SwarmOrchestrator:
    def __init__(self, task_queue: Optional[TaskQueue] = None):
        self.queue = task_queue or TaskQueue()
        self._running_goals: Dict[str, asyncio.Task] = {}

    def submit_goal(
        self,
        title: str,
        description: str,
        concurrency_limit: int = 1
    ) -> Dict[str, Any]:
        """
        Executes Steps 1 to 7:
        1. Understand the goal.
        2. Classify the task type.
        3. Identify required capabilities.
        4. Create a structured task plan.
        5. Divide into independent and dependent subtasks.
        6. Assign each subtask to suitable specialist agents.
        7. Add tasks to a persistent SQLite queue.
        """
        logger.info(f"Submitting goal: '{title}' (concurrency limit: {concurrency_limit})")

        # Step 1-6: Planning & Decomposition
        plan: GoalAnalysis = create_task_plan(title=title, description=description)

        # Step 7: Persist goal and tasks to SQLite queue
        goal_id = self.queue.create_goal(
            title=title,
            description=description,
            concurrency_limit=concurrency_limit
        )
        task_ids = self.queue.populate_goal_plan(goal_id=goal_id, analysis=plan)

        logger.info(f"Goal {goal_id} enqueued with {len(task_ids)} subtasks across {plan.task_type} domain.")

        try:
            ws_manager.emit_event("goal_created", {
                "goal_id": goal_id,
                "title": title,
                "task_type": plan.task_type,
                "task_count": len(task_ids),
                "status": GoalStatus.IN_PROGRESS.value
            })
        except Exception:
            pass

        return {
            "goal_id": goal_id,
            "task_type": plan.task_type,
            "required_capabilities": plan.required_capabilities,
            "task_count": len(task_ids),
            "status": GoalStatus.IN_PROGRESS.value
        }

    async def run_goal(self, goal_id: str) -> Dict[str, Any]:
        """
        Executes Steps 8 to 12:
        8. Execute tasks through asynchronous worker pool.
        9. Track dependencies and failures.
        10. Combine completed outputs.
        11. Request independent reviews from Team 9 Critic.
        12. Return final result.
        """
        goal_data = self.queue.get_goal(goal_id)
        if not goal_data:
            raise ValueError(f"Goal '{goal_id}' not found.")

        concurrency = goal_data.get("concurrency_limit", 1)
        worker_pool = WorkerPool(concurrency_limit=concurrency, task_queue=self.queue)

        logger.info(f"Starting execution loop for goal {goal_id} (pool concurrency: {concurrency})")

        # ---------------------------------------------------------------------
        # Steps 8 & 9: Dependency-aware execution loop
        # ---------------------------------------------------------------------
        while True:
            # Check current goal status (e.g. paused / cancelled)
            current_goal = self.queue.get_goal(goal_id)
            if not current_goal:
                break
            if current_goal["status"] == GoalStatus.PAUSED.value:
                logger.info(f"Goal {goal_id} is paused; holding worker loop.")
                await asyncio.sleep(0.5)
                continue
            if current_goal["status"] == GoalStatus.CANCELLED.value:
                logger.info(f"Goal {goal_id} was cancelled; stopping worker loop.")
                return {"goal_id": goal_id, "status": "cancelled"}

            all_done, any_failed, completed_cnt, total_cnt = self.queue.check_goal_progress(goal_id)

            if all_done:
                logger.info(f"All {total_cnt} tasks completed for goal {goal_id}.")
                break

            # Fetch ready tasks whose prerequisite dependencies are satisfied
            ready_tasks = self.queue.get_ready_tasks(goal_id)

            if not ready_tasks:
                if any_failed:
                    err_msg = f"Goal execution blocked: one or more prerequisite tasks failed."
                    logger.error(err_msg)
                    self.queue.fail_goal(goal_id, err_msg)
                    return {"goal_id": goal_id, "status": "failed", "error": err_msg}

                # Check if tasks are still running in another coroutine or wait
                running_tasks = [t for t in current_goal["tasks"] if t["status"] in ("assigned", "running")]
                if not running_tasks:
                    # Deadlock detection or unresolvable dependencies
                    err_msg = "Task dependency deadlock: no ready tasks and no running tasks."
                    logger.error(err_msg)
                    self.queue.fail_goal(goal_id, err_msg)
                    return {"goal_id": goal_id, "status": "failed", "error": err_msg}

                await asyncio.sleep(0.2)
                continue

            # Dispatch ready tasks up to concurrency limit
            batch = ready_tasks[:concurrency]
            results = await asyncio.gather(*[worker_pool.execute_task(t) for t in batch])

            # Check if any task failed
            for res in results:
                if res.get("status") == "failed":
                    failed_task_id = res.get("task_id")
                    logger.warning(f"Task {failed_task_id} failed: {res.get('error')}")

            await asyncio.sleep(0.05)

        # ---------------------------------------------------------------------
        # Step 10: Combine completed outputs (Synthesis)
        # ---------------------------------------------------------------------
        refreshed_goal = self.queue.get_goal(goal_id)
        combined_deliverable = self._combine_outputs(refreshed_goal)

        # ---------------------------------------------------------------------
        # Step 11: Request independent review from Team 9 Critic
        # ---------------------------------------------------------------------
        review = await critic_service.evaluate_deliverable(
            goal_title=refreshed_goal["title"],
            goal_description=refreshed_goal["description"],
            deliverable_content=combined_deliverable
        )

        # ---------------------------------------------------------------------
        # Step 12: Complete goal and return final result
        # ---------------------------------------------------------------------
        self.queue.complete_goal(
            goal_id=goal_id,
            final_output=combined_deliverable,
            review_score=review.score,
            review_feedback=review.feedback
        )

        logger.info(f"Goal {goal_id} completed with QA Score {review.score}/100.")

        try:
            ws_manager.emit_event("goal_completed", {
                "goal_id": goal_id,
                "title": refreshed_goal["title"],
                "status": "completed",
                "review_score": review.score,
                "review_feedback": review.feedback
            })
        except Exception:
            pass

        return {
            "goal_id": goal_id,
            "status": "completed",
            "final_output": combined_deliverable,
            "review_score": review.score,
            "review_feedback": review.feedback,
            "passed": review.passed
        }

    def _combine_outputs(self, goal_data: Dict[str, Any]) -> str:
        """Synthesizes all completed subtask deliverables into a structured report."""
        sections = [
            f"# SWARM-100 Consolidated Deliverable",
            f"**Goal**: {goal_data['title']}",
            f"**Domain**: {goal_data.get('task_type', 'General')}",
            f"**Total Subtasks Executed**: {len(goal_data.get('tasks', []))}\n",
            "---"
        ]

        for idx, task in enumerate(goal_data.get("tasks", []), 1):
            sections.append(f"## Subtask {idx}: {task['title']}")
            sections.append(f"**Assigned Agent**: `{task['assigned_agent_id']}` | **Priority**: {task['priority']}")
            sections.append(f"**Status**: {task['status'].upper()}")
            task_out = (task.get("output") or "[No Output Generated]").strip()
            sections.append(f"\n{task_out}\n")
            sections.append("---")

        sections.append("### End of Executive Deliverable")
        return "\n\n".join(sections)

    # -------------------------------------------------------------------------
    # Tool Execution Gateway for Specialist Agents
    # -------------------------------------------------------------------------
    async def request_tool_execution(
        self,
        agent_id: str,
        tool_id: str,
        parameters: Dict[str, Any],
        task_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        is_approved: bool = False,
        approved_by: Optional[str] = None,
        justification: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Primary interface for agents to request tool execution through the orchestrator.
        1. Validates that the requesting agent exists in the SWARM-100 registry.
        2. Dispatches to ToolRegistry which enforces permissions, approval gates,
           timeout protection, and audit logging.
        """
        logger.info(f"Agent '{agent_id}' requested tool '{tool_id}' via orchestrator")

        # Validate agent exists
        with get_connection(self.queue.db_path) as conn:
            agent = conn.execute("SELECT id, status FROM agents WHERE id = ?", (agent_id,)).fetchone()
            if not agent:
                raise ValueError(f"Agent '{agent_id}' not found in registry.")

        # Dispatch execution to tool registry
        return await tool_registry.execute_tool(
            tool_id=tool_id,
            agent_id=agent_id,
            parameters=parameters,
            task_id=task_id,
            goal_id=goal_id,
            is_approved=is_approved,
            approved_by=approved_by,
            justification=justification,
        )

    # -------------------------------------------------------------------------
    # Control Operations: Pause, Resume, Cancel, Retry
    # -------------------------------------------------------------------------
    def pause_goal(self, goal_id: str) -> bool:
        return self.queue.pause_goal(goal_id)

    def resume_goal(self, goal_id: str) -> bool:
        return self.queue.resume_goal(goal_id)

    def cancel_goal(self, goal_id: str) -> bool:
        return self.queue.cancel_goal(goal_id)

    def retry_task(self, task_id: str) -> bool:
        return self.queue.retry_task(task_id)

orchestrator = SwarmOrchestrator()
