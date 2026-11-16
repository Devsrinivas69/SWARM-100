"""
Tool 4: File Creation inside Approved Workspace
Creates and writes files strictly confined within the approved workspace root.
Blocks path traversal, destructive writes, and writing to sensitive system or credential files.
"""

from pathlib import Path
from pydantic import BaseModel, Field

from backend.core.tools.base import (
    BaseTool,
    PermissionLevel,
    SecurityBoundaryError,
    ToolContext,
)

BANNED_WRITE_FILENAMES = {".env", "id_rsa", "credentials.json", ".git", ".gitignore"}

class FileCreatorInput(BaseModel):
    relative_path: str = Field(..., min_length=1, description="Relative destination path inside workspace (e.g. 'output/report.txt')")
    content: str = Field(..., description="Text or structured content to write")
    overwrite: bool = Field(False, description="Whether to overwrite existing file (default False)")

class FileCreatorOutput(BaseModel):
    relative_path: str
    absolute_path: str
    bytes_written: int
    lines_written: int
    created: bool

class WorkspaceFileCreatorTool(BaseTool):
    id = "workspace_file_creator"
    name = "Workspace File Creator"
    description = (
        "Creates or writes files strictly confined inside the approved workspace root. "
        "Enforces boundary checks, prevents path traversal, and protects credential files."
    )
    permission_level = PermissionLevel.WORKSPACE_WRITE
    timeout_seconds = 10.0
    input_schema = FileCreatorInput
    output_schema = FileCreatorOutput

    async def execute(self, params: FileCreatorInput, context: ToolContext) -> FileCreatorOutput:
        workspace_root = context.workspace_path.resolve()

        # Sanitize relative path
        norm_rel = Path(params.relative_path)
        if any(part == ".." for part in norm_rel.parts):
            raise SecurityBoundaryError(f"Security Boundary Violation: Path traversal '..' is forbidden ('{params.relative_path}').")

        # Protect against writing to sensitive filenames
        filename = norm_rel.name.lower()
        if filename in BANNED_WRITE_FILENAMES or filename.startswith(".env"):
            raise SecurityBoundaryError(f"Security Restriction: Writing to protected file '{filename}' is prohibited.")

        target_file = (workspace_root / norm_rel).resolve()

        # Enforce containment within workspace root
        if not target_file.is_relative_to(workspace_root):
            raise SecurityBoundaryError(
                f"Security Boundary Violation: Target '{target_file}' escapes approved workspace '{workspace_root}'."
            )

        if target_file.exists() and not params.overwrite:
            raise FileExistsError(
                f"File '{params.relative_path}' already exists. Set 'overwrite=True' if replacement is intended."
            )

        # Create parent directories safely within workspace
        target_file.parent.mkdir(parents=True, exist_ok=True)

        # Write content
        encoded = params.content.encode("utf-8")
        target_file.write_text(params.content, encoding="utf-8")

        lines = params.content.splitlines()

        return FileCreatorOutput(
            relative_path=params.relative_path,
            absolute_path=str(target_file),
            bytes_written=len(encoded),
            lines_written=len(lines),
            created=True
        )
