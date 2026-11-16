"""
Tool 2: Date and Time
Provides current timestamp, timezone-aware conversions, date arithmetic, and duration calculations.
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from backend.core.tools.base import BaseTool, PermissionLevel, ToolContext

class DateTimeInput(BaseModel):
    operation: str = Field("now", description="Operation: 'now', 'format', 'diff', 'add'")
    timezone_offset_hours: float = Field(0.0, description="Timezone offset from UTC in hours (e.g. 5.5 for IST, -5 for EST)")
    format_string: str = Field("%Y-%m-%d %H:%M:%S", description="Output strftime format pattern")
    base_datetime: Optional[str] = Field(None, description="ISO format date/time string for arithmetic or diff")
    target_datetime: Optional[str] = Field(None, description="ISO format date/time string for diff comparison")
    days: float = Field(0.0, description="Days to add/subtract in 'add' operation")
    hours: float = Field(0.0, description="Hours to add/subtract in 'add' operation")
    minutes: float = Field(0.0, description="Minutes to add/subtract in 'add' operation")

class DateTimeOutput(BaseModel):
    operation: str
    result: str
    iso: str
    timestamp_epoch: float
    details: Dict[str, Any]

class DateTimeTool(BaseTool):
    id = "datetime_tool"
    name = "Date and Time Utility"
    description = (
        "Retrieves current date and time in UTC or custom timezone, calculates date differences, "
        "and performs deterministic time offset arithmetic."
    )
    permission_level = PermissionLevel.SAFE
    timeout_seconds = 5.0
    input_schema = DateTimeInput
    output_schema = DateTimeOutput

    async def execute(self, params: DateTimeInput, context: ToolContext) -> DateTimeOutput:
        tz = timezone(timedelta(hours=params.timezone_offset_hours))

        if params.operation == "now":
            dt = datetime.now(tz)
            formatted = dt.strftime(params.format_string)
            return DateTimeOutput(
                operation="now",
                result=formatted,
                iso=dt.isoformat(),
                timestamp_epoch=dt.timestamp(),
                details={"timezone_offset_hours": params.timezone_offset_hours, "day_of_week": dt.strftime("%A")}
            )

        elif params.operation == "add":
            if not params.base_datetime:
                dt = datetime.now(tz)
            else:
                dt = datetime.fromisoformat(params.base_datetime)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)

            delta = timedelta(days=params.days, hours=params.hours, minutes=params.minutes)
            new_dt = dt + delta
            formatted = new_dt.strftime(params.format_string)
            return DateTimeOutput(
                operation="add",
                result=formatted,
                iso=new_dt.isoformat(),
                timestamp_epoch=new_dt.timestamp(),
                details={"original": dt.isoformat(), "delta_applied": str(delta)}
            )

        elif params.operation == "diff":
            if not params.base_datetime or not params.target_datetime:
                raise ValueError("Both 'base_datetime' and 'target_datetime' are required for 'diff' operation.")

            dt1 = datetime.fromisoformat(params.base_datetime)
            dt2 = datetime.fromisoformat(params.target_datetime)
            diff = dt2 - dt1
            total_seconds = diff.total_seconds()
            days = diff.days
            hours = int((total_seconds % 86400) // 3600)
            minutes = int((total_seconds % 3600) // 60)

            diff_str = f"{days} days, {hours} hours, {minutes} minutes ({total_seconds:,.1f} seconds total)"
            return DateTimeOutput(
                operation="diff",
                result=diff_str,
                iso=datetime.now(timezone.utc).isoformat(),
                timestamp_epoch=total_seconds,
                details={
                    "total_seconds": total_seconds,
                    "days": days,
                    "hours": hours,
                    "minutes": minutes
                }
            )

        elif params.operation == "format":
            if not params.base_datetime:
                dt = datetime.now(tz)
            else:
                dt = datetime.fromisoformat(params.base_datetime)
            formatted = dt.strftime(params.format_string)
            return DateTimeOutput(
                operation="format",
                result=formatted,
                iso=dt.isoformat(),
                timestamp_epoch=dt.timestamp(),
                details={"pattern": params.format_string}
            )

        else:
            raise ValueError(f"Unknown operation '{params.operation}'. Supported: 'now', 'add', 'diff', 'format'.")
