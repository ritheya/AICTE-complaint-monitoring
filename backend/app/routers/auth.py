"""
Authentication & Officer Profile Router
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.bureau import Officer
from backend.app.auth.security import verify_password, login_rate_limiter
from backend.app.auth.jwt import create_access_token
from backend.app.auth.dependencies import get_current_user
from backend.app.schemas.auth import LoginRequest, TokenResponse, OfficerResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticates AICTE officer credentials using bcrypt.
    Enforces login rate limiting and returns signed PyJWT access token.
    Generic error message returned on failure for security.
    """
    email_clean = req.email.strip().lower()

    # Rate limiting check
    if login_rate_limiter.is_rate_limited(email_clean):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please wait 60 seconds before trying again."
        )

    officer = db.query(Officer).filter(Officer.email == email_clean).first()

    if not officer or not officer.is_active or not verify_password(req.password, officer.password_hash):
        login_rate_limiter.record_attempt(email_clean)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # Reset failed attempts upon successful login
    login_rate_limiter.reset(email_clean)

    token_data = {
        "sub": officer.email,
        "role": officer.role,
        "bureau_id": officer.bureau_id,
        "region": officer.region
    }
    access_token = create_access_token(token_data)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        officer=OfficerResponse.model_validate(officer)
    )


@router.get("/me", response_model=OfficerResponse)
def get_current_officer_profile(current_user: Officer = Depends(get_current_user)):
    """
    Returns public profile of currently authenticated AICTE officer.
    """
    return OfficerResponse.model_validate(current_user)
