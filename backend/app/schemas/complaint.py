"""
Complaint, Action History, and Lifecycle Management Schemas
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class ActionHistoryResponse(BaseModel):
    """Immutable audit trail entry for case lifecycle actions."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    actor_name: str
    actor_role: str
    bureau_code: str
    action_type: str
    remarks: str
    attachment_name: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class CandidateInstitution(BaseModel):
    """Candidate match when institution resolution falls in human review band."""
    id: int
    name: str
    permanent_id: str
    city: str
    confidence: float


class ComplaintResponse(BaseModel):
    """Full detail view of an AICTE complaint grievance record."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: str
    institution_id: Optional[int] = None
    raw_institution_name: str
    source: str
    category: str
    description: str
    complainant_type: str
    date_received: datetime
    status: str
    assigned_bureau_id: int
    assigned_officer_id: Optional[int] = None
    last_action: str
    next_action: str
    last_action_date: datetime
    expected_disposal_date: datetime
    priority: str
    is_overdue: bool
    is_escalated: bool
    match_confidence: Optional[float] = None
    needs_institution_review: bool
    candidate_institutions: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime

    # Denormalized / relational fields
    assigned_bureau_code: Optional[str] = None
    institution_name: Optional[str] = None
    action_history: List[ActionHistoryResponse] = Field(default_factory=list)


class ComplaintCreate(BaseModel):
    """Payload to register a new complaint."""
    raw_institution_name: str = Field(..., description="Institution name as stated by complainant")
    source: str = Field(default="Portal", description="Intake channel: Portal, CPGRAMS, Email, Letter")
    category: str = Field(..., description="Complaint category")
    description: str = Field(..., description="Detailed grievance description")
    complainant_type: str = Field(default="Student", description="Student, Faculty, Parent, Citizen")
    priority: str = Field(default="Medium", description="Low, Medium, High, Critical")
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    permanent_id: Optional[str] = None
    assigned_bureau_id: Optional[int] = None


class ComplaintUpdate(BaseModel):
    """Payload for officer status or assignment updates."""
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_officer_id: Optional[int] = None
    remarks: Optional[str] = None
    last_action: Optional[str] = None
    next_action: Optional[str] = None


class ComplaintTransferRequest(BaseModel):
    """Payload to transfer a complaint to another bureau."""
    target_bureau_id: int = Field(..., description="ID of destination bureau")
    remarks: str = Field(..., description="Transfer justification for audit history")


class ComplaintEscalateRequest(BaseModel):
    """Payload to escalate a complaint to Senior Management."""
    remarks: str = Field(..., description="Escalation rationale for audit history")


class ConfirmInstitutionRequest(BaseModel):
    """Payload to confirm candidate institution match during human review."""
    institution_id: int = Field(..., description="Canonical institution ID chosen by officer")
