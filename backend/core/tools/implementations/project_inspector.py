"""
Tool 8: Read-Only Project Inspection
Produces structured directory trees, file extension inventories, and project manifest discovery.
Strictly read-only and confined to the approved workspace.
"""

from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from backend.core.tools.base import (
    BaseTool,
    PermissionLevel,
    SecurityBoundaryError,
    ToolContext,
)

IGNORED_DIRS = {
    ".git", "__pycache__", "node_modules", ".pytest_cache", ".venv", "venv",
    ".idea", ".vscode", "dist", "build", ".mypy_cache"
}

MANIFEST_FILENAMES = {
    "package.json", "pyproject.toml", "requirements.txt", "setup.py", "dockerfile",
    "docker-compose.yml", "readme.md", "makefile", "cargo.toml", "go.mod"
}

class ProjectInspectorInput(BaseModel):
    sub_directory: str = Field("", description="Subdirectory within approved workspace to inspect (default root)")
    max_depth: int = Field(3, ge=1, le=6, description="Maximum directory traversal depth (default 3)")
    include_file_sizes: bool = Field(True, description="Whether to include size metrics in the tree")

class ProjectInspectorOutput(BaseModel):
    inspected_path: str
    total_files: int
    total_directories: int
    total_size_bytes: int
    extension_breakdown: Dict[str, int]
    directory_tree: str
    discovered_manifests: List[str]

class ProjectInspectorTool(BaseTool):
    id = "project_inspector"
    name = "Read-Only Project Inspector"
    description = (
        "Inspects directory structures, calculates size distributions, and maps project hierarchy "
        "within the approved workspace root while automatically filtering build and cache directories."
    )
    permission_level = PermissionLevel.WORKSPACE_READ
    timeout_seconds = 10.0
    input_schema = ProjectInspectorInput
    output_schema = ProjectInspectorOutput

    async def execute(self, params: ProjectInspectorInput, context: ToolContext) -> ProjectInspectorOutput:
        workspace_root = context.workspace_path.resolve()

        norm_rel = Path(params.sub_directory.strip())
        if any(part == ".." for part in norm_rel.parts):
            raise SecurityBoundaryError("Security Boundary Violation: Path traversal '..' is forbidden in project inspector.")

        target_dir = (workspace_root / norm_rel).resolve()

        if not target_dir.is_relative_to(workspace_root):
            raise SecurityBoundaryError(
                f"Security Boundary Violation: Target '{target_dir}' escapes approved workspace '{workspace_root}'."
            )

        if not target_dir.exists():
            raise FileNotFoundError(f"Directory '{params.sub_directory}' does not exist in workspace.")

        if not target_dir.is_dir():
            raise ValueError(f"Path '{params.sub_directory}' is a file, not a directory.")

        total_files = 0
        total_dirs = 0
        total_size = 0
        ext_breakdown: Dict[str, int] = {}
        manifests: List[str] = []
        tree_lines: List[str] = [f"{target_dir.name or 'workspace'}/"]

        def _traverse(current: Path, prefix: str, depth: int):
            nonlocal total_files, total_dirs, total_size

            if depth > params.max_depth:
                return

            try:
                entries = sorted(list(current.iterdir()), key=lambda e: (not e.is_dir(), e.name.lower()))
            except PermissionError:
                return

            filtered_entries = [e for e in entries if e.name not in IGNORED_DIRS]

            for idx, entry in enumerate(filtered_entries):
                is_last = (idx == len(filtered_entries) - 1)
                connector = "└── " if is_last else "├── "
                sub_prefix = "    " if is_last else "│   "

                if entry.is_dir():
                    total_dirs += 1
                    tree_lines.append(f"{prefix}{connector}{entry.name}/")
                    _traverse(entry, prefix + sub_prefix, depth + 1)
                elif entry.is_file():
                    total_files += 1
                    try:
                        sz = entry.stat().st_size
                        total_size += sz
                    except Exception:
                        sz = 0

                    ext = entry.suffix.lower() or "[no_ext]"
                    ext_breakdown[ext] = ext_breakdown.get(ext, 0) + 1

                    if entry.name.lower() in MANIFEST_FILENAMES:
                        rel_m = str(entry.relative_to(workspace_root))
                        manifests.append(rel_m)

                    size_tag = f" ({sz:,} B)" if params.include_file_sizes else ""
                    tree_lines.append(f"{prefix}{connector}{entry.name}{size_tag}")

        _traverse(target_dir, "", 1)

        return ProjectInspectorOutput(
            inspected_path=str(target_dir.relative_to(workspace_root)) if target_dir != workspace_root else ".",
            total_files=total_files,
            total_directories=total_dirs,
            total_size_bytes=total_size,
            extension_breakdown=ext_breakdown,
            directory_tree="\n".join(tree_lines[:250]),  # Limit tree lines to prevent output explosion
            discovered_manifests=manifests
        )
