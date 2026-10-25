"""
Script to verify that all seeded AICTE officer accounts authenticate successfully
with 'Demo@123' via bcrypt, POST /auth/login (JSON), and POST /auth/token (OAuth2 form),
and confirms rate limiter does not block legitimate first logins.
"""
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models.bureau import Officer
from backend.app.auth.security import verify_password, login_rate_limiter

client = TestClient(app)


def verify_all_officers():
    db = SessionLocal()
    officers = db.query(Officer).all()
    print("=" * 70)
    print("AICTE OFFICER ACCOUNTS AUTHENTICATION PROOF (Password: Demo@123)")
    print("=" * 70)

    if not officers:
        print("[FAIL] No officers found in database! Please run seed.py first.")
        sys.exit(1)

    all_passed = True
    test_password = "Demo@123"

    for officer in officers:
        # 1. Direct Bcrypt verification
        bcrypt_ok = verify_password(test_password, officer.password_hash)

        # 2. Rate limiter status check
        is_limited = login_rate_limiter.is_rate_limited(officer.email.lower())

        # 3. HTTP POST /auth/login (JSON body used by React frontend)
        res_json = client.post("/auth/login", json={
            "email": officer.email,
            "password": test_password
        })
        json_ok = (res_json.status_code == 200 and "access_token" in res_json.json())

        # 4. HTTP POST /auth/token (OAuth2 form data used by Swagger /docs Authorize)
        res_form = client.post("/auth/token", data={
            "username": officer.email,
            "password": test_password
        })
        form_ok = (res_form.status_code == 200 and "access_token" in res_form.json())

        status_str = "[PASS]" if (bcrypt_ok and not is_limited and json_ok and form_ok) else "[FAIL]"
        if status_str == "[FAIL]":
            all_passed = False

        print(f" {status_str} {officer.email:<28} | Role: {officer.role:<18} | Bcrypt: {bcrypt_ok} | JSON: {res_json.status_code} | Form: {res_form.status_code}")

    print("=" * 70)
    if all_passed:
        print("[SUCCESS] All seeded officers authenticate flawlessly with Demo@123.")
    else:
        print("[ERROR] One or more officer logins failed.")
    print("=" * 70)
    db.close()
    return all_passed


if __name__ == "__main__":
    success = verify_all_officers()
    sys.exit(0 if success else 1)