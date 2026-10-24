"""
Complaints Grievance Management, Lifecycle Actions, and Inter-Bureau Linkage Router
"""
from typing import Optional, List
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc

from backend.app.database import get_db
from backend.app.models.complaint import Complaint
from backend.app.models.bureau import Bureau, Officer
from backend.app.models.institution import Institution
from backend.app.models.action_history import ActionHistory
from backend.app.models.case_link import CaseLink
from backend.app.models.alert import Alert
from backend.app.utils import utc_now
from backend.app.auth.dependencies import (
    get_current_user,
    check_bureau_write_permission,
    check_regional_scope
)
from backend.app.config import (
    ROLE_ADMIN,
    ROLE_SENIOR_MGMT,
    ROLE_REGIONAL_OFFICER,
    SLA_DAYS_BY_CATEGORY,
    SLA_PRIORITY_MULTIPLIERS
)
from backend.app.services.resolution_engine import InstitutionResolutionEngine
from backend.app.services.overlap_engine import ComplaintOverlapEngine
from backend.app.services.lead_bureau_rules import LeadBureauEngine
from backend.app.schemas.complaint import (
    ComplaintResponse,
    ComplaintCreate,
    ComplaintUpdate,
    ComplaintTransferRequest,
    ComplaintEscalateRequest,
    ConfirmInstitutionRequest
)

router = APIRouter(prefix="/complaints", tags=["Complaints"])

resolution_engine = InstitutionResolutionEngine()
overlap_engine = ComplaintOverlapEngine()
lead_bureau_engine = LeadBureauEngine()


def _run_overlap_detection_for_complaint(complaint: Complaint, db: Session) -> List[CaseLink]:
    """
    Evaluates newly linked complaints against all other open active cases at the same institution
    across distinct bureaus. Creates CaseLink (status 'suggested') and Alert records.
    Enforces Item 3: Never re-suggests pairs previously rejected by officers.
    """
    if not complaint.institution_id:
        return []

    # Find active cases at the same institution in other bureaus
    other_cases = db.query(Complaint).filter(
        Complaint.institution_id == complaint.institution_id,
        Complaint.assigned_bureau_id != complaint.assigned_bureau_id,
        Complaint.id != complaint.id,
        Complaint.status.notin_(["Disposed", "Transferred"])
    ).all()

    created_links = []
    for existing in other_cases:
        case_a_id = min(complaint.id, existing.id)
        case_b_id = max(complaint.id, existing.id)

        # Check existing links to respect previous officer decisions
        existing_link = db.query(CaseLink).filter(
            CaseLink.case_a_id == case_a_id,
            CaseLink.case_b_id == case_b_id
        ).first()

        # If previously rejected by officer, strictly DO NOT re-suggest
        if existing_link and existing_link.status == "rejected":
            continue

        # If already linked in any other status, skip duplicate creation
        if existing_link:
            continue

        overlap_result = overlap_engine.evaluate_overlap(complaint, existing, db=db)
        if overlap_result.is_overlap and overlap_result.score >= 0.60:
            lead_rec = lead_bureau_engine.suggest_lead(complaint, existing)

            new_link = CaseLink(
                case_a_id=case_a_id,
                case_b_id=case_b_id,
                institution_id=complaint.institution_id,
                similarity_score=overlap_result.score,
                signals=overlap_result.signals,
                reasons=overlap_result.reasons,
                suggested_lead_bureau_id=lead_rec.lead_bureau_id,
                lead_suggestion_rule=lead_rec.rule_id,
                status="suggested"
            )
            db.add(new_link)
            db.flush()
            created_links.append(new_link)

            # Generate alerts for both involved bureaus
            band_label = "Strong" if overlap_result.band == "STRONG_OVERLAP" else "Possible"
            severity = "critical" if overlap_result.band == "STRONG_OVERLAP" else "warning"

            alert_msg = (
                f"{band_label} Inter-Bureau Overlap detected between {complaint.case_id} "
                f"({complaint.assigned_bureau.code if complaint.assigned_bureau else 'Bureau'}) and "
                f"{existing.case_id} ({existing.assigned_bureau.code if existing.assigned_bureau else 'Bureau'}) "
                f"at '{complaint.institution.name if complaint.institution else 'Institution'}' "
                f"(Score: {overlap_result.score:.2f}). Suggested Lead: {lead_rec.lead_bureau_code}."
            )

            # Alert for complaint's bureau
            db.add(Alert(
                type="overlap",
                complaint_id=complaint.id,
                institution_id=complaint.institution_id,
                message=alert_msg,
                severity=severity,
                target_bureau_id=complaint.assigned_bureau_id
            ))
            # Alert for existing case's bureau
            db.add(Alert(
                type="overlap",
                complaint_id=existing.id,
                institution_id=complaint.institution_id,
                message=alert_msg,
                severity=severity,
                target_bureau_id=existing.assigned_bureau_id
            ))

    return created_links


@router.get("", response_model=List[ComplaintResponse])
def list_complaints(
    bureau_id: Optional[int] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lists complaints with multi-parameter filtering, pagination, and RBAC scoping:
    - Regional Officers are automatically scoped to their designated geographic region.
    - Bureau Officers default to their assigned bureau (can be filtered).
    - Senior Management and Admin possess global read-all access across all records.
    """
    query = db.query(Complaint).outerjoin(Institution, Complaint.institution_id == Institution.id)

    # Regional Officer scoping
    if current_user.role == ROLE_REGIONAL_OFFICER and current_user.region:
        query = query.filter(Institution.region == current_user.region)

    # Bureau filter
    if bureau_id:
        query = query.filter(Complaint.assigned_bureau_id == bureau_id)
    elif current_user.role not in {ROLE_ADMIN, ROLE_SENIOR_MGMT, ROLE_REGIONAL_OFFICER} and current_user.bureau_id:
        # Default view for bureau officer is their own bureau's complaints
        query = query.filter(Complaint.assigned_bureau_id == current_user.bureau_id)

    # Status, Priority, Category filters
    if status:
        query = query.filter(Complaint.status == status)
    if priority:
        query = query.filter(Complaint.priority == priority)
    if category:
        query = query.filter(Complaint.category == category)

    # Text search on case ID, raw institution name, and description
    if search:
        search_pat = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Complaint.case_id.ilike(search_pat),
                Complaint.raw_institution_name.ilike(search_pat),
                Complaint.description.ilike(search_pat)
            )
        )

    complaints = query.order_by(desc(Complaint.created_at)).offset(skip).limit(limit).all()

    # Hydrate helper fields
    results = []
    for c in complaints:
        resp = ComplaintResponse.model_validate(c)
        resp.assigned_bureau_code = c.assigned_bureau.code if c.assigned_bureau else None
        resp.institution_name = c.institution.name if c.institution else None
        results.append(resp)

    return results


@router.get("/{complaint_id}", response_model=ComplaintResponse)
def get_complaint_details(
    complaint_id: int,
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns full details for a complaint including chronological action history audit trail.
    Verifies regional scoping for Regional Officers.
    """
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    # Regional scoping verification
    if current_user.role == ROLE_REGIONAL_OFFICER and current_user.region:
        inst_region = complaint.institution.region if complaint.institution else None
        if inst_region != current_user.region:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Complaint outside your assigned regional jurisdiction"
            )

    resp = ComplaintResponse.model_validate(complaint)
    resp.assigned_bureau_code = complaint.assigned_bureau.code if complaint.assigned_bureau else None
    resp.institution_name = complaint.institution.name if complaint.institution else None
    return resp


@router.post("", response_model=ComplaintResponse, status_code=status.HTTP_201_CREATED)
def create_complaint(
    req: ComplaintCreate,
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ingests a new complaint into the AICTE portal:
    1. Runs InstitutionResolutionEngine (Auto-link or flag Needs Review).
    2. Calculates priority-adjusted SLA target disposal date.
    3. Persists complaint and records initial ActionHistory audit entry.
    4. Automatically runs overlap detection if resolved and creates CaseLink + Alerts.
    """
    # Determine assigned bureau (from request or officer's bureau or default to PGRC)
    if req.assigned_bureau_id:
        assigned_bureau = db.query(Bureau).filter(Bureau.id == req.assigned_bureau_id).first()
    elif current_user.bureau_id:
        assigned_bureau = current_user.bureau
    else:
        assigned_bureau = db.query(Bureau).filter(Bureau.code == "PGRC").first()

    if not assigned_bureau:
        raise HTTPException(status_code=400, detail="Valid bureau assignment required")

    # Layer 1-3: Institution Resolution Pipeline
    res_result = resolution_engine.resolve(
        raw_name=req.raw_institution_name,
        city=req.city,
        state=req.state,
        pincode=req.pincode,
        permanent_id=req.permanent_id,
        db=db
    )

    institution_id = res_result.best_institution.id if res_result.best_institution else None
    match_confidence = res_result.confidence
    needs_review = res_result.needs_review
    candidate_institutions = res_result.candidates if needs_review else []

    # Calculate SLA Target
    now = utc_now()
    base_sla = SLA_DAYS_BY_CATEGORY.get(req.category, 30)
    priority_mult = SLA_PRIORITY_MULTIPLIERS.get(req.priority, 1.0)
    sla_duration = int(round(base_sla * priority_mult))
    expected_disposal = now + timedelta(days=sla_duration)

    # Generate sequential Case ID
    count_today = db.query(Complaint).count() + 1
    case_id = f"AICTE/{assigned_bureau.code}/{now.year}/{count_today:05d}"

    complaint = Complaint(
        case_id=case_id,
        institution_id=institution_id,
        raw_institution_name=req.raw_institution_name,
        source=req.source,
        category=req.category,
        description=req.description,
        complainant_type=req.complainant_type,
        date_received=now,
        status="Pending",
        assigned_bureau_id=assigned_bureau.id,
        assigned_officer_id=current_user.id if current_user.bureau_id == assigned_bureau.id else None,
        last_action="Grievance Registered",
        next_action="Initial Scrutiny",
        last_action_date=now,
        expected_disposal_date=expected_disposal,
        priority=req.priority,
        is_overdue=False,
        is_escalated=False,
        match_confidence=match_confidence,
        needs_institution_review=needs_review,
        candidate_institutions=candidate_institutions
    )
    db.add(complaint)
    db.flush()

    # Initial ActionHistory audit log
    history_entry = ActionHistory(
        complaint_id=complaint.id,
        timestamp=now,
        actor_name=current_user.name,
        actor_role=current_user.role,
        bureau_code=assigned_bureau.code,
        action_type="received",
        remarks=f"Complaint lodged via {req.source}. Category: {req.category}. Priority: {req.priority}.",
        details={
            "resolution_status": res_result.status,
            "match_confidence": match_confidence,
            "needs_review": needs_review
        }
    )
    db.add(history_entry)

    # Automated overlap detection for confirmed institution
    if institution_id:
        _run_overlap_detection_for_complaint(complaint, db)

    db.commit()
    db.refresh(complaint)

    resp = ComplaintResponse.model_validate(complaint)
    resp.assigned_bureau_code = assigned_bureau.code
    resp.institution_name = complaint.institution.name if complaint.institution else None
    return resp


@router.patch("/{complaint_id}", response_model=ComplaintResponse)
def update_complaint(
    complaint_id: int,
    req: ComplaintUpdate,
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Updates status, priority, or remarks for a complaint.
    Enforces Item 5: Officers may modify only complaints assigned to their own bureau.
    """
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    # Enforce bureau write security
    check_bureau_write_permission(current_user, complaint.assigned_bureau_id)

    now = utc_now()
    state_diff = {}

    if req.status and req.status != complaint.status:
        state_diff["old_status"] = complaint.status
        state_diff["new_status"] = req.status
        complaint.status = req.status

    if req.priority and req.priority != complaint.priority:
        state_diff["old_priority"] = complaint.priority
        state_diff["new_priority"] = req.priority
        complaint.priority = req.priority

    if req.assigned_officer_id:
        complaint.assigned_officer_id = req.assigned_officer_id

    if req.last_action:
        complaint.last_action = req.last_action
    if req.next_action:
        complaint.next_action = req.next_action

    complaint.last_action_date = now

    remarks_text = req.remarks or f"Case updated by {current_user.name}."
    db.add(ActionHistory(
        complaint_id=complaint.id,
        timestamp=now,
        actor_name=current_user.name,
        actor_role=current_user.role,
        bureau_code=complaint.assigned_bureau.code,
        action_type="status_change" if "old_status" in state_diff else "remark",
        remarks=remarks_text,
        details=state_diff
    ))

    db.commit()
    db.refresh(complaint)

    resp = ComplaintResponse.model_validate(complaint)
    resp.assigned_bureau_code = complaint.assigned_bureau.code
    resp.institution_name = complaint.institution.name if complaint.institution else None
    return resp


@router.post("/{complaint_id}/transfer", response_model=ComplaintResponse)
def transfer_complaint(
    complaint_id: int,
    req: ComplaintTransferRequest,
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Transfers complaint to another bureau with an immutable audit log.
    Enforces Item 5: Restricted to the assigning bureau, Admin, or Senior Management.
    """
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    check_bureau_write_permission(current_user, complaint.assigned_bureau_id)

    target_bureau = db.query(Bureau).filter(Bureau.id == req.target_bureau_id).first()
    if not target_bureau:
        raise HTTPException(status_code=400, detail="Target bureau not found")

    old_bureau_code = complaint.assigned_bureau.code
    now = utc_now()

    complaint.assigned_bureau_id = target_bureau.id
    complaint.assigned_officer_id = None
    complaint.last_action = f"Transferred to {target_bureau.name}"
    complaint.next_action = "Assigned to Bureau Scrutiny"
    complaint.last_action_date = now

    db.add(ActionHistory(
        complaint_id=complaint.id,
        timestamp=now,
        actor_name=current_user.name,
        actor_role=current_user.role,
        bureau_code=old_bureau_code,
        action_type="transferred",
        remarks=f"Case transferred from {old_bureau_code} to {target_bureau.code}. Reason: {req.remarks}",
        details={"from_bureau": old_bureau_code, "to_bureau": target_bureau.code}
    ))

    # Evaluate any new inter-bureau overlaps created by the bureau change
    _run_overlap_detection_for_complaint(complaint, db)

    db.commit()
    db.refresh(complaint)

    resp = ComplaintResponse.model_validate(complaint)
    resp.assigned_bureau_code = target_bureau.code
    resp.institution_name = complaint.institution.name if complaint.institution else None
    return resp


@router.post("/{complaint_id}/escalate", response_model=ComplaintResponse)
def escalate_complaint(
    complaint_id: int,
    req: ComplaintEscalateRequest,
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Escalates complaint to Senior Management with mandatory audit log.
    Raises critical alert for leadership.
    """
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    check_bureau_write_permission(current_user, complaint.assigned_bureau_id)

    now = utc_now()
    complaint.status = "Escalated"
    complaint.is_escalated = True
    complaint.last_action = "Escalated to Senior Management"
    complaint.last_action_date = now

    db.add(ActionHistory(
        complaint_id=complaint.id,
        timestamp=now,
        actor_name=current_user.name,
        actor_role=current_user.role,
        bureau_code=complaint.assigned_bureau.code,
        action_type="escalated",
        remarks=f"Case escalated to Senior Management. Rationale: {req.remarks}",
        details={"escalated_by": current_user.email}
    ))

    # Critical alert for Senior Management
    db.add(Alert(
        type="escalation",
        complaint_id=complaint.id,
        institution_id=complaint.institution_id,
        message=f"Critical Escalation: Case {complaint.case_id} ({complaint.category}) escalated to Senior Management.",
        severity="critical",
        target_bureau_id=None
    ))

    db.commit()
    db.refresh(complaint)

    resp = ComplaintResponse.model_validate(complaint)
    resp.assigned_bureau_code = complaint.assigned_bureau.code
    resp.institution_name = complaint.institution.name if complaint.institution else None
    return resp


@router.post("/{complaint_id}/confirm-institution", response_model=ComplaintResponse)
def confirm_institution(
    complaint_id: int,
    req: ConfirmInstitutionRequest,
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Confirms candidate institution match for complaints flagged for human review.
    Enforces Item 3: Automatically runs overlap detection and creates CaseLink + Alerts.
    """
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    check_bureau_write_permission(current_user, complaint.assigned_bureau_id)

    institution = db.query(Institution).filter(Institution.id == req.institution_id).first()
    if not institution:
        raise HTTPException(status_code=400, detail="Selected institution not found")

    now = utc_now()
    complaint.institution_id = institution.id
    complaint.needs_institution_review = False
    complaint.candidate_institutions = []
    complaint.last_action = f"Institution Confirmed: {institution.name}"
    complaint.last_action_date = now

    db.add(ActionHistory(
        complaint_id=complaint.id,
        timestamp=now,
        actor_name=current_user.name,
        actor_role=current_user.role,
        bureau_code=complaint.assigned_bureau.code,
        action_type="status_change",
        remarks=f"Institution verified and linked to '{institution.name}' (PID: {institution.permanent_id}).",
        details={"institution_id": institution.id, "permanent_id": institution.permanent_id}
    ))

    # Automated overlap detection for confirmed institution
    _run_overlap_detection_for_complaint(complaint, db)

    db.commit()
    db.refresh(complaint)

    resp = ComplaintResponse.model_validate(complaint)
    resp.assigned_bureau_code = complaint.assigned_bureau.code
    resp.institution_name = institution.name
    return resp
