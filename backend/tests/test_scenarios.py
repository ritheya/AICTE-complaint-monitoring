import pytest
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.app.database import SessionLocal
from backend.app.models.complaint import Complaint
from backend.app.models.institution import Institution
from backend.app.services.resolution_engine import InstitutionResolutionEngine
from backend.app.services.overlap_engine import ComplaintOverlapEngine
from backend.app.services.lead_bureau_rules import LeadBureauEngine
from backend.app.services.risk_scorer import InstitutionalRiskScorer


@pytest.fixture(scope="module")
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def res_engine():
    return InstitutionResolutionEngine()


@pytest.fixture(scope="module")
def overlap_engine(db_session):
    engine = ComplaintOverlapEngine()
    engine.initialize_from_db(db_session)
    return engine


@pytest.fixture(scope="module")
def lead_engine():
    return LeadBureauEngine()


class TestAllSixDemoScenarios:

    def test_scenario_1_strong_overlap_engine_calculation(self, overlap_engine, lead_engine, db_session):
        """
        Scenario 1: Strong Overlap computed dynamically from actual records.
        PGRC (Fee) vs RB (Affiliation) at ABC Inst. of Tech, Pune.
        """
        c1 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/PGRC/2026/00101").first()
        c2 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/RB/2026/00204").first()
        assert c1 is not None and c2 is not None

        # Dynamically evaluate overlap
        result = overlap_engine.evaluate_overlap(c1, c2, db=db_session)
        assert result.gated_out is False
        assert result.score >= 0.88, f"Scenario 1 score expected >= 0.88, got {result.score}"
        assert result.band == "STRONG_OVERLAP"
        assert result.is_overlap is True

        # Dynamically evaluate lead bureau
        lead_rec = lead_engine.suggest_lead(c1, c2)
        assert lead_rec.lead_bureau_code == "RB"
        assert lead_rec.lead_bureau_id in {c1.assigned_bureau_id, c2.assigned_bureau_id}
        assert "RULE_STATUTORY_REGULATORY" in lead_rec.rule_id

    def test_scenario_1_date_sensitivity_decay(self, overlap_engine, db_session):
        """
        Scenario 1 Date Sensitivity: Verify graceful degradation as the date gap
        widens to 30 days (remains Strong Overlap) and 60 days (slides into Possible Overlap).
        """
        c1 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/PGRC/2026/00101").first()
        c2 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/RB/2026/00204").first()
        assert c1 is not None and c2 is not None

        s_text = overlap_engine.compute_text_similarity(c1.description, c2.description, db=db_session)
        s_cat, _ = overlap_engine.compute_category_score(c1.category, c2.category)

        # At 3 days (base)
        s_date_3 = max(0.0, 1.0 - (3.0 / 180.0))
        tot_3 = 0.50 * s_text + 0.30 * s_cat + 0.20 * s_date_3
        assert tot_3 >= 0.88, f"Expected 3-day score >= 0.88, got {tot_3}"

        # At 30 days
        s_date_30 = max(0.0, 1.0 - (30.0 / 180.0))
        tot_30 = 0.50 * s_text + 0.30 * s_cat + 0.20 * s_date_30
        assert tot_30 >= 0.85, f"Expected 30-day score >= 0.85 (STRONG_OVERLAP), got {tot_30}"

        # At 60 days
        s_date_60 = max(0.0, 1.0 - (60.0 / 180.0))
        tot_60 = 0.50 * s_text + 0.30 * s_cat + 0.20 * s_date_60
        assert 0.60 <= tot_60 < 0.85, f"Expected 60-day score in review band [0.60, 0.85), got {tot_60}"

    def test_scenario_1b_soft_overlap_review_band(self, overlap_engine, lead_engine, db_session):
        """
        Scenario 1b: Soft Overlap deliberately in the coordination review band (0.60 - 0.85).
        Same institution (Global Institute of Technology, Mumbai), different bureaus (PGRC vs AB),
        related issue (admission irregularity vs approval compliance), wording partly similar.
        """
        c1 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/PGRC/2026/00105").first()
        c2 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/AB/2026/00205").first()
        assert c1 is not None and c2 is not None

        result = overlap_engine.evaluate_overlap(c1, c2, db=db_session)
        assert result.gated_out is False
        assert 0.60 <= result.score < 0.85, f"Scenario 1b score expected in [0.60, 0.85), got {result.score}"
        assert result.band == "POSSIBLE_OVERLAP"
        assert result.is_overlap is True

        lead_rec = lead_engine.suggest_lead(c1, c2)
        assert lead_rec.lead_bureau_code == "AB"
        assert lead_rec.lead_bureau_id in {c1.assigned_bureau_id, c2.assigned_bureau_id}

    def test_scenario_1c_negative_case_unrelated_complaints(self, overlap_engine, db_session):
        """
        Scenario 1c: Negative case.
        Same institution (Imperial College of Engineering, Chennai), different bureaus (PGRC vs AB),
        both open, but entirely unrelated issues (hostel food vs lab machinery).
        Must produce NO alert (score < 0.60, band == BELOW_THRESHOLD, is_overlap == False).
        """
        c1 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/PGRC/2026/00109").first()
        c2 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/AB/2026/00209").first()
        assert c1 is not None and c2 is not None

        result = overlap_engine.evaluate_overlap(c1, c2, db=db_session)
        assert result.gated_out is False
        assert result.score < 0.60, f"Scenario 1c score expected < 0.60, got {result.score}"
        assert result.band == "BELOW_THRESHOLD"
        assert result.is_overlap is False

    def test_scenario_2_false_match_avoidance(self, res_engine, db_session):
        """
        Scenario 2: False match avoidance.
        Query 'National College of Engineering' with city 'Jaipur' vs 'Raipur'.
        """
        res_jaipur = res_engine.resolve(
            raw_name="National College of Engineering",
            city="Jaipur",
            state="Rajasthan",
            db=db_session
        )
        assert res_jaipur.best_institution.city == "Jaipur"
        assert res_jaipur.best_institution.permanent_id == "1-1099112233"

        res_raipur = res_engine.resolve(
            raw_name="National College of Engineering",
            city="Raipur",
            state="Chhattisgarh",
            db=db_session
        )
        assert res_raipur.best_institution.city == "Raipur"
        assert res_raipur.best_institution.permanent_id == "1-1099445566"
        assert res_jaipur.best_institution.id != res_raipur.best_institution.id

    def test_scenario_3_human_review_bengaluru(self, res_engine, db_session):
        """
        Scenario 3: Human review band.
        'Apex Academy' in Bengaluru produces 3 candidate matches in 0.65 - 0.75 review band.
        """
        res = res_engine.resolve(
            raw_name="Apex Academy",
            city="Bengaluru",
            state="Karnataka",
            db=db_session
        )
        assert res.needs_review is True
        assert res.status == "NEEDS_REVIEW"
        assert 0.65 <= res.confidence <= 0.75
        assert len(res.candidates) == 3

    def test_scenario_4_overdue_ready_for_escalation(self, db_session):
        """
        Scenario 4: High-priority complaint 23 days overdue (> 7 threshold) ready for live escalation.
        """
        c = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/RB/2026/00045").first()
        assert c is not None
        assert c.is_overdue is True
        assert c.is_escalated is False
        assert c.priority == "High"

    def test_scenario_5_live_intake_fixture(self, res_engine, overlap_engine, db_session):
        """
        Scenario 5: Live intake fixture.
        User pastes noisy text: 'Sir my college ABC Tech Pune is not returning caution money and charging extra exam fee without receipt'.
        1. Resolves to ABC Institute of Technology, Pune (1-1099238411)
        2. Detects live active overlap with existing case AICTE/RB/2026/00204 before saving!
        """
        noisy_text = "Sir, ABC Tech Pune college is illegally collecting Rs 25,000 caution money deposit and charging extra examination fees without receipt, refusing refund of caution money, and withholding my student hall ticket admit card."

        # 1. Resolve institution
        res = res_engine.resolve(
            raw_name="ABC Tech Pune",
            city="Pune",
            state="Maharashtra",
            db=db_session
        )
        assert res.best_institution is not None
        assert res.best_institution.permanent_id == "1-1099238411"
        assert res.confidence >= 0.85

        # 2. Check overlap with existing open cases at this institution
        inst_id = res.best_institution.id
        existing_cases = db_session.query(Complaint).filter(
            Complaint.institution_id == inst_id,
            Complaint.status.in_(["Pending", "Under Process"])
        ).all()
        assert len(existing_cases) >= 1

        # Simulate incoming complaint object
        target_rb_case = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/RB/2026/00204").first()
        incoming_temp = Complaint(
            case_id="TEMP/INTAKE/001",
            institution_id=inst_id,
            raw_institution_name="ABC Tech Pune",
            source="Portal",
            category="Fee Related",
            description=noisy_text,
            complainant_type="Student",
            date_received=target_rb_case.date_received,
            status="Pending",
            assigned_bureau_id=2  # PGRC
        )

        overlap_result = overlap_engine.evaluate_overlap(incoming_temp, target_rb_case, db=db_session)

        assert overlap_result.gated_out is False
        assert overlap_result.is_overlap is True
        assert overlap_result.score >= 0.88, f"Expected live pre-check score >= 0.88, got {overlap_result.score}"
        assert overlap_result.band == "STRONG_OVERLAP"

    def test_scenario_6_risk_score_dynamically_calculated(self, db_session):
        """
        Scenario 6: Institutional risk score dynamically calculated by InstitutionalRiskScorer
        from database records rather than reading static values.
        """
        inst = db_session.query(Institution).filter(Institution.permanent_id == "1-1099882233").first()
        assert inst is not None

        computed_score, breakdown = InstitutionalRiskScorer.calculate_risk(inst.id, db_session)

        # High risk threshold: >= 70.0
        assert computed_score >= 75.0, f"Expected risk score >= 75, got {computed_score}"
        assert breakdown["band"] == "High Risk"
        assert breakdown["components"]["complaint_volume"]["count"] == 9
        assert breakdown["components"]["pending_ratio"]["open_count"] == 7
        assert breakdown["components"]["severity_penalty"]["critical_count"] == 2
        assert len(breakdown["components"]["repeat_categories"]["repeat_categories_list"]) >= 2
        assert breakdown["components"]["unresolved_overlaps"]["count"] == 2
