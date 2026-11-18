"""
SWARM-100 Persistent Task Queue
Manages goals and tasks in SQLite with DAG dependency tracking, state machines,
and fault-tolerant retry/pause/cancel semantics.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.database import get_connection
from backend.models.schemas import GoalAnalysis, GoalStatus, TaskPlanItem, TaskStatus

def _parse_task_row(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    if "dependencies" in data and isinstance(data["dependencies"], str):
        try:
            data["dependencies"] = json.loads(data["dependencies"])
        except Exception:
            data["dependencies"] = []
    return data

class TaskQueue:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def create_goal(
        self,
        title: str,
        description: str,
        concurrency_limit: int = 1
    ) -> str:
        """Creates a new goal record in SQLite in 'pending' status."""
        goal_id = f"goal-{uuid.uuid4().hex[:12]}"
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO goals (id, title, description, status, concurrency_limit, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (goal_id, title, description, GoalStatus.PENDING.value, concurrency_limit)
            )
            conn.commit()
        return goal_id

    def create_task(
        self,
        goal_id: str,
        title: str,
        assigned_agent_id: str,
        input: str,
        task_type: Optional[str] = None,
        priority: int = 5,
        dependencies: Optional[List[str]] = None
    ) -> str:
        """Creates an individual task in SQLite with 'pending' status."""
        t_id = f"task-{uuid.uuid4().hex[:10]}"
        deps = dependencies or []
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    id, goal_id, assigned_agent_id, title, priority,
                    dependencies, status, input, retry_count, max_retries,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, 0, 3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (t_id, goal_id, assigned_agent_id, title, priority, json.dumps(deps), input)
            )
            conn.commit()
        return t_id

    def populate_goal_plan(
        self,
        goal_id: str,
        analysis: GoalAnalysis
    ) -> List[str]:
        """
        Stores goal classification and enqueues decomposed subtasks into SQLite.
        Maps relative dependencies (task_0, task_1) to concrete UUID task IDs.
        """
        created_task_ids: List[str] = []
        task_id_map: Dict[str, str] = {}

        # 1. Pre-generate concrete task IDs
        for idx, item in enumerate(analysis.subtasks):
            t_id = f"task-{uuid.uuid4().hex[:10]}"
            task_id_map[f"task_{idx}"] = t_id
            created_task_ids.append(t_id)

        with get_connection(self.db_path) as conn:
            # Update goal metadata
            conn.execute(
                """
                UPDATE goals
                SET task_type = ?, required_capabilities = ?, status = ?
                WHERE id = ?
                """,
                (
                    analysis.task_type,
                    json.dumps(analysis.required_capabilities),
                    GoalStatus.IN_PROGRESS.value,
                    goal_id
                )
            )

            # Insert all tasks
            for idx, item in enumerate(analysis.subtasks):
                concrete_id = created_task_ids[idx]
                concrete_deps = [task_id_map.get(d, d) for d in item.dependencies]
                initial_status = TaskStatus.PENDING.value

                conn.execute(
                    """
                    INSERT INTO tasks (
                        id, goal_id, assigned_agent_id, title, priority,
                        dependencies, status, input, retry_count, max_retries,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (
                        concrete_id,
                        goal_id,
                        item.assigned_agent_id,
                        item.title,
                        item.priority,
                        json.dumps(concrete_deps),
                        initial_status,
                        item.input
                    )
                )

            conn.commit()

        return created_task_ids

    def get_goal(self, goal_id: str) -> Optional[Dict[str, Any]]:
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            if "required_capabilities" in data and isinstance(data["required_capabilities"], str):
                try:
                    data["required_capabilities"] = json.loads(data["required_capabilities"])
                except Exception:
                    data["required_capabilities"] = []
            
            # Fetch tasks
            t_rows = conn.execute(
                "SELECT * FROM tasks WHERE goal_id = ? ORDER BY priority DESC, created_at ASC",
                (goal_id,)
            ).fetchall()
            data["tasks"] = [_parse_task_row(r) for r in t_rows]
            return data

    def list_goals(self, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        with get_connection(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) as cnt FROM goals").fetchone()["cnt"]
            offset = max(0, (page - 1) * page_size)
            rows = conn.execute(
                """
                SELECT g.id, g.title, g.task_type, g.status, g.concurrency_limit,
                       g.review_score, g.created_at, g.completed_at,
                       COUNT(t.id) as total_tasks,
                       SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END) as completed_tasks
                FROM goals g
                LEFT JOIN tasks t ON t.goal_id = g.id
                GROUP BY g.id
                ORDER BY g.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, offset)
            ).fetchall()

            items = []
            for r in rows:
                d = dict(r)
                d["total_tasks"] = d["total_tasks"] or 0
                d["completed_tasks"] = d["completed_tasks"] or 0
                items.append(d)

            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": items
            }

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return _parse_task_row(row) if row else None

    def list_tasks(
        self,
        status: Optional[str] = None,
        goal_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Queries tasks across goals with optional status, goal, and agent filters."""
        query = "SELECT * FROM tasks"
        clauses = []
        params: List[Any] = []

        if status:
            clauses.append("status = ?")
            params.append(status)
        if goal_id:
            clauses.append("goal_id = ?")
            params.append(goal_id)
        if agent_id:
            clauses.append("assigned_agent_id = ?")
            params.append(agent_id)

        if clauses:
            query += " WHERE " + " AND ".join(clauses)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with get_connection(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
            return [_parse_task_row(r) for r in rows]

    def get_ready_tasks(self, goal_id: str) -> List[Dict[str, Any]]:
        """
        Returns tasks belonging to goal_id that are in 'pending' status
        whose prerequisite dependencies are ALL in 'completed' status.
        Ordered by priority DESC, created_at ASC.
        """
        with get_connection(self.db_path) as conn:
            # First fetch all tasks for this goal
            all_tasks = conn.execute(
                "SELECT id, status FROM tasks WHERE goal_id = ?",
                (goal_id,)
            ).fetchall()
            status_map = {row["id"]: row["status"] for row in all_tasks}

            pending_tasks = conn.execute(
                """
                SELECT * FROM tasks
                WHERE goal_id = ? AND status = 'pending'
                ORDER BY priority DESC, created_at ASC
                """,
                (goal_id,)
            ).fetchall()

            ready = []
            for p_row in pending_tasks:
                task = _parse_task_row(p_row)
                deps = task.get("dependencies", [])
                
                # Check if all dependency IDs are completed
                if all(status_map.get(dep_id) == TaskStatus.COMPLETED.value for dep_id in deps):
                    ready.append(task)

            return ready

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        output: Optional[str] = None,
        error: Optional[str] = None,
        tokens_used: Optional[int] = None,
        latency_ms: Optional[float] = None,
        review_score: Optional[float] = None,
        review_feedback: Optional[str] = None,
        critic_id: Optional[str] = None,
        dimensions: Optional[str] = None
    ) -> bool:
        """Atomically updates a task's status, output, QA critic reviews, telemetry, and timestamps."""
        with get_connection(self.db_path) as conn:
            started_clause = ", started_at = CURRENT_TIMESTAMP" if status == TaskStatus.RUNNING else ""
            completed_clause = ", completed_at = CURRENT_TIMESTAMP" if status in (
                TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED
            ) else ""

            tokens_clause = f", tokens_used = {int(tokens_used)}" if tokens_used is not None else ""
            latency_clause = f", latency_ms = {float(latency_ms)}" if latency_ms is not None else ""
            score_clause = f", review_score = {float(review_score)}" if review_score is not None else ""

            extra_params = []
            feedback_clause = ""
            if review_feedback is not None:
                feedback_clause = ", review_feedback = ?"
                extra_params.append(review_feedback)

            critic_clause = ""
            if critic_id is not None:
                critic_clause = ", critic_id = ?"
                extra_params.append(critic_id)

            dims_clause = ""
            if dimensions is not None:
                dims_clause = ", dimensions = ?"
                extra_params.append(dimensions)

            sql = f"""
                UPDATE tasks
                SET status = ?, output = COALESCE(?, output), error = COALESCE(?, error),
                    updated_at = CURRENT_TIMESTAMP {started_clause} {completed_clause}
                    {tokens_clause} {latency_clause} {score_clause} {feedback_clause} {critic_clause} {dims_clause}
                WHERE id = ?
            """
            params = [status.value, output, error] + extra_params + [task_id]
            cursor = conn.execute(sql, tuple(params))
            conn.commit()
            return cursor.rowcount > 0

    def retry_task(self, task_id: str) -> bool:
        """Resets a failed task to 'pending' and increments retry count."""
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET status = 'pending',
                    error = NULL,
                    retry_count = retry_count + 1,
                    completed_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (task_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def pause_goal(self, goal_id: str) -> bool:
        with get_connection(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE goals SET status = 'paused' WHERE id = ? AND status != 'completed'",
                (goal_id,)
            )
            conn.commit()
            return cur.rowcount > 0

    def resume_goal(self, goal_id: str) -> bool:
        with get_connection(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE goals SET status = 'in_progress' WHERE id = ? AND status = 'paused'",
                (goal_id,)
            )
            conn.commit()
            return cur.rowcount > 0

    def cancel_goal(self, goal_id: str) -> bool:
        with get_connection(self.db_path) as conn:
            # Cancel goal
            conn.execute(
                "UPDATE goals SET status = 'cancelled', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (goal_id,)
            )
            # Cancel all non-completed tasks
            conn.execute(
                """
                UPDATE tasks
                SET status = 'cancelled', completed_at = CURRENT_TIMESTAMP
                WHERE goal_id = ? AND status NOT IN ('completed')
                """,
                (goal_id,)
            )
            conn.commit()
            return True

    def complete_goal(
        self,
        goal_id: str,
        final_output: str,
        review_score: Optional[float] = None,
        review_feedback: Optional[str] = None
    ) -> None:
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE goals
                SET status = 'completed',
                    final_output = ?,
                    review_score = ?,
                    review_feedback = ?,
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (final_output, review_score, review_feedback, goal_id)
            )
            conn.commit()

    def fail_goal(self, goal_id: str, error_message: str) -> None:
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE goals
                SET status = 'failed',
                    error = ?,
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (error_message, goal_id)
            )
            conn.commit()

    def propagate_task_failure(
        self,
        goal_id: str,
        failed_task_id: str,
        reason: Optional[str] = None
    ) -> List[str]:
        """
        Traverses downstream dependencies in the DAG from a failed task
        and transitions all dependent tasks from 'pending' or 'assigned'
        to 'blocked' status in SQLite, recording the blocking upstream task.
        Returns the list of blocked task IDs.
        """
        blocked_ids: List[str] = []
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, status, dependencies FROM tasks WHERE goal_id = ?",
                (goal_id,)
            ).fetchall()

            tasks = [_parse_task_row(r) for r in rows]
            invalid_parents = {failed_task_id}

            # Iteratively find tasks whose dependencies intersect invalid_parents
            changed = True
            while changed:
                changed = False
                for t in tasks:
                    t_id = t["id"]
                    t_status = t.get("status")
                    if t_status in (TaskStatus.PENDING.value, TaskStatus.ASSIGNED.value):
                        deps = set(t.get("dependencies", []))
                        if deps & invalid_parents:
                            invalid_parents.add(t_id)
                            blocked_ids.append(t_id)
                            block_msg = reason or f"Blocked by failed prerequisite: {failed_task_id}"
                            conn.execute(
                                """
                                UPDATE tasks
                                SET status = 'blocked',
                                    error = ?,
                                    completed_at = CURRENT_TIMESTAMP,
                                    updated_at = CURRENT_TIMESTAMP
                                WHERE id = ?
                                """,
                                (block_msg, t_id)
                            )
                            t["status"] = TaskStatus.BLOCKED.value
                            changed = True

            conn.commit()

        # Emit websocket events for blocked tasks
        if blocked_ids:
            try:
                from backend.core.websocket_manager import ws_manager
                for b_id in blocked_ids:
                    ws_manager.emit_event("task_blocked", {
                        "task_id": b_id,
                        "goal_id": goal_id,
                        "reason": reason or f"Prerequisite {failed_task_id} failed"
                    })
            except Exception:
                pass

        return blocked_ids

    def reconcile_orphaned_tasks(self) -> int:
        """
        Cleans up orphaned 'running' or 'assigned' tasks from previous process crashes
        or server restarts, resetting them to 'pending' so they can be re-executed,
        or marking them with an error if their goal was terminated.
        """
        reconciled = 0
        with get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                UPDATE tasks
                SET status = 'pending',
                    started_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE status IN ('running', 'assigned')
                  AND goal_id IN (SELECT id FROM goals WHERE status IN ('in_progress', 'pending'))
                """
            )
            reconciled += cur.rowcount

            cur2 = conn.execute(
                """
                UPDATE tasks
                SET status = 'cancelled',
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP,
                    error = 'Orphaned task cancelled due to inactive goal state'
                WHERE status IN ('running', 'assigned')
                  AND goal_id IN (SELECT id FROM goals WHERE status NOT IN ('in_progress', 'pending'))
                """
            )
            reconciled += cur2.rowcount
            conn.commit()
        return reconciled

    def check_goal_progress(self, goal_id: str) -> Tuple[bool, bool, int, int]:
        """
        Returns: (all_completed, any_failed_or_blocked, completed_count, total_count)
        """
        with get_connection(self.db_path) as conn:
            rows = conn.execute("SELECT status FROM tasks WHERE goal_id = ?", (goal_id,)).fetchall()
            if not rows:
                return (False, False, 0, 0)

            total = len(rows)
            completed = sum(1 for r in rows if r["status"] == TaskStatus.COMPLETED.value)
            failed_or_blocked = any(
                r["status"] in (TaskStatus.FAILED.value, TaskStatus.BLOCKED.value, TaskStatus.CANCELLED.value)
                for r in rows
            )
            all_done = (completed == total)

            return (all_done, failed_or_blocked, completed, total)
