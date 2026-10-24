from sqlalchemy import Column, Integer, String, Text, Boolean, Float, JSON, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from backend.app.database import Base
from backend.app.utils import utc_now


class Complaint(Base):
    """
    Central Complaint / Case record in the AICTE system.
    """
    __tablename__ = "complaints"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    case_id = Column(String(50), unique=True, index=True, nullable=False)
    institution_id = Column(Integer, ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True, index=True)
    raw_institution_name = Column(String(255), nullable=False)
    source = Column(String(50), nullable=False)  # Portal, CPGRAMS, Email, Letter
    category = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=False)
    complainant_type = Column(String(50), nullable=False)  # Student, Faculty, Parent, Citizen
    date_received = Column(DateTime, nullable=False, index=True)
    status = Column(String(50), default="Pending", nullable=False, index=True)  # Pending, Under Process, Disposed, Transferred, Escalated
    assigned_bureau_id = Column(Integer, ForeignKey("bureaus.id", ondelete="RESTRICT"), nullable=False, index=True)
    assigned_officer_id = Column(Integer, ForeignKey("officers.id", ondelete="SET NULL"), nullable=True, index=True)
    last_action = Column(String(255), default="Grievance Registered", nullable=False)
    next_action = Column(String(255), default="Initial Scrutiny", nullable=False)
    last_action_date = Column(DateTime, default=utc_now, nullable=False)
    expected_disposal_date = Column(DateTime, nullable=False, index=True)
    priority = Column(String(20), default="Medium", nullable=False, index=True)  # Low, Medium, High, Critical
    is_overdue = Column(Boolean, default=False, nullable=False, index=True)
    is_escalated = Column(Boolean, default=False, nullable=False, index=True)
    match_confidence = Column(Float, nullable=True)
    needs_institution_review = Column(Boolean, default=False, nullable=False, index=True)
    candidate_institutions = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    # Relational associations
    institution = relationship("Institution", back_populates="complaints")
    assigned_bureau = relationship("Bureau", back_populates="complaints")
    assigned_officer = relationship("Officer", back_populates="complaints")
    action_history = relationship("ActionHistory", back_populates="complaint", cascade="all, delete-orphan", order_by="ActionHistory.timestamp.asc()")
    alerts = relationship("Alert", back_populates="complaint", cascade="all, delete-orphan")

    # Links
    links_as_a = relationship("CaseLink", foreign_keys="CaseLink.case_a_id", back_populates="case_a", cascade="all, delete-orphan")
    links_as_b = relationship("CaseLink", foreign_keys="CaseLink.case_b_id", back_populates="case_b", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Complaint(case_id='{self.case_id}', status='{self.status}', bureau_id={self.assigned_bureau_id})>"
