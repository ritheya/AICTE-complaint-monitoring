"""
Dashboard Aggregation and Analytics Schemas
"""
from typing import List, Dict, Any
from pydantic import BaseModel, Field


class DashboardSummary(BaseModel):
    """High-level KPI statistics for AICTE leadership and bureau officers."""
    total_complaints: int
    pending_complaints: int
    under_process_complaints: int
    escalated_complaints: int
    transferred_complaints: int
    disposed_complaints: int
    overdue_complaints: int
    active_overlaps: int
    high_risk_institutions: int


class BureauWorkloadItem(BaseModel):
    """Workload distribution per bureau."""
    bureau_id: int
    bureau_code: str
    bureau_name: str
    total_complaints: int
    pending_complaints: int
    overdue_complaints: int
    disposed_complaints: int
    avg_resolution_days: float


class RegionWiseItem(BaseModel):
    """Grievance volume and risk across geographic regions."""
    region: str
    complaint_count: int
    high_risk_institutions: int


class CategoryWiseItem(BaseModel):
    """Category breakdown across complaints."""
    category: str
    count: int
    percentage: float


class AgeingBracketItem(BaseModel):
    """Case ageing distribution."""
    bracket: str  # "< 15 days", "15-30 days", "30-60 days", "> 60 days"
    count: int


class MonthlyTrendItem(BaseModel):
    """Monthly receipt vs disposal timeline."""
    month: str  # "YYYY-MM"
    received: int
    disposed: int
