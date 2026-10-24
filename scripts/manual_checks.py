# Manual checks. Nothing here is saved to the database.
import inspect
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.app.database import SessionLocal
from backend.app.models.complaint import Complaint
from backend.app.services.resolution_engine import InstitutionResolutionEngine
from backend.app.services.overlap_engine import ComplaintOverlapEngine

db = SessionLocal()
res = InstitutionResolutionEngine()
ov = ComplaintOverlapEngine()

# Show what the real signature looks like (so we can see the DB argument name)
params = list(inspect.signature(res.resolve).parameters)
print("resolve() parameters:", params)
DB_ARG = next((p for p in params if p in ("db", "session", "db_session")), None)
print("database argument name:", DB_ARG)


def show_resolution(label, **kw):
    if DB_ARG:
        kw[DB_ARG] = db
    r = res.resolve(**kw)
    shown = {k: v for k, v in kw.items() if k != DB_ARG}
    print(f"\n[{label}] input: {shown}")
    print("   result:", r)


# ---------- CHECK 1: unrelated complaint should NOT alert ----------
a = db.query(Complaint).filter_by(case_id="AICTE/PGRC/2026/00101").one()
b = db.query(Complaint).filter_by(case_id="AICTE/RB/2026/00204").one()
print("\n=== CHECK 1: unrelated complaint ===")
print("Baseline (real pair):", ov.evaluate_overlap(a, b))
a.description = "The hostel mess serves poor quality food and the rooms are unclean."
a.category = "Other"
print("After making A unrelated:", ov.evaluate_overlap(a, b))
db.rollback()

# ---------- CHECK 2: misspelled names ----------
print("\n=== CHECK 2: misspellings ===")
show_resolution("misspell 1", raw_name="ABC Instt of Tech Pune", city="Pune")
show_resolution("misspell 2", raw_name="Abc technology institute pune", city="Pune")
show_resolution("misspell 3, no city", raw_name="ABC Instt of Tech")

# ---------- CHECK 3: same name, no city ----------
print("\n=== CHECK 3: no city ===")
show_resolution("no city", raw_name="National College of Engineering")

db.close()