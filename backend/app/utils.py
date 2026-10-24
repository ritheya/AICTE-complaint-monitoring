"""
AICTE Complaint Monitor - System Utilities
Provides standardized datetime and helper functions.
"""
from datetime import datetime, timezone


def utc_now() -> datetime:
    """
    Standardized application datetime provider.
    Returns current naive-UTC datetime (compatible with SQLite and SQLAlchemy DateTime columns)
    to prevent offset-naive vs offset-aware comparison errors and deprecation warnings.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
