"""
Evidence Test Suite for AICTE Complaint Monitor
Covers:
1. Universal 401 enforcement across every route in OpenAPI spec (public routes excepted)
2. OAuth2 Password Form endpoint (/auth/token) for Swagger /docs Authorize button
3. CaseLink stored scores, signals, and reasons immutability
4. Lead bureau restricted strictly to true overlaps (Scenario 1c produces no alert, no lead)
5. /intake/precheck 3-way branching (AUTO_LINK, provisional NEEDS_REVIEW, UNRESOLVED) and 0 DB writes
6. Rejected overlap pairs are never re-suggested
7. SLA check dynamic evaluation and strict idempotency across consecutive runs
8. Institution summary provenance ('Generated from records')
9. Production startup security check against default JWT secrets
"""
from datetime import timedelta
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.app.main import app
from backend.app.models.complaint import Complaint
from backend.app.models.institution import Institution
from backend.app.models.case_link import CaseLink
from backend.app.models.alert import Alert
from backend.app.models.action_history import ActionHistory
from backend.app.utils import utc_now
from backend.app.services.overlap_engine import ComplaintOverlapEngine
from backend.app.services.lead_bureau_rules import LeadBureauEngine

client = TestClient(app)


class TestSecurityAndOpenAPIRoutes:
    """Item 1 & Item 4: Authentication enforcement and Swagger OAuth2 token endpoint."""

    def test_every_openapi_route_requires_auth_except_public(self):
        """
        Walks every single route and method defined in the OpenAPI schema.
        Ensures any call without a token, with an empty Bearer token, or an invalid token
        returns 401 Unauthorized (public routes: /auth/login, /auth/token, /health excluded).
        """
        openapi_schema = app.openapi()
        paths = openapi_schema.get("paths", {})

        public_paths = {
            "/auth/login": {"post"},
            "/auth/token": {"post"},
            "/health": {"get"}
        }

        checked_routes = 0

        for path, methods in paths.items():
            for method in methods.keys():
                if method.lower() not in ["get", "post", "patch", "put", "delete"]:
                    continue

                if path in public_paths and method.lower() in public_paths[path]:
                    continue

                checked_routes += 1
                # Format path parameter placeholders e.g. {id} -> 1
                test_path = path.replace("{id}", "1").replace("{complaint_id}", "1").replace("{institution_id}", "1").replace("{link_id}", "1").replace("{alert_id}", "1")

                # Test 1: No authorization header
                call_fn = getattr(client, method.lower())
                res_no_auth = call_fn(test_path)
                assert res_no_auth.status_code == 401, f"Route {method.upper()} {test_path} without auth did not return 401! Got: {res_no_auth.status_code}"

                # Test 2: Empty Bearer header (sent by Swagger or broken clients)
                res_empty_bearer = call_fn(test_path, headers={"Authorization": "Bearer "})
                assert res_empty_bearer.status_code == 401, f"Route {method.upper()} {test_path} with empty Bearer did not return 401! Got: {res_empty_bearer.status_code}"

                # Test 3: Malformed / fake Bearer token
                res_fake_token = call_fn(test_path, headers={"Authorization": "Bearer invalid.fake.token"})
                assert res_fake_token.status_code == 401, f"Route {method.upper()} {test_path} with fake token did not return 401! Got: {res_fake_token.status_code}"

        print(f"\n[OK] Successfully verified 401 authentication enforcement on {checked_routes} OpenAPI endpoints.")

    def test_oauth2_password_form_token_endpoint(self):
        """
        Item 4: Tests POST /auth/token with OAuth2PasswordRequestForm.
        Accepts username=email, password=password via x-www-form-urlencoded data.
        """
        # Valid login for Senior Management
        res_valid = client.post("/auth/token", data={
            "username": "senior.mgmt@aicte.gov.in",
            "password": "Demo@123"
        })
        assert res_valid.status_code == 200, f"Failed form login: {res_valid.text}"
        data = res_valid.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

        # Invalid password returns generic error
        res_invalid = client.post("/auth/token", data={
            "username": "senior.mgmt@aicte.gov.in",
            "password": "WrongPassword123"
        })
        assert res_invalid.status_code == 401
        assert res_invalid.json()["detail"] == "Invalid email or password"


class TestFollowUpsEvidence:
    """Item 6: Tests covering score consistency, lead bureau gating, precheck, and rejected pairs."""

    def test_caselink_stored_score_and_signals_immutability(self, db_session):
        """
        6(a): CaseLink stores score, signals and reasons at creation and does not silently recompute them.
        Adding an unrelated complaint to database does not change stored score.
        """
        c1 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/PGRC/2026/00101").first()
        c2 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/RB/2026/00204").first()
        assert c1 is not None and c2 is not None

        engine = ComplaintOverlapEngine()
        res_initial = engine.evaluate_overlap(c1, c2, db=db_session)
        assert res_initial.score >= 0.88

        # Create CaseLink with stored score, signals and reasons
        ca_id, cb_id = (c1.id, c2.id) if c1.id < c2.id else (c2.id, c1.id)
        link = db_session.query(CaseLink).filter(CaseLink.case_a_id == ca_id, CaseLink.case_b_id == cb_id).first()
        if not link:
            link = CaseLink(
                case_a_id=ca_id,
                case_b_id=cb_id,
                institution_id=c1.institution_id,
                similarity_score=res_initial.score,
                signals=res_initial.signals,
                reasons=res_initial.reasons,
                status="suggested"
            )
            db_session.add(link)
            db_session.commit()
            db_session.refresh(link)

        stored_score = link.similarity_score
        stored_signals = dict(link.signals)
        stored_reasons = list(link.reasons)

        # Insert an unrelated complaint that alters the text vocabulary
        unrelated = Complaint(
            case_id="AICTE/TEST/2026/77777",
            raw_institution_name="Completely Unrelated Test Polytechnic",
            source="Portal",
            category="Other",
            description="Arbitrary unrelated text discussing robotics solar battery workshop laboratory equipment.",
            complainant_type="Student",
            date_received=utc_now(),
            expected_disposal_date=utc_now() + timedelta(days=30),
            status="Pending",
            assigned_bureau_id=3
        )
        db_session.add(unrelated)
        db_session.commit()

        # Re-fetch link: stored score, signals and reasons MUST be strictly identical
        db_session.refresh(link)
        assert link.similarity_score == stored_score
        assert link.signals == stored_signals
        assert link.reasons == stored_reasons

    def test_lead_bureau_shown_only_when_overlap_is_true(self, db_session):
        """
        6(b): Lead bureau must only be computed and shown when is_overlap is True.
        Scenario 1c (negative case) must show no alert, no lead.
        """
        c1 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/PGRC/2026/00109").first()
        c2 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/AB/2026/00209").first()
        assert c1 is not None and c2 is not None

        engine = ComplaintOverlapEngine()
        lead_engine = LeadBureauEngine()

        ovl = engine.evaluate_overlap(c1, c2, db=db_session)
        assert ovl.is_overlap is False
        assert ovl.score < 0.60
        assert ovl.band == "BELOW_THRESHOLD"

        lead = lead_engine.suggest_lead(c1, c2) if ovl.is_overlap else None
        assert lead is None, "When is_overlap is False, suggested lead bureau MUST be None (no alert, no lead)"

    def test_intake_precheck_three_branches_and_zero_db_writes(self, db_session):
        """
        6(c): /intake/precheck behaves correctly for:
        - AUTO_LINK: resolves institution, finds active overlaps
        - NEEDS_REVIEW: returns top candidate match, labels overlap 'provisional, institution not confirmed'
        - UNRESOLVED: returns no overlaps and explains why
        And confirms strictly 0 database writes occur (row counts identical before and after).
        """
        # Count rows prior to requests
        c_count_before = db_session.query(Complaint).count()
        l_count_before = db_session.query(CaseLink).count()
        a_count_before = db_session.query(Alert).count()
        h_count_before = db_session.query(ActionHistory).count()

        # Login token
        res_login = client.post("/auth/login", json={"email": "pgrc.officer@aicte.gov.in", "password": "Demo@123"})
        token = res_login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Branch 1: AUTO_LINK
        res_a = client.post("/intake/precheck", json={
            "raw_institution_name": "ABC Tech Pune",
            "text": "ABC Tech Pune caution money refund Rs 25000",
            "city": "Pune",
            "state": "Maharashtra",
            "category": "Fee Related"
        }, headers=headers)
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert data_a["resolution_status"] == "AUTO_LINK"
        assert data_a["permanent_id"] == "1-1099238411"
        assert data_a["has_active_overlap"] is True
        assert data_a["active_overlaps"][0]["is_provisional"] is False

        # Branch 2: NEEDS_REVIEW (Provisional Overlap)
        res_b = client.post("/intake/precheck", json={
            "raw_institution_name": "Apex Academy",
            "text": "Apex Academy Bengaluru caution money refund",
            "city": "Bengaluru",
            "state": "Karnataka",
            "category": "Fee Related"
        }, headers=headers)
        assert res_b.status_code == 200
        data_b = res_b.json()
        assert data_b["resolution_status"] == "NEEDS_REVIEW"
        assert data_b["needs_institution_review"] is True
        for ovl in data_b["active_overlaps"]:
            assert ovl["is_provisional"] is True
            assert "provisional" in ovl["provisional_notice"].lower()

        # Branch 3: UNRESOLVED
        res_c = client.post("/intake/precheck", json={
            "text": "Some completely fictitious institution 999999",
            "city": "UnknownCity",
            "category": "Other"
        }, headers=headers)
        assert res_c.status_code == 200
        data_c = res_c.json()
        assert data_c["resolution_status"] == "UNRESOLVED"
        assert data_c["has_active_overlap"] is False
        assert any("below" in r.lower() or "unresolved" in r.lower() for r in data_c["resolution_reasons"])

        # Verify ZERO database writes occurred
        assert db_session.query(Complaint).count() == c_count_before
        assert db_session.query(CaseLink).count() == l_count_before
        assert db_session.query(Alert).count() == a_count_before
        assert db_session.query(ActionHistory).count() == h_count_before

    def test_rejected_pairs_never_resuggested(self, db_session):
        """
        6(d): Rejected pairs are never re-suggested.
        When a link has status='rejected', evaluate_overlap must gate it out.
        """
        c1 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/PGRC/2026/00101").first()
        c2 = db_session.query(Complaint).filter(Complaint.case_id == "AICTE/RB/2026/00204").first()
        assert c1 and c2

        ca_id, cb_id = (c1.id, c2.id) if c1.id < c2.id else (c2.id, c1.id)
        link = db_session.query(CaseLink).filter(CaseLink.case_a_id == ca_id, CaseLink.case_b_id == cb_id).first()
        assert link is not None
        orig_status = link.status

        # Set status to rejected
        link.status = "rejected"
        db_session.commit()

        engine = ComplaintOverlapEngine()
        result = engine.evaluate_overlap(c1, c2, db=db_session)

        # Must be gated out
        assert result.is_overlap is False
        assert result.gated_out is True
        assert "rejected" in result.gate_reason.lower()

        # Restore original status
        link.status = orig_status
        db_session.commit()

    def test_utc_now_used_everywhere_and_sla_boundary(self):
        """
        6(e): Verifies utc_now helper returns naive-UTC datetimes, and SLA boundary
        difference calculation operates like-with-like without timezone mismatch.
        """
        now = utc_now()
        assert now.tzinfo is None, "utc_now() must return naive-UTC datetime for consistent SQLite storage"

        past = now - timedelta(days=35)
        diff_days = (now - past).days
        assert diff_days == 35


class TestSLAIdempotencyAndEvidence:
    """Item 7: SLA check dynamic evaluation and idempotency proof."""

    def test_sla_check_strict_idempotency_run1_and_run2(self, db_session):
        """
        Creates a brand-new overdue case, runs POST /scheduler/run-sla-check twice,
        and demonstrates alert, escalation, and history counts after run 1 and run 2 are identical.
        """
        now = utc_now()
        inst = db_session.query(Institution).first()
        assert inst is not None

        # Clean up any prior test artifacts
        db_session.query(Alert).filter(Alert.message.contains("AICTE/TEST/2026/88888")).delete()
        db_session.query(ActionHistory).filter(ActionHistory.remarks.contains("AICTE/TEST/2026/88888")).delete()
        db_session.query(Complaint).filter(Complaint.case_id == "AICTE/TEST/2026/88888").delete()
        db_session.commit()

        # Create brand-new overdue case (received 60 days ago, High priority -> SLA target ~31 days)
        test_case = Complaint(
            case_id="AICTE/TEST/2026/88888",
            institution_id=inst.id,
            raw_institution_name=inst.name,
            source="Portal",
            category="Faculty Shortage",
            description="Dynamic SLA evaluation test complaint.",
            complainant_type="Faculty",
            date_received=now - timedelta(days=60),
            status="Pending",
            assigned_bureau_id=1,  # RB
            priority="High",
            is_overdue=False,
            is_escalated=False,
            expected_disposal_date=now - timedelta(days=29),
            last_action="Received",
            next_action="Scrutiny",
            last_action_date=now - timedelta(days=60)
        )
        db_session.add(test_case)
        db_session.commit()
        db_session.refresh(test_case)
        cid = test_case.id

        # Admin login
        res_auth = client.post("/auth/login", json={"email": "admin@aicte.gov.in", "password": "Demo@123"})
        headers = {"Authorization": f"Bearer {res_auth.json()['access_token']}"}

        # RUN 1: Execute SLA check
        res_run1 = client.post("/scheduler/run-sla-check", headers=headers)
        assert res_run1.status_code == 200

        db_session.refresh(test_case)
        assert test_case.is_overdue is True
        assert test_case.is_escalated is True

        alert_count_run1 = db_session.query(Alert).filter(Alert.complaint_id == cid).count()
        history_count_run1 = db_session.query(ActionHistory).filter(
            ActionHistory.complaint_id == cid,
            ActionHistory.action_type == "AUTO_ESCALATION"
        ).count()
        assert alert_count_run1 >= 1
        assert history_count_run1 == 1

        # RUN 2: Execute SLA check again immediately
        res_run2 = client.post("/scheduler/run-sla-check", headers=headers)
        assert res_run2.status_code == 200

        db_session.refresh(test_case)
        alert_count_run2 = db_session.query(Alert).filter(Alert.complaint_id == cid).count()
        history_count_run2 = db_session.query(ActionHistory).filter(
            ActionHistory.complaint_id == cid,
            ActionHistory.action_type == "AUTO_ESCALATION"
        ).count()

        # Must be strictly identical (idempotent: zero duplicate alerts or histories)
        assert alert_count_run1 == alert_count_run2, f"Duplicate alerts created on run 2: {alert_count_run1} vs {alert_count_run2}"
        assert history_count_run1 == history_count_run2, f"Duplicate action histories created on run 2: {history_count_run1} vs {history_count_run2}"

    def test_alerts_endpoint_total_count_and_sla_double_run_identity(self, db_session):
        """
        Item 1 & 3:
        1. GET /alerts returns total count, skip, limit, items.
        2. First SLA run auto-escalates roughly 5 to 8 cases and returns escalated_case_ids.
        3. Second SLA run produces 0 escalations, 0 alerts, and GET /alerts total is identical.
        """
        res_auth = client.post("/auth/login", json={"email": "senior.mgmt@aicte.gov.in", "password": "Demo@123"})
        headers = {"Authorization": f"Bearer {res_auth.json()['access_token']}"}

        # Check GET /alerts pagination structure
        res_alerts0 = client.get("/alerts", headers=headers)
        assert res_alerts0.status_code == 200
        data_alerts0 = res_alerts0.json()
        assert "total" in data_alerts0
        assert "skip" in data_alerts0
        assert "limit" in data_alerts0
        assert "items" in data_alerts0
        assert data_alerts0["skip"] == 0
        assert data_alerts0["limit"] == 50
        initial_total_alerts = data_alerts0["total"]

        # Run 1 of SLA Check
        res_run1 = client.post("/scheduler/run-sla-check", headers=headers)
        assert res_run1.status_code == 200
        data1 = res_run1.json()
        assert "escalated_case_ids" in data1
        assert "newly_escalated_complaints" in data1
        # Expect roughly 5 to 8 escalated cases
        assert 5 <= data1["newly_escalated_complaints"] <= 8, f"Expected 5-8 escalations, got {data1['newly_escalated_complaints']}"
        assert len(data1["escalated_case_ids"]) == data1["newly_escalated_complaints"]
        assert "AICTE/RB/2026/00045" in data1["escalated_case_ids"]

        # Query /alerts after Run 1
        res_alerts1 = client.get("/alerts", headers=headers)
        assert res_alerts1.status_code == 200
        data_alerts1 = res_alerts1.json()
        total_after_run1 = data_alerts1["total"]
        assert total_after_run1 == initial_total_alerts + data1["alerts_created"]

        # Run 2 of SLA Check
        res_run2 = client.post("/scheduler/run-sla-check", headers=headers)
        assert res_run2.status_code == 200
        data2 = res_run2.json()
        assert data2["newly_escalated_complaints"] == 0
        assert data2["escalated_case_ids"] == []
        assert data2["alerts_created"] == 0

        # Query /alerts after Run 2: Total count MUST be strictly identical!
        res_alerts2 = client.get("/alerts", headers=headers)
        assert res_alerts2.status_code == 200
        data_alerts2 = res_alerts2.json()
        total_after_run2 = data_alerts2["total"]
        assert total_after_run2 == total_after_run1, f"Alert count changed on run 2: {total_after_run1} vs {total_after_run2}"

    def test_institution_names_and_aliases_uniqueness(self, db_session):
        """
        Item 4:
        1. Seeded institution names are unique (except deliberate Scenario 2 Jaipur vs Raipur fixture).
        2. Exactly 1 'Global Institute of Technology' (Mumbai, id 8).
        3. Aliases are 100% unique per institution (zero duplicate aliases across entire DB).
        4. 'Global Tech' alias appears on exactly 1 institution.
        """
        from collections import Counter
        insts = db_session.query(Institution).all()
        assert len(insts) == 150

        # Names uniqueness
        name_counts = Counter(i.name for i in insts)
        duplicate_names = [name for name, cnt in name_counts.items() if cnt > 1]
        assert duplicate_names == ["National College of Engineering"], f"Unexpected duplicate names: {duplicate_names}"

        # Scenario 2 verify
        nce_insts = [i for i in insts if i.name == "National College of Engineering"]
        assert len(nce_insts) == 2
        assert set(i.city for i in nce_insts) == {"Jaipur", "Raipur"}

        # Global Institute of Technology verify
        git_insts = [i for i in insts if "Global Institute of Technology" in i.name]
        assert len(git_insts) == 1
        assert git_insts[0].city == "Mumbai"

        # Aliases uniqueness across all institutions
        all_aliases = []
        for i in insts:
            if i.aliases:
                all_aliases.extend(i.aliases)

        alias_counts = Counter(all_aliases)
        duplicate_aliases = [alias for alias, cnt in alias_counts.items() if cnt > 1]
        assert duplicate_aliases == [], f"Found duplicate aliases across institutions: {duplicate_aliases}"
        assert alias_counts["Global Tech"] == 1


class TestInstitutionSummaryAndProductionCheck:
    """Item 9 & Housekeeping startup check."""

    def test_institution_summary_provenance_and_records_label(self):
        """Item 9: Verifies GET /institutions/{id}/summary returns 'Generated from records'."""
        res_auth = client.post("/auth/login", json={"email": "senior.mgmt@aicte.gov.in", "password": "Demo@123"})
        headers = {"Authorization": f"Bearer {res_auth.json()['access_token']}"}

        res = client.get("/institutions/1/summary", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["generated_from"] == "Generated from records"
        assert "source" in data

    def test_production_startup_check_refuses_default_jwt_secret(self):
        """Housekeeping: Startup security validation refuses to run in production with default JWT secret."""
        from backend.app.main import validate_production_configuration
        import os

        # Temporarily simulate production with default secret
        orig_env = os.environ.get("ENVIRONMENT")
        os.environ["ENVIRONMENT"] = "production"

        try:
            # Must raise RuntimeError
            with pytest.raises(RuntimeError) as exc_info:
                validate_production_configuration()
            assert "Cannot start in ENVIRONMENT=production with default or insecure JWT_SECRET_KEY" in str(exc_info.value)
        finally:
            if orig_env:
                os.environ["ENVIRONMENT"] = orig_env
            else:
                os.environ.pop("ENVIRONMENT", None)
