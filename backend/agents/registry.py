"""
Agent Registry Persistence Layer
Handles SQLite CRUD operations, initial seeding, and querying for SWARM-100 agents and teams.
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.agents.definitions import AGENTS, TEAMS
from backend.database import get_connection, init_db

logger = logging.getLogger(__name__)

VALID_STATUSES = {"idle", "busy", "error", "paused", "retired"}

def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    if "capabilities" in data and isinstance(data["capabilities"], str):
        try:
            data["capabilities"] = json.loads(data["capabilities"])
        except Exception:
            data["capabilities"] = []
    return data

def seed_registry(conn: sqlite3.Connection) -> None:
    """Idempotently seed the 10 teams and 100 agents."""
    # Seed teams
    for team in TEAMS:
        conn.execute(
            """
            INSERT OR IGNORE INTO teams (id, name, domain, description)
            VALUES (?, ?, ?, ?)
            """,
            (team["id"], team["name"], team["domain"], team["description"])
        )

    # Seed agents
    for agent in AGENTS:
        conn.execute(
            """
            INSERT OR IGNORE INTO agents (
                id, team_id, name, role, system_prompt, capabilities,
                memory_key, status, performance_score, task_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent["id"],
                agent["team_id"],
                agent["name"],
                agent["role"],
                agent["system_prompt"],
                json.dumps(agent["capabilities"]),
                agent["memory_key"],
                agent["status"],
                agent["performance_score"],
                agent["task_count"]
            )
        )
    conn.commit()

def init_and_seed(db_path: Optional[Path] = None) -> None:
    """Initialize SQLite tables and populate registry."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        seed_registry(conn)

# -----------------------------------------------------------------------------
# Read Operations
# -----------------------------------------------------------------------------

def count_agents(conn: sqlite3.Connection) -> int:
    cursor = conn.execute("SELECT COUNT(*) AS cnt FROM agents")
    row = cursor.fetchone()
    return row["cnt"] if row else 0

def get_all_agents(
    conn: sqlite3.Connection,
    team_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
) -> Dict[str, Any]:
    clauses = []
    params: List[Any] = []

    if team_id is not None:
        clauses.append("team_id = ?")
        params.append(team_id)

    if status is not None:
        clauses.append("status = ?")
        params.append(status)

    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    count_cur = conn.execute(f"SELECT COUNT(*) AS cnt FROM agents {where_sql}", params)
    total = count_cur.fetchone()["cnt"]

    offset = max(0, (page - 1) * page_size)
    query_sql = f"""
        SELECT id, team_id, name, role, capabilities, memory_key,
               status, performance_score, task_count
        FROM agents
        {where_sql}
        ORDER BY team_id ASC, id ASC
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(query_sql, params + [page_size, offset]).fetchall()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_row_to_dict(r) for r in rows]
    }

def get_agent_by_id(conn: sqlite3.Connection, agent_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT id, team_id, name, role, system_prompt, capabilities,
               memory_key, status, performance_score, task_count,
               created_at, updated_at
        FROM agents
        WHERE id = ?
        """,
        (agent_id,)
    ).fetchone()

    return _row_to_dict(row) if row else None

def get_all_teams(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT t.id, t.name, t.domain, t.description, t.created_at,
               COUNT(a.id) as agent_count
        FROM teams t
        LEFT JOIN agents a ON a.team_id = t.id
        GROUP BY t.id
        ORDER BY t.id ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]

def get_team_by_id(conn: sqlite3.Connection, team_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT t.id, t.name, t.domain, t.description, t.created_at,
               COUNT(a.id) as agent_count
        FROM teams t
        LEFT JOIN agents a ON a.team_id = t.id
        WHERE t.id = ?
        GROUP BY t.id
        """,
        (team_id,)
    ).fetchone()
    return dict(row) if row else None

def get_team_agents(conn: sqlite3.Connection, team_id: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, team_id, name, role, capabilities, memory_key,
               status, performance_score, task_count
        FROM agents
        WHERE team_id = ?
        ORDER BY id ASC
        """,
        (team_id,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]

# -----------------------------------------------------------------------------
# Write Operations
# -----------------------------------------------------------------------------

def update_agent_status(conn: sqlite3.Connection, agent_id: str, status: str) -> bool:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of {sorted(VALID_STATUSES)}")

    cursor = conn.execute(
        "UPDATE agents SET status = ? WHERE id = ?",
        (status, agent_id)
    )
    conn.commit()
    return cursor.rowcount > 0

def update_agent_score(
    conn: sqlite3.Connection,
    agent_id: str,
    performance_score: float,
    task_count: Optional[int] = None
) -> bool:
    if not (0.0 <= performance_score <= 100.0):
        raise ValueError("performance_score must be between 0.0 and 100.0")

    if task_count is not None:
        if task_count < 0:
            raise ValueError("task_count must be non-negative")
        cursor = conn.execute(
            """
            UPDATE agents
            SET performance_score = ?, task_count = ?
            WHERE id = ?
            """,
            (performance_score, task_count, agent_id)
        )
    else:
        cursor = conn.execute(
            """
            UPDATE agents
            SET performance_score = ?
            WHERE id = ?
            """,
            (performance_score, agent_id)
        )
    conn.commit()
    return cursor.rowcount > 0
