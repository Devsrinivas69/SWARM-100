"""
SWARM-100 Three-Tier Persistent Memory System
Manages:
1. Agent Memory: Individual experiences, previous tasks, and lessons learned.
2. Project Memory: Goal specifications, decisions, and accumulated project context.
3. Global Knowledge: Reusable verified lessons, successful approaches, and failure patterns.
All memories persist in SQLite and survive application restarts.
"""

import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.database import get_connection

logger = logging.getLogger("swarm100.memory")

class MemoryService:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    # =========================================================================
    # LAYER 1: AGENT MEMORY
    # =========================================================================

    def save_agent_memory(
        self,
        agent_id: str,
        memory_type: str,
        summary: str,
        content: str,
        task_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        score: Optional[float] = None,
        importance: float = 1.0
    ) -> str:
        """Saves an experiential lesson or task outcome to an agent's individual memory."""
        mem_id = f"mem-agent-{uuid.uuid4().hex[:10]}"
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO agent_memories (
                    id, agent_id, memory_type, task_id, goal_id,
                    summary, content, score, importance, access_count, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
                """,
                (mem_id, agent_id, memory_type, task_id, goal_id, summary, content, score, importance)
            )
            conn.commit()

        logger.info(f"Saved Agent Memory [{mem_id}] for agent {agent_id} (type: {memory_type})")
        return mem_id

    def get_agent_memories(
        self,
        agent_id: str,
        memory_type: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Retrieves recent memories for a specific agent."""
        query = "SELECT * FROM agent_memories WHERE agent_id = ?"
        params: List[Any] = [agent_id]

        if memory_type:
            query += " AND memory_type = ?"
            params.append(memory_type)

        query += " ORDER BY importance DESC, created_at DESC LIMIT ?"
        params.append(limit)

        with get_connection(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # =========================================================================
    # LAYER 2: PROJECT MEMORY
    # =========================================================================

    def save_project_memory(
        self,
        goal_id: str,
        key: str,
        category: str,
        content: str,
        created_by_task_id: Optional[str] = None
    ) -> str:
        """Saves or updates a project context milestone, decision, or deliverable."""
        mem_id = f"mem-proj-{uuid.uuid4().hex[:10]}"
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO project_memories (
                    id, goal_id, key, category, content, created_by_task_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(goal_id, key) DO UPDATE SET
                    content = excluded.content,
                    category = excluded.category,
                    created_by_task_id = excluded.created_by_task_id
                """,
                (mem_id, goal_id, key, category, content, created_by_task_id)
            )
            conn.commit()

        logger.info(f"Saved Project Memory [{key}] for goal {goal_id} (category: {category})")
        return mem_id

    def get_project_memories(
        self,
        goal_id: str,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieves accumulated context and decisions for a project/goal."""
        query = "SELECT * FROM project_memories WHERE goal_id = ?"
        params: List[Any] = [goal_id]

        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY created_at ASC"

        with get_connection(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # =========================================================================
    # LAYER 3: GLOBAL KNOWLEDGE
    # =========================================================================

    def save_global_knowledge(
        self,
        pattern_type: str,
        domain: str,
        title: str,
        content: str,
        evidence: Optional[str] = None,
        confidence_score: float = 85.0
    ) -> str:
        """Stores reusable, verified organizational knowledge and known failure patterns."""
        know_id = f"mem-glob-{uuid.uuid4().hex[:10]}"
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO global_knowledge (
                    id, pattern_type, domain, title, content, evidence, confidence_score, usage_count, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (know_id, pattern_type, domain, title, content, evidence, confidence_score)
            )
            conn.commit()

        logger.info(f"Saved Global Knowledge [{know_id}] '{title}' (domain: {domain})")
        return know_id

    def get_global_knowledge(
        self,
        domain: Optional[str] = None,
        pattern_type: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Retrieves global best practices, verified lessons, or failure patterns."""
        clauses = []
        params: List[Any] = []

        if domain:
            clauses.append("(domain = ? OR domain = 'General')")
            params.append(domain)

        if pattern_type:
            clauses.append("pattern_type = ?")
            params.append(pattern_type)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"SELECT * FROM global_knowledge {where} ORDER BY confidence_score DESC, usage_count DESC LIMIT ?"
        params.append(limit)

        with get_connection(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # =========================================================================
    # COMPREHENSIVE RETRIEVAL FOR TASK INVOCATION
    # =========================================================================

    def retrieve_context_for_task(
        self,
        agent_id: str,
        goal_id: str,
        task_title: str,
        task_type: str
    ) -> str:
        """
        Retrieves and synthesizes lessons from all 3 memory layers before an agent runs:
        - Layer 1: Agent's own past lessons and failure warnings.
        - Layer 2: Active project decisions and constraints.
        - Layer 3: Global verified approaches and anti-patterns for this domain.
        """
        sections: List[str] = []

        # 1. Agent Memory
        agent_mems = self.get_agent_memories(agent_id, limit=3)
        if agent_mems:
            sec = ["### [Agent Memory: Prior Lessons & Experiences]"]
            for m in agent_mems:
                sec.append(f"- **{m['memory_type'].upper()}**: {m['summary']}\n  {m['content']}")
                self._increment_access_count("agent_memories", m["id"])
            sections.append("\n".join(sec))

        # 2. Project Memory
        proj_mems = self.get_project_memories(goal_id)
        if proj_mems:
            sec = ["### [Project Memory: Architecture & Context Decisions]"]
            for p in proj_mems:
                sec.append(f"- **{p['key']}** ({p['category']}): {p['content']}")
            sections.append("\n".join(sec))

        # 3. Global Knowledge
        glob_mems = self.get_global_knowledge(domain=task_type, limit=3)
        if glob_mems:
            sec = ["### [Global Knowledge: Proven Patterns & Failure Warnings]"]
            for g in glob_mems:
                sec.append(f"- **{g['pattern_type'].upper()}**: {g['title']}\n  {g['content']}")
                self._increment_access_count("global_knowledge", g["id"])
            sections.append("\n".join(sec))

        return "\n\n".join(sections)

    def _increment_access_count(self, table_name: str, record_id: str) -> None:
        try:
            with get_connection(self.db_path) as conn:
                conn.execute(f"UPDATE {table_name} SET access_count = access_count + 1 WHERE id = ?", (record_id,))
                conn.commit()
        except Exception:
            pass

# Global memory service singleton
memory_service = MemoryService()
