from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, JSON, DateTime
from sqlalchemy.orm import relationship
from backend.app.database import Base


class Institution(Base):
    """
    Represents an AICTE-approved or recorded technical institution.
    """
    __tablename__ = "institutions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    permanent_id = Column(String(32), unique=True, index=True, nullable=False)
    name = Column(String(255), index=True, nullable=False)
    normalized_name = Column(String(255), index=True, nullable=False)
    aliases = Column(JSON, default=list, nullable=False)
    address = Column(Text, nullable=False)
    city = Column(String(100), index=True, nullable=False)
    state = Column(String(100), index=True, nullable=False)
    region = Column(String(50), index=True, nullable=False)  # North, South, East, West, Central, North-East
    pincode = Column(String(10), index=True, nullable=False)
    institution_type = Column(String(100), nullable=False)  # Engineering & Tech, Management, Pharmacy, etc.
    risk_score = Column(Float, default=0.0, index=True, nullable=False)
    risk_breakdown = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relational associations
    complaints = relationship("Complaint", back_populates="institution", cascade="all, delete-orphan")
    case_links = relationship("CaseLink", back_populates="institution", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="institution", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Institution(id={self.id}, permanent_id='{self.permanent_id}', name='{self.name}')>"
