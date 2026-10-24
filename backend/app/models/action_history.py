from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from backend.app.database import Base
from backend.app.utils import utc_now


class ActionHistory(Base):
    """
    Immutable chronological audit trail of all complaint actions,
    status changes, officer remarks, transfers, and system triggers.
    """
    __tablename__ = "action_history"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime, default=utc_now, nullable=False, index=True)
    actor_name = Column(String(100), nullable=False)
    actor_role = Column(String(50), nullable=False)
    bureau_code = Column(String(10), nullable=False)
    action_type = Column(String(50), nullable=False)  # received, assigned, remark, transferred, escalated, linked, status_change, etc.
    remarks = Column(Text, nullable=False)
    attachment_name = Column(String(255), nullable=True)
    details = Column(JSON, default=dict, nullable=False)

    # Relational association
    complaint = relationship("Complaint", back_populates="action_history")

    def __repr__(self):
        return f"<ActionHistory(complaint_id={self.complaint_id}, type='{self.action_type}', actor='{self.actor_name}')>"
