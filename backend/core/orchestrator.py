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
        concurrency_limit: int = 1,
        workforce_density: str = "adaptive"
    ) -> Dict[str, Any]:
        """
        Executes Steps 1 to 7:
        1. Understand the goal.
        2. Classify the task type.
        3. Identify required capabilities.
        4. Create a structured task plan with customizable workforce density (up to all 100 agents).
        5. Divide into independent and dependent subtasks.
        6. Assign each subtask to suitable specialist agents.
        7. Add tasks to a persistent SQLite queue.
        """
        logger.info(f"Submitting goal: '{title}' (concurrency limit: {concurrency_limit}, density: {workforce_density})")

        # Step 1-6: Planning & Decomposition
        plan: GoalAnalysis = create_task_plan(
            title=title,
            description=description,
            workforce_density=workforce_density
        )

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
                if any_failed:
                    err_msg = f"Goal execution halted: all tasks finished but one or more tasks failed or were blocked."
                    logger.error(err_msg)
                    self.queue.fail_goal(goal_id, err_msg)
                    try:
                        ws_manager.emit_event("goal_failed", {
                            "goal_id": goal_id,
                            "title": current_goal.get("title", ""),
                            "status": "failed",
                            "error": err_msg
                        })
                    except Exception:
                        pass
                    return {"goal_id": goal_id, "status": "failed", "error": err_msg}

                logger.info(f"All {total_cnt} tasks completed successfully for goal {goal_id}.")
                break

            # Fetch ready tasks whose prerequisite dependencies are satisfied
            ready_tasks = self.queue.get_ready_tasks(goal_id)

            if not ready_tasks:
                # Check if tasks are still running in worker coroutines
                running_tasks = [t for t in current_goal["tasks"] if t["status"] in ("assigned", "running")]
                if running_tasks:
                    await asyncio.sleep(0.2)
                    continue

                # No ready tasks and no running tasks: DAG execution is blocked
                all_tasks = current_goal.get("tasks", [])
                pending_tasks = [t for t in all_tasks if t["status"] == TaskStatus.PENDING.value]

                # Transition any stranded pending tasks with unsatisfied dependencies to blocked
                for pt in pending_tasks:
                    self.queue.update_task_status(
                        pt["id"],
                        TaskStatus.BLOCKED,
                        error="Blocked: prerequisite dependencies unfulfilled or terminally failed."
                    )
                    try:
                        ws_manager.emit_event("task_blocked", {
                            "task_id": pt["id"],
                            "goal_id": goal_id,
                            "reason": "Prerequisite dependencies unfulfilled"
                        })
                    except Exception:
                        pass

                failed_count = sum(1 for t in all_tasks if t["status"] == TaskStatus.FAILED.value)
                blocked_count = sum(1 for t in all_tasks if t["status"] == TaskStatus.BLOCKED.value) + len(pending_tasks)

                err_msg = f"Goal execution halted: {failed_count} task(s) failed, {blocked_count} task(s) blocked."
                logger.error(err_msg)
                self.queue.fail_goal(goal_id, err_msg)
                try:
                    ws_manager.emit_event("goal_failed", {
                        "goal_id": goal_id,
                        "title": current_goal.get("title", ""),
                        "status": "failed",
                        "error": err_msg
                    })
                except Exception:
                    pass
                return {"goal_id": goal_id, "status": "failed", "error": err_msg}

            # Dispatch ready tasks up to concurrency limit
            batch = ready_tasks[:concurrency]
            results = await asyncio.gather(*[worker_pool.execute_task(t) for t in batch])

            # Process execution outcomes and handle retries or failure cascades
            for res in results:
                if res.get("status") == "failed":
                    failed_task_id = res.get("task_id")
                    err = res.get("error", "Unknown error")
                    t_record = self.queue.get_task(failed_task_id)
                    retries_done = t_record.get("retry_count", 0) if t_record else 0
                    max_retries = t_record.get("max_retries", 3) if t_record else 3

                    if retries_done < max_retries:
                        logger.info(f"Task {failed_task_id} failed ({err}). Retrying (attempt {retries_done + 1}/{max_retries})...")
                        self.queue.retry_task(failed_task_id)
                        try:
                            ws_manager.emit_event("task_retrying", {
                                "task_id": failed_task_id,
                                "goal_id": goal_id,
                                "retry_count": retries_done + 1,
                                "max_retries": max_retries,
                                "error": err
                            })
                        except Exception:
                            pass
                    else:
                        logger.warning(f"Task {failed_task_id} exhausted all {max_retries} retries: {err}. Propagating failure downstream.")
                        blocked = self.queue.propagate_task_failure(
                            goal_id=goal_id,
                            failed_task_id=failed_task_id,
                            reason=f"Prerequisite task {failed_task_id} failed: {err}"
                        )
                        if blocked:
                            logger.info(f"Marked {len(blocked)} downstream task(s) as BLOCKED: {blocked}")

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

    def start_goal_execution(self, goal_id: str) -> Optional[asyncio.Task]:
        """
        Dispatches goal execution as a managed background asyncio Task if not already running.
        Guarantees that the worker loop survives HTTP request closures, browser reloads, and navigation.
        Safely adapts to running event loops, thread execution, or test environments.
        """
        existing_task = self._running_goals.get(goal_id)
        if existing_task and not existing_task.done():
            logger.info(f"Goal {goal_id} execution is already active in background.")
            return existing_task

        logger.info(f"Spawning background execution task for goal {goal_id}...")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

        if loop.is_running():
            task = loop.create_task(self.run_goal(goal_id))
            self._running_goals[goal_id] = task

            def _on_done(t):
                self._running_goals.pop(goal_id, None)
                if t.cancelled():
                    logger.info(f"Background execution for goal {goal_id} was cancelled.")
                elif t.exception():
                    logger.error(f"Background execution for goal {goal_id} failed with error: {t.exception()}")
                else:
                    logger.info(f"Background execution for goal {goal_id} concluded successfully.")

            task.add_done_callback(_on_done)
            return task
        else:
            logger.debug(f"Event loop is not running; skipping background task for goal {goal_id}.")
            return None

    # -------------------------------------------------------------------------
    # Control Operations: Pause, Resume, Cancel, Retry
    # -------------------------------------------------------------------------
    def pause_goal(self, goal_id: str) -> bool:
        return self.queue.pause_goal(goal_id)

    def resume_goal(self, goal_id: str) -> bool:
        ok = self.queue.resume_goal(goal_id)
        if ok:
            self.start_goal_execution(goal_id)
        return ok

    def cancel_goal(self, goal_id: str) -> bool:
        ok = self.queue.cancel_goal(goal_id)
        existing_task = self._running_goals.get(goal_id)
        if existing_task and not existing_task.done():
            existing_task.cancel()
        return ok

    def retry_task(self, task_id: str) -> bool:
        return self.queue.retry_task(task_id)

orchestrator = SwarmOrchestrator()
