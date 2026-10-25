"""
System Alerts and Notifications Schemas
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class AlertResponse(BaseModel):
    """Notification record for overlaps, SLA breaches, and reminders."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str  # overlap, escalation, sla_due_soon, sla_breached, pending_reminder
    complaint_id: Optional[int] = None
    institution_id: Optional[int] = None
    message: str
    severity: str  # info, warning, critical
    target_bureau_id: Optional[int] = None
    is_read: bool
    created_at: datetime


class PaginatedAlertResponse(BaseModel):
    """Paginated list of operational alerts with total match count."""
    model_config = ConfigDict(from_attributes=True)

    total: int
    skip: int
    limit: int
    items: list[AlertResponse]
