"""
FastAPI Router: /api/v1/foundry
Endpoints for the SWARM-100 Autonomous Product Foundry:
- Building software products from natural language specs
- Listing synthesized workspace projects
- Inspecting project manifests, source files, and test results
- Re-running autonomous sandbox tests on demand
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.config import settings
from backend.core.foundry import product_foundry, FoundryBuildResult, FoundryTestResult
from backend.core.memory import memory_service
from backend.database import get_connection

router = APIRouter(prefix="/foundry", tags=["Product Foundry"])

# -----------------------------------------------------------------------------
# Request Schemas
# -----------------------------------------------------------------------------

class FoundryBuildRequest(BaseModel):
    product_intent: str = Field(..., description="Natural language specification of the software product")
    slug: Optional[str] = Field(None, description="Optional custom directory slug")
    project_name: Optional[str] = Field(None, description="Optional custom project name")
    run_in_background: bool = Field(False, description="Whether to run asynchronously and return immediately")

class FileContentResponse(BaseModel):
    slug: str
    relative_path: str
    content: str
    size_bytes: int
    line_count: int

# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@router.post("/build", summary="Build an autonomous software product")
async def build_product(
    payload: FoundryBuildRequest,
    background_tasks: BackgroundTasks
):
    """
    Triggers the 5-stage SWARM-100 Product Foundry pipeline:
    1. Specification & Architecture
    2. Multi-File Code Synthesis
    3. Security & Vulnerability SAST Audit
    4. Autonomous Sandboxed Testing & Self-Healing Loop
    5. Packaging & Certification Report
    """
    if not payload.product_intent.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product intent cannot be empty."
        )

    if payload.run_in_background:
        # Schedule build in background
        background_tasks.add_task(
            product_foundry.build_product,
            payload.product_intent,
            payload.slug,
            payload.project_name
        )
        return {
            "status": "initiated",
            "message": "Product Foundry build initiated in background. Track progress via WebSockets.",
            "intent": payload.product_intent
        }

    try:
        result = await product_foundry.build_product(
            product_intent=payload.product_intent,
            custom_slug=payload.slug,
            project_name=payload.project_name
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Foundry build failed: {str(e)}"
        )

@router.get("/projects", summary="List all generated workspace projects")
def list_projects() -> List[Dict[str, Any]]:
    """
    Lists all generated software projects in the workspace/projects directory.
    """
    projects_dir = product_foundry.workspace_root
    if not projects_dir.exists():
        return []

    projects = []
    for item in sorted(projects_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if item.is_dir() and not item.name.startswith("."):
            # Count files and inspect structure
            all_files = [f for f in item.rglob("*") if f.is_file() and not f.name.startswith(".")]
            has_tests = any("test" in f.name.lower() for f in all_files)
            has_readme = (item / "README.md").exists()

            projects.append({
                "slug": item.name,
                "project_name": item.name.replace("-", " ").title(),
                "path": str(item),
                "file_count": len(all_files),
                "has_tests": has_tests,
                "has_readme": has_readme,
                "modified_at": item.stat().st_mtime
            })

    return projects

@router.get("/projects/{slug}", summary="Inspect a specific project")
def get_project_details(slug: str) -> Dict[str, Any]:
    """
    Returns the file tree, metadata, and status of a generated project.
    """
    project_dir = (product_foundry.workspace_root / slug).resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{slug}' not found in workspace."
        )

    # Safe validation that directory stays within workspace_root
    if not str(project_dir).startswith(str(product_foundry.workspace_root.resolve())):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access outside project workspace forbidden."
        )

    files = []
    for f in sorted(project_dir.rglob("*")):
        if f.is_file() and not f.name.startswith(".") and "__pycache__" not in f.parts:
            rel = f.relative_to(project_dir).as_posix()
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                line_count = len(content.splitlines())
            except Exception:
                line_count = 0

            files.append({
                "relative_path": rel,
                "file_type": "test" if "test" in rel else ("doc" if rel.endswith(".md") else "source"),
                "size_bytes": f.stat().st_size,
                "line_count": line_count
            })

    # Read README if present
    readme_content = ""
    readme_file = project_dir / "README.md"
    if readme_file.exists():
        readme_content = readme_file.read_text(encoding="utf-8", errors="replace")

    return {
        "slug": slug,
        "project_name": slug.replace("-", " ").title(),
        "directory": str(project_dir),
        "file_count": len(files),
        "files": files,
        "readme": readme_content
    }

@router.get("/projects/{slug}/file", response_model=FileContentResponse, summary="Read source file content")
def read_project_file(
    slug: str,
    file_path: str = Query(..., description="Relative file path within project")
):
    """
    Reads the content of a specific file within a project, verifying path safety.
    """
    project_dir = (product_foundry.workspace_root / slug).resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{slug}' not found."
        )

    # Resolve targeted file path
    target = (project_dir / file_path).resolve()
    if not str(target).startswith(str(project_dir)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Directory traversal outside project root is forbidden."
        )

    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File '{file_path}' not found in project '{slug}'."
        )

    content = target.read_text(encoding="utf-8", errors="replace")
    return FileContentResponse(
        slug=slug,
        relative_path=file_path,
        content=content,
        size_bytes=target.stat().st_size,
        line_count=len(content.splitlines())
    )

@router.post("/projects/{slug}/test", response_model=List[FoundryTestResult], summary="Run automated tests for project")
async def run_project_tests(slug: str):
    """
    Executes automated tests in the project directory in a sandboxed subprocess.
    """
    project_dir = (product_foundry.workspace_root / slug).resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{slug}' not found."
        )

    test_files = [f.name for f in project_dir.glob("test_*.py")]
    if not test_files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No test files matching 'test_*.py' found in project '{slug}'."
        )

    results = []
    for tf in test_files:
        res = await product_foundry._run_test_file(project_dir, tf)
        results.append(res)

    return results
