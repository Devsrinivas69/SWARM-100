"""
Tool 5: Structured Data Analysis
Performs deterministic statistical analysis and distribution profiling on structured JSON/dict tables.
Computes count, mean, median, standard deviation, min, max, missingness, and pairwise correlation.
Operates with pure mathematical algorithms without external arbitrary code execution.
"""

import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.core.tools.base import BaseTool, PermissionLevel, ToolContext

class DataAnalysisInput(BaseModel):
    data: List[Dict[str, Any]] = Field(..., min_length=1, description="List of row dictionaries representing structured tabular records")
    numeric_columns: Optional[List[str]] = Field(None, description="Subset of numeric columns to profile (auto-detected if None)")
    categorical_columns: Optional[List[str]] = Field(None, description="Subset of categorical columns to profile")
    compute_correlation: bool = Field(False, description="Whether to compute pairwise Pearson correlation between numeric columns")

class ColumnStats(BaseModel):
    count: int
    missing_count: int
    missing_percent: float
    mean: Optional[float] = None
    std: Optional[float] = None
    median: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None

class DataAnalysisOutput(BaseModel):
    row_count: int
    column_count: int
    columns: List[str]
    numeric_summary: Dict[str, ColumnStats]
    categorical_top_frequencies: Dict[str, Dict[str, int]]
    correlation_matrix: Optional[Dict[str, Dict[str, float]]] = None

class StructuredDataAnalysisTool(BaseTool):
    id = "structured_data_analysis"
    name = "Structured Data Analysis"
    description = (
        "Computes descriptive statistics (mean, std, median, min, max, missingness) and correlation matrices "
        "on structured tabular datasets. Completely sandboxed with mathematical determinism."
    )
    permission_level = PermissionLevel.SAFE
    timeout_seconds = 15.0
    input_schema = DataAnalysisInput
    output_schema = DataAnalysisOutput

    async def execute(self, params: DataAnalysisInput, context: ToolContext) -> DataAnalysisOutput:
        rows = params.data
        row_count = len(rows)
        if row_count == 0:
            raise ValueError("Input data cannot be empty.")

        # Identify all columns
        all_cols_set = set()
        for r in rows:
            all_cols_set.update(r.keys())
        all_columns = sorted(list(all_cols_set))

        # Detect column types
        detected_numeric = []
        detected_categorical = []

        for col in all_columns:
            non_null_vals = [r[col] for r in rows if r.get(col) is not None]
            if not non_null_vals:
                continue
            is_num = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null_vals)
            if is_num:
                detected_numeric.append(col)
            else:
                detected_categorical.append(col)

        target_numeric = params.numeric_columns if params.numeric_columns is not None else detected_numeric
        target_categorical = params.categorical_columns if params.categorical_columns is not None else detected_categorical

        # Compute numeric stats
        numeric_summary: Dict[str, ColumnStats] = {}
        numeric_series: Dict[str, List[float]] = {}

        for col in target_numeric:
            raw_vals = [r.get(col) for r in rows]
            missing_count = sum(1 for v in raw_vals if v is None)
            valid_nums = [float(v) for v in raw_vals if v is not None and isinstance(v, (int, float)) and not isinstance(v, bool)]
            numeric_series[col] = valid_nums

            n = len(valid_nums)
            missing_pct = round((missing_count / row_count) * 100.0, 2)

            if n == 0:
                numeric_summary[col] = ColumnStats(count=0, missing_count=missing_count, missing_percent=missing_pct)
                continue

            sorted_nums = sorted(valid_nums)
            mean_val = sum(sorted_nums) / n
            variance = sum((x - mean_val) ** 2 for x in sorted_nums) / (n - 1) if n > 1 else 0.0
            std_val = math.sqrt(variance)

            # Median
            if n % 2 == 1:
                median_val = sorted_nums[n // 2]
            else:
                median_val = (sorted_nums[n // 2 - 1] + sorted_nums[n // 2]) / 2.0

            numeric_summary[col] = ColumnStats(
                count=n,
                missing_count=missing_count,
                missing_percent=missing_pct,
                mean=round(mean_val, 4),
                std=round(std_val, 4),
                median=round(median_val, 4),
                min=round(sorted_nums[0], 4),
                max=round(sorted_nums[-1], 4)
            )

        # Compute categorical frequency
        cat_frequencies: Dict[str, Dict[str, int]] = {}
        for col in target_categorical:
            freq: Dict[str, int] = {}
            for r in rows:
                val = r.get(col)
                if val is not None:
                    s_val = str(val)
                    freq[s_val] = freq.get(s_val, 0) + 1
            # Top 10 items
            sorted_items = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]
            cat_frequencies[col] = dict(sorted_items)

        # Correlation matrix
        corr_matrix = None
        if params.compute_correlation and len(target_numeric) > 1:
            corr_matrix = {}
            for col_a in target_numeric:
                corr_matrix[col_a] = {}
                for col_b in target_numeric:
                    if col_a == col_b:
                        corr_matrix[col_a][col_b] = 1.0
                    else:
                        r = self._pearson_correlation(rows, col_a, col_b)
                        corr_matrix[col_a][col_b] = round(r, 4) if r is not None else 0.0

        return DataAnalysisOutput(
            row_count=row_count,
            column_count=len(all_columns),
            columns=all_columns,
            numeric_summary=numeric_summary,
            categorical_top_frequencies=cat_frequencies,
            correlation_matrix=corr_matrix
        )

    def _pearson_correlation(self, rows: List[Dict[str, Any]], col_a: str, col_b: str) -> Optional[float]:
        # Pairwise complete rows
        pairs = []
        for r in rows:
            va = r.get(col_a)
            vb = r.get(col_b)
            if va is not None and vb is not None and isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                pairs.append((float(va), float(vb)))

        n = len(pairs)
        if n < 2:
            return None

        sum_a = sum(p[0] for p in pairs)
        sum_b = sum(p[1] for p in pairs)
        mean_a = sum_a / n
        mean_b = sum_b / n

        numerator = sum((p[0] - mean_a) * (p[1] - mean_b) for p in pairs)
        var_a = sum((p[0] - mean_a) ** 2 for p in pairs)
        var_b = sum((p[1] - mean_b) ** 2 for p in pairs)

        denominator = math.sqrt(var_a * var_b)
        if denominator == 0:
            return 0.0

        return numerator / denominator
