"""
Inter-Bureau Overlaps and Case Link Coordination Router
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.case_link import CaseLink
from backend.app.models.complaint import Complaint
from backend.app.models.action_history import ActionHistory
from backend.app.models.bureau import Officer
from backend.app.utils import utc_now
from backend.app.auth.dependencies import get_current_user
from backend.app.schemas.overlap import (
    CaseLinkResponse,
    OverlapDecisionRequest
)

router = APIRouter(prefix="/overlaps", tags=["Inter-Bureau Overlaps"])


def _format_case_link_response(link: CaseLink) -> CaseLinkResponse:
    """Helper to populate display conveniences on CaseLinkResponse."""
    resp = CaseLinkResponse.model_validate(link)
    if link.case_a:
        resp.case_a_case_id = link.case_a.case_id
    if link.case_b:
        resp.case_b_case_id = link.case_b.case_id
    if link.institution:
        resp.institution_name = link.institution.name
    if link.suggested_lead_bureau:
        resp.suggested_lead_bureau_code = link.suggested_lead_bureau.code
    if link.final_lead_bureau:
        resp.final_lead_bureau_code = link.final_lead_bureau.code
    return resp


@router.get("", response_model=List[CaseLinkResponse])
def list_overlaps(
    status_filter: Optional[str] = Query(None, alias="status", description="suggested, approved, rejected, needs_discussion, related_only"),
    institution_id: Optional[int] = Query(None, description="Filter overlaps for specific institution"),
    bureau_id: Optional[int] = Query(None, description="Filter overlaps involving specific bureau"),
    min_score: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum overlap similarity score"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lists cross-bureau overlap linkages.
    Enforces regional scoping for Regional Officers.
    """
    query = db.query(CaseLink)

    # Scoping for Regional Officers: only see overlaps at institutions in their assigned region
    if current_user.role == "Regional Officer" and current_user.region:
        query = query.join(CaseLink.institution).filter(CaseLink.institution.has(region=current_user.region))

    if status_filter:
        query = query.filter(CaseLink.status == status_filter.strip().lower())

    if institution_id:
        query = query.filter(CaseLink.institution_id == institution_id)

    if min_score is not None:
        query = query.filter(CaseLink.similarity_score >= min_score)

    if bureau_id:
        query = query.filter(
            (CaseLink.case_a.has(assigned_bureau_id=bureau_id)) |
            (CaseLink.case_b.has(assigned_bureau_id=bureau_id))
        )

    links = query.order_by(CaseLink.similarity_score.desc()).offset(skip).limit(limit).all()
    return [_format_case_link_response(link) for link in links]


@router.get("/{link_id}", response_model=CaseLinkResponse)
def get_overlap(
    link_id: int,
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retrieves full details of a specific inter-bureau case linkage.
    """
    link = db.query(CaseLink).filter(CaseLink.id == link_id).first()
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case linkage with ID {link_id} not found"
        )

    # Scoping for Regional Officers
    if current_user.role == "Regional Officer" and current_user.region:
        if link.institution and link.institution.region != current_user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Linkage is in {link.institution.region} Region outside officer jurisdiction"
            )

    return _format_case_link_response(link)


@router.post("/{link_id}/decision", response_model=CaseLinkResponse)
def decide_overlap(
    link_id: int,
    req: OverlapDecisionRequest,
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Records an official officer decision on an inter-bureau overlap alert:
    - Supported decisions: approved, rejected, needs_discussion, related_only.
    - Sets designated final lead bureau if approved.
    - Automatically appends audit history entries on BOTH involved complaint cases.
    """
    link = db.query(CaseLink).filter(CaseLink.id == link_id).first()
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case linkage with ID {link_id} not found"
        )

    # Bureau officer authorization check: user must be Admin, Senior Mgmt, or belong to one of the involved bureaus
    case_a = db.query(Complaint).filter(Complaint.id == link.case_a_id).first()
    case_b = db.query(Complaint).filter(Complaint.id == link.case_b_id).first()
    if not case_a or not case_b:
        raise HTTPException(status_code=404, detail="Underlying complaint record not found")

    if current_user.role not in ["System Administrator", "Senior Management"]:
        officer_bureau_id = current_user.bureau_id
        if officer_bureau_id not in [case_a.assigned_bureau_id, case_b.assigned_bureau_id]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Only officers from the involved bureaus or Senior Management can record overlap decisions."
            )

    now = utc_now()
    link.status = req.decision
    link.decided_by_id = current_user.id
    link.decided_at = now
    link.decision_remarks = req.remarks or ""

    if req.final_lead_bureau_id:
        link.final_lead_bureau_id = req.final_lead_bureau_id
    elif req.decision == "approved" and link.suggested_lead_bureau_id:
        # Default to suggested lead bureau if none specified
        link.final_lead_bureau_id = link.suggested_lead_bureau_id

    # Append immutable ActionHistory to Case A
    history_a = ActionHistory(
        complaint_id=case_a.id,
        timestamp=now,
        actor_name=current_user.name,
        actor_role=current_user.role,
        bureau_code=current_user.bureau.code if current_user.bureau else "HQ",
        action_type="OVERLAP_DECISION",
        remarks=f"Overlap linkage with {case_b.case_id} decided as '{req.decision}'. Remarks: {req.remarks or 'None'}",
        details={
            "case_link_id": link.id,
            "paired_case_id": case_b.case_id,
            "decision": req.decision,
            "final_lead_bureau_id": link.final_lead_bureau_id
        }
    )
    db.add(history_a)

    # Append immutable ActionHistory to Case B
    history_b = ActionHistory(
        complaint_id=case_b.id,
        timestamp=now,
        actor_name=current_user.name,
        actor_role=current_user.role,
        bureau_code=current_user.bureau.code if current_user.bureau else "HQ",
        action_type="OVERLAP_DECISION",
        remarks=f"Overlap linkage with {case_a.case_id} decided as '{req.decision}'. Remarks: {req.remarks or 'None'}",
        details={
            "case_link_id": link.id,
            "paired_case_id": case_a.case_id,
            "decision": req.decision,
            "final_lead_bureau_id": link.final_lead_bureau_id
        }
    )
    db.add(history_b)

    db.commit()
    db.refresh(link)

    return _format_case_link_response(link)
