"""
Real-Time Intake Pre-Check & Extraction Router (Scenario 5 Demo)
Stateless pre-submission analytics. Enforces Item 8: NEVER writes to the database.
"""
import re
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from backend.app.database import get_db
from backend.app.models.complaint import Complaint
from backend.app.models.institution import Institution
from backend.app.utils import utc_now
from backend.app.auth.dependencies import get_current_user
from backend.app.models.bureau import Officer
from backend.app.services.resolution_engine import InstitutionResolutionEngine
from backend.app.services.overlap_engine import ComplaintOverlapEngine
from backend.app.services.lead_bureau_rules import LeadBureauEngine
from backend.app.schemas.overlap import (
    LivePrecheckRequest,
    LivePrecheckResponse,
    ActiveOverlapAlert
)

router = APIRouter(prefix="/intake", tags=["Live Intake"])

res_engine = InstitutionResolutionEngine()
overlap_engine = ComplaintOverlapEngine()
lead_engine = LeadBureauEngine()


class ExtractRequest(BaseModel):
    """Raw grievance text submitted for automated concept extraction."""
    text: str = Field(..., description="Unstructured grievance text entered by citizen/student")


class ExtractResponse(BaseModel):
    """Structured extraction output from raw grievance narrative."""
    extracted_institution_name: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    permanent_id: Optional[str] = None
    category: str = "Other"
    priority: str = "Medium"
    confidence: float = 0.85
    method: str = "keyword_concept_extractor"


@router.post("/extract", response_model=ExtractResponse)
def extract_complaint_metadata(
    req: ExtractRequest,
    current_user: Officer = Depends(get_current_user)
):
    """
    Extracts structured governance metadata from raw complaint text:
    - Extracts AICTE Permanent ID (format: 1-XXXXXXXXX).
    - Extracts 6-digit postal pincodes.
    - Resolves grievance category via concept normalization.
    - Evaluates priority urgency signals.
    """
    raw_text = req.text.strip()
    lower_text = raw_text.lower()

    # 1. Extract Permanent ID if present
    pid_match = re.search(r"\b1-[0-9]{8,11}\b", raw_text)
    permanent_id = pid_match.group(0) if pid_match else None

    # 2. Extract Pincode if present
    pin_match = re.search(r"\b[1-9][0-9]{5}\b", raw_text)
    pincode = pin_match.group(0) if pin_match else None

    # 3. Category detection from domain keywords
    category = "Other"
    if any(k in lower_text for k in ["fee", "caution money", "refund", "deposit", "capitation", "receipt", "exam fee"]):
        category = "Fee Related"
    elif any(k in lower_text for k in ["faculty", "teacher", "professor", "adjunct", "vacancy", "staff shortage"]):
        category = "Faculty Shortage"
    elif any(k in lower_text for k in ["infrastructure", "lab", "terminal", "equipment", "machinery", "building", "library"]):
        category = "Infrastructure"
    elif any(k in lower_text for k in ["harassment", "ragging", "mess", "hostel", "food", "safety", "water"]):
        category = "Harassment/Student Welfare"
    elif any(k in lower_text for k in ["unapproved", "fake course", "without approval", "bogus"]):
        category = "Fake/Unapproved Courses"
    elif any(k in lower_text for k in ["approval", "affiliation", "compliance", "show-cause", "intake sanction"]):
        category = "Approval/Affiliation Compliance"
    elif any(k in lower_text for k in ["exam", "result", "marksheet", "transcript", "hall ticket", "admit card"]):
        category = "Examination/Result"
    elif any(k in lower_text for k in ["placement", "package", "recruiter", "job offer"]):
        category = "Placement Misrepresentation"
    elif any(k in lower_text for k in ["admission", "quota", "seat allocation"]):
        category = "Admission Irregularity"

    # 4. Priority detection from urgency signals
    priority = "Medium"
    if any(k in lower_text for k in ["urgent", "emergency", "suicide", "threat", "severe", "violence"]):
        priority = "Critical"
    elif any(k in lower_text for k in ["admit card", "hall ticket", "withholding", "immediate", "tomorrow", "deadline"]):
        priority = "High"
    elif any(k in lower_text for k in ["query", "clarification", "information"]):
        priority = "Low"

    # 5. Extract rough institution name candidate
    # If text mentions college/institute/tech, extract relevant clause
    name_match = re.search(r"(?:against|at|in|my college)\s+([A-Za-z0-9\s&.,'-]+?(?:institute|college|academy|polytechnic|university|tech)[A-Za-z0-9\s&.,'-]*)", raw_text, re.IGNORECASE)
    extracted_name = name_match.group(1).strip() if name_match else None

    # Detect known cities
    from backend.app.config import CITY_TO_STATE_LOOKUP
    detected_city = None
    detected_state = None
    for city_key, state_val in CITY_TO_STATE_LOOKUP.items():
        if re.search(r"\b" + re.escape(city_key) + r"\b", lower_text):
            detected_city = city_key.title()
            detected_state = state_val.title()
            break

    return ExtractResponse(
        extracted_institution_name=extracted_name or raw_text[:60],
        city=detected_city,
        state=detected_state,
        pincode=pincode,
        permanent_id=permanent_id,
        category=category,
        priority=priority,
        confidence=0.88,
        method="grounded_keyword_extractor"
    )


@router.post("/precheck", response_model=LivePrecheckResponse)
def live_intake_precheck(
    req: LivePrecheckRequest,
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Scenario 5: Real-time complaint intake pre-check.
    Enforces Item 5 & Item 8:
    1. Runs InstitutionResolutionEngine (AUTO_LINK, NEEDS_REVIEW, or UNRESOLVED).
    2. If AUTO_LINK: runs overlap check against active cases at the resolved institution.
    3. If NEEDS_REVIEW: runs overlap check against the top candidate institution,
       labelled 'provisional, institution not confirmed' (is_provisional = True).
    4. If UNRESOLVED: returns no overlaps with explicit explanation.
    5. STRICTLY DOES NOT PERSIST ANY ROWS TO THE DATABASE.
    """
    # Step 1: Run Institution Resolution Pipeline
    query_name = req.raw_institution_name.strip() if req.raw_institution_name else req.text.strip()
    res_result = res_engine.resolve(
        raw_name=query_name,
        city=req.city,
        state=req.state,
        pincode=req.pincode,
        permanent_id=req.permanent_id,
        db=db
    )

    detected_overlaps: List[ActiveOverlapAlert] = []

    # Step 2: Handle Resolution Cases
    if res_result.status == "UNRESOLVED":
        # Case C: Unresolved - No overlap check performed
        return LivePrecheckResponse(
            institution_id=None,
            institution_name=None,
            permanent_id=None,
            resolution_confidence=res_result.confidence,
            resolution_status=res_result.status,
            needs_institution_review=False,
            candidate_institutions=res_result.candidates,
            resolution_reasons=res_result.reasons + [
                "No inter-bureau overlap check performed: institution could not be resolved from provided query (confidence below 0.60)."
            ],
            has_active_overlap=False,
            active_overlaps=[]
        )

    # Determine target institution to check (best institution for AUTO_LINK or top candidate for NEEDS_REVIEW)
    target_institution: Optional[Institution] = None
    is_provisional = False
    provisional_notice = None

    if res_result.status == "AUTO_LINK" and res_result.best_institution:
        target_institution = res_result.best_institution
        is_provisional = False
    elif res_result.candidates:
        # Case B: NEEDS_REVIEW - check against top candidate
        top_cand_id = res_result.candidates[0]["id"]
        target_institution = db.query(Institution).filter(Institution.id == top_cand_id).first()
        is_provisional = True
        provisional_notice = "Provisional overlap alert (institution not confirmed - human review required)"

    if target_institution:
        # Query active open complaints at the target institution
        active_cases = db.query(Complaint).filter(
            Complaint.institution_id == target_institution.id,
            Complaint.status.notin_(["Disposed", "Transferred"])
        ).all()

        # Build in-memory mock complaint for text/category/date comparison
        mock_complaint = Complaint(
            id=999999,
            case_id="LIVE/PRECHECK/TEMP",
            institution_id=target_institution.id,
            raw_institution_name=target_institution.name,
            source="Portal",
            category=req.category or "Fee Related",
            description=req.text,
            complainant_type="Student",
            date_received=utc_now(),
            status="Pending",
            assigned_bureau_id=current_user.bureau_id or 2  # PGRC default
        )

        for existing_case in active_cases:
            # Overlap engine checks distinct bureaus, text similarity, category relationship, date proximity
            if existing_case.assigned_bureau_id == mock_complaint.assigned_bureau_id:
                continue

            ovl = overlap_engine.evaluate_overlap(mock_complaint, existing_case, db=db)
            if ovl.is_overlap and ovl.score >= 0.60:
                lead = lead_engine.suggest_lead(mock_complaint, existing_case)

                reasons_list = list(ovl.reasons)
                if is_provisional and provisional_notice:
                    reasons_list.insert(0, provisional_notice)

                detected_overlaps.append(ActiveOverlapAlert(
                    existing_case_id=existing_case.case_id,
                    existing_case_bureau=existing_case.assigned_bureau.code if existing_case.assigned_bureau else "Bureau",
                    existing_category=existing_case.category,
                    overlap_score=ovl.score,
                    band=ovl.band,
                    signals=ovl.signals,
                    reasons=reasons_list,
                    suggested_lead_bureau=lead.lead_bureau_code if lead else None,
                    lead_rule=lead.rule_id if lead else None,
                    is_provisional=is_provisional,
                    provisional_notice=provisional_notice
                ))

    return LivePrecheckResponse(
        institution_id=target_institution.id if target_institution else None,
        institution_name=target_institution.name if target_institution else None,
        permanent_id=target_institution.permanent_id if target_institution else None,
        resolution_confidence=res_result.confidence,
        resolution_status=res_result.status,
        needs_institution_review=res_result.needs_review,
        candidate_institutions=res_result.candidates,
        resolution_reasons=res_result.reasons,
        has_active_overlap=len(detected_overlaps) > 0,
        active_overlaps=detected_overlaps
    )
