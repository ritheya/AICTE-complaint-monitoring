"""
Step 3 (b) API Test Suite:
Covers /institutions, /overlaps, /alerts, /scheduler, and /dashboard routers.
Validates dynamic leaderboard, RBAC permissions, inter-bureau coordination,
idempotent SLA auto-escalation without hardcoded IDs, and analytical aggregations.
"""
from datetime import timedelta
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models.complaint import Complaint
from backend.app.models.institution import Institution
from backend.app.models.case_link import CaseLink
from backend.app.models.alert import Alert
from backend.app.models.action_history import ActionHistory
from backend.app.utils import utc_now

client = TestClient(app)


@pytest.fixture(scope="module")
def auth_tokens():
    """Generates bearer access tokens for various officer test personas."""
    personas = {
        "admin": ("admin@aicte.gov.in", "Demo@123"),
        "senior_mgmt": ("senior.mgmt@aicte.gov.in", "Demo@123"),
        "rb_officer": ("rb.officer@aicte.gov.in", "Demo@123"),
        "pgrc_officer": ("pgrc.officer@aicte.gov.in", "Demo@123"),
        "ab_officer": ("ab.officer@aicte.gov.in", "Demo@123"),
        "regional_officer": ("ro.west@aicte.gov.in", "Demo@123")
    }
    tokens = {}
    for key, (email, pw) in personas.items():
        res = client.post("/auth/login", json={"email": email, "password": pw})
        assert res.status_code == 200, f"Login failed for persona {key}: {res.text}"
        tokens[key] = res.json()["access_token"]
    return tokens


@pytest.fixture
def headers(auth_tokens):
    """Returns authorization headers for a given persona."""
    def _headers(role="pgrc_officer"):
        return {"Authorization": f"Bearer {auth_tokens[role]}"}
    return _headers


class TestInstitutionsEndpoints:
    """Validates /institutions endpoints, dynamic risk leaderboard, and scoping."""

    def test_list_institutions_and_search(self, headers):
        res = client.get("/institutions?search=ABC&limit=10", headers=headers("pgrc_officer"))
        assert res.status_code == 200
        data = res.json()
        assert len(data) >= 1
        assert any("ABC" in inst["name"] for inst in data)

    def test_institution_detail_and_dynamic_risk(self, headers):
        res = client.get("/institutions?search=1-1099882233", headers=headers("senior_mgmt"))
        assert res.status_code == 200
        inst_list = res.json()
        assert len(inst_list) == 1
        inst_id = inst_list[0]["id"]

        detail_res = client.get(f"/institutions/{inst_id}", headers=headers("senior_mgmt"))
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert detail["permanent_id"] == "1-1099882233"
        assert detail["risk_score"] >= 75.0
        assert "components" in detail["risk_breakdown"]
        assert detail["risk_breakdown"]["band"] == "High Risk"

    def test_risk_leaderboard_ranked_dynamically_from_db(self, headers):
        """
        Scenario 6 Verification: Leaderboard ranks institutions dynamically strictly from
        database records using 5-component InstitutionalRiskScorer.
        """
        res = client.get("/institutions/leaderboard/risk?limit=10", headers=headers("senior_mgmt"))
        assert res.status_code == 200
        board = res.json()
        assert len(board) >= 5

        # Check descending order of computed scores
        scores = [item["risk_score"] for item in board]
        assert scores == sorted(scores, reverse=True), "Leaderboard must be strictly sorted by computed risk score descending"

        # Top institution must be Sunrise Institute (1-1099882233)
        top = board[0]
        assert top["permanent_id"] == "1-1099882233"
        assert top["risk_score"] >= 75.0
        assert top["risk_band"] == "High Risk"
        assert top["rank"] == 1

    def test_institution_summary_grounded_in_grievance_history(self, headers):
        db = SessionLocal()
        try:
            inst = db.query(Institution).filter(Institution.permanent_id == "1-1099882233").first()
            assert inst is not None
            inst_id = inst.id
        finally:
            db.close()

        res = client.get(f"/institutions/{inst_id}/summary", headers=headers("senior_mgmt"))
        assert res.status_code == 200
        data = res.json()
        assert data["institution_id"] == inst_id
        assert data["source"] == "template_fallback"
        assert "1-1099882233" in data["summary_text"]
        assert "High Risk" in data["summary_text"]

    def test_regional_officer_institution_scope_protection(self, headers):
        """Regional officer (Western) cannot view institutions outside Western region."""
        db = SessionLocal()
        try:
            northern_inst = db.query(Institution).filter(Institution.region == "North").first()
            assert northern_inst is not None
            inst_id = northern_inst.id
        finally:
            db.close()

        res = client.get(f"/institutions/{inst_id}", headers=headers("regional_officer"))
        assert res.status_code == 403
        assert "outside officer jurisdiction" in res.json()["detail"].lower()


class TestOverlapsEndpoints:
    """Validates /overlaps listing, retrieval, and decision workflow with dual audit logging."""

    def test_list_overlaps_and_filtering(self, headers):
        res = client.get("/overlaps?status=suggested", headers=headers("senior_mgmt"))
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        for link in data:
            assert link["status"] == "suggested"
            assert "similarity_score" in link

    def test_overlap_detail_view(self, headers):
        db = SessionLocal()
        try:
            link = db.query(CaseLink).first()
            assert link is not None
            link_id = link.id
        finally:
            db.close()

        res = client.get(f"/overlaps/{link_id}", headers=headers("senior_mgmt"))
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == link_id
        assert "signals" in data
        assert "reasons" in data

    def test_overlap_decision_workflow_and_dual_audit_trail(self, headers):
        """
        Tests approving an overlap:
        - Updates status to 'approved'
        - Sets final lead bureau
        - Appends ActionHistory on BOTH case_a and case_b
        """
        db = SessionLocal()
        try:
            link = db.query(CaseLink).filter(CaseLink.status == "suggested").first()
            assert link is not None
            link_id = link.id
            case_a_id = link.case_a_id
            case_b_id = link.case_b_id
            suggested_lead = link.suggested_lead_bureau_id
        finally:
            db.close()

        payload = {
            "decision": "approved",
            "final_lead_bureau_id": suggested_lead,
            "remarks": "Senior Management coordinated approval: Joint inspection warranted under designated lead bureau."
        }
        res = client.post(f"/overlaps/{link_id}/decision", json=payload, headers=headers("senior_mgmt"))
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "approved"
        assert data["final_lead_bureau_id"] == suggested_lead

        # Verify dual audit trail in database
        db = SessionLocal()
        try:
            hist_a = db.query(ActionHistory).filter(
                ActionHistory.complaint_id == case_a_id,
                ActionHistory.action_type == "OVERLAP_DECISION"
            ).order_by(ActionHistory.id.desc()).first()
            assert hist_a is not None
            assert "approved" in hist_a.remarks

            hist_b = db.query(ActionHistory).filter(
                ActionHistory.complaint_id == case_b_id,
                ActionHistory.action_type == "OVERLAP_DECISION"
            ).order_by(ActionHistory.id.desc()).first()
            assert hist_b is not None
            assert "approved" in hist_b.remarks

            # Restore original link status and clean up test action histories
            link_restore = db.query(CaseLink).filter(CaseLink.id == link_id).first()
            if link_restore:
                link_restore.status = "suggested"
                link_restore.final_lead_bureau_id = None
                link_restore.decided_by_id = None
                link_restore.decided_at = None
                link_restore.decision_remarks = None
            if hist_a:
                db.delete(hist_a)
            if hist_b:
                db.delete(hist_b)
            db.commit()
        finally:
            db.close()


class TestAlertsEndpoints:
    """Validates /alerts listing, bureau scoping, and acknowledgement."""

    def test_list_alerts_and_scoping(self, headers):
        # Senior management sees all alerts
        res_mgmt = client.get("/alerts", headers=headers("senior_mgmt"))
        assert res_mgmt.status_code == 200
        assert len(res_mgmt.json()) >= 1

        # PGRC officer sees bureau-targeted alerts or global alerts
        res_pgrc = client.get("/alerts", headers=headers("pgrc_officer"))
        assert res_pgrc.status_code == 200
        for alert in res_pgrc.json():
            assert alert["target_bureau_id"] in [None, 2]

    def test_mark_alert_read(self, headers):
        db = SessionLocal()
        try:
            alert = db.query(Alert).filter(
                Alert.is_read.is_(False),
                (Alert.target_bureau_id == 2) | (Alert.target_bureau_id.is_(None))
            ).first()
            if not alert:
                alert = Alert(
                    type="sla_due_soon",
                    message="Test SLA due soon notice",
                    severity="warning",
                    target_bureau_id=2,
                    is_read=False,
                    created_at=utc_now()
                )
                db.add(alert)
                db.commit()
                db.refresh(alert)
            alert_id = alert.id
        finally:
            db.close()

        res = client.patch(f"/alerts/{alert_id}/read", headers=headers("pgrc_officer"))
        assert res.status_code == 200
        assert res.json()["is_read"] is True


class TestSchedulerAndSlaCheck:
    """
    Validates on-demand SLA evaluation, dynamic overdue detection,
    and automatic escalation with strict idempotency and role restriction.
    """

    def test_scheduler_status(self, headers):
        res = client.get("/scheduler/status", headers=headers("senior_mgmt"))
        assert res.status_code == 200
        data = res.json()
        assert data["scheduler_running"] is True
        assert data["active_jobs_count"] >= 1
        assert any(job["id"] == "sla_daily_monitoring_job" for job in data["jobs"])

    def test_sla_check_role_restriction(self, headers):
        """Regular bureau officers cannot trigger manual SLA check."""
        res = client.post("/scheduler/run-sla-check", headers=headers("pgrc_officer"))
        assert res.status_code == 403

    def test_sla_check_dynamic_evaluation_and_idempotent_auto_escalation(self, headers):
        """
        Creates a brand-new complaint that is well past statutory SLA target,
        runs POST /scheduler/run-sla-check, and verifies:
        1. It dynamically flags the case overdue without hardcoded IDs.
        2. It auto-escalates past threshold to Senior Management.
        3. Creates ActionHistory and Alert entries.
        4. Running a second time is 100% idempotent (zero duplicates).
        """
        now = utc_now()
        db = SessionLocal()
        try:
            # Clean up any previous test artifacts for complete repeatability
            prev = db.query(Complaint).filter(Complaint.case_id == "AICTE/TEST/2026/99999").first()
            if prev:
                db.query(Alert).filter(Alert.complaint_id == prev.id).delete()
                db.query(ActionHistory).filter(ActionHistory.complaint_id == prev.id).delete()
                db.delete(prev)
                db.commit()

            inst = db.query(Institution).first()
            # Create a high-priority complaint received 65 days ago (Faculty Shortage base 45d * 0.7 = 32d SLA)
            new_overdue_case = Complaint(
                case_id="AICTE/TEST/2026/99999",
                institution_id=inst.id,
                raw_institution_name=inst.name,
                source="Portal",
                category="Faculty Shortage",
                description="Test complaint for dynamic SLA evaluation and statutory escalation.",
                complainant_type="Faculty",
                date_received=now - timedelta(days=65),
                status="Pending",
                assigned_bureau_id=1,  # RB
                priority="High",
                is_overdue=False,
                is_escalated=False,
                expected_disposal_date=now - timedelta(days=33),
                last_action="Initial filing received",
                next_action="Scrutiny pending",
                last_action_date=now - timedelta(days=65)
            )
            db.add(new_overdue_case)
            db.commit()
            db.refresh(new_overdue_case)
            case_id_val = new_overdue_case.id
        finally:
            db.close()

        # Run 1: Trigger SLA check via API
        res1 = client.post("/scheduler/run-sla-check", headers=headers("senior_mgmt"))
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["status"] == "success"
        assert data1["overdue_complaints"] >= 1

        # Verify case was dynamically flagged overdue and escalated
        db = SessionLocal()
        try:
            updated_case = db.query(Complaint).filter(Complaint.id == case_id_val).first()
            assert updated_case.is_overdue is True
            assert updated_case.is_escalated is True
            assert "Auto-Escalated" in updated_case.last_action

            # Count action histories and alerts
            hist_count_run1 = db.query(ActionHistory).filter(
                ActionHistory.complaint_id == case_id_val,
                ActionHistory.action_type == "AUTO_ESCALATION"
            ).count()
            assert hist_count_run1 == 1

            alert_count_run1 = db.query(Alert).filter(
                Alert.complaint_id == case_id_val,
                Alert.type == "escalation"
            ).count()
            assert alert_count_run1 == 1
        finally:
            db.close()

        # Run 2: Re-run immediately to verify strict idempotency
        res2 = client.post("/scheduler/run-sla-check", headers=headers("senior_mgmt"))
        assert res2.status_code == 200

        db = SessionLocal()
        try:
            hist_count_run2 = db.query(ActionHistory).filter(
                ActionHistory.complaint_id == case_id_val,
                ActionHistory.action_type == "AUTO_ESCALATION"
            ).count()
            assert hist_count_run2 == 1, "Scheduler must be idempotent: duplicate auto-escalation histories created!"

            alert_count_run2 = db.query(Alert).filter(
                Alert.complaint_id == case_id_val,
                Alert.type == "escalation"
            ).count()
            assert alert_count_run2 == 1, "Scheduler must be idempotent: duplicate escalation alerts created!"

            # Reset Scenario 4 demo case so it remains in ready state
            sc4 = db.query(Complaint).filter(Complaint.case_id == "AICTE/RB/2026/00045").first()
            if sc4:
                sc4.is_escalated = False
                sc4.last_action = "Under Process at Regulatory Bureau"
                db.query(Alert).filter(Alert.complaint_id == sc4.id, Alert.type == "escalation").delete()
                db.query(ActionHistory).filter(ActionHistory.complaint_id == sc4.id, ActionHistory.action_type == "AUTO_ESCALATION").delete()

            # Clean up the test complaint
            prev = db.query(Complaint).filter(Complaint.case_id == "AICTE/TEST/2026/99999").first()
            if prev:
                db.query(Alert).filter(Alert.complaint_id == prev.id).delete()
                db.query(ActionHistory).filter(ActionHistory.complaint_id == prev.id).delete()
                db.delete(prev)
            db.commit()
        finally:
            db.close()


class TestDashboardEndpoints:
    """Validates /dashboard summary, workload, regional, category, ageing, and trend endpoints."""

    def test_dashboard_summary(self, headers):
        res = client.get("/dashboard/summary", headers=headers("senior_mgmt"))
        assert res.status_code == 200
        data = res.json()
        assert "total_complaints" in data
        assert "pending_complaints" in data
        assert "active_overlaps" in data
        assert "high_risk_institutions" in data
        assert data["total_complaints"] >= 1

    def test_bureau_workload(self, headers):
        res = client.get("/dashboard/bureau-workload", headers=headers("senior_mgmt"))
        assert res.status_code == 200
        data = res.json()
        assert len(data) >= 4
        codes = [item["bureau_code"] for item in data]
        assert "RB" in codes and "PGRC" in codes and "AB" in codes and "AFB" in codes

    def test_region_wise_metrics(self, headers):
        res = client.get("/dashboard/region-wise", headers=headers("senior_mgmt"))
        assert res.status_code == 200
        data = res.json()
        assert len(data) >= 5
        assert any(item["region"] == "West" for item in data)

    def test_category_wise_metrics(self, headers):
        res = client.get("/dashboard/category-wise", headers=headers("senior_mgmt"))
        assert res.status_code == 200
        data = res.json()
        assert len(data) >= 3
        # Check percentage sums close to 100
        pct_sum = sum(item["percentage"] for item in data)
        assert 95.0 <= pct_sum <= 105.0

    def test_ageing_distribution(self, headers):
        res = client.get("/dashboard/ageing", headers=headers("senior_mgmt"))
        assert res.status_code == 200
        data = res.json()
        brackets = [item["bracket"] for item in data]
        assert "< 15 days" in brackets
        assert "> 60 days" in brackets

    def test_monthly_trend(self, headers):
        res = client.get("/dashboard/monthly-trend", headers=headers("senior_mgmt"))
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 6
        assert "month" in data[0]
        assert "received" in data[0]
        assert "disposed" in data[0]
