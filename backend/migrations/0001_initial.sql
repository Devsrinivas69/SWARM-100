-- SWARM-100 Database Schema
-- Migration 0001: Initial Teams and Agents Registry

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS teams (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE,
    domain      TEXT    NOT NULL,
    description TEXT    NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agents (
    id                TEXT    PRIMARY KEY,
    team_id           INTEGER NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
    name              TEXT    NOT NULL UNIQUE,
    role              TEXT    NOT NULL,
    system_prompt     TEXT    NOT NULL,
    capabilities      TEXT    NOT NULL,   -- JSON array of capability strings
    memory_key        TEXT    NOT NULL UNIQUE,
    status            TEXT    NOT NULL DEFAULT 'idle'
                      CHECK(status IN ('idle', 'busy', 'error', 'paused', 'retired')),
    performance_score REAL    NOT NULL DEFAULT 0.0
                      CHECK(performance_score >= 0.0 AND performance_score <= 100.0),
    task_count        INTEGER NOT NULL DEFAULT 0
                      CHECK(task_count >= 0),
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agents_team   ON agents(team_id);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_name   ON agents(name);

CREATE TRIGGER IF NOT EXISTS trg_agents_updated_at
    AFTER UPDATE ON agents
    FOR EACH ROW
    BEGIN
        UPDATE agents SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;
