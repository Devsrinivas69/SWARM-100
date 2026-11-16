"""
Tool 9: Code Testing in a Restricted Environment
Executes Python tests, algorithms, and assertions in an isolated sandbox.
Enforces:
- MANDATORY APPROVAL: Cannot execute without explicit approval token (ApprovalRequiredError).
- AST SECURITY VERIFICATION: Statically inspects code and rejects shell, network, and reflection calls.
- ISOLATED BUILTINS: Strips access to os, sys, subprocess, sockets, filesystem, and dunder attributes.
- TIMEOUT GUARD: Enforces execution timeout (default 5.0s).
- STDOUT/STDERR CAPTURE: Captures all output cleanly without leakage.
"""

import ast
import io
import math
import sys
import time
from typing import Optional
from pydantic import BaseModel, Field

from backend.core.tools.base import (
    ApprovalRequiredError,
    BaseTool,
    PermissionLevel,
    SecurityBoundaryError,
    ToolContext,
)

BANNED_MODULES = {
    "os", "sys", "subprocess", "socket", "urllib", "requests", "http", "ftplib",
    "importlib", "shutil", "ctypes", "threading", "multiprocessing", "pty",
    "posix", "nt", "builtins", "signal", "tempfile", "glob", "pathlib", "io"
}

BANNED_FUNCTIONS = {
    "eval", "exec", "compile", "__import__", "open", "input", "breakpoint",
    "getattr", "setattr", "delattr"
}

BANNED_ATTRIBUTES = {
    "__class__", "__subclasses__", "__bases__", "__mro__", "__code__",
    "__globals__", "__builtins__", "__dict__"
}

class CodeTesterInput(BaseModel):
    code: str = Field(..., min_length=1, max_length=15000, description="Python test or validation script to execute")
    expected_output: Optional[str] = Field(None, description="Optional expected string in stdout for automated validation")

class CodeTesterOutput(BaseModel):
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    assertions_count: int
    execution_time_ms: float

class RestrictedCodeTesterTool(BaseTool):
    id = "restricted_code_tester"
    name = "Restricted Code Testing Environment"
    description = (
        "Executes algorithmic Python code and unit test assertions within an isolated sandbox. "
        "Strictly requires explicit orchestrator/human approval. Banned from network, shell, and filesystem access."
    )
    permission_level = PermissionLevel.RESTRICTED_EXECUTION
    timeout_seconds = 5.0
    input_schema = CodeTesterInput
    output_schema = CodeTesterOutput

    async def execute(self, params: CodeTesterInput, context: ToolContext) -> CodeTesterOutput:
        # Rule 1: Mandatory Approval Gate
        if not context.is_approved:
            raise ApprovalRequiredError(
                f"Security Restriction: Tool 'restricted_code_tester' has permission level "
                f"'{self.permission_level.value}'. Execution requires explicit approval before running.",
                tool_id=self.id
            )

        # Rule 2: Static AST Security Verification
        assertions_count = self._verify_ast_safety(params.code)

        # Rule 3: Isolated Sandboxed Execution
        start_time = time.perf_counter()
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        # Build isolated builtins
        safe_builtins = {
            "print": lambda *args, **kwargs: print(*args, **kwargs, file=stdout_buf),
            "range": range,
            "len": len,
            "int": int,
            "float": float,
            "str": str,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "bool": bool,
            "min": min,
            "max": max,
            "sum": sum,
            "sorted": sorted,
            "abs": abs,
            "round": round,
            "enumerate": enumerate,
            "zip": zip,
            "all": all,
            "any": any,
            "isinstance": isinstance,
            "issubclass": issubclass,
            "Exception": Exception,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "KeyError": KeyError,
            "IndexError": IndexError,
            "AssertionError": AssertionError,
            "True": True,
            "False": False,
            "None": None,
        }

        sandbox_globals = {
            "__builtins__": safe_builtins,
            "math": math,
        }

        passed = True
        exit_code = 0

        # Execute in restricted namespace
        try:
            compiled = compile(params.code, "<restricted_sandbox>", "exec")
            exec(compiled, sandbox_globals)
        except AssertionError as e:
            passed = False
            exit_code = 1
            stderr_buf.write(f"AssertionError: {e}\n")
        except Exception as e:
            passed = False
            exit_code = 1
            stderr_buf.write(f"{type(e).__name__}: {e}\n")

        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        captured_stdout = stdout_buf.getvalue()
        captured_stderr = stderr_buf.getvalue()

        if params.expected_output and params.expected_output not in captured_stdout:
            passed = False
            captured_stderr += f"\nValidation Failure: Expected output '{params.expected_output}' not found in stdout."

        return CodeTesterOutput(
            passed=passed,
            exit_code=exit_code,
            stdout=captured_stdout,
            stderr=captured_stderr,
            assertions_count=assertions_count,
            execution_time_ms=elapsed_ms
        )

    def _verify_ast_safety(self, code: str) -> int:
        """Parses AST and validates that no banned imports, calls, or attributes are accessed."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise ValueError(f"Code syntax error: {e}")

        assertions_count = 0

        for node in ast.walk(tree):
            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0].lower()
                    if root_mod in BANNED_MODULES:
                        raise SecurityBoundaryError(
                            f"Security Boundary Violation: Import of restricted module '{alias.name}' is strictly prohibited."
                        )

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_mod = node.module.split(".")[0].lower()
                    if root_mod in BANNED_MODULES:
                        raise SecurityBoundaryError(
                            f"Security Boundary Violation: Import from restricted module '{node.module}' is strictly prohibited."
                        )

            # Check calls
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in BANNED_FUNCTIONS:
                        raise SecurityBoundaryError(
                            f"Security Boundary Violation: Call to restricted function '{node.func.id}' is strictly prohibited."
                        )

            # Check attributes
            elif isinstance(node, ast.Attribute):
                if node.attr in BANNED_ATTRIBUTES or (node.attr.startswith("__") and node.attr.endswith("__")):
                    raise SecurityBoundaryError(
                        f"Security Boundary Violation: Access to dunder attribute '{node.attr}' is prohibited."
                    )

            # Track assertions
            elif isinstance(node, ast.Assert):
                assertions_count += 1

        return assertions_count
