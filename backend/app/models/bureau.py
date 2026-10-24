from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from backend.app.database import Base
from backend.app.utils import utc_now


class Bureau(Base):
    """
    Administrative Bureaus and Cells within AICTE.
    """
    __tablename__ = "bureaus"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    code = Column(String(10), unique=True, index=True, nullable=False)  # RB, PGRC, AB, AFB
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=False)

    # Relational associations
    officers = relationship("Officer", back_populates="bureau")
    complaints = relationship("Complaint", back_populates="assigned_bureau")
    alerts = relationship("Alert", back_populates="target_bureau")

    def __repr__(self):
        return f"<Bureau(code='{self.code}', name='{self.name}')>"


class Officer(Base):
    """
    Authorized AICTE Officer with role-based permissions.
    """
    __tablename__ = "officers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(150), nullable=False)
    email = Column(String(150), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)  # RB Officer, PGRC Officer, AB Officer, Senior Management, Admin, etc.
    bureau_id = Column(Integer, ForeignKey("bureaus.id", ondelete="SET NULL"), nullable=True)
    region = Column(String(50), nullable=True)  # Populated for Regional Officers
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    # Relational associations
    bureau = relationship("Bureau", back_populates="officers")
    complaints = relationship("Complaint", back_populates="assigned_officer")
    decided_links = relationship("CaseLink", back_populates="decided_by")

    def __repr__(self):
        return f"<Officer(email='{self.email}', role='{self.role}')>"
