-- SWARM-100 Database Schema
-- Migration 0004: Three Memory Layers & Controlled Self-Improvement System

PRAGMA foreign_keys = ON;

-- ============================================================================
-- LAYER 1: AGENT MEMORY (Individual experiences, tasks, and lessons)
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_memories (
    id           TEXT    PRIMARY KEY,
    agent_id     TEXT    NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    memory_type  TEXT    NOT NULL
                 CHECK(memory_type IN ('task_experience', 'lesson_learned', 'failure_pattern', 'successful_approach')),
    task_id      TEXT    REFERENCES tasks(id) ON DELETE SET NULL,
    goal_id      TEXT    REFERENCES goals(id) ON DELETE SET NULL,
    summary      TEXT    NOT NULL,
    content      TEXT    NOT NULL,
    score        REAL    DEFAULT NULL,
    importance   REAL    NOT NULL DEFAULT 1.0,
    access_count INTEGER NOT NULL DEFAULT 0,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_mem_agent ON agent_memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_mem_type  ON agent_memories(agent_id, memory_type);
CREATE INDEX IF NOT EXISTS idx_agent_mem_task  ON agent_memories(task_id);

-- ============================================================================
-- LAYER 2: PROJECT MEMORY (Goals, architectural decisions, task outputs)
-- ============================================================================
CREATE TABLE IF NOT EXISTS project_memories (
    id                 TEXT PRIMARY KEY,
    goal_id            TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    key                TEXT NOT NULL,
    category           TEXT NOT NULL
                       CHECK(category IN ('decision', 'context', 'task_output', 'milestone', 'constraint')),
    content            TEXT NOT NULL,
    created_by_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    created_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(goal_id, key)
);

CREATE INDEX IF NOT EXISTS idx_proj_mem_goal ON project_memories(goal_id);
CREATE INDEX IF NOT EXISTS idx_proj_mem_cat  ON project_memories(goal_id, category);

-- ============================================================================
-- LAYER 3: GLOBAL KNOWLEDGE (Verified lessons, successful patterns, failure modes)
-- ============================================================================
CREATE TABLE IF NOT EXISTS global_knowledge (
    id               TEXT PRIMARY KEY,
    pattern_type     TEXT NOT NULL
                     CHECK(pattern_type IN ('verified_lesson', 'successful_approach', 'known_failure_pattern', 'best_practice')),
    domain           TEXT NOT NULL,
    title            TEXT NOT NULL,
    content          TEXT NOT NULL,
    evidence         TEXT,
    confidence_score REAL NOT NULL DEFAULT 80.0
                     CHECK(confidence_score >= 0.0 AND confidence_score <= 100.0),
    usage_count      INTEGER NOT NULL DEFAULT 0,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_glob_domain ON global_knowledge(domain);
CREATE INDEX IF NOT EXISTS idx_glob_type   ON global_knowledge(pattern_type);

-- ============================================================================
-- CONTROLLED SELF-IMPROVEMENT: PROMPT VERSIONS & PROPOSALS
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_prompt_versions (
    id               TEXT PRIMARY KEY,
    agent_id         TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    version          INTEGER NOT NULL,
    prompt_text      TEXT NOT NULL,
    change_rationale TEXT NOT NULL,
    proposed_by      TEXT NOT NULL,
    benchmark_score  REAL DEFAULT NULL,
    status           TEXT NOT NULL DEFAULT 'active'
                     CHECK(status IN ('active', 'superseded', 'rejected', 'testing')),
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(agent_id, version)
);

CREATE INDEX IF NOT EXISTS idx_prompt_ver_agent ON agent_prompt_versions(agent_id);

CREATE TABLE IF NOT EXISTS improvement_proposals (
    id                 TEXT PRIMARY KEY,
    agent_id           TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    proposed_prompt    TEXT NOT NULL,
    rationale          TEXT NOT NULL,
    target_metric      TEXT NOT NULL,
    baseline_score     REAL NOT NULL,
    test_score         REAL DEFAULT NULL,
    safety_score       REAL DEFAULT NULL,
    safety_passed      INTEGER NOT NULL DEFAULT 0,
    status             TEXT NOT NULL DEFAULT 'pending'
                       CHECK(status IN ('pending', 'testing', 'accepted', 'rejected')),
    evaluator_verdict  TEXT,
    iteration          INTEGER NOT NULL DEFAULT 1,
    max_iterations     INTEGER NOT NULL DEFAULT 3,
    created_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    evaluated_at       DATETIME
);

CREATE INDEX IF NOT EXISTS idx_prop_agent  ON improvement_proposals(agent_id);
CREATE INDEX IF NOT EXISTS idx_prop_status ON improvement_proposals(status);
