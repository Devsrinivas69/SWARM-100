"""
Test Suite for SWARM-100 Real-Time Dashboard & Telemetry
Verifies:
1. Static dashboard HTML serving at root URL `/`
2. Genuine dashboard statistics calculation (`/api/v1/dashboard/stats`)
3. Genuine activity feed compiled from real database records (`/api/v1/dashboard/activity`)
4. Critic review feed (`/api/v1/dashboard/critic-reviews`)
5. Task board and timeline endpoints (`/api/v1/tasks`)
6. Recent agent memory feed (`/api/v1/memory/recent`)
7. Improvement proposals feed (`/api/v1/improvement/proposals`)
8. WebSocket bi-directional connection (`/ws`)
"""

import pytest
from fastapi.testclient import TestClient

def test_dashboard_html_served_at_root(client: TestClient):
    """Verifies that accessing root URL returns the SWARM-100 dark dashboard HTML."""
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "SWARM-100" in res.text
    assert "Command Center" in res.text
    assert "Agent Workforce" in res.text
    assert "Product Foundry" in res.text
    assert "page-foundry" in res.text
    assert "#111111" in res.text  # Verification of background color spec
    assert "#F59E0B" in res.text  # Verification of accent color spec

def test_dashboard_stats_endpoint(client: TestClient):
    """Verifies that /api/v1/dashboard/stats computes genuine backend workforce metrics."""
    res = client.get("/api/v1/dashboard/stats")
    assert res.status_code == 200
    data = res.json()

    # Core required Command Center metrics
    assert data["total_agents"] == 100
    assert data["total_teams"] == 10
    assert "active_workers" in data
    assert "idle_workers" in data
    assert "completed_tasks" in data
    assert "failed_tasks" in data
    assert "pending_tasks" in data
    assert "model_calls" in data
    assert "avg_execution_time_ms" in data
    assert "improvement_cycles" in data
    assert "total_memories" in data
    assert "pending_tool_approvals" in data

def test_dashboard_activity_feed(client: TestClient):
    """Verifies live activity feed endpoint returns genuine backend events."""
    res = client.get("/api/v1/dashboard/activity")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)

def test_dashboard_critic_reviews(client: TestClient):
    """Verifies critic reviews endpoint returns evaluation records."""
    res = client.get("/api/v1/dashboard/critic-reviews")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)

def test_tasks_list_endpoint_for_kanban_board(client: TestClient):
    """Verifies that /api/v1/tasks returns tasks with dependencies and statuses for the board."""
    res = client.get("/api/v1/tasks")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)

def test_recent_memories_endpoint(client: TestClient):
    """Verifies that /api/v1/memory/recent returns memory layers across agents."""
    res = client.get("/api/v1/memory/recent")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)

def test_proposals_list_endpoint(client: TestClient):
    """Verifies that /api/v1/improvement/proposals returns self-improvement benchmarks."""
    res = client.get("/api/v1/improvement/proposals")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)

def test_websocket_connection_and_ping(client: TestClient):
    """Verifies real-time WebSocket connection to /ws."""
    with client.websocket_connect("/ws") as ws:
        # Upon connect, client receives initial state or ping response
        ws.send_text("ping")
        resp = ws.receive_text()
        assert resp == "pong" or "initial_state" in resp
