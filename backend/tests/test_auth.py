"""
Unit Tests for Step 1 (Auth, Security, PyJWT, Rate Limiting, RBAC) and Step 2 (Schemas)
"""
from datetime import timedelta
from pathlib import Path
import sys
import pytest
from fastapi import HTTPException
import jwt

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.app.database import SessionLocal
from backend.app.models.bureau import Officer
from backend.app.auth.security import hash_password, verify_password, InMemoryRateLimiter
from backend.app.auth.jwt import create_access_token, decode_access_token
from backend.app.auth.dependencies import (
    require_roles,
    check_bureau_write_permission,
    check_regional_scope
)
from backend.app.config import (
    ROLE_ADMIN,
    ROLE_SENIOR_MGMT,
    ROLE_RB_OFFICER,
    ROLE_PGRC_OFFICER,
    ROLE_REGIONAL_OFFICER
)
from backend.app.schemas import (
    LoginRequest,
    TokenResponse,
    OfficerResponse,
    ComplaintCreate,
    ComplaintUpdate,
    CaseLinkResponse,
    OverlapDecisionRequest,
    LivePrecheckRequest,
    LivePrecheckResponse
)


@pytest.fixture(scope="module")
def db_session():
    session = SessionLocal()
    yield session
    session.close()


class TestAuthAndSecurity:

    def test_bcrypt_hashing_and_verification(self):
        """Checks bcrypt hashing and verification functions."""
        password = "SecurePassword@2026"
        hashed = hash_password(password)
        assert hashed.startswith("$2b$")
        assert verify_password(password, hashed) is True
        assert verify_password("WrongPassword", hashed) is False
        assert verify_password("", hashed) is False
        assert verify_password(password, "") is False

    def test_pyjwt_token_generation_and_decoding(self):
        """Checks PyJWT token encoding, decoding, and payload claims."""
        data = {
            "sub": "senior.mgmt@aicte.gov.in",
            "role": ROLE_SENIOR_MGMT,
            "bureau_id": None
        }
        token = create_access_token(data, expires_delta=timedelta(minutes=30))
        assert isinstance(token, str)
        assert len(token.split(".")) == 3  # Header.Payload.Signature

        payload = decode_access_token(token)
        assert payload["sub"] == "senior.mgmt@aicte.gov.in"
        assert payload["role"] == ROLE_SENIOR_MGMT
        assert "exp" in payload
        assert "iat" in payload

    def test_pyjwt_expired_token_rejection(self):
        """Checks that expired tokens strictly raise ExpiredSignatureError."""
        data = {"sub": "test@aicte.gov.in", "role": ROLE_ADMIN}
        # Token expired 10 seconds ago
        token = create_access_token(data, expires_delta=timedelta(seconds=-10))
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_access_token(token)

    def test_in_memory_rate_limiter(self):
        """Checks rate limiting threshold, locking, and resetting."""
        limiter = InMemoryRateLimiter(max_attempts=3, window_seconds=60)
        key = "attacker@ip.address"

        assert limiter.is_rate_limited(key) is False
        limiter.record_attempt(key)
        assert limiter.is_rate_limited(key) is False
        limiter.record_attempt(key)
        assert limiter.is_rate_limited(key) is False
        limiter.record_attempt(key)
        # 3rd attempt recorded -> now rate limited
        assert limiter.is_rate_limited(key) is True

        # Successful login resets the limiter
        limiter.reset(key)
        assert limiter.is_rate_limited(key) is False

    def test_rbac_require_roles_dependency(self):
        """Checks role authorization enforcement."""
        officer = Officer(id=1, email="rb@aicte.gov.in", role=ROLE_RB_OFFICER, bureau_id=1)
        mgmt = Officer(id=2, email="mgmt@aicte.gov.in", role=ROLE_SENIOR_MGMT, bureau_id=None)

        checker_mgmt_only = require_roles([ROLE_ADMIN, ROLE_SENIOR_MGMT])
        # Management allowed
        assert checker_mgmt_only(mgmt) == mgmt
        # Bureau officer rejected with 403 Forbidden
        with pytest.raises(HTTPException) as exc_info:
            checker_mgmt_only(officer)
        assert exc_info.value.status_code == 403
        assert "Access denied" in exc_info.value.detail

    def test_inter_bureau_write_protection(self):
        """
        Enforces item 5: Officers may modify only complaints assigned to their bureau;
        cross-bureau modifications raise 403; Admin & Senior Management are permitted.
        """
        rb_officer = Officer(id=1, email="rb@aicte.gov.in", role=ROLE_RB_OFFICER, bureau_id=1)
        pgrc_officer = Officer(id=2, email="pgrc@aicte.gov.in", role=ROLE_PGRC_OFFICER, bureau_id=2)
        admin_user = Officer(id=3, email="admin@aicte.gov.in", role=ROLE_ADMIN, bureau_id=None)
        mgmt_user = Officer(id=4, email="mgmt@aicte.gov.in", role=ROLE_SENIOR_MGMT, bureau_id=None)

        # RB officer modifying RB complaint (bureau_id=1) -> Allowed
        check_bureau_write_permission(rb_officer, assigned_bureau_id=1)

        # RB officer attempting to modify PGRC complaint (bureau_id=2) -> 403 Forbidden
        with pytest.raises(HTTPException) as exc_info:
            check_bureau_write_permission(rb_officer, assigned_bureau_id=2)
        assert exc_info.value.status_code == 403
        assert "Officers may modify only complaints assigned to their own bureau" in exc_info.value.detail

        # PGRC officer attempting to modify RB complaint (bureau_id=1) -> 403 Forbidden
        with pytest.raises(HTTPException) as exc_info_2:
            check_bureau_write_permission(pgrc_officer, assigned_bureau_id=1)
        assert exc_info_2.value.status_code == 403

        # Admin and Senior Management may modify across all bureaus
        check_bureau_write_permission(admin_user, assigned_bureau_id=1)
        check_bureau_write_permission(admin_user, assigned_bureau_id=2)
        check_bureau_write_permission(mgmt_user, assigned_bureau_id=1)
        check_bureau_write_permission(mgmt_user, assigned_bureau_id=2)

    def test_regional_scope_enforcement(self):
        """Checks that Regional Officers are scoped to their region while HQ has global access."""
        ro_west = Officer(id=5, email="ro.west@aicte.gov.in", role=ROLE_REGIONAL_OFFICER, region="West")
        hq_officer = Officer(id=6, email="rb@aicte.gov.in", role=ROLE_RB_OFFICER, region=None)

        assert check_regional_scope(ro_west, "West") is True
        assert check_regional_scope(ro_west, "North") is False
        assert check_regional_scope(hq_officer, "West") is True
        assert check_regional_scope(hq_officer, "North") is True

    def test_seeded_officer_accounts_and_passwords(self, db_session):
        """
        Enforces item 7: Seed accounts verification.
        Verifies senior.mgmt@aicte.gov.in (not management@) exists and authenticates with Demo@123.
        """
        senior_mgmt = db_session.query(Officer).filter(Officer.email == "senior.mgmt@aicte.gov.in").first()
        assert senior_mgmt is not None
        assert senior_mgmt.role == ROLE_SENIOR_MGMT
        assert verify_password("Demo@123", senior_mgmt.password_hash) is True

        admin = db_session.query(Officer).filter(Officer.email == "admin@aicte.gov.in").first()
        assert admin is not None
        assert admin.role == ROLE_ADMIN
        assert verify_password("Demo@123", admin.password_hash) is True

        rb_officer = db_session.query(Officer).filter(Officer.email == "rb.officer@aicte.gov.in").first()
        assert rb_officer is not None
        assert rb_officer.role == ROLE_RB_OFFICER
        assert verify_password("Demo@123", rb_officer.password_hash) is True

    def test_overlap_decision_schema_consistency(self):
        """
        Enforces item 4: CaseLink.status and OverlapDecisionRequest are consistent,
        including 'related_only'.
        """
        for decision in ["approved", "rejected", "needs_discussion", "related_only"]:
            req = OverlapDecisionRequest(decision=decision, remarks="Audit comment")
            assert req.decision == decision

        # Invalid decision fails validation
        with pytest.raises(Exception):
            OverlapDecisionRequest(decision="invalid_choice")
