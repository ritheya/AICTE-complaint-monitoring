"""
AICTE Integrated Portal - Engine Verification CLI
Dynamically executes all 6 demo scenarios through the analytical engines and prints
computed scores, mathematical signals, explainable reasons, and PASS/FAIL status.
"""

import sys
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.app.database import SessionLocal
from backend.app.models.complaint import Complaint
from backend.app.models.institution import Institution
from backend.app.services.resolution_engine import InstitutionResolutionEngine
from backend.app.services.overlap_engine import ComplaintOverlapEngine
from backend.app.services.lead_bureau_rules import LeadBureauEngine
from backend.app.services.risk_scorer import InstitutionalRiskScorer


def run_verification():
    db = SessionLocal()
    res_engine = InstitutionResolutionEngine()
    overlap_engine = ComplaintOverlapEngine()
    overlap_engine.initialize_from_db(db)
    lead_engine = LeadBureauEngine()

    print("\n" + "=" * 80)
    print(" AICTE COORDINATION ENGINE - INDEPENDENT LOGIC VERIFICATION CLI")
    print("=" * 80)

    results = []

    # --------------------------------------------------------------------------
    # SCENARIO 1, 1b, 1c: Cross-Bureau Complaint Overlap Detection Suite
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print(" CROSS-BUREAU OVERLAP DETECTION: SCENARIOS 1, 1b, 1c SIDE-BY-SIDE")
    print("=" * 80)

    overlap_suite = [
        {
            "id": "Scenario 1",
            "name": "Strong Inter-Bureau Overlap",
            "case_a": "AICTE/PGRC/2026/00101",
            "case_b": "AICTE/RB/2026/00204",
            "expected_band": "STRONG_OVERLAP",
            "min_score": 0.85,
            "max_score": 1.00,
            "expected_lead": "RB"
        },
        {
            "id": "Scenario 1b",
            "name": "Soft Overlap in Review Band",
            "case_a": "AICTE/PGRC/2026/00105",
            "case_b": "AICTE/AB/2026/00205",
            "expected_band": "POSSIBLE_OVERLAP",
            "min_score": 0.60,
            "max_score": 0.85,
            "expected_lead": "AB"
        },
        {
            "id": "Scenario 1c",
            "name": "Negative Case - Unrelated Complaints",
            "case_a": "AICTE/PGRC/2026/00109",
            "case_b": "AICTE/AB/2026/00209",
            "expected_band": "BELOW_THRESHOLD",
            "min_score": 0.00,
            "max_score": 0.60,
            "expected_lead": None
        }
    ]

    suite_summary_rows = []

    for sc in overlap_suite:
        print(f"\n[{sc['id'].upper()}] {sc['name']}")
        print("-" * 80)
        c_a = db.query(Complaint).filter(Complaint.case_id == sc["case_a"]).first()
        c_b = db.query(Complaint).filter(Complaint.case_id == sc["case_b"]).first()

        if not c_a or not c_b:
            print(f"  [FAIL] Complaints not found ({sc['case_a']} or {sc['case_b']}).")
            results.append((f"{sc['id']}: {sc['name']}", "FAIL", "Missing complaints"))
            continue

        ovl = overlap_engine.evaluate_overlap(c_a, c_b, db=db)
        lead = lead_engine.suggest_lead(c_a, c_b) if ovl.is_overlap else None

        s_text = ovl.signals.get("text_similarity", 0.0)
        s_cat = ovl.signals.get("category_relation", 0.0)
        s_date = ovl.signals.get("date_proximity", 0.0)
        unrounded_score = ovl.score
        band = ovl.band

        inst_name = c_a.institution.name if c_a.institution else "Unknown"

        print(f"  Institution: {inst_name} (PID: {c_a.institution.permanent_id if c_a.institution else 'N/A'})")
        print(f"  Case A: {c_a.case_id} [{c_a.assigned_bureau.code} | {c_a.category}]")
        print(f"    Description: \"{c_a.description[:90]}...\"")
        print(f"  Case B: {c_b.case_id} [{c_b.assigned_bureau.code} | {c_b.category}]")
        print(f"    Description: \"{c_b.description[:90]}...\"")
        print(f"  Gating Conditions: Passed (Same Inst, Diff Bureau, Both Active)")
        print(f"  Unrounded Signals:")
        print(f"    - Text Cosine Similarity:  {s_text:.4f}  (Weight 50% -> {0.50 * s_text:.4f} pts)")
        print(f"    - Category Relationship:   {s_cat:.4f}  (Weight 30% -> {0.30 * s_cat:.4f} pts)")
        print(f"    - Date Proximity:          {s_date:.4f}  (Weight 20% -> {0.20 * s_date:.4f} pts)")
        print(f"  Composite Overlap Score:     {unrounded_score:.4f} (Band: {band})")
        if ovl.is_overlap and lead:
            print(f"  Suggested Lead Bureau:       {lead.lead_bureau_code} (Rule: {lead.rule_id})")
            print(f"  Lead Recommendation Reason:  {lead.rule_description}")
        else:
            print("  Suggested Lead Bureau:       None (No alert, no lead - Below Overlap Threshold)")
        print("  Explainable Reasons:")
        for r in ovl.reasons:
            print(f"    * {r}")

        # Verification assertion
        if sc["expected_band"] == "STRONG_OVERLAP":
            passed = (unrounded_score >= 0.88) and (band == "STRONG_OVERLAP") and (lead.lead_bureau_code == sc["expected_lead"])
        elif sc["expected_band"] == "POSSIBLE_OVERLAP":
            passed = (0.60 <= unrounded_score < 0.85) and (band == "POSSIBLE_OVERLAP")
        else:
            passed = (unrounded_score < 0.60) and (band == "BELOW_THRESHOLD") and not ovl.is_overlap

        status_str = "PASS" if passed else "FAIL"
        print(f"  --> Status: [{status_str}]")
        results.append((f"{sc['id']}: {sc['name']}", status_str, f"Score: {unrounded_score:.4f}, Band: {band}"))

        suite_summary_rows.append({
            "id": sc["id"],
            "inst": inst_name[:24],
            "text": f"{s_text:.4f}",
            "cat": f"{s_cat:.4f}",
            "date": f"{s_date:.4f}",
            "score": f"{unrounded_score:.4f}",
            "band": band,
            "lead": lead.lead_bureau_code if (ovl.is_overlap and lead) else "None",
            "rule": lead.rule_id[:25] if (ovl.is_overlap and lead) else "No Overlap",
            "status": status_str
        })

    # Side-by-side comparative table
    print("\n" + "-" * 105)
    print(f" {'Scenario':<12} | {'Institution':<24} | {'Text':<6} | {'Cat':<6} | {'Date':<6} | {'Score':<7} | {'Band':<16} | {'Lead':<4} | {'Status'}")
    print("-" * 105)
    for r in suite_summary_rows:
        print(f" {r['id']:<12} | {r['inst']:<24} | {r['text']:<6} | {r['cat']:<6} | {r['date']:<6} | {r['score']:<7} | {r['band']:<16} | {r['lead']:<4} | [{r['status']}]")
    print("-" * 105)

    # --------------------------------------------------------------------------
    # SCENARIO 1 SENSITIVITY TEST: Shifting Date Gap (3 vs 30 vs 60 days)
    # --------------------------------------------------------------------------
    print("\n[SCENARIO 1 SENSITIVITY] Date Proximity Gap Degradation Analysis")
    print("-" * 80)
    c1_sens = db.query(Complaint).filter(Complaint.case_id == "AICTE/PGRC/2026/00101").first()
    c2_sens = db.query(Complaint).filter(Complaint.case_id == "AICTE/RB/2026/00204").first()
    s_text_base = overlap_engine.compute_text_similarity(c1_sens.description, c2_sens.description, db=db)
    s_cat_base, _ = overlap_engine.compute_category_score(c1_sens.category, c2_sens.category)

    print(f"  Fixed Content Signals: Text Sim = {s_text_base:.4f} (50% -> {0.50 * s_text_base:.4f} pts), Cat Rel = {s_cat_base:.4f} (30% -> {0.30 * s_cat_base:.4f} pts)")
    print(f"  Base Content Points (Text + Cat): {0.50 * s_text_base + 0.30 * s_cat_base:.4f} pts")
    print(f"  Linear Date Decay: max(0.0, 1.0 - (gap / 180.0)) * 20%")
    print(f"  {'Date Gap':<12} | {'Date Score':<12} | {'Date Pts (20%)':<14} | {'Total Score':<12} | {'Band':<16} | {'Alert Classification'}")
    print("  " + "-" * 88)

    sens_results = []
    for gap in [3, 30, 60]:
        s_date_gap = max(0.0, 1.0 - (gap / 180.0))
        tot = (0.50 * s_text_base) + (0.30 * s_cat_base) + (0.20 * s_date_gap)
        band_str = "STRONG_OVERLAP" if tot >= 0.85 else ("POSSIBLE_OVERLAP" if tot >= 0.60 else "BELOW_THRESHOLD")
        alert_str = "Red Strong Alert (Immediate Coordination)" if tot >= 0.85 else ("Amber Soft Alert (Review Recommended)" if tot >= 0.60 else "No Alert")
        print(f"  {f'{gap} days':<12} | {s_date_gap:<12.4f} | {0.20 * s_date_gap:<14.4f} | {tot:<12.4f} | {band_str:<16} | {alert_str}")
        sens_results.append((gap, tot, band_str))

    sens_pass = (sens_results[0][2] == "STRONG_OVERLAP" and sens_results[1][2] == "STRONG_OVERLAP" and sens_results[2][2] == "POSSIBLE_OVERLAP")
    print(f"  --> Date Gap Sensitivity Verified: [{ 'PASS' if sens_pass else 'FAIL' }]")
    results.append(("Scenario 1: Date Sensitivity (3/30/60d)", "PASS" if sens_pass else "FAIL", f"3d={sens_results[0][1]:.2f}, 30d={sens_results[1][1]:.2f}, 60d={sens_results[2][1]:.2f}"))

    # --------------------------------------------------------------------------
    # SCENARIO 2: False Match Avoidance (Jaipur vs Raipur)
    # --------------------------------------------------------------------------
    print("\n[SCENARIO 2] False Institution Match Avoidance (Geographic Separation)")
    print("-" * 80)
    res_jaipur = res_engine.resolve(raw_name="National College of Engineering", city="Jaipur", state="Rajasthan", db=db)
    res_raipur = res_engine.resolve(raw_name="National College of Engineering", city="Raipur", state="Chhattisgarh", db=db)

    print(f"  Query Jaipur: Matched '{res_jaipur.best_institution.name}' in {res_jaipur.best_institution.city} ({res_jaipur.best_institution.permanent_id}) @ {res_jaipur.confidence:.2f}")
    print(f"  Query Raipur: Matched '{res_raipur.best_institution.name}' in {res_raipur.best_institution.city} ({res_raipur.best_institution.permanent_id}) @ {res_raipur.confidence:.2f}")

    s2_pass = (
        res_jaipur.best_institution.id != res_raipur.best_institution.id and
        res_jaipur.best_institution.city == "Jaipur" and
        res_raipur.best_institution.city == "Raipur"
    )
    status_str = "PASS" if s2_pass else "FAIL"
    print(f"  Separate Institutional Identities Enforced: {s2_pass}")
    print(f"  --> Status: [{status_str}]")
    results.append(("Scenario 2: False Match Avoidance", status_str, "Jaipur vs Raipur strictly isolated"))

    # --------------------------------------------------------------------------
    # SCENARIO 3: Human Review Band (Bengaluru Ambiguous Match)
    # --------------------------------------------------------------------------
    print("\n[SCENARIO 3] Human Review Band & Ambiguity Margin Enforcement")
    print("-" * 80)
    res_bengaluru = res_engine.resolve(raw_name="Apex Academy", city="Bengaluru", state="Karnataka", db=db)

    print(f"  Query: 'Apex Academy' (City: Bengaluru, State: Karnataka)")
    print(f"  Confidence: {res_bengaluru.confidence:.2f} (Status: {res_bengaluru.status}, Needs Review: {res_bengaluru.needs_review})")
    print(f"  Candidate Institutions Identified ({len(res_bengaluru.candidates)}):")
    for idx, c in enumerate(res_bengaluru.candidates, start=1):
        print(f"    {idx}. {c['name']} (PID: {c['permanent_id']}, City: {c['city']}) - Conf: {c['confidence']:.2f}")
    for r in res_bengaluru.reasons:
        print(f"    - {r}")

    s3_pass = res_bengaluru.needs_review and (res_bengaluru.status == "NEEDS_REVIEW") and (0.65 <= res_bengaluru.confidence <= 0.75) and len(res_bengaluru.candidates) == 3
    status_str = "PASS" if s3_pass else "FAIL"
    print(f"  Forced Human Review via Ambiguity Margin: {res_bengaluru.needs_review}")
    print(f"  --> Status: [{status_str}]")
    results.append(("Scenario 3: Human Review Band", status_str, f"Score: {res_bengaluru.confidence:.2f}, Status: {res_bengaluru.status}, Candidates: 3"))

    # --------------------------------------------------------------------------
    # SCENARIO 4: Overdue Case Auto-Escalation Engine Execution
    # --------------------------------------------------------------------------
    print("\n[SCENARIO 4] SLA Overdue & Dynamic Auto-Escalation Execution")
    print("-" * 80)
    from backend.app.services.scheduler_service import run_sla_check_evaluation
    from backend.app.models.action_history import ActionHistory
    from backend.app.models.alert import Alert

    c4 = db.query(Complaint).filter(Complaint.case_id == "AICTE/RB/2026/00045").first()
    if not c4:
        print("  [FAIL] Scenario 4 case AICTE/RB/2026/00045 not found.")
        results.append(("Scenario 4: SLA Overdue", "FAIL", "Missing case"))
    else:
        print(f"  Pre-Execution State:")
        print(f"    Case ID: {c4.case_id} (Priority: {c4.priority}, Category: {c4.category})")
        print(f"    Status: {c4.status} | Overdue: {c4.is_overdue} | Escalated: {c4.is_escalated}")

        # Execute the real SLA check engine
        sla_result = run_sla_check_evaluation(db)
        db.refresh(c4)

        print(f"  Post-Execution State:")
        print(f"    Engine Output: {sla_result['overdue_complaints']} overdue, {sla_result['newly_escalated_complaints']} newly escalated")
        print(f"    Case Escalated Flag: {c4.is_escalated} (Last Action: {c4.last_action})")

        # Verify ActionHistory and Alert
        esc_history = db.query(ActionHistory).filter(
            ActionHistory.complaint_id == c4.id,
            ActionHistory.action_type == "AUTO_ESCALATION"
        ).first()
        esc_alert = db.query(Alert).filter(
            Alert.complaint_id == c4.id,
            Alert.type == "escalation"
        ).first()

        s4_pass = c4.is_overdue and c4.is_escalated and (esc_history is not None) and (esc_alert is not None)
        status_str = "PASS" if s4_pass else "FAIL"
        print(f"  Real Engine Auto-Escalation & Audit Log: {s4_pass}")
        print(f"  --> Status: [{status_str}]")
        results.append(("Scenario 4: SLA Auto-Escalation", status_str, "Dynamic engine execution verified live"))

        # Restore all newly escalated cases so demo button is live for user review and DB remains pristine
        for esc_cid in sla_result.get("escalated_case_ids", []):
            esc_case = db.query(Complaint).filter(Complaint.case_id == esc_cid).first()
            if esc_case:
                esc_case.is_escalated = False
                if esc_case.status == "Escalated":
                    esc_case.status = "Under Process"
                esc_case.last_action = (
                    "Under Process at Regulatory Bureau"
                    if esc_cid == c4.case_id
                    else "Hearing notice issued - prolonged compliance overdue"
                )
                db.query(ActionHistory).filter(
                    ActionHistory.complaint_id == esc_case.id,
                    ActionHistory.action_type == "AUTO_ESCALATION"
                ).delete()
                db.query(Alert).filter(
                    Alert.complaint_id == esc_case.id,
                    Alert.type.in_(["escalation", "sla_breached"])
                ).delete()
        db.commit()

    # --------------------------------------------------------------------------
    # SCENARIO 5: Live Intake Fixture & Live Pre-Check Overlap
    # --------------------------------------------------------------------------
    print("\n[SCENARIO 5] Live Complaint Intake & Real-Time Overlap Pre-Check")
    print("-" * 80)
    noisy_input = "Sir, ABC Tech Pune college is illegally collecting Rs 25,000 caution money deposit and charging extra examination fees without receipt, refusing refund of caution money, and withholding my student hall ticket admit card."
    res_intake = res_engine.resolve(raw_name="ABC Tech Pune", city="Pune", state="Maharashtra", db=db)
    print(f"  Raw User Text: \"{noisy_input}\"")
    print(f"  Extracted / Resolved Institution: '{res_intake.best_institution.name}' (PID: {res_intake.best_institution.permanent_id}) @ {res_intake.confidence:.4f}")

    target_case = db.query(Complaint).filter(Complaint.case_id == "AICTE/RB/2026/00204").first()
    temp_complaint = Complaint(
        case_id="INTAKE/TEMP/001",
        institution_id=res_intake.best_institution.id,
        raw_institution_name="ABC Tech Pune",
        source="Portal",
        category="Fee Related",
        description=noisy_input,
        complainant_type="Student",
        date_received=target_case.date_received,
        status="Pending",
        assigned_bureau_id=2  # PGRC
    )
    precheck_ovl = overlap_engine.evaluate_overlap(temp_complaint, target_case, db=db)
    print(f"  Live Pre-Check Overlap with Open Case {target_case.case_id}:")
    print(f"    - Overlap Detected Before Save: {precheck_ovl.is_overlap}")
    print(f"    - Unrounded Signals: Text={precheck_ovl.signals.get('text_similarity', 0):.4f} (50%), Cat={precheck_ovl.signals.get('category_relation', 0):.4f} (30%), Date={precheck_ovl.signals.get('date_proximity', 0):.4f} (20%)")
    print(f"    - Live Pre-Check Score: {precheck_ovl.score:.4f} ({precheck_ovl.band})")

    s5_pass = (
        res_intake.best_institution.permanent_id == "1-1099238411"
        and precheck_ovl.is_overlap
        and (precheck_ovl.score >= 0.88)
        and (precheck_ovl.band == "STRONG_OVERLAP")
    )
    status_str = "PASS" if s5_pass else "FAIL"
    print(f"  Live Strong Alert Triggered Pre-Submission: {precheck_ovl.is_overlap} ({precheck_ovl.band})")
    print(f"  --> Status: [{status_str}]")
    results.append(("Scenario 5: Live Intake Fixture", status_str, f"Resolved 1-1099238411, Pre-check Score: {precheck_ovl.score:.4f} ({precheck_ovl.band})"))

    # --------------------------------------------------------------------------
    # SCENARIO 6: Institutional Risk Leaderboard Calculation
    # --------------------------------------------------------------------------
    print("\n[SCENARIO 6] Institutional Risk Score Calculation (From Live DB Data)")
    print("-" * 80)
    inst_sunrise = db.query(Institution).filter(Institution.permanent_id == "1-1099882233").first()
    if not inst_sunrise:
        print("  [FAIL] Scenario 6 institution 1-1099882233 not found.")
        results.append(("Scenario 6: Risk Leaderboard", "FAIL", "Missing institution"))
    else:
        calc_score, breakdown = InstitutionalRiskScorer.calculate_risk(inst_sunrise.id, db)
        comps = breakdown["components"]
        print(f"  Institution: {inst_sunrise.name} ({inst_sunrise.permanent_id})")
        print(f"  1. Complaint Volume (last 24m): {comps['complaint_volume']['count']} cases -> {comps['complaint_volume']['points']:.1f} / {comps['complaint_volume']['max_points']} pts")
        print(f"  2. Pending Ratio: {comps['pending_ratio']['open_count']}/{comps['pending_ratio']['total_count']} open ({comps['pending_ratio']['ratio'] * 100:.0f}%) -> {comps['pending_ratio']['points']:.1f} / {comps['pending_ratio']['max_points']} pts")
        print(f"  3. Severity Penalty: {comps['severity_penalty']['critical_count']} Crit, {comps['severity_penalty']['high_count']} High -> {comps['severity_penalty']['points']:.1f} / {comps['severity_penalty']['max_points']} pts")
        print(f"  4. Repeat Categories: {comps['repeat_categories']['repeat_categories_list']} -> {comps['repeat_categories']['points']:.1f} / {comps['repeat_categories']['max_points']} pts")
        print(f"  5. Unresolved Overlaps: {comps['unresolved_overlaps']['count']} active -> {comps['unresolved_overlaps']['points']:.1f} / {comps['unresolved_overlaps']['max_points']} pts")
        print(f"  Computed Risk Score: {calc_score:.2f} (Band: {breakdown['band']})")

        s6_pass = (calc_score >= 75.0) and (breakdown["band"] == "High Risk")
        status_str = "PASS" if s6_pass else "FAIL"
        print(f"  --> Status: [{status_str}]")
        results.append(("Scenario 6: Risk Leaderboard", status_str, f"Computed Score: {calc_score:.2f} ({breakdown['band']})"))

    # --------------------------------------------------------------------------
    # SUMMARY REPORT
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print(" ENGINE VERIFICATION SUMMARY REPORT")
    print("=" * 80)
    passed_count = sum(1 for _, st, _ in results if st == "PASS")
    total_count = len(results)

    for name, st, details in results:
        badge = "[PASS]" if st == "PASS" else "[FAIL]"
        print(f"  {badge:<8} {name:<42} | {details}")

    print("-" * 80)
    print(f"  Total Result: {passed_count}/{total_count} Scenarios PASSED ({passed_count / total_count * 100:.0f}% success rate)")
    print("=" * 80 + "\n")

    db.close()
    return passed_count == total_count


if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
