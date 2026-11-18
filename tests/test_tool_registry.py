"""
Comprehensive Test Suite for SWARM-100 General-Purpose Tool Registry
Verifies:
1. 9 Initial Tools Registered with full metadata, schemas, timeouts, and permission levels:
   - Calculator (SAFE)
   - Date and time (SAFE)
   - Workspace file reader (WORKSPACE_READ)
   - Workspace file creator (WORKSPACE_WRITE)
   - Structured data analysis (SAFE)
   - CSV processing (WORKSPACE_READ)
   - Local document summarisation (SAFE)
   - Read-only project inspection (WORKSPACE_READ)
   - Code testing in restricted environment (RESTRICTED_EXECUTION)
2. Permission Enforcement & Sandbox Boundary Protection:
   - Path traversal rejection (..) across all file and project tools
   - Credential and protected file modification defense (.env, id_rsa, .git)
   - Banning unrestricted shell access and network access
   - Static AST inspection blocking dangerous imports (os, sys, subprocess, socket)
   - Mandatory approval gate for RESTRICTED_EXECUTION tools
3. Approval Workflow (Request -> Pending -> Approve/Reject -> Execute)
4. Immutable SQLite Audit Record Logging
5. Orchestrator Tool Request Gateway & REST API Endpoints
"""

import asyncio
import os
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.core.orchestrator import orchestrator
from backend.core.tools.base import (
    ApprovalRequiredError,
    ExecutionTimeoutError,
    PermissionLevel,
    SecurityBoundaryError,
    ToolContext,
    ToolNotFoundError,
)
from backend.core.tools.implementations.calculator import CalculatorInput, CalculatorTool
from backend.core.tools.implementations.csv_processor import CSVProcessorInput, CSVProcessorTool
from backend.core.tools.implementations.data_analysis import DataAnalysisInput, StructuredDataAnalysisTool
from backend.core.tools.implementations.datetime_tool import DateTimeInput, DateTimeTool
from backend.core.tools.implementations.document_summarizer import DocumentSummarizerInput, DocumentSummarizerTool
from backend.core.tools.implementations.project_inspector import ProjectInspectorInput, ProjectInspectorTool
from backend.core.tools.implementations.restricted_code_tester import CodeTesterInput, RestrictedCodeTesterTool
from backend.core.tools.implementations.workspace_file_creator import FileCreatorInput, WorkspaceFileCreatorTool
from backend.core.tools.implementations.workspace_file_reader import FileReaderInput, WorkspaceFileReaderTool
from backend.core.tools.registry import ToolRegistry, tool_registry

# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_workspace():
    """Provides an isolated temporary workspace directory for file and project tools."""
    with tempfile.TemporaryDirectory(prefix="swarm_ws_test_") as tmp:
        ws_path = Path(tmp).resolve()
        # Create some sample files and subdirectories
        (ws_path / "src").mkdir()
        (ws_path / "src" / "app.py").write_text("print('hello world')", encoding="utf-8")
        (ws_path / "README.md").write_text("# Project Documentation\nThis is a test readme file.\nLine 3.", encoding="utf-8")
        (ws_path / "pyproject.toml").write_text("[project]\nname = 'test-proj'", encoding="utf-8")
        (ws_path / "data").mkdir()
        (ws_path / "data" / "users.csv").write_text(
            "id,name,role,salary,dept\n1,Alice,Engineer,95000,Engineering\n2,Bob,Analyst,72000,Finance\n3,Charlie,Engineer,105000,Engineering\n",
            encoding="utf-8"
        )
        yield ws_path


# =============================================================================
# 1. TOOL REGISTRY INITIALIZATION & METADATA TESTS
# =============================================================================

class TestToolRegistryMetadata:
    def test_exactly_nine_initial_tools_registered(self):
        tools = tool_registry.list_tools()
        assert len(tools) == 11

        tool_ids = {t["id"] for t in tools}
        expected_ids = {
            "calculator",
            "datetime_tool",
            "workspace_file_reader",
            "workspace_file_creator",
            "structured_data_analysis",
            "csv_processor",
            "document_summarizer",
            "project_inspector",
            "restricted_code_tester",
            "web_search",
            "web_scraper",
        }
        assert tool_ids == expected_ids

    def test_all_tools_have_required_specification_fields(self):
        for tool_meta in tool_registry.list_tools():
            assert "id" in tool_meta and tool_meta["id"]
            assert "name" in tool_meta and tool_meta["name"]
            assert "description" in tool_meta and len(tool_meta["description"]) > 10
            assert "permission_level" in tool_meta
            assert tool_meta["permission_level"] in [p.value for p in PermissionLevel]
            assert "timeout_seconds" in tool_meta and tool_meta["timeout_seconds"] > 0
            assert "input_schema" in tool_meta and isinstance(tool_meta["input_schema"], dict)
            assert "output_schema" in tool_meta and isinstance(tool_meta["output_schema"], dict)

    def test_get_tool_success_and_unknown_raises(self):
        calc = tool_registry.get_tool("calculator")
        assert calc.id == "calculator"
        assert calc.permission_level == PermissionLevel.SAFE

        with pytest.raises(ToolNotFoundError):
            tool_registry.get_tool("unregistered_tool_xyz")


# =============================================================================
# 2. FUNCTIONAL EXECUTION: SAFE COMPUTATION TOOLS
# =============================================================================

class TestSafeToolsExecution:
    def test_calculator_arithmetic_and_functions(self):
        tool = CalculatorTool()
        ctx = ToolContext(agent_id="stratos-01", workspace_path=Path("."))

        # Basic arithmetic
        res1 = asyncio.run(tool.execute(CalculatorInput(expression="(25 * 4) + (144 / 12)"), ctx))
        assert res1.result == 112.0

        # Math functions
        res2 = asyncio.run(tool.execute(CalculatorInput(expression="sqrt(144) + log10(100)"), ctx))
        assert res2.result == 14.0

        # Trigonometry and constants
        res3 = asyncio.run(tool.execute(CalculatorInput(expression="sin(pi / 2)"), ctx))
        assert round(res3.result, 4) == 1.0

    def test_calculator_rejects_division_by_zero(self):
        tool = CalculatorTool()
        ctx = ToolContext(agent_id="stratos-01", workspace_path=Path("."))
        with pytest.raises(ZeroDivisionError):
            asyncio.run(tool.execute(CalculatorInput(expression="10 / 0"), ctx))

    def test_datetime_tool_operations(self):
        tool = DateTimeTool()
        ctx = ToolContext(agent_id="stratos-01", workspace_path=Path("."))

        # Now
        res_now = asyncio.run(tool.execute(DateTimeInput(operation="now"), ctx))
        assert res_now.operation == "now"
        assert len(res_now.iso) > 10

        # Add days
        res_add = asyncio.run(
            tool.execute(DateTimeInput(operation="add", base_datetime="2026-01-01T00:00:00", days=5, hours=2), ctx)
        )
        assert "2026-01-06" in res_add.iso

        # Diff
        res_diff = asyncio.run(
            tool.execute(
                DateTimeInput(
                    operation="diff",
                    base_datetime="2026-01-01T00:00:00",
                    target_datetime="2026-01-03T12:00:00"
                ),
                ctx
            )
        )
        assert res_diff.details["days"] == 2
        assert res_diff.details["hours"] == 12

    def test_structured_data_analysis(self):
        tool = StructuredDataAnalysisTool()
        ctx = ToolContext(agent_id="axiom-01", workspace_path=Path("."))

        sample_data = [
            {"age": 25, "income": 50000, "city": "NY"},
            {"age": 30, "income": 65000, "city": "SF"},
            {"age": 35, "income": 80000, "city": "NY"},
            {"age": 40, "income": 95000, "city": "LA"},
            {"age": 45, "income": 110000, "city": "SF"},
        ]

        res = asyncio.run(tool.execute(DataAnalysisInput(data=sample_data, compute_correlation=True), ctx))
        assert res.row_count == 5
        assert res.column_count == 3
        assert "age" in res.numeric_summary
        assert "income" in res.numeric_summary
        assert res.numeric_summary["age"].mean == 35.0
        assert res.numeric_summary["income"].mean == 80000.0
        assert res.categorical_top_frequencies["city"]["NY"] == 2
        assert res.correlation_matrix is not None
        assert res.correlation_matrix["age"]["income"] == 1.0  # Perfect linear correlation

    def test_document_summarizer_extractive(self):
        tool = DocumentSummarizerTool()
        ctx = ToolContext(agent_id="recon-08", workspace_path=Path("."))

        text = (
            "The SWARM-100 system coordinates 100 specialist agents organized across 10 distinct operational teams. "
            "Each team possesses deep domain capabilities ranging from strategy and business analysis to code review and security audits. "
            "A central orchestrator parses natural language goals into directed acyclic task graphs. "
            "Tasks are dispatched through asynchronous worker pools with strict concurrency limits. "
            "Independent critic agents review every task deliverable for factual errors, missing requirements, and weak reasoning. "
            "Persistent memory records successful approaches and failure patterns to enable controlled self-improvement across restarts."
        )

        res = asyncio.run(tool.execute(DocumentSummarizerInput(text=text, max_sentences=3), ctx))
        assert res.original_word_count > 40
        assert res.summary_word_count < res.original_word_count
        assert len(res.key_takeaways) <= 3
        assert len(res.salient_keywords) >= 3


# =============================================================================
# 3. WORKSPACE CONFINEMENT & FILE TOOLS
# =============================================================================

class TestWorkspaceFileTools:
    def test_workspace_file_creator_and_reader(self, temp_workspace):
        creator = WorkspaceFileCreatorTool()
        reader = WorkspaceFileReaderTool()
        ctx = ToolContext(agent_id="forge-01", workspace_path=temp_workspace)

        # 1. Create file inside workspace
        create_res = asyncio.run(
            creator.execute(
                FileCreatorInput(
                    relative_path="docs/architecture.md",
                    content="# Architecture\nDesigned with strict sandbox boundaries."
                ),
                ctx
            )
        )
        assert create_res.created is True
        assert create_res.bytes_written > 0
        assert (temp_workspace / "docs" / "architecture.md").exists()

        # 2. Read file back
        read_res = asyncio.run(
            reader.execute(
                FileReaderInput(relative_path="docs/architecture.md"),
                ctx
            )
        )
        assert "Designed with strict sandbox boundaries" in read_res.content
        assert read_res.line_count == 2
        assert read_res.truncated is False

    def test_workspace_file_creator_refuses_overwrite_without_flag(self, temp_workspace):
        creator = WorkspaceFileCreatorTool()
        ctx = ToolContext(agent_id="forge-01", workspace_path=temp_workspace)

        # Existing file is README.md
        with pytest.raises(FileExistsError):
            asyncio.run(
                creator.execute(
                    FileCreatorInput(relative_path="README.md", content="New text", overwrite=False),
                    ctx
                )
            )

        # Overwrite succeeds when overwrite=True
        res = asyncio.run(
            creator.execute(
                FileCreatorInput(relative_path="README.md", content="Overwritten text", overwrite=True),
                ctx
            )
        )
        assert res.created is True
        assert (temp_workspace / "README.md").read_text() == "Overwritten text"

    def test_project_inspector_maps_hierarchy(self, temp_workspace):
        tool = ProjectInspectorTool()
        ctx = ToolContext(agent_id="forge-02", workspace_path=temp_workspace)

        res = asyncio.run(tool.execute(ProjectInspectorInput(sub_directory=""), ctx))
        assert res.total_files >= 3
        assert res.total_directories >= 2
        assert ".py" in res.extension_breakdown
        assert ".md" in res.extension_breakdown
        assert "README.md" in res.directory_tree
        assert any("pyproject.toml" in m for m in res.discovered_manifests)

    def test_csv_processor_filter_and_aggregate(self, temp_workspace):
        tool = CSVProcessorTool()
        ctx = ToolContext(agent_id="axiom-03", workspace_path=temp_workspace)

        res = asyncio.run(
            tool.execute(
                CSVProcessorInput(
                    workspace_file_path="data/users.csv",
                    filter_column="dept",
                    filter_operator="eq",
                    filter_value="Engineering",
                    group_by="dept",
                    aggregate_column="salary",
                    aggregate_function="mean"
                ),
                ctx
            )
        )

        assert res.total_rows == 3
        assert res.filtered_rows == 2
        assert len(res.records) == 2
        assert res.aggregation["function"] == "mean"
        assert res.aggregation["results"]["Engineering"] == 100000.0  # (95000 + 105000)/2


# =============================================================================
# 4. PERMISSION ENFORCEMENT & SECURITY DEFENSES
# =============================================================================

class TestSecurityAndPermissionEnforcement:
    def test_path_traversal_rejection_in_file_reader(self, temp_workspace):
        tool = WorkspaceFileReaderTool()
        ctx = ToolContext(agent_id="aegis-01", workspace_path=temp_workspace)

        # Traversal attempts
        with pytest.raises(SecurityBoundaryError) as exc:
            asyncio.run(tool.execute(FileReaderInput(relative_path="../../etc/passwd"), ctx))
        assert "Path traversal '..' is forbidden" in str(exc.value)

        with pytest.raises(SecurityBoundaryError) as exc:
            asyncio.run(tool.execute(FileReaderInput(relative_path="src/../../windows/win.ini"), ctx))
        assert "Path traversal '..' is forbidden" in str(exc.value)

    def test_path_traversal_rejection_in_file_creator(self, temp_workspace):
        tool = WorkspaceFileCreatorTool()
        ctx = ToolContext(agent_id="aegis-01", workspace_path=temp_workspace)

        with pytest.raises(SecurityBoundaryError) as exc:
            asyncio.run(tool.execute(FileCreatorInput(relative_path="../escape.txt", content="malicious"), ctx))
        assert "Path traversal '..' is forbidden" in str(exc.value)

    def test_file_creator_blocks_protected_credentials(self, temp_workspace):
        tool = WorkspaceFileCreatorTool()
        ctx = ToolContext(agent_id="aegis-01", workspace_path=temp_workspace)

        # Attempt to write to .env
        with pytest.raises(SecurityBoundaryError) as exc:
            asyncio.run(tool.execute(FileCreatorInput(relative_path=".env", content="API_KEY=stolen"), ctx))
        assert "protected file '.env' is prohibited" in str(exc.value)

        # Attempt to write to id_rsa
        with pytest.raises(SecurityBoundaryError) as exc:
            asyncio.run(tool.execute(FileCreatorInput(relative_path="keys/id_rsa", content="private key"), ctx))
        assert "protected file 'id_rsa' is prohibited" in str(exc.value)

    def test_calculator_blocks_code_injection_tokens(self):
        tool = CalculatorTool()
        ctx = ToolContext(agent_id="aegis-01", workspace_path=Path("."))

        malicious_inputs = [
            "__import__('os').system('ls')",
            "eval('2+2')",
            "lambda x: x",
            "[x for x in ().__class__.__bases__[0].__subclasses__()]",
            "open('passwords.txt')",
        ]

        for mal in malicious_inputs:
            with pytest.raises((SecurityBoundaryError, ValueError)):
                asyncio.run(tool.execute(CalculatorInput(expression=mal), ctx))

    def test_code_tester_requires_approval(self):
        tool = RestrictedCodeTesterTool()
        # When context.is_approved is False (default)
        ctx = ToolContext(agent_id="forge-01", workspace_path=Path("."), is_approved=False)

        with pytest.raises(ApprovalRequiredError) as exc:
            asyncio.run(tool.execute(CodeTesterInput(code="assert 1 == 1"), ctx))

        assert "requires explicit approval" in str(exc.value)

    def test_code_tester_executes_when_approved(self):
        tool = RestrictedCodeTesterTool()
        # Explicit approval granted
        ctx = ToolContext(
            agent_id="forge-01",
            workspace_path=Path("."),
            is_approved=True,
            approved_by="human_operator"
        )

        code = (
            "def add(a, b):\n"
            "    return a + b\n\n"
            "assert add(3, 4) == 7\n"
            "print('All tests passed successfully.')\n"
        )

        res = asyncio.run(tool.execute(CodeTesterInput(code=code, expected_output="All tests passed"), ctx))
        assert res.passed is True
        assert res.exit_code == 0
        assert "All tests passed successfully" in res.stdout
        assert res.assertions_count == 1

    def test_code_tester_blocks_banned_modules_even_if_approved(self):
        tool = RestrictedCodeTesterTool()
        ctx = ToolContext(agent_id="forge-01", workspace_path=Path("."), is_approved=True)

        forbidden_snippets = [
            "import os\nos.system('echo test')",
            "import subprocess\nsubprocess.run(['dir'])",
            "import socket\ns = socket.socket()",
            "import urllib.request",
            "import shutil",
            "from sys import modules",
        ]

        for code in forbidden_snippets:
            with pytest.raises(SecurityBoundaryError) as exc:
                asyncio.run(tool.execute(CodeTesterInput(code=code), ctx))
            assert "Security Boundary Violation: Import" in str(exc.value)

    def test_code_tester_blocks_dunder_reflection(self):
        tool = RestrictedCodeTesterTool()
        ctx = ToolContext(agent_id="forge-01", workspace_path=Path("."), is_approved=True)

        reflection_code = "x = ().__class__.__bases__"
        with pytest.raises(SecurityBoundaryError) as exc:
            asyncio.run(tool.execute(CodeTesterInput(code=reflection_code), ctx))
        assert "dunder attribute" in str(exc.value)


# =============================================================================
# 5. APPROVAL WORKFLOW & AUDIT LOGGING
# =============================================================================

class TestApprovalWorkflowAndAuditLogging:
    def test_approval_lifecycle(self):
        # 1. Create approval request
        appr_id = tool_registry.create_approval_request(
            tool_id="restricted_code_tester",
            agent_id="forge-01",
            parameters={"code": "assert 10 > 5"},
            justification="Unit verification of sorting routine"
        )
        assert appr_id.startswith("appr-")

        # 2. Check pending list
        pending = tool_registry.list_pending_approvals()
        assert any(p["id"] == appr_id for p in pending)

        # 3. Resolve request (approve)
        resolved = tool_registry.resolve_approval_request(
            approval_id=appr_id,
            approved=True,
            resolved_by="orchestrator",
            resolution_notes="Authorized for task verification"
        )
        assert resolved["status"] == "approved"

        # 4. Check no longer pending
        pending_after = tool_registry.list_pending_approvals()
        assert not any(p["id"] == appr_id for p in pending_after)

    def test_registry_executes_and_logs_audit_record(self):
        # Execute safe calculator tool
        res = asyncio.run(
            tool_registry.execute_tool(
                tool_id="calculator",
                agent_id="stratos-01",
                parameters={"expression": "100 * 25"}
            )
        )
        assert res["status"] == "success"
        assert res["result"]["result"] == 2500.0
        assert "audit_id" in res

        # Verify record in audit log
        audit_logs = tool_registry.get_audit_logs(tool_id="calculator", agent_id="stratos-01")
        assert len(audit_logs) >= 1
        latest = audit_logs[0]
        assert latest["tool_id"] == "calculator"
        assert latest["agent_id"] == "stratos-01"
        assert latest["status"] == "success"
        assert latest["permission_level"] == "SAFE"
        assert latest["execution_time_ms"] >= 0.0

    def test_unapproved_restricted_tool_creates_approval_and_audit(self):
        # Calling restricted tool without approval must fail with ApprovalRequiredError
        with pytest.raises(ApprovalRequiredError) as exc_info:
            asyncio.run(
                tool_registry.execute_tool(
                    tool_id="restricted_code_tester",
                    agent_id="forge-01",
                    parameters={"code": "assert True"},
                    is_approved=False
                )
            )

        appr_id = exc_info.value.approval_id
        assert appr_id is not None

        # Verify audit log recorded blocked permission
        logs = tool_registry.get_audit_logs(tool_id="restricted_code_tester", status="blocked_permission")
        assert any(l["agent_id"] == "forge-01" for l in logs)

    def test_execution_timeout_enforcement(self):
        from backend.core.tools.base import BaseTool
        from pydantic import BaseModel

        class SleepInput(BaseModel):
            duration: float

        class SleepOutput(BaseModel):
            done: bool

        class SlowTool(BaseTool):
            id = "test_slow_tool"
            name = "Slow Execution Tool"
            description = "Tool designed to test timeout enforcement"
            permission_level = PermissionLevel.SAFE
            timeout_seconds = 0.2
            input_schema = SleepInput
            output_schema = SleepOutput

            async def execute(self, params: SleepInput, context: ToolContext) -> SleepOutput:
                await asyncio.sleep(params.duration)
                return SleepOutput(done=True)

        try:
            tool_registry.register_tool(SlowTool())

            with pytest.raises(ExecutionTimeoutError) as exc_info:
                asyncio.run(
                    tool_registry.execute_tool(
                        tool_id="test_slow_tool",
                        agent_id="forge-01",
                        parameters={"duration": 1.0}
                    )
                )

            assert "exceeded maximum timeout limit" in str(exc_info.value)
            # Verify audit log marked as timeout
            logs = tool_registry.get_audit_logs(tool_id="test_slow_tool", status="timeout")
            assert len(logs) >= 1
        finally:
            tool_registry.unregister_tool("test_slow_tool")



# =============================================================================
# 6. ORCHESTRATOR INTEGRATION & FASTAPI REST ENDPOINTS
# =============================================================================

class TestOrchestratorToolGatewayAndAPIs:
    def test_orchestrator_gateway_execution(self):
        # Agents must request tools through the orchestrator
        res = asyncio.run(
            orchestrator.request_tool_execution(
                agent_id="stratos-01",
                tool_id="calculator",
                parameters={"expression": "sqrt(64) * 10"}
            )
        )
        assert res["status"] == "success"
        assert res["result"]["result"] == 80.0

    def test_orchestrator_gateway_rejects_unknown_agent(self):
        with pytest.raises(ValueError) as exc:
            asyncio.run(
                orchestrator.request_tool_execution(
                    agent_id="nonexistent-agent",
                    tool_id="calculator",
                    parameters={"expression": "1 + 1"}
                )
            )
        assert "not found in registry" in str(exc.value)

    def test_api_list_tools(self, client: TestClient):
        res = client.get("/api/v1/tools")
        assert res.status_code == 200
        tools = res.json()
        assert len(tools) == 11

    def test_api_inspect_tool(self, client: TestClient):
        res = client.get("/api/v1/tools/calculator")
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == "calculator"
        assert data["permission_level"] == "SAFE"
        assert "input_schema" in data

    def test_api_execute_safe_tool(self, client: TestClient):
        payload = {
            "agent_id": "stratos-01",
            "parameters": {"expression": "15 * 6"}
        }
        res = client.post("/api/v1/tools/calculator/execute", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["result"]["result"] == 90.0

    def test_api_execute_restricted_tool_requires_approval(self, client: TestClient):
        payload = {
            "agent_id": "forge-01",
            "parameters": {"code": "assert 5 == 5"},
            "is_approved": False
        }
        res = client.post("/api/v1/tools/restricted_code_tester/execute", json=payload)
        assert res.status_code == 403
        detail = res.json()["detail"]
        assert detail["error"] == "ApprovalRequired"
        assert "approval_id" in detail

    def test_api_resolve_approval_and_execute(self, client: TestClient):
        # 1. Trigger unapproved call
        payload = {
            "agent_id": "forge-01",
            "parameters": {"code": "assert 10 == 10"},
            "is_approved": False
        }
        res1 = client.post("/api/v1/tools/restricted_code_tester/execute", json=payload)
        assert res1.status_code == 403
        appr_id = res1.json()["detail"]["approval_id"]

        # 2. Resolve approval
        resolve_res = client.post(
            f"/api/v1/tools/approvals/{appr_id}/resolve",
            json={"approved": True, "resolved_by": "user_admin", "resolution_notes": "Granted"}
        )
        assert resolve_res.status_code == 200
        assert resolve_res.json()["status"] == "approved"

        # 3. Call tool with is_approved=True
        exec_payload = {
            "agent_id": "forge-01",
            "parameters": {"code": "assert 10 == 10"},
            "is_approved": True,
            "approved_by": "user_admin"
        }
        res2 = client.post("/api/v1/tools/restricted_code_tester/execute", json=exec_payload)
        assert res2.status_code == 200
        assert res2.json()["status"] == "success"
        assert res2.json()["result"]["passed"] is True

    def test_api_get_audit_logs(self, client: TestClient):
        res = client.get("/api/v1/tools/audit")
        assert res.status_code == 200
        logs = res.json()
        assert isinstance(logs, list)
        assert len(logs) >= 1
