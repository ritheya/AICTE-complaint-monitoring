from sqlalchemy import Column, Integer, String, Text, Float, JSON, DateTime, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import relationship
from backend.app.database import Base
from backend.app.utils import utc_now


class CaseLink(Base):
    """
    Represents detected and approved overlaps between complaint pairs.
    Enforces canonical ordering (case_a_id < case_b_id) to prevent duplicate reciprocal pairs.
    """
    __tablename__ = "case_links"

    __table_args__ = (
        CheckConstraint("case_a_id < case_b_id", name="check_canonical_case_order"),
        UniqueConstraint("case_a_id", "case_b_id", name="uq_case_link_pair"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    case_a_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    case_b_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    institution_id = Column(Integer, ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True)
    similarity_score = Column(Float, nullable=False)
    signals = Column(JSON, default=dict, nullable=False)
    reasons = Column(JSON, default=list, nullable=False)
    suggested_lead_bureau_id = Column(Integer, ForeignKey("bureaus.id", ondelete="RESTRICT"), nullable=True)
    lead_suggestion_rule = Column(String(255), nullable=True)
    final_lead_bureau_id = Column(Integer, ForeignKey("bureaus.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(30), default="suggested", nullable=False, index=True)  # suggested, approved, rejected, needs_discussion, related_only
    decided_by_id = Column(Integer, ForeignKey("officers.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    decision_remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    # Relational associations
    case_a = relationship("Complaint", foreign_keys=[case_a_id], back_populates="links_as_a")
    case_b = relationship("Complaint", foreign_keys=[case_b_id], back_populates="links_as_b")
    institution = relationship("Institution", back_populates="case_links")
    suggested_lead_bureau = relationship("Bureau", foreign_keys=[suggested_lead_bureau_id])
    final_lead_bureau = relationship("Bureau", foreign_keys=[final_lead_bureau_id])
    decided_by = relationship("Officer", back_populates="decided_links")

    def __repr__(self):
        return f"<CaseLink(case_a_id={self.case_a_id}, case_b_id={self.case_b_id}, score={self.similarity_score}, status='{self.status}')>"
