-- SWARM-100 Database Schema
-- Migration 0005: General-Purpose Tool Registry, Approvals, and Audit Logging

PRAGMA foreign_keys = ON;

-- ============================================================================
-- TOOL APPROVAL REQUESTS (Human-in-the-loop / Orchestrator approval gates)
-- ============================================================================
CREATE TABLE IF NOT EXISTS tool_approval_requests (
    id                TEXT     PRIMARY KEY,
    tool_id           TEXT     NOT NULL,
    agent_id          TEXT     NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    task_id           TEXT     REFERENCES tasks(id) ON DELETE SET NULL,
    goal_id           TEXT     REFERENCES goals(id) ON DELETE SET NULL,
    permission_level  TEXT     NOT NULL,
    parameters        TEXT     NOT NULL, -- JSON formatted parameters
    justification     TEXT,
    status            TEXT     NOT NULL DEFAULT 'pending'
                               CHECK(status IN ('pending', 'approved', 'rejected', 'executed', 'cancelled')),
    resolved_by       TEXT,
    resolution_notes  TEXT,
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at       DATETIME
);

CREATE INDEX IF NOT EXISTS idx_tool_appr_agent  ON tool_approval_requests(agent_id);
CREATE INDEX IF NOT EXISTS idx_tool_appr_status ON tool_approval_requests(status);
CREATE INDEX IF NOT EXISTS idx_tool_appr_tool   ON tool_approval_requests(tool_id);

-- ============================================================================
-- TOOL AUDIT LOGS (Immutable record of every tool invocation)
-- ============================================================================
CREATE TABLE IF NOT EXISTS tool_audit_logs (
    id                TEXT     PRIMARY KEY,
    tool_id           TEXT     NOT NULL,
    agent_id          TEXT     NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    task_id           TEXT     REFERENCES tasks(id) ON DELETE SET NULL,
    goal_id           TEXT     REFERENCES goals(id) ON DELETE SET NULL,
    permission_level  TEXT     NOT NULL,
    input_params      TEXT     NOT NULL, -- JSON formatted input parameters
    output_result     TEXT,              -- JSON formatted output deliverable
    status            TEXT     NOT NULL
                               CHECK(status IN ('success', 'failed', 'blocked_permission', 'timeout', 'rejected_approval', 'security_violation')),
    approved_by       TEXT,
    execution_time_ms REAL     NOT NULL DEFAULT 0.0,
    error             TEXT,
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tool_audit_tool   ON tool_audit_logs(tool_id);
CREATE INDEX IF NOT EXISTS idx_tool_audit_agent  ON tool_audit_logs(agent_id);
CREATE INDEX IF NOT EXISTS idx_tool_audit_status ON tool_audit_logs(status);
CREATE INDEX IF NOT EXISTS idx_tool_audit_created ON tool_audit_logs(created_at);
