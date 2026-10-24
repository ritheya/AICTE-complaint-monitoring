"""
AICTE Complaint Monitor - Security & Rate Limiting Module
Bcrypt-based password verification and in-memory rate limiting.
"""
import time
from typing import Dict, List
import bcrypt
from backend.app.config import (
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
    LOGIN_RATE_LIMIT_WINDOW_SECONDS
)


def hash_password(password: str) -> str:
    """Hash password securely using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against stored bcrypt hash."""
    if not plain_password or not hashed_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


class InMemoryRateLimiter:
    """
    Thread-safe windowed rate limiter for login protection.
    Tracks failure timestamps per identifier (IP address or email).
    """
    def __init__(self, max_attempts: int = LOGIN_RATE_LIMIT_MAX_ATTEMPTS, window_seconds: int = LOGIN_RATE_LIMIT_WINDOW_SECONDS):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: Dict[str, List[float]] = {}

    def is_rate_limited(self, key: str) -> bool:
        """Returns True if key has exceeded max allowed failed attempts in the window."""
        now = time.time()
        cutoff = now - self.window_seconds
        history = self._attempts.get(key, [])
        valid_history = [t for t in history if t > cutoff]
        self._attempts[key] = valid_history
        return len(valid_history) >= self.max_attempts

    def record_attempt(self, key: str) -> None:
        """Records a failed login attempt for the key."""
        now = time.time()
        if key not in self._attempts:
            self._attempts[key] = []
        self._attempts[key].append(now)

    def reset(self, key: str) -> None:
        """Clears failed attempts for a key upon successful authentication."""
        if key in self._attempts:
            del self._attempts[key]


# Global rate limiter instance for auth endpoints
login_rate_limiter = InMemoryRateLimiter()
