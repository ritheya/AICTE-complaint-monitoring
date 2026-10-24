"""
AICTE Automated SLA Monitoring & Escalation Service
Evaluates open complaints dynamically without hardcoding.
"""
from datetime import timedelta
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from backend.app.database import SessionLocal
from backend.app.models.complaint import Complaint
from backend.app.models.action_history import ActionHistory
from backend.app.models.alert import Alert
from backend.app.utils import utc_now
from backend.app.config import (
    SLA_DAYS_BY_CATEGORY,
    SLA_PRIORITY_MULTIPLIERS,
    SLA_AUTO_ESCALATE_OVERDUE_DAYS
)


def run_sla_check_evaluation(db: Session) -> Dict[str, Any]:
    """
    Evaluates every open complaint dynamically from date_received, category, priority, and current naive-UTC date.
    - Flags overdue cases (is_overdue = True).
    - Auto-escalates cases that have exceeded SLA_AUTO_ESCALATE_OVERDUE_DAYS (is_escalated = True).
    - Generates system alerts and action history entries.
    - Fully idempotent: running multiple times does not produce duplicate alerts, duplicate escalations, or duplicate history entries.
    """
    now = utc_now()
    open_complaints = db.query(Complaint).filter(
        Complaint.status.notin_(["Disposed", "Transferred"])
    ).all()

    evaluated_count = len(open_complaints)
    flagged_overdue_count = 0
    newly_escalated_count = 0
    alerts_created_count = 0

    for c in open_complaints:
        # Calculate expected disposal date dynamically if not set
        base_days = SLA_DAYS_BY_CATEGORY.get(c.category, 30)
        mult = SLA_PRIORITY_MULTIPLIERS.get(c.priority, 1.0)
        total_sla_days = int(round(base_days * mult))
        target_disposal_date = c.date_received + timedelta(days=total_sla_days)

        # Update expected_disposal_date if missing or mismatched
        if not c.expected_disposal_date:
            c.expected_disposal_date = target_disposal_date

        # Check if overdue
        if now > c.expected_disposal_date:
            if not c.is_overdue:
                c.is_overdue = True
                flagged_overdue_count += 1
            else:
                flagged_overdue_count += 1

            days_overdue = (now - c.expected_disposal_date).days

            # 1. Idempotent SLA Warning / Breach Alert creation
            existing_alert = db.query(Alert).filter(
                Alert.complaint_id == c.id,
                Alert.type == "sla_breached"
            ).first()

            if not existing_alert:
                alert = Alert(
                    type="sla_breached",
                    complaint_id=c.id,
                    institution_id=c.institution_id,
                    message=f"Case {c.case_id} has exceeded statutory SLA target by {days_overdue} day(s).",
                    severity="critical",
                    target_bureau_id=c.assigned_bureau_id,
                    is_read=False,
                    created_at=now
                )
                db.add(alert)
                alerts_created_count += 1

            # 2. Auto-escalation if past configured threshold (e.g., >= 7 days overdue)
            if days_overdue >= SLA_AUTO_ESCALATE_OVERDUE_DAYS and not c.is_escalated:
                c.is_escalated = True
                c.last_action = "Auto-Escalated to Senior Management due to prolonged SLA breach"
                c.last_action_date = now

                # Idempotent action history check
                existing_escalation_history = db.query(ActionHistory).filter(
                    ActionHistory.complaint_id == c.id,
                    ActionHistory.action_type == "AUTO_ESCALATION"
                ).first()

                if not existing_escalation_history:
                    history = ActionHistory(
                        complaint_id=c.id,
                        timestamp=now,
                        actor_name="System Automated Scheduler",
                        actor_role="System Scheduler",
                        bureau_code="HQ",
                        action_type="AUTO_ESCALATION",
                        remarks=f"Automated statutory escalation: Case is {days_overdue} days past target disposal date.",
                        details={
                            "days_overdue": days_overdue,
                            "threshold_days": SLA_AUTO_ESCALATE_OVERDUE_DAYS,
                            "date_received": c.date_received.isoformat(),
                            "expected_disposal_date": c.expected_disposal_date.isoformat()
                        }
                    )
                    db.add(history)
                    newly_escalated_count += 1

                # Alert Senior Management
                existing_mgmt_alert = db.query(Alert).filter(
                    Alert.complaint_id == c.id,
                    Alert.type == "escalation"
                ).first()
                if not existing_mgmt_alert:
                    mgmt_alert = Alert(
                        type="escalation",
                        complaint_id=c.id,
                        institution_id=c.institution_id,
                        message=f"Case {c.case_id} auto-escalated to Senior Management ({days_overdue} days overdue).",
                        severity="critical",
                        target_bureau_id=None,  # Broadcast to Senior Management
                        is_read=False,
                        created_at=now
                    )
                    db.add(mgmt_alert)

    db.commit()

    return {
        "status": "success",
        "evaluated_complaints": evaluated_count,
        "overdue_complaints": flagged_overdue_count,
        "newly_escalated_complaints": newly_escalated_count,
        "alerts_created": alerts_created_count,
        "timestamp": now.isoformat()
    }


# Background task wrapper for APScheduler
def scheduled_sla_check_job():
    """Job executed periodically by APScheduler."""
    db = SessionLocal()
    try:
        run_sla_check_evaluation(db)
    finally:
        db.close()
