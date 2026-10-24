"""
AICTE Complaint Monitor - Authentication & RBAC Dependencies
Enforces token validation, role-based access control, and bureau scoping.
"""
from typing import List, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import jwt

from backend.app.database import get_db
from backend.app.models.bureau import Officer
from backend.app.auth.jwt import decode_access_token
from backend.app.config import (
    ROLE_ADMIN,
    ROLE_SENIOR_MGMT,
    ROLE_REGIONAL_OFFICER
)

# Standard OAuth2 bearer token scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Officer:
    """
    Validates PyJWT bearer token and resolves the corresponding active Officer.
    Raises 401 UNAUTHORIZED on missing, expired, or invalid tokens.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception

    try:
        payload = decode_access_token(token)
        email: Optional[str] = payload.get("sub")
        if not email:
            raise credentials_exception
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise credentials_exception

    officer = db.query(Officer).filter(Officer.email == email).first()
    if not officer or not officer.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return officer


def require_roles(allowed_roles: List[str]):
    """
    Factory dependency ensuring current user possesses one of the allowed roles.
    Raises 403 FORBIDDEN if the role is unauthorized.
    """
    def role_checker(current_user: Officer = Depends(get_current_user)) -> Officer:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Requires one of roles: {', '.join(allowed_roles)}"
            )
        return current_user
    return role_checker


def check_bureau_write_permission(user: Officer, assigned_bureau_id: int) -> None:
    """
    Enforces inter-bureau security policy:
    - Admin and Senior Management possess global write permission across all bureaus.
    - Bureau Officers may modify ONLY complaints assigned to their own bureau.
    - Cross-bureau write attempts are strictly rejected with 403 FORBIDDEN.
    """
    if user.role in {ROLE_ADMIN, ROLE_SENIOR_MGMT}:
        return

    if user.bureau_id != assigned_bureau_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Officers may modify only complaints assigned to their own bureau"
        )


def check_regional_scope(user: Officer, complaint_region: Optional[str]) -> bool:
    """
    Returns True if user has authorization to view the complaint:
    - Regional Officers are scoped to their assigned geographic region.
    - All HQ Officers and Management can view across all regions.
    """
    if user.role == ROLE_REGIONAL_OFFICER and user.region:
        return complaint_region == user.region
    return True
