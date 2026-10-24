"""
Complaint Overlap, Inter-Bureau Linkage, and Live Precheck Schemas
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, ConfigDict, Field

# Consistent status definitions
OverlapDecision = Literal["approved", "rejected", "needs_discussion", "related_only"]
OverlapStatus = Literal["suggested", "approved", "rejected", "needs_discussion", "related_only"]


class OverlapDecisionRequest(BaseModel):
    """
    Officer decision payload on a suggested complaint overlap.
    Supports approved, rejected, needs_discussion, and related_only.
    """
    decision: OverlapDecision = Field(..., description="Decision on inter-bureau link")
    final_lead_bureau_id: Optional[int] = Field(None, description="Bureau designated as coordination lead")
    remarks: Optional[str] = Field(None, description="Official decision rationale for audit history")


class CaseLinkResponse(BaseModel):
    """Inter-bureau overlap linkage record between two complaints."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_a_id: int
    case_b_id: int
    institution_id: int
    similarity_score: float
    signals: Dict[str, Any] = Field(default_factory=dict)
    reasons: List[str] = Field(default_factory=list)
    suggested_lead_bureau_id: Optional[int] = None
    lead_suggestion_rule: Optional[str] = None
    final_lead_bureau_id: Optional[int] = None
    status: OverlapStatus
    decided_by_id: Optional[int] = None
    decided_at: Optional[datetime] = None
    decision_remarks: Optional[str] = None
    created_at: datetime

    # Display conveniences
    case_a_case_id: Optional[str] = None
    case_b_case_id: Optional[str] = None
    institution_name: Optional[str] = None
    suggested_lead_bureau_code: Optional[str] = None
    final_lead_bureau_code: Optional[str] = None


class LivePrecheckRequest(BaseModel):
    """
    Real-time intake pre-check query (Scenario 5 Demo).
    Read-only pre-flight analysis; MUST NOT persist rows to database.
    """
    text: str = Field(..., description="Raw complaint text entered by citizen/student")
    raw_institution_name: Optional[str] = Field(None, description="Raw institution name if extracted or provided separately")
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    permanent_id: Optional[str] = None
    category: Optional[str] = None


class ActiveOverlapAlert(BaseModel):
    """Pre-check overlap alert with an existing active case at the resolved institution."""
    existing_case_id: str
    existing_case_bureau: str
    existing_category: str
    overlap_score: float
    band: str
    signals: Dict[str, float]
    reasons: List[str]
    suggested_lead_bureau: Optional[str] = None
    lead_rule: Optional[str] = None
    is_provisional: bool = False
    provisional_notice: Optional[str] = None


class LivePrecheckResponse(BaseModel):
    """Real-time intake resolution and pre-check output."""
    institution_id: Optional[int] = None
    institution_name: Optional[str] = None
    permanent_id: Optional[str] = None
    resolution_confidence: float
    resolution_status: str
    needs_institution_review: bool
    candidate_institutions: List[Dict[str, Any]] = Field(default_factory=list)
    resolution_reasons: List[str] = Field(default_factory=list)
    has_active_overlap: bool = False
    active_overlaps: List[ActiveOverlapAlert] = Field(default_factory=list)
