import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models.institution import Institution
from backend.app.services.risk_scorer import InstitutionalRiskScorer
from backend.app.services.overlap_engine import ComplaintOverlapEngine

client = TestClient(app)

def test_overlaps_endpoint():
    print("=" * 80)
    print(" 1. AUTHENTICATING AND CALLING GET /overlaps AFTER FRESH SEED")
    print("=" * 80)
    
    # Login as Senior Management
    login_res = client.post("/auth/login", json={"email": "senior.mgmt@aicte.gov.in", "password": "Demo@123"})
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Call GET /overlaps
    res = client.get("/overlaps", headers=headers)
    assert res.status_code == 200, f"GET /overlaps failed: {res.text}"
    overlaps = res.json()
    
    print(f"Total CaseLinks returned by GET /overlaps: {len(overlaps)}")
    print(json.dumps(overlaps, indent=2))

    print("\n" + "=" * 80)
    print(" 2. VERIFYING ALL 4 TEST FINDINGS AGAINST THE LIVE API DATA")
    print("=" * 80)

    db = SessionLocal()
    overlap_engine = ComplaintOverlapEngine()
    overlap_engine.initialize_from_db(db)

    for i, row in enumerate(overlaps, 1):
        ca_id = row["case_a_case_id"]
        cb_id = row["case_b_case_id"]
        inst_name = row["institution_name"]
        score = row["similarity_score"]
        signals = row["signals"]
        reasons = row["reasons"]
        lead = row["suggested_lead_bureau_code"]
        rule = row["lead_suggestion_rule"]

        # Parse bureau from case_id: AICTE/{BUREAU}/2026/XXXXX
        bur_a = ca_id.split("/")[1]
        bur_b = cb_id.split("/")[1]

        print(f"\n--- Row {i}: {ca_id} ({bur_a}) vs {cb_id} ({bur_b}) @ '{inst_name}' ---")
        print(f"  * Different Bureaus: {bur_a != bur_b} ({bur_a} vs {bur_b})")
        print(f"  * Suggested Lead Bureau: {lead} -> In involved bureaus: {lead in [bur_a, bur_b]}")
        print(f"  * Stored Signals: {signals} -> Non-empty: {bool(signals)}")
        print(f"  * Stored Score: {score}")
        print(f"  * Engine Rule: {rule}")
        print(f"  * Engine Reasons: {reasons}")

    print("\n" + "=" * 80)
    print(" 3. SUNRISE INSTITUTE RISK SCORE & LEADERBOARD POSITION")
    print("=" * 80)
    sunrise = db.query(Institution).filter(Institution.permanent_id == "1-1099882233").first()
    score, bdown = InstitutionalRiskScorer.calculate_risk(sunrise.id, db)
    comps = bdown["components"]
    print(f"Institution: {sunrise.name} (PID: {sunrise.permanent_id})")
    print(f"1. Volume:             {comps['complaint_volume']['count']} cases -> {comps['complaint_volume']['points']:.2f} / {comps['complaint_volume']['max_points']} pts")
    print(f"2. Pending Ratio:      {comps['pending_ratio']['open_count']}/{comps['pending_ratio']['total_count']} open ({comps['pending_ratio']['ratio'] * 100:.1f}%) -> {comps['pending_ratio']['points']:.2f} / {comps['pending_ratio']['max_points']} pts")
    print(f"3. Severity Penalty:   {comps['severity_penalty']['critical_count']} Crit, {comps['severity_penalty']['high_count']} High -> {comps['severity_penalty']['points']:.2f} / {comps['severity_penalty']['max_points']} pts")
    print(f"4. Repeat Categories:  {comps['repeat_categories']['repeat_categories_list']} -> {comps['repeat_categories']['points']:.2f} / {comps['repeat_categories']['max_points']} pts")
    print(f"5. Active Overlaps:    {comps['unresolved_overlaps']['count']} active links -> {comps['unresolved_overlaps']['points']:.2f} / {comps['unresolved_overlaps']['max_points']} pts")
    print(f"Computed Risk Score:   {score:.2f} (Band: {bdown['band']})")

    # Check leaderboard
    institutions = db.query(Institution).all()
    ranks = []
    for inst in institutions:
        s, _ = InstitutionalRiskScorer.calculate_risk(inst.id, db)
        ranks.append((inst.permanent_id, inst.name, s))
    ranks.sort(key=lambda x: x[2], reverse=True)
    top_pid, top_name, top_score = ranks[0]
    second_pid, second_name, second_score = ranks[1]
    print(f"\nLeaderboard Rank #1: {top_name} ({top_pid}) with Score {top_score:.2f}")
    print(f"Leaderboard Rank #2: {second_name} ({second_pid}) with Score {second_score:.2f}")
    print(f"Sunrise stays first on the leaderboard: {top_pid == '1-1099882233'}")

    db.close()

if __name__ == "__main__":
    test_overlaps_endpoint()
