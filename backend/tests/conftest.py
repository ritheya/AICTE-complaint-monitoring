"""
Pytest Master Configuration and Database Isolation Fixture
Guarantees tests run against a separate temporary SQLite database,
strictly leaving data/aicte_portal.db untouched.
Restores pristine test database state before each test function.
"""
import shutil
import tempfile
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import sys
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
PROD_DB_PATH = BASE_DIR / "data" / "aicte_portal.db"

_test_temp_dir = tempfile.mkdtemp(prefix="aicte_test_db_")
_test_db_path = Path(_test_temp_dir) / "aicte_isolated_test.db"
_pristine_db_path = Path(_test_temp_dir) / "aicte_pristine_test.db"

if PROD_DB_PATH.exists():
    shutil.copyfile(PROD_DB_PATH, _pristine_db_path)
    shutil.copyfile(PROD_DB_PATH, _test_db_path)
else:
    from data.seed import seed_database
    seed_database()
    shutil.copyfile(PROD_DB_PATH, _pristine_db_path)
    shutil.copyfile(PROD_DB_PATH, _test_db_path)

test_db_url = f"sqlite:///{_test_db_path.as_posix()}"
test_engine = create_engine(test_db_url, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Monkey-patch backend.app.database BEFORE other modules import it
import backend.app.database as db_mod
db_mod.engine = test_engine
db_mod.SessionLocal = TestSessionLocal

from backend.app.main import app
from backend.app.database import get_db

def _override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(scope="session", autouse=True)
def test_database_isolation():
    """
    Session-wide fixture ensuring app.dependency_overrides is maintained
    and cleaning up the temp directory after the test session.
    """
    yield TestSessionLocal
    test_engine.dispose()
    if _test_temp_dir and Path(_test_temp_dir).exists():
        shutil.rmtree(_test_temp_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def reset_test_db_state():
    """Restores the isolated test database from pristine copy before each test function."""
    test_engine.dispose()
    shutil.copyfile(_pristine_db_path, _test_db_path)
    yield
    test_engine.dispose()


@pytest.fixture(scope="function")
def db_session():
    """Provides an isolated test database session for each test function."""
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
