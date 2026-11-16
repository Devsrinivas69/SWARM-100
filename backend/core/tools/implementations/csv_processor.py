"""
Tool 6: CSV Processing
Parses, filters, sorts, projects, and aggregates tabular CSV records.
Accepts raw CSV text or files strictly confined inside the approved workspace.
"""

import csv
import io
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.core.tools.base import (
    BaseTool,
    PermissionLevel,
    SecurityBoundaryError,
    ToolContext,
)

class CSVProcessorInput(BaseModel):
    csv_content: Optional[str] = Field(None, description="Raw CSV string to parse and process")
    workspace_file_path: Optional[str] = Field(None, description="Relative path to CSV file within approved workspace")
    filter_column: Optional[str] = Field(None, description="Column name to filter upon")
    filter_operator: Optional[str] = Field(None, description="'eq', 'neq', 'gt', 'lt', 'gte', 'lte', 'contains'")
    filter_value: Optional[str] = Field(None, description="Target value for filter condition")
    select_columns: Optional[List[str]] = Field(None, description="Columns to project/include in output")
    sort_by: Optional[str] = Field(None, description="Column name to sort results by")
    sort_descending: bool = Field(False, description="Sort descending if True")
    group_by: Optional[str] = Field(None, description="Optional column to group by for aggregation")
    aggregate_column: Optional[str] = Field(None, description="Column to aggregate")
    aggregate_function: Optional[str] = Field(None, description="'count', 'sum', 'mean', 'min', 'max'")
    limit: int = Field(100, ge=1, le=1000, description="Max records to return in output")

class CSVProcessorOutput(BaseModel):
    total_rows: int
    filtered_rows: int
    headers: List[str]
    records: List[Dict[str, Any]]
    aggregation: Optional[Dict[str, Any]] = None

class CSVProcessorTool(BaseTool):
    id = "csv_processor"
    name = "CSV Processing Engine"
    description = (
        "Parses, filters, projects, sorts, and aggregates tabular CSV datasets from raw text or "
        "files strictly confined within the approved workspace root."
    )
    permission_level = PermissionLevel.WORKSPACE_READ
    timeout_seconds = 15.0
    input_schema = CSVProcessorInput
    output_schema = CSVProcessorOutput

    async def execute(self, params: CSVProcessorInput, context: ToolContext) -> CSVProcessorOutput:
        raw_text = params.csv_content

        # If a workspace file is specified, read it within boundary checks
        if params.workspace_file_path:
            norm_rel = Path(params.workspace_file_path)
            if any(part == ".." for part in norm_rel.parts):
                raise SecurityBoundaryError("Security Boundary Violation: Path traversal '..' is forbidden in CSV path.")

            workspace_root = context.workspace_path.resolve()
            target_file = (workspace_root / norm_rel).resolve()

            if not target_file.is_relative_to(workspace_root):
                raise SecurityBoundaryError("Security Boundary Violation: File path escapes approved workspace.")

            if not target_file.exists():
                raise FileNotFoundError(f"CSV file '{params.workspace_file_path}' not found in workspace.")

            raw_text = target_file.read_text(encoding="utf-8", errors="replace")

        if not raw_text or not raw_text.strip():
            raise ValueError("No CSV content provided (neither valid raw text nor workspace file).")

        # Parse CSV
        reader = csv.DictReader(io.StringIO(raw_text))
        if not reader.fieldnames:
            raise ValueError("CSV contains no valid header row.")

        headers = list(reader.fieldnames)
        all_records = list(reader)
        total_rows = len(all_records)

        # Filtering
        filtered = all_records
        if params.filter_column and params.filter_operator and params.filter_value is not None:
            col = params.filter_column
            op = params.filter_operator.lower()
            val = params.filter_value

            def _match(row: Dict[str, str]) -> bool:
                r_val = row.get(col, "")
                if op == "eq":
                    return r_val == val
                elif op == "neq":
                    return r_val != val
                elif op == "contains":
                    return val.lower() in r_val.lower()
                elif op in ("gt", "lt", "gte", "lte"):
                    try:
                        num_r = float(r_val)
                        num_v = float(val)
                        if op == "gt":
                            return num_r > num_v
                        elif op == "lt":
                            return num_r < num_v
                        elif op == "gte":
                            return num_r >= num_v
                        elif op == "lte":
                            return num_r <= num_v
                    except ValueError:
                        return False
                return True

            filtered = [r for r in filtered if _match(r)]

        # Sorting
        if params.sort_by and params.sort_by in headers:
            sort_col = params.sort_by
            def _sort_key(r):
                v = r.get(sort_col, "")
                try:
                    return (0, float(v))
                except ValueError:
                    return (1, v)

            filtered.sort(key=_sort_key, reverse=params.sort_descending)

        # Aggregation
        aggregation_output = None
        if params.group_by and params.aggregate_column and params.aggregate_function:
            grp_col = params.group_by
            agg_col = params.aggregate_column
            fn = params.aggregate_function.lower()

            groups: Dict[str, List[float]] = {}
            for r in filtered:
                k = r.get(grp_col, "Unknown")
                raw_v = r.get(agg_col, "")
                try:
                    num_v = float(raw_v)
                    groups.setdefault(k, []).append(num_v)
                except ValueError:
                    pass

            agg_summary = {}
            for k, nums in groups.items():
                if not nums:
                    agg_summary[k] = 0
                elif fn == "count":
                    agg_summary[k] = len(nums)
                elif fn == "sum":
                    agg_summary[k] = round(sum(nums), 4)
                elif fn == "mean":
                    agg_summary[k] = round(sum(nums) / len(nums), 4)
                elif fn == "min":
                    agg_summary[k] = min(nums)
                elif fn == "max":
                    agg_summary[k] = max(nums)

            aggregation_output = {
                "group_by": grp_col,
                "aggregate_column": agg_col,
                "function": fn,
                "results": agg_summary
            }

        # Projection (select columns)
        final_headers = params.select_columns if params.select_columns else headers
        projected = []
        for r in filtered[:params.limit]:
            row_dict = {}
            for h in final_headers:
                row_dict[h] = r.get(h, "")
            projected.append(row_dict)

        return CSVProcessorOutput(
            total_rows=total_rows,
            filtered_rows=len(filtered),
            headers=final_headers,
            records=projected,
            aggregation=aggregation_output
        )
