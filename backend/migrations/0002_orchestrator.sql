-- SWARM-100 Database Schema
-- Migration 0002: Orchestrator Goals, Tasks, and Queue

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS goals (
    id                    TEXT    PRIMARY KEY,
    title                 TEXT    NOT NULL,
    description           TEXT    NOT NULL,
    task_type             TEXT    NOT NULL DEFAULT 'General',
    required_capabilities TEXT    NOT NULL DEFAULT '[]', -- JSON array
    status                TEXT    NOT NULL DEFAULT 'pending'
                          CHECK(status IN ('pending', 'planning', 'in_progress', 'reviewing', 'completed', 'failed', 'paused', 'cancelled')),
    concurrency_limit     INTEGER NOT NULL DEFAULT 1
                          CHECK(concurrency_limit >= 1),
    final_output          TEXT,
    review_feedback       TEXT,
    review_score          REAL    DEFAULT NULL
                          CHECK(review_score IS NULL OR (review_score >= 0.0 AND review_score <= 100.0)),
    error                 TEXT,
    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at          DATETIME
);

CREATE TABLE IF NOT EXISTS tasks (
    id                 TEXT    PRIMARY KEY,
    goal_id            TEXT    NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    parent_task_id     TEXT    REFERENCES tasks(id) ON DELETE SET NULL,
    assigned_agent_id  TEXT    NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
    title              TEXT    NOT NULL,
    priority           INTEGER NOT NULL DEFAULT 5
                       CHECK(priority >= 1 AND priority <= 10),
    dependencies       TEXT    NOT NULL DEFAULT '[]', -- JSON array of prerequisite task IDs
    status             TEXT    NOT NULL DEFAULT 'pending'
                       CHECK(status IN ('pending', 'assigned', 'running', 'reviewing', 'completed', 'failed', 'blocked', 'cancelled')),
    input              TEXT    NOT NULL,
    output             TEXT,
    error              TEXT,
    retry_count        INTEGER NOT NULL DEFAULT 0
                       CHECK(retry_count >= 0),
    max_retries        INTEGER NOT NULL DEFAULT 3
                       CHECK(max_retries >= 0),
    tokens_used        INTEGER NOT NULL DEFAULT 0,
    latency_ms         REAL    NOT NULL DEFAULT 0.0,
    created_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at         DATETIME,
    completed_at       DATETIME,
    updated_at         DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);
CREATE INDEX IF NOT EXISTS idx_tasks_goal   ON tasks(goal_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_agent  ON tasks(assigned_agent_id);

CREATE TRIGGER IF NOT EXISTS trg_goals_updated_at
    AFTER UPDATE ON goals
    FOR EACH ROW
    BEGIN
        UPDATE goals SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;

CREATE TRIGGER IF NOT EXISTS trg_tasks_updated_at
    AFTER UPDATE ON tasks
    FOR EACH ROW
    BEGIN
        UPDATE tasks SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;
