"""
SWARM-100 Asynchronous Worker Pool
Enforces configurable concurrency limits (default 1) using asyncio Semaphore.
Integrates with the 3-tier persistent memory system and automated critic reviews:
- Injects previous lessons, project context, and global knowledge before execution.
- Audits completed outputs with Team 9 Critic for factual errors, missing requirements, and reasoning flaws.
- Automatically records successful approaches and failure patterns into persistent memory.
"""

import asyncio
import logging
import traceback
from typing import Any, Dict, List, Optional

from backend.agents.definitions import AGENTS
from backend.agents.registry import get_agent_by_id, update_agent_score, update_agent_status
from backend.core.critic import critic_service
from backend.core.llm_service import llm_service
from backend.core.memory import memory_service
from backend.core.task_queue import TaskQueue
from backend.core.websocket_manager import ws_manager
from backend.database import get_connection
from backend.models.schemas import TaskStatus

logger = logging.getLogger("swarm100.worker_pool")

class WorkerPool:
    def __init__(self, concurrency_limit: int = 1, task_queue: Optional[TaskQueue] = None):
        self.concurrency_limit = max(1, concurrency_limit)
        self._semaphore: Optional[asyncio.Semaphore] = None
        self.queue = task_queue or TaskQueue()
        self.memory = memory_service
        self._active_workers = 0

    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.concurrency_limit)
        return self._semaphore

    def set_concurrency_limit(self, limit: int) -> None:
        """Dynamically adjusts the concurrency limit."""
        self.concurrency_limit = max(1, limit)
        self._semaphore = asyncio.Semaphore(self.concurrency_limit)
        logger.info(f"WorkerPool concurrency limit updated to: {self.concurrency_limit}")

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a single task within the concurrency limit:
        1. Injects relevant previous lessons and project context from memory.
        2. Dispatches to assigned specialist agent via dedicated LLM service.
        3. Invokes Critic agent to audit for factual errors, missing requirements, and weak reasoning.
        4. Persists verified lessons, successful approaches, or failure patterns to SQLite.
        """
        task_id = task["id"]
        agent_id = task["assigned_agent_id"]
        goal_id = task["goal_id"]

        async with self.semaphore:
            self._active_workers += 1
            logger.info(f"Worker acquired slot for task {task_id} (active: {self._active_workers}/{self.concurrency_limit})")

            # 1. State transition: Assigned -> Running
            self.queue.update_task_status(task_id, TaskStatus.ASSIGNED)
            self.queue.update_task_status(task_id, TaskStatus.RUNNING)

            try:
                ws_manager.emit_event("task_running", {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "goal_id": goal_id,
                    "title": task["title"]
                })
            except Exception:
                pass

            with get_connection(self.queue.db_path) as conn:
                update_agent_status(conn, agent_id, "busy")

            try:
                # 2. Gather context from upstream completed dependencies
                upstream_outputs: List[str] = []
                for dep_id in task.get("dependencies", []):
                    dep_task = self.queue.get_task(dep_id)
                    if dep_task and dep_task.get("output"):
                        upstream_outputs.append(
                            f"--- Upstream Deliverable from Task [{dep_task['title']}] ---\n{dep_task['output']}"
                        )

                # 3. Memory Retrieval: Inject previous agent lessons, project context & global knowledge
                memory_context = self.memory.retrieve_context_for_task(
                    agent_id=agent_id,
                    goal_id=goal_id,
                    task_title=task["title"],
                    task_type="General"
                )

                context_blocks = [
                    f"Task Title: {task['title']}",
                    f"Directives:\n{task['input']}"
                ]
                if memory_context:
                    context_blocks.insert(0, f"=== RELEVANT HISTORICAL MEMORY & LESSONS ===\n{memory_context}\n===========================================")

                if upstream_outputs:
                    context_blocks.append("\nPrerequisite Artifacts:\n" + "\n\n".join(upstream_outputs))

                upstream_text = "\n\n".join(upstream_outputs) if upstream_outputs else None
                task_user_message = "\n\n".join(context_blocks)

                # 4. Retrieve agent's specific behavioral system instructions
                agent_profile = None
                with get_connection(self.queue.db_path) as conn:
                    agent_profile = get_agent_by_id(conn, agent_id)

                if not agent_profile:
                    agent_profile = next((a for a in AGENTS if a["id"] == agent_id), None)

                sys_prompt = agent_profile["system_prompt"] if agent_profile else "You are an autonomous specialist agent."

                # 5. Execute through dedicated LLM service
                llm_response = await llm_service.chat(
                    system_prompt=sys_prompt,
                    user_message=task_user_message,
                    upstream_context=upstream_text
                )

                output_content = llm_response.content
                telemetry = llm_response.telemetry

                if not output_content or not output_content.strip():
                    raise RuntimeError(f"Agent {agent_id} generated empty output for task {task_id}.")

                # 6. Ask Critic Agent to Review Completed Task
                eval_result = await critic_service.evaluate_task_result(
                    task_id=task_id,
                    task_title=task["title"],
                    task_input=task["input"],
                    output_content=output_content,
                    agent_id=agent_id
                )

                # 7. Persistent Memory Recording (Three Layers)
                # Layer 1: Agent Memory
                if eval_result.passed:
                    self.memory.save_agent_memory(
                        agent_id=agent_id,
                        memory_type="successful_approach",
                        summary=f"Successfully executed: {task['title']}",
                        content=f"Evaluator scored {eval_result.score}/100. Effective execution strategy established.",
                        task_id=task_id,
                        goal_id=goal_id,
                        score=eval_result.score,
                        importance=1.5
                    )
                else:
                    flaws = []
                    if eval_result.factual_errors:
                        flaws.append(f"Factual errors: {'; '.join(eval_result.factual_errors)}")
                    if eval_result.missing_requirements:
                        flaws.append(f"Missing requirements: {'; '.join(eval_result.missing_requirements)}")
                    if eval_result.weak_reasoning:
                        flaws.append(f"Reasoning flaws: {'; '.join(eval_result.weak_reasoning)}")
                    
                    self.memory.save_agent_memory(
                        agent_id=agent_id,
                        memory_type="failure_pattern",
                        summary=f"Deficiencies identified in: {task['title']}",
                        content=" | ".join(flaws) if flaws else "Score fell below acceptance threshold.",
                        task_id=task_id,
                        goal_id=goal_id,
                        score=eval_result.score,
                        importance=2.0
                    )

                # Layer 2: Project Memory
                self.memory.save_project_memory(
                    goal_id=goal_id,
                    key=f"task:{task_id}",
                    category="task_output",
                    content=output_content,
                    created_by_task_id=task_id
                )

                # Layer 3: Global Knowledge (Promote top lessons or document failure traps)
                if eval_result.score >= 88.0:
                    self.memory.save_global_knowledge(
                        pattern_type="successful_approach",
                        domain="General",
                        title=f"Verified Execution Pattern: {task['title']}",
                        content=f"High-quality approach validated by {eval_result.critic_id} ({eval_result.score}/100).",
                        evidence=f"Task {task_id}",
                        confidence_score=eval_result.score
                    )
                elif eval_result.score < 65.0:
                    self.memory.save_global_knowledge(
                        pattern_type="known_failure_pattern",
                        domain="General",
                        title=f"Avoid Failure Pattern: {task['title']}",
                        content=f"Deficiencies recorded during task execution: {eval_result.critic_feedback[:120]}",
                        evidence=f"Task {task_id}",
                        confidence_score=eval_result.score
                    )

                # 8. State transition: Running -> Completed
                self.queue.update_task_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    output=output_content,
                    tokens_used=telemetry.total_tokens,
                    latency_ms=telemetry.total_latency_ms
                )

                try:
                    ws_manager.emit_event("task_completed", {
                        "task_id": task_id,
                        "agent_id": agent_id,
                        "goal_id": goal_id,
                        "title": task["title"],
                        "score": eval_result.score,
                        "critic_id": eval_result.critic_id,
                        "tokens": telemetry.total_tokens,
                        "latency_ms": telemetry.total_latency_ms
                    })
                except Exception:
                    pass

                # Restore agent state to idle and increment metrics
                with get_connection(self.queue.db_path) as conn:
                    update_agent_status(conn, agent_id, "idle")
                    current_count = (agent_profile.get("task_count", 0) if agent_profile else 0) + 1
                    update_agent_score(conn, agent_id, eval_result.score, task_count=current_count)

                logger.info(
                    f"Task {task_id} completed and verified by {eval_result.critic_id} "
                    f"(Score: {eval_result.score}/100, {telemetry.total_tokens} tokens)."
                )

                return {
                    "task_id": task_id,
                    "status": "completed",
                    "output": output_content,
                    "evaluation": eval_result.model_dump(),
                    "telemetry": telemetry.model_dump()
                }

            except Exception as e:
                err_trace = traceback.format_exc()
                err_msg = f"{type(e).__name__}: {str(e)}"
                logger.error(f"Task {task_id} failed on agent {agent_id}: {err_msg}\n{err_trace}")

                # Save failure to memory
                self.memory.save_agent_memory(
                    agent_id=agent_id,
                    memory_type="failure_pattern",
                    summary=f"Execution error on: {task['title']}",
                    content=err_msg,
                    task_id=task_id,
                    goal_id=goal_id,
                    score=0.0,
                    importance=2.0
                )

                self.queue.update_task_status(task_id, TaskStatus.FAILED, error=err_msg)

                try:
                    ws_manager.emit_event("task_failed", {
                        "task_id": task_id,
                        "agent_id": agent_id,
                        "goal_id": goal_id,
                        "title": task.get("title", ""),
                        "error": err_msg
                    })
                except Exception:
                    pass

                try:
                    with get_connection(self.queue.db_path) as conn:
                        update_agent_status(conn, agent_id, "idle")
                except Exception:
                    pass

                return {"task_id": task_id, "status": "failed", "error": err_msg}

            finally:
                self._active_workers -= 1
                logger.debug(f"Worker released slot for task {task_id} (active: {self._active_workers})")
