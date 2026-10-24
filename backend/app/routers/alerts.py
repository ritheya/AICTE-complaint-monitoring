"""
System Notifications and Operational Alerts Router
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.alert import Alert
from backend.app.models.bureau import Officer
from backend.app.auth.dependencies import get_current_user
from backend.app.schemas.alert import AlertResponse

router = APIRouter(prefix="/alerts", tags=["System Alerts"])


@router.get("", response_model=List[AlertResponse])
def list_alerts(
    unread_only: bool = Query(False, description="Filter for unacknowledged alerts"),
    severity: Optional[str] = Query(None, description="info, warning, critical"),
    alert_type: Optional[str] = Query(None, description="overlap, escalation, sla_due_soon, sla_breached, pending_reminder"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lists system notifications, SLA warning triggers, and overlap alerts.
    Filters by user's assigned bureau for bureau-level officers.
    """
    query = db.query(Alert)

    # Scoping: Senior Management & Admin see all; bureau officers see bureau-targeted + global alerts
    if current_user.role not in ["System Administrator", "Senior Management"]:
        if current_user.bureau_id:
            query = query.filter(
                (Alert.target_bureau_id == current_user.bureau_id) |
                (Alert.target_bureau_id.is_(None))
            )

    if unread_only:
        query = query.filter(Alert.is_read.is_(False))

    if severity:
        query = query.filter(Alert.severity == severity.strip().lower())

    if alert_type:
        query = query.filter(Alert.type == alert_type.strip().lower())

    alerts = query.order_by(Alert.created_at.desc()).offset(skip).limit(limit).all()
    return alerts


@router.patch("/{alert_id}/read", response_model=AlertResponse)
def mark_alert_read(
    alert_id: int,
    current_user: Officer = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Marks an operational alert notification as read/acknowledged.
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with ID {alert_id} not found"
        )

    # Authorization check
    if current_user.role not in ["System Administrator", "Senior Management"]:
        if alert.target_bureau_id and alert.target_bureau_id != current_user.bureau_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Cannot acknowledge alert targeted to another bureau"
            )

    alert.is_read = True
    db.commit()
    db.refresh(alert)
    return alert
