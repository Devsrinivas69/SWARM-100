"""
Comprehensive Test Suite for SWARM-100 Agent Registry
Verifies:
1. Exact definitions of 10 teams and 100 specialist agents.
2. Uniqueness of all agent IDs, names, and memory references.
3. SQLite persistence, schema constraints, and idempotent seeding.
4. FastAPI endpoints for listing, filtering, inspecting, and updating agent statuses and scores.
"""

import json
import sqlite3
import pytest
from fastapi.testclient import TestClient

from backend.agents.definitions import AGENTS, TEAMS
from backend.agents.registry import (
    count_agents,
    get_agent_by_id,
    get_all_agents,
    get_all_teams,
    get_team_agents,
    get_team_by_id,
    seed_registry,
    update_agent_score,
    update_agent_status,
)

# =============================================================================
# 1. DEFINITION TESTS
# =============================================================================

class TestAgentDefinitions:
    def test_exactly_10_teams_defined(self):
        assert len(TEAMS) == 10, f"Expected 10 teams, got {len(TEAMS)}"

    def test_team_ids_are_1_through_10(self):
        team_ids = {t["id"] for t in TEAMS}
        assert team_ids == set(range(1, 11)), "Team IDs must be integers from 1 to 10"

    def test_all_team_names_and_domains_present(self):
        expected_team_names = {
            "Strategy", "Research", "Business", "Content", "Development",
            "Data", "Operations", "Security", "Critic", "Optimization"
        }
        actual_names = {t["name"] for t in TEAMS}
        assert actual_names == expected_team_names, f"Mismatch in team names: {actual_names ^ expected_team_names}"

        for team in TEAMS:
            assert len(team["domain"].strip()) > 10, f"Team {team['name']} domain description is too short"
            assert len(team["description"].strip()) > 10, f"Team {team['name']} description is too short"

    def test_exactly_100_agents_defined(self):
        assert len(AGENTS) == 100, f"Expected exactly 100 agents, got {len(AGENTS)}"

    def test_each_team_has_exactly_10_agents(self):
        for team_id in range(1, 11):
            team_agents = [a for a in AGENTS if a["team_id"] == team_id]
            assert len(team_agents) == 10, (
                f"Team ID {team_id} has {len(team_agents)} agents; expected exactly 10"
            )

    def test_all_100_agent_ids_are_unique(self):
        ids = [a["id"] for a in AGENTS]
        assert len(ids) == 100
        assert len(set(ids)) == 100, "Duplicate agent IDs detected!"

    def test_all_100_agent_names_are_unique(self):
        names = [a["name"] for a in AGENTS]
        assert len(names) == 100
        assert len(set(names)) == 100, "Duplicate agent names detected!"

    def test_all_100_agent_memory_keys_are_unique(self):
        memory_keys = [a["memory_key"] for a in AGENTS]
        assert len(memory_keys) == 100
        assert len(set(memory_keys)) == 100, "Duplicate agent memory keys detected!"

    def test_all_required_agent_fields_present_and_valid(self):
        required_fields = {
            "id", "team_id", "name", "role", "system_prompt",
            "capabilities", "memory_key", "status",
            "performance_score", "task_count"
        }
        for agent in AGENTS:
            missing = required_fields - set(agent.keys())
            assert not missing, f"Agent {agent.get('id')} missing fields: {missing}"

            # Validate initial values
            assert agent["status"] == "idle", f"Agent {agent['id']} status not idle"
            assert agent["performance_score"] == 0.0, f"Agent {agent['id']} score not 0.0"
            assert agent["task_count"] == 0, f"Agent {agent['id']} task_count not 0"
            assert isinstance(agent["capabilities"], list), f"Agent {agent['id']} capabilities not a list"
            assert len(agent["capabilities"]) >= 3, f"Agent {agent['id']} has fewer than 3 capabilities"
            assert len(agent["system_prompt"].strip()) >= 50, f"Agent {agent['id']} system prompt is too brief"
            assert agent["memory_key"].startswith("mem:"), f"Agent {agent['id']} memory_key must start with 'mem:'"

# =============================================================================
# 2. SQLITE PERSISTENCE TESTS
# =============================================================================

class TestSqlitePersistence:
    def test_db_has_exactly_10_teams(self, db_conn):
        teams = get_all_teams(db_conn)
        assert len(teams) == 10
        assert all(t["agent_count"] == 10 for t in teams), "Each team must have 10 linked agents"

    def test_db_has_exactly_100_agents(self, db_conn):
        total = count_agents(db_conn)
        assert total == 100, f"SQLite contains {total} agents, expected 100"

    def test_each_team_in_db_has_10_agents(self, db_conn):
        for team_id in range(1, 11):
            agents = get_team_agents(db_conn, team_id)
            assert len(agents) == 10, f"Team {team_id} has {len(agents)} agents in DB"
            for a in agents:
                assert a["team_id"] == team_id

    def test_seeding_is_idempotent(self, db_conn):
        # Re-running seed_registry must not duplicate records or raise exceptions
        seed_registry(db_conn)
        seed_registry(db_conn)
        total = count_agents(db_conn)
        assert total == 100, f"Agent count changed after re-seeding: {total}"

    def test_agent_capabilities_stored_and_retrieved_as_list(self, db_conn):
        agent = get_agent_by_id(db_conn, "forge-01")
        assert agent is not None
        assert agent["name"] == "FORGE-01"
        assert isinstance(agent["capabilities"], list)
        assert "clean_code" in agent["capabilities"]

    def test_update_agent_status_in_db(self, db_conn):
        agent_id = "stratos-01"
        assert update_agent_status(db_conn, agent_id, "busy")
        agent = get_agent_by_id(db_conn, agent_id)
        assert agent["status"] == "busy"

        # Revert back to idle
        assert update_agent_status(db_conn, agent_id, "idle")
        agent = get_agent_by_id(db_conn, agent_id)
        assert agent["status"] == "idle"

    def test_update_invalid_status_raises_error(self, db_conn):
        with pytest.raises(ValueError) as exc:
            update_agent_status(db_conn, "stratos-01", "nonexistent_status")
        assert "Invalid status" in str(exc.value)

    def test_update_agent_score_and_task_count(self, db_conn):
        agent_id = "recon-01"
        assert update_agent_score(db_conn, agent_id, 88.5, task_count=5)
        agent = get_agent_by_id(db_conn, agent_id)
        assert agent["performance_score"] == 88.5
        assert agent["task_count"] == 5

        # Revert back
        assert update_agent_score(db_conn, agent_id, 0.0, task_count=0)

    def test_update_out_of_bounds_score_raises_error(self, db_conn):
        with pytest.raises(ValueError):
            update_agent_score(db_conn, "recon-01", 105.0)
        with pytest.raises(ValueError):
            update_agent_score(db_conn, "recon-01", -5.0)

    def test_nonexistent_agent_returns_none_and_false(self, db_conn):
        agent = get_agent_by_id(db_conn, "ghost-999")
        assert agent is None
        assert not update_agent_status(db_conn, "ghost-999", "busy")
        assert not update_agent_score(db_conn, "ghost-999", 50.0)

# =============================================================================
# 3. FASTAPI REST API TESTS
# =============================================================================

class TestFastAPIRoutes:
    def test_health_check(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "SWARM-100"

    def test_api_agent_count(self, client: TestClient):
        response = client.get("/api/v1/agents/count")
        assert response.status_code == 200
        data = response.json()
        assert data["total_agents"] == 100
        assert data["expected"] == 100
        assert data["ok"] is True

    def test_api_list_agents_pagination(self, client: TestClient):
        response = client.get("/api/v1/agents?page=1&page_size=25")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 100
        assert data["page"] == 1
        assert data["page_size"] == 25
        assert len(data["items"]) == 25

    def test_api_list_agents_filter_by_team(self, client: TestClient):
        for team_id in range(1, 11):
            response = client.get(f"/api/v1/agents?team_id={team_id}&page_size=50")
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 10, f"Team {team_id} filter should return total 10"
            assert len(data["items"]) == 10
            for item in data["items"]:
                assert item["team_id"] == team_id

    def test_api_list_agents_filter_by_status(self, client: TestClient):
        response = client.get("/api/v1/agents?status=idle&page_size=100")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 100
        assert len(data["items"]) == 100

    def test_api_inspect_agent_by_id(self, client: TestClient):
        response = client.get("/api/v1/agents/argus-01")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "argus-01"
        assert data["name"] == "ARGUS-01"
        assert data["team_id"] == 9
        assert data["role"] == "Independent Reviewer"
        assert "ARGUS-01" in data["system_prompt"]
        assert "independent_review" in data["capabilities"]
        assert data["memory_key"] == "mem:argus_01"

    def test_api_inspect_agent_not_found(self, client: TestClient):
        response = client.get("/api/v1/agents/phantom-agent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_api_update_agent_status(self, client: TestClient):
        # Transition idle -> busy
        patch_res = client.patch(
            "/api/v1/agents/apex-01/status",
            json={"status": "busy"}
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["status"] == "busy"

        # Verify state via GET
        get_res = client.get("/api/v1/agents/apex-01")
        assert get_res.json()["status"] == "busy"

        # Transition busy -> idle
        revert_res = client.patch(
            "/api/v1/agents/apex-01/status",
            json={"status": "idle"}
        )
        assert revert_res.status_code == 200
        assert revert_res.json()["status"] == "idle"

    def test_api_update_agent_status_invalid_value(self, client: TestClient):
        response = client.patch(
            "/api/v1/agents/apex-01/status",
            json={"status": "sleeping"}
        )
        # Pydantic regex validation triggers 422
        assert response.status_code == 422

    def test_api_update_agent_score(self, client: TestClient):
        patch_res = client.patch(
            "/api/v1/agents/cipher-01/score",
            json={"performance_score": 95.5, "task_count": 8}
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["performance_score"] == 95.5
        assert patch_res.json()["task_count"] == 8

        # Verify via GET
        get_res = client.get("/api/v1/agents/cipher-01")
        assert get_res.json()["performance_score"] == 95.5
        assert get_res.json()["task_count"] == 8

        # Revert
        client.patch(
            "/api/v1/agents/cipher-01/score",
            json={"performance_score": 0.0, "task_count": 0}
        )

    def test_api_update_agent_score_invalid_range(self, client: TestClient):
        response = client.patch(
            "/api/v1/agents/cipher-01/score",
            json={"performance_score": 150.0}
        )
        assert response.status_code == 422

    def test_api_list_teams(self, client: TestClient):
        response = client.get("/api/v1/teams")
        assert response.status_code == 200
        teams = response.json()
        assert len(teams) == 10
        for team in teams:
            assert team["agent_count"] == 10

    def test_api_inspect_team_with_10_agents(self, client: TestClient):
        response = client.get("/api/v1/teams/5")  # Development
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 5
        assert data["name"] == "Development"
        assert len(data["agents"]) == 10
        agent_names = [a["name"] for a in data["agents"]]
        assert "FORGE-01" in agent_names
        assert "FORGE-10" in agent_names

    def test_api_inspect_team_not_found(self, client: TestClient):
        response = client.get("/api/v1/teams/99")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
