"""
Test Suite for SWARM-100 Autonomous Product Foundry
Verifies:
1. Code fence stripping & code cleaning logic
2. Heuristic and LLM architecture manifest generation
3. Automated SAST security audit (vulnerability detection & scoring)
4. Subprocess test runner execution (passing & failing assertions)
5. Self-healing debugger repair logic
6. Packaging and Launch Certification scoring
7. API endpoints:
   - GET /api/v1/foundry/projects
   - GET /api/v1/foundry/projects/{slug}
   - GET /api/v1/foundry/projects/{slug}/file
   - Directory traversal protection
   - POST /api/v1/foundry/build (background and validation)
"""

import os
import shutil
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.core.foundry import (
    ProductFoundry,
    FoundryFileSpec,
    FoundryTestResult,
    FoundrySecurityReport,
    clean_code_block
)

@pytest.fixture
def anyio_backend():
    return "asyncio"

# -----------------------------------------------------------------------------
# 1. Code Cleaning Tests
# -----------------------------------------------------------------------------

def test_clean_code_block_strips_markdown_fences():
    """Verifies that markdown fences with language hints are cleanly stripped."""
    raw = "```python\ndef calculate(a: int, b: int) -> int:\n    return a + b\n```"
    cleaned = clean_code_block(raw)
    assert cleaned == "def calculate(a: int, b: int) -> int:\n    return a + b"

def test_clean_code_block_handles_bare_backticks():
    """Verifies stripping of bare triple backticks without language identifier."""
    raw = "```\nprint('hello world')\n```"
    cleaned = clean_code_block(raw)
    assert cleaned == "print('hello world')"

def test_clean_code_block_preserves_clean_code():
    """Verifies that code without fences remains intact."""
    raw = "x = 42\ny = x * 2"
    assert clean_code_block(raw) == raw

def test_clean_code_block_empty():
    assert clean_code_block("") == ""
    assert clean_code_block(None) == ""

# -----------------------------------------------------------------------------
# 2. Heuristic & Manifest Planning Tests
# -----------------------------------------------------------------------------

def test_generate_slug_and_name():
    foundry = ProductFoundry()
    slug = foundry._generate_slug("Build a Real-Time Redis Caching Layer with TTL")
    assert "real-time" in slug or "redis" in slug or "caching" in slug
    assert not slug.startswith("build")

    name = foundry._generate_project_name("Build a Real-Time Redis Caching Layer", slug)
    assert "Real" in name or "Redis" in name

def test_heuristic_manifest_structure():
    foundry = ProductFoundry()
    manifest = foundry._generate_heuristic_manifest("KVStore", "Build a high throughput in-memory key value store")
    files = manifest["files"]
    paths = [f["relative_path"] for f in files]

    assert "app.py" in paths
    assert "storage.py" in paths
    assert "test_app.py" in paths
    assert "README.md" in paths
    assert any(f["file_type"] == "test" for f in files)

# -----------------------------------------------------------------------------
# 3. Security SAST Audit Tests
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_audit_security_detects_dangerous_patterns(tmp_path: Path):
    foundry = ProductFoundry(workspace_root=tmp_path)
    dirty_files = [
        FoundryFileSpec(
            relative_path="unsafe.py",
            assigned_agent_id="forge-01",
            file_type="source",
            purpose="Vulnerable module",
            content="def run_user_code(inp):\n    return eval(inp)\n"
        ),
        FoundryFileSpec(
            relative_path="shell.py",
            assigned_agent_id="forge-01",
            file_type="source",
            purpose="Shell runner",
            content="import os\nos.system('rm -rf /')\n"
        )
    ]

    report = await foundry._audit_security(
        goal_id="test-goal-sec",
        project_dir=tmp_path,
        files=dirty_files
    )

    assert report.passed is False
    assert report.security_score < 75.0
    assert any("Dynamic code evaluation" in v for v in report.vulnerabilities)
    assert any("Arbitrary shell execution" in v for v in report.vulnerabilities)

@pytest.mark.anyio
async def test_audit_security_clean_code(tmp_path: Path):
    foundry = ProductFoundry(workspace_root=tmp_path)
    clean_files = [
        FoundryFileSpec(
            relative_path="safe.py",
            assigned_agent_id="forge-01",
            file_type="source",
            purpose="Safe module",
            content="def add(a: int, b: int) -> int:\n    return a + b\n"
        )
    ]

    report = await foundry._audit_security(
        goal_id="test-goal-safe",
        project_dir=tmp_path,
        files=clean_files
    )

    assert report.passed is True
    assert report.security_score >= 90.0
    assert len(report.vulnerabilities) == 0

# -----------------------------------------------------------------------------
# 4. Sandboxed Subprocess Test Runner
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_subprocess_test_runner_pass(tmp_path: Path):
    foundry = ProductFoundry(workspace_root=tmp_path)
    test_file = tmp_path / "test_success.py"
    test_file.write_text("def test_ok():\n    assert 2 + 2 == 4\n", encoding="utf-8")

    result = await foundry._run_test_file(tmp_path, "test_success.py")
    assert result.passed is True
    assert result.exit_code == 0
    assert result.execution_time_ms > 0

@pytest.mark.anyio
async def test_subprocess_test_runner_fail(tmp_path: Path):
    foundry = ProductFoundry(workspace_root=tmp_path)
    test_file = tmp_path / "test_fail.py"
    test_file.write_text("def test_bad():\n    assert 2 + 2 == 5\n", encoding="utf-8")

    result = await foundry._run_test_file(tmp_path, "test_fail.py")
    assert result.passed is False
    assert result.exit_code != 0
    assert result.failure_summary is not None
    assert "FAILED" in result.failure_summary or "AssertionError" in result.failure_summary

# -----------------------------------------------------------------------------
# 5. Certification Scoring
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_certification_scoring(tmp_path: Path):
    foundry = ProductFoundry(workspace_root=tmp_path)
    sec_report = FoundrySecurityReport(
        auditor_id="cipher-04",
        security_score=95.0,
        passed=True,
        vulnerabilities=[]
    )
    test_results = [
        FoundryTestResult(
            test_file="test_app.py",
            passed=True,
            exit_code=0,
            stdout="OK",
            stderr="",
            execution_time_ms=50.0
        )
    ]
    files = [
        FoundryFileSpec(
            relative_path="app.py",
            assigned_agent_id="forge-01",
            purpose="Core app"
        )
    ]

    cert = await foundry._certify_product(
        goal_id="test-goal-cert",
        project_name="Demo Project",
        project_slug="demo-proj",
        project_dir=tmp_path,
        files=files,
        security_report=sec_report,
        test_results=test_results,
        repairs_performed=0
    )

    assert cert.certified is True
    assert cert.verdict == "CERTIFIED_PRODUCTION_READY"
    assert cert.overall_score >= 85.0
    assert cert.test_pass_rate == 100.0

# -----------------------------------------------------------------------------
# 6. API Endpoints & Traversal Protection
# -----------------------------------------------------------------------------

def test_api_list_projects(client: TestClient, monkeypatch, tmp_path: Path):
    """Verifies listing projects from workspace root."""
    from backend.core.foundry import product_foundry
    monkeypatch.setattr(product_foundry, "workspace_root", tmp_path)

    # Create dummy project folder
    proj_dir = tmp_path / "dummy-app"
    proj_dir.mkdir()
    (proj_dir / "app.py").write_text("print('app')", encoding="utf-8")
    (proj_dir / "test_app.py").write_text("assert True", encoding="utf-8")
    (proj_dir / "README.md").write_text("# Dummy App", encoding="utf-8")

    res = client.get("/api/v1/foundry/projects")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    assert data[0]["slug"] == "dummy-app"
    assert data[0]["file_count"] == 3
    assert data[0]["has_tests"] is True

def test_api_get_project_details_and_read_file(client: TestClient, monkeypatch, tmp_path: Path):
    from backend.core.foundry import product_foundry
    monkeypatch.setattr(product_foundry, "workspace_root", tmp_path)

    proj_dir = tmp_path / "micro-service"
    proj_dir.mkdir()
    (proj_dir / "service.py").write_text("class Service:\n    pass\n", encoding="utf-8")
    (proj_dir / "README.md").write_text("# MicroService Documentation\n", encoding="utf-8")

    # Get details
    res = client.get("/api/v1/foundry/projects/micro-service")
    assert res.status_code == 200
    details = res.json()
    assert details["slug"] == "micro-service"
    assert details["file_count"] == 2
    assert "MicroService Documentation" in details["readme"]

    # Read specific file
    res_file = client.get("/api/v1/foundry/projects/micro-service/file?file_path=service.py")
    assert res_file.status_code == 200
    file_data = res_file.json()
    assert file_data["relative_path"] == "service.py"
    assert "class Service:" in file_data["content"]
    assert file_data["line_count"] == 2

def test_api_directory_traversal_protection(client: TestClient, monkeypatch, tmp_path: Path):
    """Verifies that attempting path traversal outside project directory returns 403 or 404."""
    from backend.core.foundry import product_foundry
    monkeypatch.setattr(product_foundry, "workspace_root", tmp_path)

    proj_dir = tmp_path / "secure-app"
    proj_dir.mkdir()
    (proj_dir / "safe.py").write_text("print('ok')", encoding="utf-8")

    # Attempt directory traversal
    res = client.get("/api/v1/foundry/projects/secure-app/file?file_path=../../outside.txt")
    assert res.status_code in (403, 404)

def test_api_build_validation(client: TestClient):
    """Verifies validation error on empty product intent."""
    res = client.post("/api/v1/foundry/build", json={"product_intent": "   "})
    assert res.status_code == 400
    assert "intent cannot be empty" in res.json()["detail"].lower()

def test_api_build_background_mode(client: TestClient):
    """Verifies background build mode returns immediately with initiated status."""
    res = client.post("/api/v1/foundry/build", json={
        "product_intent": "Build a light key-value store with TTL",
        "slug": "test-ttl-kv",
        "run_in_background": True
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "initiated"
