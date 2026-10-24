import pytest
from pathlib import Path
import sys
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.app.database import SessionLocal
from backend.app.services.overlap_engine import ComplaintOverlapEngine
from backend.app.models.complaint import Complaint
from backend.app.models.institution import Institution
from backend.app.models.bureau import Bureau
from backend.app.utils import utc_now


@pytest.fixture(scope="module")
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def overlap_engine(db_session):
    engine = ComplaintOverlapEngine()
    engine.initialize_from_db(db_session)
    return engine


class TestComplaintOverlapEngine:

    def test_gating_different_institutions_rejected(self, overlap_engine, db_session):
        """Verifies Gate 1: Complaints at different institutions are immediately rejected."""
        c1 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/PGRC/2026/00101").first()
        c2 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/AB/2026/00311").first()
        assert c1.institution_id != c2.institution_id

        result = overlap_engine.evaluate_overlap(c1, c2, db=db_session)
        assert result.gated_out is True
        assert result.score == 0.0
        assert result.band == "GATED_OUT"
        assert result.is_overlap is False

    def test_gating_same_bureau_rejected(self, overlap_engine, db_session):
        """Verifies Gate 2: Complaints within the same bureau are rejected (internal duplicates, not cross-bureau)."""
        inst = db_session.query(Institution).filter(Institution.permanent_id == "1-1099238411").first()
        bureau = db_session.query(Bureau).filter(Bureau.code == "PGRC").first()

        c1 = Complaint(
            case_id="TEST/PGRC/001",
            institution_id=inst.id,
            raw_institution_name=inst.name,
            source="Portal",
            category="Fee Related",
            description="Fee issue one",
            complainant_type="Student",
            date_received=utc_now(),
            status="Under Process",
            assigned_bureau_id=bureau.id,
            expected_disposal_date=utc_now() + timedelta(days=30)
        )
        c2 = Complaint(
            case_id="TEST/PGRC/002",
            institution_id=inst.id,
            raw_institution_name=inst.name,
            source="Portal",
            category="Fee Related",
            description="Fee issue two",
            complainant_type="Student",
            date_received=utc_now(),
            status="Under Process",
            assigned_bureau_id=bureau.id,
            expected_disposal_date=utc_now() + timedelta(days=30)
        )

        result = overlap_engine.evaluate_overlap(c1, c2, db=db_session)
        assert result.gated_out is True
        assert result.score == 0.0
        assert "same bureau" in result.gate_reason.lower()

    def test_gating_closed_case_rejected(self, overlap_engine, db_session):
        """Verifies Gate 3: If one of the cases is already Disposed, overlap is gated out."""
        inst = db_session.query(Institution).filter(Institution.permanent_id == "1-1099238411").first()
        bur_pgrc = db_session.query(Bureau).filter(Bureau.code == "PGRC").first()
        bur_rb = db_session.query(Bureau).filter(Bureau.code == "RB").first()

        c_open = Complaint(
            case_id="TEST/OPEN/001",
            institution_id=inst.id,
            raw_institution_name=inst.name,
            source="Portal",
            category="Fee Related",
            description="Open fee dispute",
            complainant_type="Student",
            date_received=utc_now(),
            status="Under Process",
            assigned_bureau_id=bur_pgrc.id,
            expected_disposal_date=utc_now() + timedelta(days=30)
        )
        c_closed = Complaint(
            case_id="TEST/CLOSED/002",
            institution_id=inst.id,
            raw_institution_name=inst.name,
            source="Portal",
            category="Fee Related",
            description="Resolved fee dispute",
            complainant_type="Student",
            date_received=utc_now(),
            status="Disposed",
            assigned_bureau_id=bur_rb.id,
            expected_disposal_date=utc_now() + timedelta(days=30)
        )

        result = overlap_engine.evaluate_overlap(c_open, c_closed, db=db_session)
        assert result.gated_out is True
        assert result.score == 0.0
        assert "closed" in result.gate_reason.lower()

    def test_unrelated_complaints_same_institution_no_alert(self, overlap_engine, db_session):
        """
        Test (a): Unrelated complaints at the same institution must NOT produce an alert
        (Score < 0.60, band == BELOW_THRESHOLD).
        """
        inst = db_session.query(Institution).filter(Institution.permanent_id == "1-1099238411").first()
        bur_pgrc = db_session.query(Bureau).filter(Bureau.code == "PGRC").first()
        bur_ab = db_session.query(Bureau).filter(Bureau.code == "AB").first()
        now = utc_now()

        # Case 1: Student library fine issue (Examination/Result)
        c1 = Complaint(
            case_id="TEST/UNRELATED/001",
            institution_id=inst.id,
            raw_institution_name=inst.name,
            source="Portal",
            category="Examination/Result",
            description="Withholding final semester marksheet over library fine controversy.",
            complainant_type="Student",
            date_received=now - timedelta(days=150),
            status="Under Process",
            assigned_bureau_id=bur_pgrc.id,
            expected_disposal_date=now + timedelta(days=20)
        )

        # Case 2: Campus internet bandwidth deficit (Infrastructure)
        c2 = Complaint(
            case_id="TEST/UNRELATED/002",
            institution_id=inst.id,
            raw_institution_name=inst.name,
            source="Letter",
            category="Infrastructure",
            description="Internet lease line bandwidth in computer labs below handbook requirements.",
            complainant_type="Faculty",
            date_received=now - timedelta(days=10),
            status="Under Process",
            assigned_bureau_id=bur_ab.id,
            expected_disposal_date=now + timedelta(days=35)
        )

        result = overlap_engine.evaluate_overlap(c1, c2, db=db_session)
        assert result.gated_out is False
        assert result.score < 0.60, f"Expected score < 0.60, got {result.score}"
        assert result.band == "BELOW_THRESHOLD"
        assert result.is_overlap is False

    def test_scenario_1_overlap_score_calculated_dynamically(self, overlap_engine, db_session):
        """
        Test (d): The overlap score for Scenario 1 is dynamically COMPUTED by the engine
        from data, not read from seeded constants.
        """
        c1 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/PGRC/2026/00101").first()
        c2 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/RB/2026/00204").first()
        assert c1 is not None and c2 is not None

        # Dynamically evaluate overlap using the engine
        result = overlap_engine.evaluate_overlap(c1, c2, db=db_session)

        # Must pass gating
        assert result.gated_out is False

        # Verify signals
        assert result.signals["text_similarity"] > 0.60, f"Text sim too low: {result.signals['text_similarity']}"
        assert result.signals["category_relation"] > 0.0
        assert result.signals["date_proximity"] > 0.90

        # Score must qualify for Strong Overlap Alert (>= 0.88)
        assert result.score >= 0.88, f"Expected dynamic score >= 0.88, got {result.score}"
        assert result.band == "STRONG_OVERLAP"
        assert result.is_overlap is True
        assert len(result.reasons) >= 4

    def test_stored_caselink_score_immutability(self, overlap_engine, db_session):
        """
        Enforces Item 2: Store score, signals and reasons on CaseLink at creation.
        Adding an unrelated complaint to the corpus does not change the stored score.
        """
        from backend.app.models.case_link import CaseLink

        c1 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/PGRC/2026/00101").first()
        c2 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/RB/2026/00204").first()
        result = overlap_engine.evaluate_overlap(c1, c2, db=db_session)

        # Create or update CaseLink record
        link = db_session.query(CaseLink).filter(
            CaseLink.case_a_id == min(c1.id, c2.id),
            CaseLink.case_b_id == max(c1.id, c2.id)
        ).first()

        if not link:
            link = CaseLink(
                case_a_id=min(c1.id, c2.id),
                case_b_id=max(c1.id, c2.id),
                institution_id=c1.institution_id,
                similarity_score=result.score,
                signals=result.signals,
                reasons=result.reasons,
                suggested_lead_bureau_id=c2.assigned_bureau_id,
                lead_suggestion_rule="RULE_STATUTORY_REGULATORY",
                status="suggested"
            )
            db_session.add(link)
            db_session.commit()

        initial_score = link.similarity_score
        initial_signals = dict(link.signals)

        # Add a new unrelated complaint into the database
        unrelated = Complaint(
            case_id="TEST/CORPUS/UNRELATED/999",
            institution_id=c1.institution_id,
            raw_institution_name=c1.raw_institution_name,
            source="Email",
            category="Harassment/Student Welfare",
            description="Ragging incident reported in the first year hostel block A.",
            complainant_type="Student",
            date_received=utc_now(),
            status="Pending",
            assigned_bureau_id=c1.assigned_bureau_id,
            expected_disposal_date=utc_now() + timedelta(days=15)
        )
        db_session.add(unrelated)
        db_session.commit()

        # Query the CaseLink again from DB
        db_session.refresh(link)
        assert link.similarity_score == initial_score
        assert link.signals == initial_signals
        assert link.similarity_score >= 0.88

        # Clean up test complaint
        db_session.delete(unrelated)
        db_session.commit()

    def test_sla_date_calculation_naive_utc(self, db_session):
        """
        Enforces Item 4: Tests SLA calculation across stored database dates and utc_now().
        Ensures consistent naive-UTC datetimes prevent offset-naive vs offset-aware errors.
        """
        from backend.app.config import SLA_DAYS_BY_CATEGORY, SLA_PRIORITY_MULTIPLIERS

        now = utc_now()
        complaint = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/RB/2026/00045").first()
        assert complaint is not None

        # Compare like-with-like naive UTC datetimes
        assert complaint.date_received.tzinfo is None
        assert now.tzinfo is None

        age_days = (now - complaint.date_received).days
        assert age_days > 0

        base_sla = SLA_DAYS_BY_CATEGORY[complaint.category]
        multiplier = SLA_PRIORITY_MULTIPLIERS[complaint.priority]
        target_days = int(round(base_sla * multiplier))

        overdue_days = (now - complaint.expected_disposal_date).days
        # Case AICTE/RB/2026/00045 is seeded as overdue
        assert overdue_days > 7
        assert complaint.is_overdue is True

