"""
Scheduler Management and On-Demand SLA Evaluation Router
"""
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler

from backend.app.database import get_db
from backend.app.models.bureau import Officer
from backend.app.auth.dependencies import get_current_user, require_roles
from backend.app.services.scheduler_service import (
    run_sla_check_evaluation,
    scheduled_sla_check_job
)

from backend.app.config import ENABLE_BACKGROUND_SLA_JOB

router = APIRouter(prefix="/scheduler", tags=["Scheduler"])

# Global APScheduler background instance
scheduler = BackgroundScheduler(daemon=True)

# Register the periodic daily SLA evaluation job
scheduler.add_job(
    scheduled_sla_check_job,
    trigger="interval",
    hours=24,
    id="sla_daily_monitoring_job",
    name="AICTE Statutory SLA Compliance Evaluation",
    replace_existing=True
)

if ENABLE_BACKGROUND_SLA_JOB and not scheduler.running:
    scheduler.start()


@router.post("/run-sla-check", response_model=Dict[str, Any])
def trigger_sla_check(
    current_user: Officer = Depends(require_roles(["Admin", "System Administrator", "Senior Management"])),
    db: Session = Depends(get_db)
):
    """
    On-demand execution of the AICTE statutory SLA compliance evaluation.
    - Restricted to Admin and Senior Management.
    - Evaluates every open complaint dynamically without hardcoding.
    - Flags overdue cases and auto-escalates cases exceeding prolonged SLA threshold.
    - Guaranteed idempotent: running multiple times does not produce duplicate alerts or escalations.
    """
    result = run_sla_check_evaluation(db)
    result["triggered_by"] = current_user.email
    return result


@router.get("/status", response_model=Dict[str, Any])
def get_scheduler_status(
    current_user: Officer = Depends(get_current_user)
):
    """
    Returns current health and operational status of the APScheduler background worker.
    """
    jobs = []
    for job in scheduler.get_jobs():
        next_run = getattr(job, "next_run_time", None)
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": next_run.isoformat() if next_run else None
        })

    return {
        "scheduler_running": scheduler.running,
        "background_job_enabled": ENABLE_BACKGROUND_SLA_JOB,
        "active_jobs_count": len(jobs),
        "jobs": jobs
    }
