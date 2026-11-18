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
import time
import traceback
from typing import Any, Dict, List, Optional

from backend.agents.definitions import AGENTS
from backend.agents.registry import get_agent_by_id, update_agent_score, update_agent_status
from backend.config import settings
from backend.core.critic import critic_service
from backend.core.llm_service import LLMResponse, LLMTelemetry, llm_service
from backend.core.memory import memory_service
from backend.core.react_loop import react_engine
from backend.core.task_queue import TaskQueue
from backend.core.websocket_manager import ws_manager
from backend.database import get_connection
from backend.models.schemas import TaskStatus

logger = logging.getLogger("swarm100.worker_pool")


class TokenStreamBuffer:
    """
    Batches streaming generation tokens to emit smooth, rate-limited WebSocket frames
    without overwhelming browser DOM or client networks.
    """
    def __init__(self, task_id: str, agent_id: str, goal_id: str, flush_interval: float = 0.08):
        self.task_id = task_id
        self.agent_id = agent_id
        self.goal_id = goal_id
        self.flush_interval = flush_interval
        self._buffer: List[str] = []
        self._last_flush = time.perf_counter()

    async def add_token(self, token: str) -> None:
        self._buffer.append(token)
        now = time.perf_counter()
        if (now - self._last_flush) >= self.flush_interval or len(self._buffer) >= 6:
            await self.flush()

    async def flush(self) -> None:
        if not self._buffer:
            return
        text_chunk = "".join(self._buffer)
        self._buffer = []
        self._last_flush = time.perf_counter()
        try:
            ws_manager.emit_event("token_stream", {
                "task_id": self.task_id,
                "agent_id": self.agent_id,
                "goal_id": self.goal_id,
                "token": text_chunk
            })
        except Exception:
            pass

class WorkerPool:
    def __init__(self, concurrency_limit: Optional[int] = None, task_queue: Optional[TaskQueue] = None):
        self.concurrency_limit = max(1, concurrency_limit if concurrency_limit is not None else settings.max_concurrency)
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

                # 5. Execute through autonomous ReAct loop or direct streaming chat
                stream_buffer = TokenStreamBuffer(task_id=task_id, agent_id=agent_id, goal_id=goal_id)
                on_token_cb = stream_buffer.add_token if settings.enable_token_streaming else None

                if settings.enable_react_tools:
                    output_content, tools_invoked, tele_summary = await react_engine.execute_react_task(
                        agent_id=agent_id,
                        system_prompt=sys_prompt,
                        task_title=task["title"],
                        task_directives=task["input"],
                        upstream_context=upstream_text,
                        task_id=task_id,
                        goal_id=goal_id,
                        on_token=on_token_cb
                    )
                    await stream_buffer.flush()
                    telemetry = LLMTelemetry(
                        total_tokens=tele_summary["total_tokens"],
                        total_latency_ms=tele_summary["total_latency_ms"]
                    )
                else:
                    llm_response = await llm_service.chat(
                        system_prompt=sys_prompt,
                        user_message=task_user_message,
                        upstream_context=upstream_text,
                        on_token=on_token_cb
                    )
                    await stream_buffer.flush()
                    output_content = llm_response.content
                    telemetry = llm_response.telemetry

                if not output_content or not output_content.strip():
                    raise RuntimeError(f"Agent {agent_id} generated empty output for task {task_id}.")

                # 6. Transition to Critic Review state & Audit Completed Deliverable
                self.queue.update_task_status(task_id, TaskStatus.REVIEWING)
                try:
                    ws_manager.emit_event("task_reviewing", {
                        "task_id": task_id,
                        "agent_id": agent_id,
                        "goal_id": goal_id,
                        "title": task["title"]
                    })
                except Exception:
                    pass

                eval_result = await critic_service.evaluate_task_result(
                    task_id=task_id,
                    task_title=task["title"],
                    task_input=task["input"],
                    output_content=output_content,
                    agent_id=agent_id
                )

                # 6b. Critic Self-Correction Loop
                max_critic_retries = min(task.get("max_retries", settings.max_critic_retries), settings.max_critic_retries)
                current_retry = 0
                initial_score = eval_result.score

                while (not eval_result.passed or eval_result.score < 70.0) and current_retry < max_critic_retries:
                    current_retry += 1
                    logger.info(
                        f"Task {task_id} scored {eval_result.score}/100 (< 70). "
                        f"Initiating Critic Self-Correction attempt {current_retry}/{max_critic_retries}..."
                    )

                    try:
                        ws_manager.emit_event("task_revising", {
                            "task_id": task_id,
                            "agent_id": agent_id,
                            "goal_id": goal_id,
                            "title": task["title"],
                            "retry_count": current_retry,
                            "max_retries": max_critic_retries,
                            "score": eval_result.score,
                            "critic_id": eval_result.critic_id,
                            "deficiencies": {
                                "factual_errors": eval_result.factual_errors,
                                "missing_requirements": eval_result.missing_requirements,
                                "weak_reasoning": eval_result.weak_reasoning,
                            },
                            "critic_feedback": eval_result.critic_feedback[:300]
                        })
                    except Exception:
                        pass

                    revision_directive = (
                        f"[CRITIC AUDIT REVISION DIRECTIVE - ATTEMPT {current_retry}/{max_critic_retries}]\n"
                        f"Your deliverable for '{task['title']}' was reviewed by Independent Critic {eval_result.critic_id} "
                        f"and scored {eval_result.score}/100. VERDICT: NEEDS REVISION.\n\n"
                        f"CRITIQUE & DEFICIENCIES DETECTED:\n"
                        f"- Factual Errors: {', '.join(eval_result.factual_errors) if eval_result.factual_errors else 'None'}\n"
                        f"- Missing Requirements: {', '.join(eval_result.missing_requirements) if eval_result.missing_requirements else 'None'}\n"
                        f"- Weak Reasoning: {', '.join(eval_result.weak_reasoning) if eval_result.weak_reasoning else 'None'}\n\n"
                        f"CRITIC FEEDBACK NOTES:\n{eval_result.critic_feedback}\n\n"
                        f"PREVIOUS DRAFT:\n{output_content}\n\n"
                        f"REVISION INSTRUCTIONS:\n"
                        f"Directly fix every defect identified by the Critic above. "
                        f"Supply missing sections, correct factual inaccuracies, tighten reasoning, and deliver the complete, corrected final Markdown artifact."
                    )

                    rev_stream_buffer = TokenStreamBuffer(task_id=task_id, agent_id=agent_id, goal_id=goal_id)
                    revised_resp = await llm_service.chat(
                        system_prompt=sys_prompt,
                        user_message=revision_directive,
                        upstream_context=upstream_text,
                        on_token=rev_stream_buffer.add_token if settings.enable_token_streaming else None
                    )
                    await rev_stream_buffer.flush()

                    if revised_resp.content and revised_resp.content.strip():
                        output_content = revised_resp.content
                        telemetry.total_tokens += revised_resp.telemetry.total_tokens
                        telemetry.total_latency_ms += revised_resp.telemetry.total_latency_ms

                    # Re-audit revised deliverable with Critic
                    eval_result = await critic_service.evaluate_task_result(
                        task_id=task_id,
                        task_title=task["title"],
                        task_input=task["input"],
                        output_content=output_content,
                        agent_id=agent_id
                    )
                    logger.info(
                        f"Self-correction round {current_retry} evaluated: "
                        f"Score {eval_result.score}/100 (Passed: {eval_result.passed})"
                    )

                # 7. Persistent Memory Recording (Three Layers)
                # Layer 1: Agent Memory
                if eval_result.passed:
                    summary_text = (
                        f"Successfully executed: {task['title']}"
                        if current_retry == 0
                        else f"Self-correction succeeded on {task['title']} (Score improved from {initial_score} to {eval_result.score}/100)"
                    )
                    self.memory.save_agent_memory(
                        agent_id=agent_id,
                        memory_type="successful_approach",
                        summary=summary_text,
                        content=f"Evaluator scored {eval_result.score}/100. Effective execution strategy established after {current_retry} self-correction cycles.",
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

                # 8. State transition: Reviewing -> Completed (with full Critic Audit telemetry)
                import json
                dim_json = json.dumps(eval_result.dimensions) if eval_result.dimensions else None
                self.queue.update_task_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    output=output_content,
                    tokens_used=telemetry.total_tokens,
                    latency_ms=telemetry.total_latency_ms,
                    review_score=eval_result.score,
                    review_feedback=eval_result.critic_feedback,
                    critic_id=eval_result.critic_id,
                    dimensions=dim_json
                )

                try:
                    ws_manager.emit_event("task_completed", {
                        "task_id": task_id,
                        "agent_id": agent_id,
                        "goal_id": goal_id,
                        "title": task["title"],
                        "score": eval_result.score,
                        "critic_id": eval_result.critic_id,
                        "critic_feedback": eval_result.critic_feedback,
                        "dimensions": eval_result.dimensions,
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
