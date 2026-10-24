import pytest
from pathlib import Path
import sys
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.app.services.lead_bureau_rules import LeadBureauEngine
from backend.app.models.complaint import Complaint
from backend.app.models.bureau import Bureau
from backend.app.utils import utc_now


@pytest.fixture
def lead_engine():
    return LeadBureauEngine()


class TestLeadBureauRules:

    def test_recommended_lead_must_be_one_of_the_two_involved_bureaus(self, lead_engine):
        """
        Critical constraint: The recommended lead bureau must strictly belong to
        {complaint_a.assigned_bureau_id, complaint_b.assigned_bureau_id}.
        """
        bur_pgrc = Bureau(id=2, code="PGRC", name="PGRC", description="")
        bur_ab = Bureau(id=3, code="AB", name="Approval Bureau", description="")

        c_a = Complaint(
            id=10, case_id="C_PGRC", category="Fee Related",
            assigned_bureau_id=bur_pgrc.id, assigned_bureau=bur_pgrc,
            date_received=utc_now() - timedelta(days=20)
        )
        c_b = Complaint(
            id=11, case_id="C_AB", category="Infrastructure",
            assigned_bureau_id=bur_ab.id, assigned_bureau=bur_ab,
            date_received=utc_now() - timedelta(days=10)
        )

        rec = lead_engine.suggest_lead(c_a, c_b)
        assert rec.lead_bureau_id in {c_a.assigned_bureau_id, c_b.assigned_bureau_id}
        assert rec.lead_bureau_code in {"PGRC", "AB"}

    def test_regulatory_takes_precedence_when_rb_involved(self, lead_engine):
        """When an affiliation/compliance issue exists and RB is involved, RB leads."""
        bur_rb = Bureau(id=1, code="RB", name="Regulation Bureau", description="")
        bur_pgrc = Bureau(id=2, code="PGRC", name="PGRC", description="")

        c_pgrc = Complaint(
            id=101, case_id="PGRC_1", category="Fee Related",
            assigned_bureau_id=bur_pgrc.id, assigned_bureau=bur_pgrc,
            date_received=utc_now() - timedelta(days=30)
        )
        c_rb = Complaint(
            id=102, case_id="RB_1", category="Approval/Affiliation Compliance",
            assigned_bureau_id=bur_rb.id, assigned_bureau=bur_rb,
            date_received=utc_now() - timedelta(days=15)
        )

        rec = lead_engine.suggest_lead(c_pgrc, c_rb)
        assert rec.lead_bureau_code == "RB"
        assert rec.lead_bureau_id == bur_rb.id
        assert "RULE_STATUTORY_REGULATORY" in rec.rule_id

    def test_infrastructure_takes_precedence_when_ab_involved(self, lead_engine):
        """When an infrastructure issue is paired with individual grievance and AB is involved, AB leads."""
        bur_ab = Bureau(id=3, code="AB", name="Approval Bureau", description="")
        bur_pgrc = Bureau(id=2, code="PGRC", name="PGRC", description="")

        c_ab = Complaint(
            id=201, case_id="AB_1", category="Infrastructure",
            assigned_bureau_id=bur_ab.id, assigned_bureau=bur_ab,
            date_received=utc_now() - timedelta(days=10)
        )
        c_pgrc = Complaint(
            id=202, case_id="PGRC_2", category="Examination/Result",
            assigned_bureau_id=bur_pgrc.id, assigned_bureau=bur_pgrc,
            date_received=utc_now() - timedelta(days=12)
        )

        rec = lead_engine.suggest_lead(c_ab, c_pgrc)
        assert rec.lead_bureau_code == "AB"
        assert rec.lead_bureau_id == bur_ab.id
        assert "RULE_INFRASTRUCTURE_APPROVAL" in rec.rule_id

    def test_default_joint_review_earliest_anchor(self, lead_engine):
        """When multiple issues of same tier collide, earliest case bureau anchors with joint review."""
        bur_ab = Bureau(id=3, code="AB", name="Approval Bureau", description="")
        bur_afb = Bureau(id=4, code="AFB", name="Affiliation Bureau", description="")
        now = utc_now()

        c_earlier = Complaint(
            id=301, case_id="AB_EARLY", category="Other",
            assigned_bureau_id=bur_ab.id, assigned_bureau=bur_ab,
            date_received=now - timedelta(days=40)
        )
        c_later = Complaint(
            id=302, case_id="AFB_LATE", category="Other",
            assigned_bureau_id=bur_afb.id, assigned_bureau=bur_afb,
            date_received=now - timedelta(days=10)
        )

        rec = lead_engine.suggest_lead(c_earlier, c_later)
        assert rec.lead_bureau_code == "AB"
        assert rec.lead_bureau_id == bur_ab.id
        assert rec.is_joint_review_recommended is True
