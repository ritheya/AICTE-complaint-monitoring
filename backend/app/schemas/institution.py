"""
Institution, Risk Breakdown, and Leaderboard Schemas
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class RiskBreakdownResponse(BaseModel):
    """5-component institutional risk breakdown calculated strictly from DB records."""
    volume: float = Field(..., description="Complaint volume component (max 30 pts)")
    pending_ratio: float = Field(..., description="Pending ratio component (max 20 pts)")
    severity: float = Field(..., description="Critical/High severity penalty (max 20 pts)")
    repeat_categories: float = Field(..., description="Repeat categories penalty (max 15 pts)")
    unresolved_overlaps: float = Field(..., description="Unresolved overlaps penalty (max 15 pts)")
    total_score: float = Field(..., description="Composite risk score (0 to 100)")
    risk_band: str = Field(..., description="Low (<30), Moderate (30-59), High (>=60)")


class InstitutionResponse(BaseModel):
    """Canonical Institution Registry record."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    permanent_id: str
    name: str
    normalized_name: str
    aliases: List[str] = Field(default_factory=list)
    address: str
    city: str
    state: str
    region: str
    pincode: str
    institution_type: str
    risk_score: float
    risk_breakdown: Dict[str, Any] = Field(default_factory=dict)


class InstitutionLeaderboardItem(BaseModel):
    """Entry on the dynamic Institutional Risk Leaderboard."""
    rank: int
    id: int
    permanent_id: str
    name: str
    city: str
    state: str
    risk_score: float
    risk_band: str
    open_complaints: int
    total_complaints: int


class InstitutionSummaryResponse(BaseModel):
    """AI-generated executive summary grounded in database grievance history."""
    institution_id: int
    summary_text: str
    source: str = Field(default="template_fallback", description="'llm' or 'template_fallback'")
