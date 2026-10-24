from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from backend.app.database import Base
from backend.app.utils import utc_now


class Alert(Base):
    """
    System alerts for overlaps, SLA breaches, and pending reminders.
    """
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    type = Column(String(50), nullable=False, index=True)  # overlap, pending_reminder, escalation, sla_due_soon, sla_breached
    complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=True, index=True)
    institution_id = Column(Integer, ForeignKey("institutions.id", ondelete="CASCADE"), nullable=True, index=True)
    message = Column(Text, nullable=False)
    severity = Column(String(20), nullable=False, index=True)  # info, warning, critical
    target_bureau_id = Column(Integer, ForeignKey("bureaus.id", ondelete="SET NULL"), nullable=True, index=True)
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    # Relational associations
    complaint = relationship("Complaint", back_populates="alerts")
    institution = relationship("Institution", back_populates="alerts")
    target_bureau = relationship("Bureau", back_populates="alerts")

    def __repr__(self):
        return f"<Alert(type='{self.type}', severity='{self.severity}', read={self.is_read})>"
