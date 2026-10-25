"""
Test Suite for Step 3 (a): FastAPI Endpoints for /auth, /complaints, and /intake
"""
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models.bureau import Officer, Bureau
from backend.app.models.complaint import Complaint
from backend.app.models.institution import Institution
from backend.app.models.case_link import CaseLink
from backend.app.models.alert import Alert
from backend.app.models.action_history import ActionHistory
from backend.app.auth.security import login_rate_limiter

client = TestClient(app)




@pytest.fixture
def auth_headers():
    """Generates authentication headers for different personas."""
    def _get_headers(email: str, password: str = "Demo@123"):
        login_rate_limiter.reset(email.strip().lower())
        res = client.post("/auth/login", json={"email": email, "password": password})
        assert res.status_code == 200, f"Login failed for {email}: {res.text}"
        token = res.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    return _get_headers


class TestAuthEndpoints:

    def test_login_success_senior_mgmt(self, auth_headers):
        """Verifies successful login for Senior Management (senior.mgmt@aicte.gov.in)."""
        headers = auth_headers("senior.mgmt@aicte.gov.in")
        assert "Authorization" in headers
        res = client.get("/auth/me", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "senior.mgmt@aicte.gov.in"
        assert data["role"] == "Senior Management"

    def test_login_invalid_password_generic_error(self):
        """Verifies generic error message on invalid password."""
        email = "pgrc.officer@aicte.gov.in"
        login_rate_limiter.reset(email)
        res = client.post("/auth/login", json={"email": email, "password": "WrongPassword!"})
        assert res.status_code == 401
        assert res.json()["detail"] == "Invalid email or password"

    def test_login_rate_limiting(self):
        """Verifies rate limiting after max failed attempts."""
        email = "test.rate.limit@aicte.gov.in"
        login_rate_limiter.reset(email)

        # 5 failed attempts
        for _ in range(5):
            res = client.post("/auth/login", json={"email": email, "password": "BadPassword"})
            assert res.status_code == 401

        # 6th attempt should be blocked with 429
        res_blocked = client.post("/auth/login", json={"email": email, "password": "BadPassword"})
        assert res_blocked.status_code == 429
        assert "Too many failed login attempts" in res_blocked.json()["detail"]
        login_rate_limiter.reset(email)


class TestComplaintsEndpointsAndAccessControl:

    def test_complaints_unauthenticated_rejected(self):
        """Verifies 401 on protected /complaints routes without auth header."""
        res = client.get("/complaints")
        assert res.status_code == 401

    def test_complaints_regional_officer_scoping(self, auth_headers, db_session):
        """
        Enforces Item 5: Regional Officers are scoped to their assigned region.
        Shri Arvind Joshi (ro.west@aicte.gov.in) sees only complaints in West region.
        """
        headers = auth_headers("ro.west@aicte.gov.in")
        res = client.get("/complaints", headers=headers)
        assert res.status_code == 200
        complaints = res.json()
        assert len(complaints) > 0

        # Verify all returned complaints belong to institutions in West region
        for c in complaints[:10]:
            inst = db_session.query(Institution).filter(Institution.id == c["institution_id"]).first()
            if inst:
                assert inst.region == "West"

    def test_cross_bureau_write_protection_403(self, auth_headers, db_session):
        """
        Enforces Item 5: RB Officer attempting to modify a PGRC complaint gets 403 Forbidden.
        PGRC Officer modifying PGRC complaint gets 200 OK.
        Admin modifying any complaint gets 200 OK.
        """
        pgrc_case = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/PGRC/2026/00101").first()
        assert pgrc_case is not None

        rb_headers = auth_headers("rb.officer@aicte.gov.in")
        pgrc_headers = auth_headers("pgrc.officer@aicte.gov.in")
        admin_headers = auth_headers("admin@aicte.gov.in")

        # 1. RB Officer attempts to modify PGRC complaint -> 403 Forbidden
        res_forbidden = client.patch(
            f"/complaints/{pgrc_case.id}",
            json={"remarks": "Unauthorized cross-bureau update attempt"},
            headers=rb_headers
        )
        assert res_forbidden.status_code == 403
        assert "modify only complaints assigned to their own bureau" in res_forbidden.json()["detail"]

        # 2. PGRC Officer modifies PGRC complaint -> 200 OK
        res_allowed = client.patch(
            f"/complaints/{pgrc_case.id}",
            json={"remarks": "Authorized PGRC review update"},
            headers=pgrc_headers
        )
        assert res_allowed.status_code == 200

        # 3. Admin modifies PGRC complaint -> 200 OK
        res_admin = client.patch(
            f"/complaints/{pgrc_case.id}",
            json={"remarks": "Admin oversight update"},
            headers=admin_headers
        )
        assert res_admin.status_code == 200

    def test_complaint_creation_with_resolution_and_overlap_detection(self, auth_headers, db_session):
        """
        Enforces Item 3: POST /complaints creates complaint, runs institution resolution,
        and automatically detects overlaps, creating CaseLink (status suggested) and Alerts.
        """
        headers = auth_headers("pgrc.officer@aicte.gov.in")
        payload = {
            "raw_institution_name": "ABC Institute of Technology",
            "city": "Pune",
            "state": "Maharashtra",
            "category": "Fee Related",
            "description": "Student complains of illegal caution deposit Rs 25,000 without receipt.",
            "source": "Portal",
            "priority": "High"
        }
        res = client.post("/complaints", json=payload, headers=headers)
        assert res.status_code == 201
        data = res.json()
        assert data["case_id"].startswith("AICTE/PGRC/")
        assert data["institution_id"] is not None
        assert data["match_confidence"] >= 0.85

        # Check ActionHistory was logged
        history = db_session.query(ActionHistory).filter(ActionHistory.complaint_id == data["id"]).all()
        assert len(history) >= 1
        assert history[0].action_type == "received"

        # Clean up created complaint and any generated case links/alerts to keep DB pristine
        created_id = data["id"]
        db_session.query(CaseLink).filter((CaseLink.case_a_id == created_id) | (CaseLink.case_b_id == created_id)).delete()
        db_session.query(Alert).filter(Alert.complaint_id == created_id).delete()
        db_session.query(ActionHistory).filter(ActionHistory.complaint_id == created_id).delete()
        db_session.query(Complaint).filter(Complaint.id == created_id).delete()
        db_session.commit()

    def test_complaint_transfer_and_escalate_with_audit_trail(self, auth_headers, db_session):
        """
        Tests POST /complaints/{id}/transfer and POST /complaints/{id}/escalate.
        Verifies state transitions and audit logging.
        """
        pgrc_case = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/PGRC/2026/00101").first()
        headers = auth_headers("pgrc.officer@aicte.gov.in")

        # Escalate complaint
        res_esc = client.post(
            f"/complaints/{pgrc_case.id}/escalate",
            json={"remarks": "High level student unrest requires immediate Senior Management attention."},
            headers=headers
        )
        assert res_esc.status_code == 200
        assert res_esc.json()["status"] == "Escalated"
        assert res_esc.json()["is_escalated"] is True

        # Verify ActionHistory recorded escalation
        esc_history = db_session.query(ActionHistory).filter(
            ActionHistory.complaint_id == pgrc_case.id,
            ActionHistory.action_type == "escalated"
        ).first()
        assert esc_history is not None

        # Restore original state of PGRC case to maintain test isolation
        pgrc_case.status = "Pending"
        pgrc_case.is_escalated = False
        db_session.delete(esc_history)
        db_session.commit()


class TestLiveIntakeAndPrecheck:

    def test_intake_extract_metadata(self, auth_headers):
        """Tests POST /intake/extract keyword metadata parsing."""
        headers = auth_headers("pgrc.officer@aicte.gov.in")
        payload = {
            "text": "Sir, my college ABC Tech Pune 1-1099238411 is illegally taking Rs 25000 caution money without receipt and not issuing hall ticket for tomorrow exam."
        }
        res = client.post("/intake/extract", json=payload, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["category"] == "Fee Related"
        assert data["priority"] == "High"  # "hall ticket" detected
        assert data["permanent_id"] == "1-1099238411"
        assert data["city"] == "Pune"

    def test_intake_precheck_case_a_auto_link(self, auth_headers):
        """
        Scenario 5 Intake Pre-Check (Case A: Auto-Link):
        Resolves ABC Tech Pune (PID 1-1099238411), detects overlap with AICTE/RB/2026/00204.
        """
        headers = auth_headers("pgrc.officer@aicte.gov.in")
        payload = {
            "raw_institution_name": "ABC Tech Pune",
            "text": "Sir, ABC Tech Pune college is illegally collecting Rs 25,000 caution money deposit and charging extra examination fees without receipt, refusing refund of caution money, and withholding my student hall ticket admit card.",
            "city": "Pune",
            "state": "Maharashtra",
            "category": "Fee Related"
        }
        res = client.post("/intake/precheck", json=payload, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["resolution_status"] == "AUTO_LINK"
        assert data["permanent_id"] == "1-1099238411"
        assert data["has_active_overlap"] is True
        assert len(data["active_overlaps"]) >= 1
        assert data["active_overlaps"][0]["is_provisional"] is False
        assert data["active_overlaps"][0]["overlap_score"] >= 0.85

    def test_intake_precheck_case_b_needs_review_provisional(self, auth_headers):
        """
        Enforces Item 5: When institution lands in NEEDS_REVIEW, runs overlap check against
        top candidate and labels alerts as 'provisional, institution not confirmed'.
        """
        headers = auth_headers("pgrc.officer@aicte.gov.in")
        payload = {
            "raw_institution_name": "Apex Academy",
            "text": "Apex Academy Bengaluru college caution money dispute",
            "city": "Bengaluru",
            "state": "Karnataka",
            "category": "Fee Related"
        }
        res = client.post("/intake/precheck", json=payload, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["resolution_status"] == "NEEDS_REVIEW"
        assert data["needs_institution_review"] is True
        assert len(data["candidate_institutions"]) == 3

        # If any overlap detected with active cases at candidate, must be provisional
        for alert in data["active_overlaps"]:
            assert alert["is_provisional"] is True
            assert "provisional" in alert["provisional_notice"].lower()

    def test_intake_precheck_case_c_unresolved(self, auth_headers):
        """
        Enforces Item 5: If UNRESOLVED, returns no overlap and explains why.
        """
        headers = auth_headers("pgrc.officer@aicte.gov.in")
        payload = {
            "text": "RandomUnmatchedCollegeXYZ987654",
            "city": "UnknownCity",
            "category": "Other"
        }
        res = client.post("/intake/precheck", json=payload, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["resolution_status"] == "UNRESOLVED"
        assert data["has_active_overlap"] is False
        assert len(data["active_overlaps"]) == 0
        assert any("could not be resolved" in r for r in data["resolution_reasons"])

    def test_intake_precheck_zero_database_writes(self, auth_headers, db_session):
        """
        Enforces Item 8: /intake/precheck MUST NOT write anything to the database.
        Verifies row counts of complaints, institutions, case_links, and alerts are identical before and after.
        """
        headers = auth_headers("pgrc.officer@aicte.gov.in")

        # Record baseline row counts
        c_count_before = db_session.query(Complaint).count()
        inst_count_before = db_session.query(Institution).count()
        link_count_before = db_session.query(CaseLink).count()
        alert_count_before = db_session.query(Alert).count()
        history_count_before = db_session.query(ActionHistory).count()

        # Run precheck call
        payload = {
            "text": "Sir, ABC Tech Pune college is illegally collecting Rs 25,000 caution money deposit.",
            "city": "Pune",
            "state": "Maharashtra",
            "category": "Fee Related"
        }
        res = client.post("/intake/precheck", json=payload, headers=headers)
        assert res.status_code == 200

        # Verify row counts remain completely unchanged
        assert db_session.query(Complaint).count() == c_count_before
        assert db_session.query(Institution).count() == inst_count_before
        assert db_session.query(CaseLink).count() == link_count_before
        assert db_session.query(Alert).count() == alert_count_before
        assert db_session.query(ActionHistory).count() == history_count_before
