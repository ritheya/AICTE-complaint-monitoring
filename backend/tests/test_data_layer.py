import os
import sys
import pytest
import bcrypt
from pathlib import Path
from sqlalchemy.exc import IntegrityError

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.app.database import SessionLocal, engine, Base
from backend.app.models.institution import Institution
from backend.app.models.bureau import Bureau, Officer
from backend.app.models.complaint import Complaint
from backend.app.models.action_history import ActionHistory
from backend.app.models.case_link import CaseLink
from backend.app.models.alert import Alert


@pytest.fixture(scope="module")
def db_session():
    """Provides a transactional database session for data layer testing."""
    session = SessionLocal()
    yield session
    session.close()


class TestDatabaseSchemaAndConstraints:
    """Tests for database tables, foreign keys, and relational constraints."""

    def test_tables_exist(self):
        """Verifies that all required tables exist in metadata."""
        table_names = Base.metadata.tables.keys()
        expected_tables = {"institutions", "bureaus", "officers", "complaints", "action_history", "case_links", "alerts"}
        for tbl in expected_tables:
            assert tbl in table_names, f"Table '{tbl}' is missing from metadata"

    def test_case_link_canonical_order_constraint(self, db_session):
        """Verifies that case_a_id >= case_b_id is strictly rejected by database check constraint."""
        # Find any 2 complaints
        complaints = db_session.query(Complaint).limit(2).all()
        assert len(complaints) == 2, "Need at least 2 complaints to test link constraint"
        c1, c2 = complaints[0], complaints[1]
        higher_id = max(c1.id, c2.id)
        lower_id = min(c1.id, c2.id)

        # Attempt to insert inverted pair (case_a_id > case_b_id)
        invalid_link = CaseLink(
            case_a_id=higher_id,
            case_b_id=lower_id,
            institution_id=c1.institution_id or 1,
            similarity_score=0.75,
            reasons=["Test constraint violation"],
            suggested_lead_bureau_id=c1.assigned_bureau_id,
            lead_suggestion_rule="TEST_RULE",
            status="suggested"
        )
        db_session.add(invalid_link)
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    def test_case_link_self_link_constraint(self, db_session):
        """Verifies that linking a case to itself (case_a_id == case_b_id) fails."""
        c = db_session.query(Complaint).first()
        assert c is not None

        self_link = CaseLink(
            case_a_id=c.id,
            case_b_id=c.id,
            institution_id=c.institution_id or 1,
            similarity_score=0.99,
            reasons=["Self link test"],
            suggested_lead_bureau_id=c.assigned_bureau_id,
            lead_suggestion_rule="TEST_RULE",
            status="suggested"
        )
        db_session.add(self_link)
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()


class TestSeededDataVolumeAndIntegrity:
    """Tests confirming the volume and integrity of the seeded database."""

    def test_bureaus_seeded(self, db_session):
        """Verifies all 4 core AICTE bureaus exist."""
        codes = [b.code for b in db_session.query(Bureau).all()]
        for code in ["RB", "PGRC", "AB", "AFB"]:
            assert code in codes, f"Bureau code '{code}' not found in database"

    def test_officers_seeded_and_passwords_valid(self, db_session):
        """Verifies demo officer accounts and their bcrypt hashes."""
        officers = db_session.query(Officer).all()
        assert len(officers) >= 6, "At least 6 demo officers must be seeded"

        for officer in officers:
            assert officer.email is not None
            assert officer.password_hash.startswith("$2b$") or officer.password_hash.startswith("$2a$")
            # Verify password Demo@123
            assert bcrypt.checkpw(b"Demo@123", officer.password_hash.encode("utf-8")), f"Password check failed for {officer.email}"

    def test_institutions_volume(self, db_session):
        """Verifies that at least 150 institutions are seeded across all 6 regions."""
        inst_count = db_session.query(Institution).count()
        assert inst_count >= 150, f"Expected >= 150 institutions, found {inst_count}"

        regions = {i.region for i in db_session.query(Institution.region).distinct()}
        for reg in ["North", "South", "East", "West", "Central", "North-East"]:
            assert reg in regions, f"Region '{reg}' missing from institutions"

    def test_complaints_volume_and_history(self, db_session):
        """Verifies at least 450 complaints and their action history audit trails."""
        complaint_count = db_session.query(Complaint).count()
        assert complaint_count >= 450, f"Expected >= 450 complaints, found {complaint_count}"

        # Check action history is populated
        history_count = db_session.query(ActionHistory).count()
        assert history_count >= 450, "Every complaint must have at least one audit entry"


class TestDemoScenariosData:
    """Verifies that all 6 scripted demo scenarios are present and correctly configured in the database."""

    def test_scenario_1_strong_overlap(self, db_session):
        """Scenario 1: ABC Institute of Technology, Pune has strong overlap between PGRC and RB."""
        inst = db_session.query(Institution).filter(Institution.permanent_id == "1-1099238411").first()
        assert inst is not None, "Scenario 1 institution (1-1099238411) missing"
        assert "Pune" in inst.city

        case_a = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/PGRC/2026/00101").first()
        case_b = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/RB/2026/00204").first()
        assert case_a is not None, "Scenario 1 Case A missing"
        assert case_b is not None, "Scenario 1 Case B missing"
        assert case_a.institution_id == inst.id
        assert case_b.institution_id == inst.id

        # Verify case link
        link = db_session.query(CaseLink).filter(
            ((CaseLink.case_a_id == case_a.id) & (CaseLink.case_b_id == case_b.id)) |
            ((CaseLink.case_a_id == case_b.id) & (CaseLink.case_b_id == case_a.id))
        ).first()
        assert link is not None, "Scenario 1 CaseLink missing"
        assert link.similarity_score >= 0.85, f"Expected score >= 0.85, got {link.similarity_score}"
        assert link.status == "suggested"
        assert link.suggested_lead_bureau.code == "RB"

    def test_scenario_2_false_match_avoidance(self, db_session):
        """Scenario 2: National College of Engineering in Jaipur and Raipur must be distinct."""
        jaipur = db_session.query(Institution).filter(Institution.permanent_id == "1-1099112233").first()
        raipur = db_session.query(Institution).filter(Institution.permanent_id == "1-1099445566").first()
        assert jaipur is not None and raipur is not None
        assert jaipur.city == "Jaipur" and raipur.city == "Raipur"
        assert jaipur.id != raipur.id

        # Check there is NO cross-institution link
        link = db_session.query(CaseLink).filter(
            CaseLink.institution_id.in_([jaipur.id, raipur.id])
        ).first()
        assert link is None, "False match link should not exist between Jaipur and Raipur institutions"

    def test_scenario_3_human_review_band(self, db_session):
        """Scenario 3: Complaint with ambiguous Bengaluru name flagged for human review."""
        c = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/PGRC/2026/00450").first()
        assert c is not None
        assert c.needs_institution_review is True
        assert 0.60 <= c.match_confidence < 0.85
        assert len(c.candidate_institutions) == 3

    def test_scenario_4_overdue_ready_for_escalation(self, db_session):
        """Scenario 4: High-priority complaint overdue by >7 days ready for auto-escalation."""
        c = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/RB/2026/00045").first()
        assert c is not None
        assert c.priority == "High"
        assert c.is_overdue is True
        assert c.is_escalated is False  # Ready to be triggered

    def test_scenario_6_risk_leaderboard_fixture(self, db_session):
        """Scenario 6: Sunrise Institute of Technology & Management has high risk score ~82."""
        inst = db_session.query(Institution).filter(Institution.permanent_id == "1-1099882233").first()
        assert inst is not None
        assert inst.risk_score >= 75.0, f"Expected High Risk Score >= 75, got {inst.risk_score}"

        complaints = db_session.query(Complaint).filter(Complaint.institution_id == inst.id).all()
        assert len(complaints) == 9, f"Expected 9 complaints for Sunrise Institute, found {len(complaints)}"
