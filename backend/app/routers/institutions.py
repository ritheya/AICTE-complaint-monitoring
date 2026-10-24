"""
Canonical Institution Registry and Dynamic Risk Leaderboard Router
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.app.database import get_db
from backend.app.models.institution import Institution
from backend.app.models.complaint import Complaint
from backend.app.models.case_link import CaseLink
from backend.app.models.bureau import Officer
from backend.app.auth.dependencies import get_current_user
from backend.app.services.risk_scorer import InstitutionalRiskScorer
from backend.app.schemas.institution import (
    InstitutionResponse,
    InstitutionLeaderboardItem,
    InstitutionSummaryResponse
)

router = APIRouter(prefix="/institutions", tags=["Institutions"])


@router.get("/leaderboard/risk", response_model=List[InstitutionLeaderboardItem])
def get_risk_leaderboard(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Dynamic Institutional Risk Leaderboard (Scenario 6).
    Evaluates institutions based on dynamic 5-component scoring computed from live DB records:
    1. Complaint Volume (last 24m)
    2. Pending Ratio
    3. Severity Penalty
    4. Repeat Categories Penalty
    5. Unresolved Overlaps Penalty
    Ranks institutions strictly by computed DB data without bias or hardcoding.
    """
    institutions = db.query(Institution).all()
    scored_items = []

    for inst in institutions:
        score, breakdown = InstitutionalRiskScorer.calculate_risk(inst.id, db)
        
        # Count open complaints and total complaints
        total_count = db.query(Complaint).filter(Complaint.institution_id == inst.id).count()
        open_count = db.query(Complaint).filter(
            Complaint.institution_id == inst.id,
            Complaint.status.notin_(["Disposed", "Transferred"])
        ).count()

        scored_items.append({
            "id": inst.id,
            "permanent_id": inst.permanent_id,
            "name": inst.name,
            "city": inst.city,
            "state": inst.state,
            "risk_score": score,
            "risk_band": breakdown["band"],
            "open_complaints": open_count,
            "total_complaints": total_count
        })

    # Sort descending by computed risk score
    scored_items.sort(key=lambda x: x["risk_score"], reverse=True)

    leaderboard = []
    for rank, item in enumerate(scored_items[:limit], start=1):
        leaderboard.append(InstitutionLeaderboardItem(
            rank=rank,
            id=item["id"],
            permanent_id=item["permanent_id"],
            name=item["name"],
            city=item["city"],
            state=item["state"],
            risk_score=item["risk_score"],
            risk_band=item["risk_band"],
            open_complaints=item["open_complaints"],
            total_complaints=item["total_complaints"]
        ))

    return leaderboard


@router.get("", response_model=List[InstitutionResponse])
def list_institutions(
    search: Optional[str] = Query(None, description="Search by institution name or Permanent ID"),
    region: Optional[str] = Query(None, description="Filter by AICTE regional office jurisdiction"),
    state: Optional[str] = Query(None, description="Filter by Indian State"),
    risk_band: Optional[str] = Query(None, description="Filter by Low, Moderate, High risk"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lists canonical institutions with optional search, region, state, and risk-band filtering.
    """
    query = db.query(Institution)

    # Scoping for Regional Officers: if user role is Regional Officer, restrict to their assigned region
    if current_user.role == "Regional Officer" and current_user.region:
        query = query.filter(Institution.region == current_user.region)
    elif region:
        query = query.filter(Institution.region == region)

    if search:
        search_clean = f"%{search.strip()}%"
        query = query.filter(
            (Institution.name.ilike(search_clean)) |
            (Institution.permanent_id.ilike(search_clean)) |
            (Institution.city.ilike(search_clean))
        )

    if state:
        query = query.filter(Institution.state == state)

    institutions = query.offset(skip).limit(limit).all()
    results = []

    for inst in institutions:
        score, breakdown = InstitutionalRiskScorer.calculate_risk(inst.id, db)
        inst_data = InstitutionResponse.model_validate(inst)
        inst_data.risk_score = score
        inst_data.risk_breakdown = breakdown
        if risk_band and breakdown.get("band", "").lower() != risk_band.strip().lower():
            continue
        results.append(inst_data)

    return results


@router.get("/{institution_id}", response_model=InstitutionResponse)
def get_institution(
    institution_id: int,
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retrieves full details of an institution including dynamically evaluated risk breakdown.
    """
    inst = db.query(Institution).filter(Institution.id == institution_id).first()
    if not inst:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Institution with ID {institution_id} not found"
        )

    # Regional officer scope enforcement
    if current_user.role == "Regional Officer" and current_user.region and inst.region != current_user.region:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Institution is in {inst.region} Region outside officer jurisdiction"
        )

    score, breakdown = InstitutionalRiskScorer.calculate_risk(inst.id, db)
    inst_resp = InstitutionResponse.model_validate(inst)
    inst_resp.risk_score = score
    inst_resp.risk_breakdown = breakdown
    return inst_resp


@router.get("/{institution_id}/summary", response_model=InstitutionSummaryResponse)
def get_institution_executive_summary(
    institution_id: int,
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generates an executive complaint briefing for the institution, grounded strictly in
    historical grievance volume, active inter-bureau overlaps, and risk factor breakdown.
    """
    inst = db.query(Institution).filter(Institution.id == institution_id).first()
    if not inst:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Institution with ID {institution_id} not found"
        )

    score, breakdown = InstitutionalRiskScorer.calculate_risk(inst.id, db)
    total_complaints = db.query(Complaint).filter(Complaint.institution_id == inst.id).count()
    open_complaints = db.query(Complaint).filter(
        Complaint.institution_id == inst.id,
        Complaint.status.notin_(["Disposed", "Transferred"])
    ).count()

    # Category counts
    cat_counts = (
        db.query(Complaint.category, func.count(Complaint.id))
        .filter(Complaint.institution_id == inst.id)
        .group_by(Complaint.category)
        .all()
    )
    cat_summary = ", ".join([f"{cat} ({cnt})" for cat, cnt in cat_counts]) if cat_counts else "None"

    # Active overlaps
    overlaps_count = (
        db.query(CaseLink)
        .filter(
            CaseLink.institution_id == inst.id,
            CaseLink.status.in_(["suggested", "approved", "needs_discussion"])
        )
        .count()
    )

    summary_text = (
        f"Executive Governance Summary for {inst.name} (Permanent ID: {inst.permanent_id}, {inst.city}, {inst.state}): "
        f"Institution currently holds an aggregate risk score of {score:.1f}/100 ({breakdown['band']}). "
        f"Total complaints filed to date: {total_complaints}, of which {open_complaints} remain actively under investigation. "
        f"Primary grievance categories: {cat_summary}. "
        f"Inter-bureau coordination alert status: {overlaps_count} active cross-bureau overlap link(s) recorded. "
        f"Primary risk drivers identified: {breakdown['components']['complaint_volume']['count']} volume events, "
        f"{breakdown['components']['severity_penalty']['critical_count']} critical/high severity cases, and "
        f"{len(breakdown['components']['repeat_categories']['repeat_categories_list'])} recurring category patterns."
    )

    return InstitutionSummaryResponse(
        institution_id=inst.id,
        summary_text=summary_text,
        source="template_fallback"
    )
