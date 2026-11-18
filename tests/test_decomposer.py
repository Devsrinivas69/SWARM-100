"""
SWARM-100 Dynamic Multi-Team Decomposer Tests
Validates workforce density modes, multi-stage DAG generation, 100-agent allocation,
and adaptive prompt directive extraction.
"""

import pytest
from backend.agents.definitions import AGENTS, AGENTS_BY_TEAM
from backend.core.planner import (
    create_task_plan,
    extract_team_directives,
    resolve_workforce_density,
    build_multi_team_plan,
)
from backend.core.task_queue import TaskQueue
from backend.models.schemas import TaskStatus

ALL_AGENT_IDS = {a["id"] for a in AGENTS}

class TestDynamicDecomposer:
    def test_all_100_agents_available_in_registry(self):
        assert len(AGENTS) == 100
        assert len(AGENTS_BY_TEAM) == 10
        for tid in range(1, 11):
            assert len(AGENTS_BY_TEAM[tid]) == 10

    def test_focused_mode_preserves_compact_templates(self):
        plan = create_task_plan(
            title="Design Payment Gateway Microservice",
            description="Build scalable API contracts and threat model.",
            workforce_density="focused"
        )
        assert 3 <= len(plan.subtasks) <= 5
        assert any(len(t.dependencies) == 0 for t in plan.subtasks)
        assert any(len(t.dependencies) > 0 for t in plan.subtasks)

    def test_balanced_mode_spans_all_10_teams(self):
        plan = create_task_plan(
            title="Enterprise Digital Transformation",
            description="Multi-functional audit and strategy.",
            workforce_density="balanced"
        )
        assert len(plan.subtasks) == 10
        assigned_teams = set()
        for t in plan.subtasks:
            agent = next(a for a in AGENTS if a["id"] == t.assigned_agent_id)
            assigned_teams.add(agent["team_id"])
        assert assigned_teams == set(range(1, 11)), "Must touch all 10 teams"

    def test_comprehensive_mode_30_agents(self):
        plan = create_task_plan(
            title="SaaS Product Expansion",
            description="Comprehensive cross-functional launch strategy.",
            workforce_density="comprehensive"
        )
        assert len(plan.subtasks) == 30
        assigned_ids = [t.assigned_agent_id for t in plan.subtasks]
        assert len(set(assigned_ids)) == 30, "All 30 assigned agents must be unique"

    def test_full_swarm_mode_exactly_100_agents(self):
        plan = create_task_plan(
            title="PROJECT LAST MILE (BENGALURU)",
            description="Full-scale business launch across all 10 teams and 100 agents.",
            workforce_density="full_swarm"
        )
        assert len(plan.subtasks) == 100, "Full swarm must generate exactly 100 tasks"
        assigned_ids = [t.assigned_agent_id for t in plan.subtasks]
        assert len(set(assigned_ids)) == 100, "Must assign all 100 distinct agents"
        assert set(assigned_ids) == ALL_AGENT_IDS, "Must match exactly the 100 specialist agent IDs"

        # Verify DAG structure:
        # Stage 1 Strategy tasks must have 0 dependencies (independent root)
        stage_1_tasks = plan.subtasks[:10]
        assert all(len(t.dependencies) == 0 for t in stage_1_tasks), "Stage 1 tasks must be independent roots"

        # Downstream tasks must have non-empty dependencies
        downstream_tasks = plan.subtasks[10:]
        assert all(len(t.dependencies) > 0 for t in downstream_tasks), "Downstream tasks must have dependencies"

    def test_adaptive_detection_from_prompt_keywords(self):
        # Prompts containing 'all 100 agents' auto-select full_swarm
        prompt_100 = "Activate all 100 specialist agents to plan the Bengaluru metro mobility network."
        mode, per_team = resolve_workforce_density(prompt_100, requested_density="adaptive")
        assert mode == "full_swarm"
        assert per_team == 10

        # Normal single brief defaults to focused for fast execution
        prompt_quick = "Build a Python microservice with fast-api."
        mode_quick, per_team_quick = resolve_workforce_density(prompt_quick, requested_density="adaptive")
        assert mode_quick == "focused"
        assert per_team_quick == 0

    def test_extract_team_directives_from_markdown(self):
        sample = """
        ## TEAM 1 — STRATEGY
        Define the 90-day WBS and operational gates.
        ## TEAM 2 — RESEARCH
        Investigate 5 metro stations along Purple Line.
        ## TEAM 3 — BUSINESS
        Calculate unit economics within 5 lakh bootstrap budget.
        """
        directives = extract_team_directives(sample)
        assert 1 in directives
        assert 2 in directives
        assert 3 in directives
        assert "WBS" in directives[1]
        assert "Purple Line" in directives[2]
        assert "bootstrap" in directives[3]

    def test_100_task_queue_dag_resolution(self, db_conn):
        from backend.config import settings
        queue = TaskQueue(settings.db_path)
        plan = create_task_plan(
            title="100 Agent Verification Run",
            description="Full swarm mission test.",
            workforce_density="full_swarm"
        )
        goal_id = queue.create_goal("Swarm Test", "Testing 100-agent DAG", concurrency_limit=1)
        task_ids = queue.populate_goal_plan(goal_id, plan)

        assert len(task_ids) == 100

        # Stage 1: Exactly 10 tasks ready initially (all 10 Strategy specialists)
        ready_initial = queue.get_ready_tasks(goal_id)
        assert len(ready_initial) == 10
        for r in ready_initial:
            assert len(r["dependencies"]) == 0
            assert r["assigned_agent_id"].startswith("stratos-")

        # Simulate completing the lead Strategy task (task_0)
        lead_strat_id = task_ids[0]
        queue.update_task_status(lead_strat_id, TaskStatus.COMPLETED, output="Strategic Charter Established.")

        # Stage 2 (Research & Data) tasks depending on task_0 must now be unblocked
        ready_next = queue.get_ready_tasks(goal_id)
        assert len(ready_next) > len(ready_initial) - 1
        new_ready = [t for t in ready_next if t["id"] != lead_strat_id]
        new_agents = {t["assigned_agent_id"] for t in new_ready}
        assert any(a.startswith("recon-") for a in new_agents), "Recon agents must be unblocked"

        # Clean up test artifacts immediately
        db_conn.execute("DELETE FROM tasks WHERE goal_id = ?", (goal_id,))
        db_conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
        db_conn.commit()
