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

    def test_all_seeded_caselinks_integrity_scan(self):
        """
        Enforces Item (c): Scans every CaseLink in the seeded database and asserts:
        1. The two cases are in different bureaus.
        2. The suggested lead is one of those two bureaus.
        3. signals is non-empty and contains expected component keys.
        4. Stored score equals what the engine recomputes within small tolerance (< 0.005).
        """
        from backend.app.services.overlap_engine import ComplaintOverlapEngine

        db = SessionLocal()
        try:
            overlap_engine = ComplaintOverlapEngine()
            overlap_engine.initialize_from_db(db)

            links = db.query(CaseLink).all()
            assert len(links) > 0, "Database must have seeded CaseLinks"

            for link in links:
                ca = link.case_a
                cb = link.case_b
                assert ca is not None and cb is not None, f"Link {link.id} has missing complaint"

                # 1. Different bureaus
                assert ca.assigned_bureau_id != cb.assigned_bureau_id, (
                    f"Link {link.id} pairs two cases in the same bureau: {ca.case_id} vs {cb.case_id}"
                )

                # 2. Suggested lead is one of the two involved bureaus
                involved_bureaus = {ca.assigned_bureau_id, cb.assigned_bureau_id}
                assert link.suggested_lead_bureau_id in involved_bureaus, (
                    f"Link {link.id} suggested lead {link.suggested_lead_bureau_id} not in involved bureaus {involved_bureaus}"
                )

                # 3. signals is non-empty
                assert bool(link.signals) is True, f"Link {link.id} has empty signals"
                assert "text_similarity" in link.signals
                assert "category_relation" in link.signals
                assert "date_proximity" in link.signals

                # 4. Stored score equals engine recomputed score within small tolerance
                recomputed = overlap_engine.evaluate_overlap(ca, cb, db=db)
                assert abs(link.similarity_score - recomputed.score) < 0.005, (
                    f"Link {link.id} stored score {link.similarity_score} differs from recomputed {recomputed.score}"
                )
        finally:
            db.close()

    def test_overlap_decision_comprehensive_behaviour(self, headers):
        """
        Enforces Item (e): Confirms complete overlap decision behaviour:
        1. Both cases get exactly one history entry per decision.
        2. Repeat decision does not add duplicate history entries.
        3. A non-party bureau gets 403.
        4. Rejection requires remarks (400 if empty).
        5. needs_discussion creates an alert for the other bureau.
        """
        db = SessionLocal()
        try:
            # Pick a suggested link (e.g. Scenario 1)
            link = db.query(CaseLink).filter(CaseLink.status == "suggested").first()
            assert link is not None, "A suggested CaseLink must exist"
            link_id = link.id
            ca_id = link.case_a_id
            cb_id = link.case_b_id
            ca_bureau = link.case_a.assigned_bureau.code
            cb_bureau = link.case_b.assigned_bureau.code
        finally:
            db.close()

        # Determine party personas vs non-party persona
        party_bureau_roles = []
        if ca_bureau == "PGRC" or cb_bureau == "PGRC":
            party_bureau_roles.append("pgrc_officer")
        if ca_bureau == "RB" or cb_bureau == "RB":
            party_bureau_roles.append("rb_officer")
        if ca_bureau == "AB" or cb_bureau == "AB":
            party_bureau_roles.append("ab_officer")

        acting_party_role = party_bureau_roles[0]
        # Choose non-party officer
        non_party_role = "ab_officer" if "ab_officer" not in party_bureau_roles else "pgrc_officer"

        # --- A. Non-party bureau gets 403 ---
        res_403 = client.post(
            f"/overlaps/{link_id}/decision",
            json={"decision": "needs_discussion", "remarks": "Unauthorized decision attempt"},
            headers=headers(non_party_role)
        )
        assert res_403.status_code == 403, f"Expected 403 for non-party bureau, got {res_403.status_code}"

        # --- B. Rejection requires remarks (400 if empty) ---
        res_reject_no_remarks = client.post(
            f"/overlaps/{link_id}/decision",
            json={"decision": "rejected", "remarks": ""},
            headers=headers(acting_party_role)
        )
        assert res_reject_no_remarks.status_code == 400, "Rejection without remarks must return 400"
        assert "remarks" in res_reject_no_remarks.json()["detail"].lower()

        # --- C. Valid decision: both cases get exactly one history entry ---
        db = SessionLocal()
        hist_a_before = db.query(ActionHistory).filter(ActionHistory.complaint_id == ca_id).count()
        hist_b_before = db.query(ActionHistory).filter(ActionHistory.complaint_id == cb_id).count()
        db.close()

        # Decision: needs_discussion
        res_disc = client.post(
            f"/overlaps/{link_id}/decision",
            json={"decision": "needs_discussion", "remarks": "Let us coordinate on fee refund policy."},
            headers=headers(acting_party_role)
        )
        assert res_disc.status_code == 200
        assert res_disc.json()["status"] == "needs_discussion"

        db = SessionLocal()
        try:
            hist_a_after = db.query(ActionHistory).filter(ActionHistory.complaint_id == ca_id).count()
            hist_b_after = db.query(ActionHistory).filter(ActionHistory.complaint_id == cb_id).count()
            assert hist_a_after == hist_a_before + 1, "Case A must get exactly one new ActionHistory entry"
            assert hist_b_after == hist_b_before + 1, "Case B must get exactly one new ActionHistory entry"

            # --- D. needs_discussion creates an alert for the other bureau ---
            created_alert = db.query(Alert).filter(
                Alert.type == "overlap",
                Alert.complaint_id == ca_id
            ).order_by(Alert.id.desc()).first()
            assert created_alert is not None, "needs_discussion must create an alert"
            link_db = db.query(CaseLink).filter(CaseLink.id == link_id).first()
            assert created_alert.target_bureau_id in [link_db.case_a.assigned_bureau_id, link_db.case_b.assigned_bureau_id]

            # --- E. Repeat decision does not add duplicates ---
            res_repeat = client.post(
                f"/overlaps/{link_id}/decision",
                json={"decision": "needs_discussion", "remarks": "Duplicate repeat request"},
                headers=headers(acting_party_role)
            )
            assert res_repeat.status_code == 200

            hist_a_repeat = db.query(ActionHistory).filter(ActionHistory.complaint_id == ca_id).count()
            hist_b_repeat = db.query(ActionHistory).filter(ActionHistory.complaint_id == cb_id).count()
            assert hist_a_repeat == hist_a_after, "Repeat decision must NOT add duplicate history to Case A"
            assert hist_b_repeat == hist_b_after, "Repeat decision must NOT add duplicate history to Case B"
        finally:
            db.close()



class TestAlertsEndpoints:
    """Validates /alerts listing, bureau scoping, and acknowledgement."""

    def test_list_alerts_and_scoping(self, headers):
        # Senior management sees all alerts
        res_mgmt = client.get("/alerts", headers=headers("senior_mgmt"))
        assert res_mgmt.status_code == 200
        data_mgmt = res_mgmt.json()
        assert data_mgmt["total"] >= 1
        assert len(data_mgmt["items"]) >= 1

        # PGRC officer sees bureau-targeted alerts or global alerts
        res_pgrc = client.get("/alerts", headers=headers("pgrc_officer"))
        assert res_pgrc.status_code == 200
        data_pgrc = res_pgrc.json()
        assert data_pgrc["total"] >= 1
        for alert in data_pgrc["items"]:
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
        from backend.app.config import ENABLE_BACKGROUND_SLA_JOB
        res = client.get("/scheduler/status", headers=headers("senior_mgmt"))
        assert res.status_code == 200
        data = res.json()
        assert data["background_job_enabled"] is ENABLE_BACKGROUND_SLA_JOB
        assert data["scheduler_running"] is ENABLE_BACKGROUND_SLA_JOB
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
        assert "escalated_case_ids" in data1
        assert "AICTE/TEST/2026/99999" in data1["escalated_case_ids"]

        # Verify case was dynamically flagged overdue and escalated
        db = SessionLocal()
        try:
            updated_case = db.query(Complaint).filter(Complaint.id == case_id_val).first()
            assert updated_case.is_overdue is True
            assert updated_case.is_escalated is True
            assert updated_case.status == "Escalated"
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
        data2 = res2.json()
        assert data2["newly_escalated_complaints"] == 0
        assert data2["escalated_case_ids"] == []

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
        assert "under_process_complaints" in data
        assert "escalated_complaints" in data
        assert "transferred_complaints" in data
        assert "disposed_complaints" in data
        assert "overdue_complaints" in data
        assert "active_overlaps" in data
        assert "high_risk_institutions" in data
        sum_statuses = (
            data["pending_complaints"] +
            data["under_process_complaints"] +
            data["escalated_complaints"] +
            data["transferred_complaints"] +
            data["disposed_complaints"]
        )
        assert sum_statuses == data["total_complaints"], f"Status counts sum ({sum_statuses}) != total ({data['total_complaints']})"

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
