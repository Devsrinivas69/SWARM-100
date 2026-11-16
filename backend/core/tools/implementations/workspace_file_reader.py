"""
Tool 3: File Reading inside Approved Workspace
Enforces strict path containment within the approved workspace.
Blocks path traversal (../), symlink escape, and access to external filesystem locations.
"""

from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

from backend.core.tools.base import (
    BaseTool,
    PermissionLevel,
    SecurityBoundaryError,
    ToolContext,
)

class FileReaderInput(BaseModel):
    relative_path: str = Field(..., min_length=1, description="Relative path within the approved workspace (e.g. 'data/sample.json')")
    start_line: int = Field(1, ge=1, description="Starting line to read (1-indexed)")
    end_line: Optional[int] = Field(None, ge=1, description="Optional ending line to read (inclusive)")
    max_bytes: int = Field(200_000, ge=100, le=2_000_000, description="Maximum bytes to read before truncating")

class FileReaderOutput(BaseModel):
    relative_path: str
    absolute_path: str
    content: str
    line_count: int
    byte_size: int
    truncated: bool

class WorkspaceFileReaderTool(BaseTool):
    id = "workspace_file_reader"
    name = "Workspace File Reader"
    description = (
        "Reads text, configuration, and data files strictly confined inside the approved workspace root. "
        "Strictly rejects path traversal ('..'), absolute system paths, and symlinks escaping the workspace boundary."
    )
    permission_level = PermissionLevel.WORKSPACE_READ
    timeout_seconds = 10.0
    input_schema = FileReaderInput
    output_schema = FileReaderOutput

    async def execute(self, params: FileReaderInput, context: ToolContext) -> FileReaderOutput:
        workspace_root = context.workspace_path.resolve()

        # Sanitize path: block raw '..' sequences in relative path
        norm_rel = Path(params.relative_path)
        if any(part == ".." for part in norm_rel.parts):
            raise SecurityBoundaryError(f"Security Boundary Violation: Path traversal '..' is forbidden ('{params.relative_path}').")

        target_file = (workspace_root / norm_rel).resolve()

        # Enforce containment within workspace root
        try:
            if not target_file.is_relative_to(workspace_root):
                raise SecurityBoundaryError(
                    f"Security Boundary Violation: Resolved target '{target_file}' escapes approved workspace '{workspace_root}'."
                )
        except AttributeError:
            # Fallback for Python versions where is_relative_to might behave differently
            if not str(target_file).startswith(str(workspace_root)):
                raise SecurityBoundaryError(f"Security Boundary Violation: Path escapes approved workspace.")

        if not target_file.exists():
            raise FileNotFoundError(f"File '{params.relative_path}' not found inside approved workspace.")

        if not target_file.is_file():
            raise ValueError(f"Path '{params.relative_path}' is a directory, not a file.")

        # Read content safely
        try:
            raw_text = target_file.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            raise IOError(f"Failed to read file '{params.relative_path}': {e}")

        lines = raw_text.splitlines(keepends=True)
        total_lines = len(lines)

        start_idx = max(0, params.start_line - 1)
        end_idx = min(total_lines, params.end_line) if params.end_line else total_lines

        selected_lines = lines[start_idx:end_idx]
        content = "".join(selected_lines)

        truncated = False
        if len(content.encode("utf-8")) > params.max_bytes:
            content = content.encode("utf-8")[:params.max_bytes].decode("utf-8", errors="ignore")
            truncated = True

        return FileReaderOutput(
            relative_path=params.relative_path,
            absolute_path=str(target_file),
            content=content,
            line_count=len(selected_lines),
            byte_size=len(content.encode("utf-8")),
            truncated=truncated
        )
