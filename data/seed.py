import os
import sys
import random
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import bcrypt
from backend.app.database import engine, Base, SessionLocal
from backend.app.models.institution import Institution
from backend.app.models.bureau import Bureau, Officer
from backend.app.models.complaint import Complaint
from backend.app.utils import utc_now
from backend.app.models.action_history import ActionHistory
from backend.app.models.case_link import CaseLink
from backend.app.models.alert import Alert


def hash_password(password: str) -> str:
    """Hash password securely using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


# Pre-hashed default password 'Demo@123' for fast seeding
DEFAULT_PASSWORD_HASH = hash_password("Demo@123")

COMPLAINT_CATEGORIES = [
    "Fee Related",
    "Faculty Shortage",
    "Infrastructure",
    "Approval/Affiliation Compliance",
    "Admission Irregularity",
    "Placement Misrepresentation",
    "Examination/Result",
    "Harassment/Student Welfare",
    "Fake/Unapproved Courses",
    "Other"
]

COMPLAINANT_TYPES = ["Student", "Faculty", "Parent", "Citizen"]
SOURCES = ["Portal", "CPGRAMS", "Email", "Letter"]
PRIORITIES = ["Low", "Medium", "High", "Critical"]
STATUSES = ["Pending", "Under Process", "Disposed", "Transferred", "Escalated"]

INDIAN_CITIES = [
    ("Mumbai", "Maharashtra", "West", "400001"),
    ("Pune", "Maharashtra", "West", "411001"),
    ("Nagpur", "Maharashtra", "West", "440001"),
    ("Ahmedabad", "Gujarat", "West", "380001"),
    ("Bengaluru", "Karnataka", "South", "560001"),
    ("Mysuru", "Karnataka", "South", "570001"),
    ("Chennai", "Tamil Nadu", "South", "600001"),
    ("Coimbatore", "Tamil Nadu", "South", "641001"),
    ("Hyderabad", "Telangana", "South", "500001"),
    ("Kolkata", "West Bengal", "East", "700001"),
    ("Bhubaneswar", "Odisha", "East", "751001"),
    ("Patna", "Bihar", "East", "800001"),
    ("Ranchi", "Jharkhand", "East", "834001"),
    ("New Delhi", "Delhi", "North", "110001"),
    ("Jaipur", "Rajasthan", "North", "302001"),
    ("Lucknow", "Uttar Pradesh", "North", "226001"),
    ("Kanpur", "Uttar Pradesh", "North", "208001"),
    ("Chandigarh", "Punjab", "North", "160001"),
    ("Bhopal", "Madhya Pradesh", "Central", "462001"),
    ("Indore", "Madhya Pradesh", "Central", "452001"),
    ("Raipur", "Chhattisgarh", "Central", "492001"),
    ("Guwahati", "Assam", "North-East", "781001"),
    ("Shillong", "Meghalaya", "North-East", "793001")
]

INST_PREFIXES = ["Apex", "National", "Global", "Imperial", "Vanguard", "Metropolitan", "Universal", "Modern", "Beacon", "Pioneer", "Silicon", "Zenith", "Horizon", "Sterling", "Elite", "Premier"]
INST_TYPES = ["Institute of Technology", "College of Engineering", "Institute of Management & Tech", "Engineering Academy", "Polytechnic Institute"]


def seed_database():
    """Seeds the SQLite database with 150 institutions, 450 complaints, and the 6 demo scenarios."""
    print("=" * 60)
    print("AICTE Integrated Portal - Seeding Synthetic Demo Data")
    print("=" * 60)

    # 1. Reset tables
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # ---------------------------------------------------------
        # 2. Seed Bureaus
        # ---------------------------------------------------------
        bureaus_data = [
            {"code": "RB", "name": "Regulation Bureau", "description": "Enforces statutory standards, unapproved course inquiries, and institutional compliance."},
            {"code": "PGRC", "name": "Public Grievance Redressal Cell", "description": "Handles individual student, faculty, and stakeholder grievances, fee refunds, and welfare."},
            {"code": "AB", "name": "Approval Bureau", "description": "Processes institution approvals, intake sanctioning, land/building norms, and expansions."},
            {"code": "AFB", "name": "Affiliation & Academic Bureau", "description": "Monitors university affiliations, curriculum compliance, and academic calendars."}
        ]

        bureau_map = {}
        for b_data in bureaus_data:
            bureau = Bureau(**b_data)
            db.add(bureau)
            db.flush()
            bureau_map[bureau.code] = bureau
        print(f"[OK] Seeded {len(bureau_map)} Bureaus.")

        # ---------------------------------------------------------
        # 3. Seed Officers
        # ---------------------------------------------------------
        officers_data = [
            {"name": "Dr. Ramesh Sharma", "email": "rb.officer@aicte.gov.in", "role": "RB Officer", "bureau_id": bureau_map["RB"].id, "region": None},
            {"name": "Ms. Sunita Patil", "email": "pgrc.officer@aicte.gov.in", "role": "PGRC Officer", "bureau_id": bureau_map["PGRC"].id, "region": None},
            {"name": "Shri Rajesh Verma", "email": "ab.officer@aicte.gov.in", "role": "AB Officer", "bureau_id": bureau_map["AB"].id, "region": None},
            {"name": "Dr. Ananya Sen", "email": "afb.officer@aicte.gov.in", "role": "AFB Officer", "bureau_id": bureau_map["AFB"].id, "region": None},
            {"name": "Shri Arvind Joshi", "email": "ro.west@aicte.gov.in", "role": "Regional Officer", "bureau_id": None, "region": "West"},
            {"name": "Dr. K. S. Venkatesh", "email": "senior.mgmt@aicte.gov.in", "role": "Senior Management", "bureau_id": None, "region": None},
            {"name": "System Administrator", "email": "admin@aicte.gov.in", "role": "Admin", "bureau_id": None, "region": None}
        ]

        officer_map = {}
        for o_data in officers_data:
            officer = Officer(password_hash=DEFAULT_PASSWORD_HASH, is_active=True, **o_data)
            db.add(officer)
            db.flush()
            officer_map[officer.email] = officer
        print(f"[OK] Seeded {len(officer_map)} Officers (Password: Demo@123).")

        # ---------------------------------------------------------
        # 4. Seed Institutions (Explicit Fixtures for Demo Scenarios)
        # ---------------------------------------------------------
        institutions = []

        # Scenario 1 Fixture: ABC Institute of Technology, Pune
        inst_abc_pune = Institution(
            permanent_id="1-1099238411",
            name="ABC Institute of Technology",
            normalized_name="abc institute of technology",
            aliases=["ABC Inst. of Tech.", "ABC Tech Pune", "AIT Pune"],
            address="Survey No. 42, Hinjawadi Phase 1, Pune",
            city="Pune",
            state="Maharashtra",
            region="West",
            pincode="411057",
            institution_type="Engineering & Technology",
            risk_score=68.5,
            risk_breakdown={"volume": 18.0, "pending": 15.0, "severity": 15.5, "repeats": 10.0, "overlaps": 10.0}
        )
        db.add(inst_abc_pune)
        institutions.append(inst_abc_pune)

        # Scenario 2 Fixtures: False Match Avoidance (Jaipur vs Raipur)
        inst_nat_jaipur = Institution(
            permanent_id="1-1099112233",
            name="National College of Engineering",
            normalized_name="national college of engineering",
            aliases=["NCE Jaipur", "National Engg Coll"],
            address="Sector 12, Malviya Nagar, Jaipur",
            city="Jaipur",
            state="Rajasthan",
            region="North",
            pincode="302017",
            institution_type="Engineering & Technology",
            risk_score=24.0,
            risk_breakdown={"volume": 9.0, "pending": 5.0, "severity": 5.0, "repeats": 5.0, "overlaps": 0.0}
        )
        inst_nat_raipur = Institution(
            permanent_id="1-1099445566",
            name="National College of Engineering",
            normalized_name="national college of engineering",
            aliases=["NCE Raipur"],
            address="VIP Estate, Near Airport, Raipur",
            city="Raipur",
            state="Chhattisgarh",
            region="Central",
            pincode="492006",
            institution_type="Engineering & Technology",
            risk_score=15.0,
            risk_breakdown={"volume": 6.0, "pending": 4.0, "severity": 5.0, "repeats": 0.0, "overlaps": 0.0}
        )
        db.add(inst_nat_jaipur)
        db.add(inst_nat_raipur)
        institutions.extend([inst_nat_jaipur, inst_nat_raipur])

        # Scenario 3 Fixtures: Bengaluru Ambiguous Match Trio
        inst_apex_1 = Institution(
            permanent_id="1-1099334411",
            name="Apex Institute of Technology",
            normalized_name="apex institute of technology",
            aliases=["Apex Tech", "AIT Bengaluru"],
            address="Whitefield Main Road, Bengaluru",
            city="Bengaluru",
            state="Karnataka",
            region="South",
            pincode="560066",
            institution_type="Engineering & Technology",
            risk_score=35.0,
            risk_breakdown={"volume": 12.0, "pending": 10.0, "severity": 8.0, "repeats": 5.0, "overlaps": 0.0}
        )
        inst_apex_2 = Institution(
            permanent_id="1-1099334422",
            name="Apex College of Engineering & Technology",
            normalized_name="apex college of engineering & technology",
            aliases=["Apex Engg & Tech"],
            address="Electronic City Phase 2, Bengaluru",
            city="Bengaluru",
            state="Karnataka",
            region="South",
            pincode="560100",
            institution_type="Engineering & Technology",
            risk_score=28.0,
            risk_breakdown={"volume": 9.0, "pending": 8.0, "severity": 6.0, "repeats": 5.0, "overlaps": 0.0}
        )
        inst_apex_3 = Institution(
            permanent_id="1-1099334433",
            name="Apex Polytechnic College",
            normalized_name="apex polytechnic college",
            aliases=["Apex Polytech"],
            address="Yelahanka New Town, Bengaluru",
            city="Bengaluru",
            state="Karnataka",
            region="South",
            pincode="560064",
            institution_type="Polytechnic Diploma",
            risk_score=18.0,
            risk_breakdown={"volume": 6.0, "pending": 5.0, "severity": 4.0, "repeats": 3.0, "overlaps": 0.0}
        )
        db.add(inst_apex_1)
        db.add(inst_apex_2)
        db.add(inst_apex_3)
        institutions.extend([inst_apex_1, inst_apex_2, inst_apex_3])

        # Scenario 6 Fixture: Sunrise Institute of Technology & Management (Risk Leaderboard #1)
        inst_sunrise = Institution(
            permanent_id="1-1099882233",
            name="Sunrise Institute of Technology & Management",
            normalized_name="sunrise institute of technology & management",
            aliases=["Sunrise Tech", "SITM Lucknow"],
            address="Faizabad Road, Chinhat, Lucknow",
            city="Lucknow",
            state="Uttar Pradesh",
            region="North",
            pincode="226028",
            institution_type="Management & Engineering",
            risk_score=81.6,
            risk_breakdown={"complaint_volume": 27.0, "pending_ratio": 15.6, "severity": 19.0, "repeat_categories": 10.0, "unresolved_overlaps": 10.0}
        )
        db.add(inst_sunrise)
        institutions.append(inst_sunrise)

        # Scenario 1b Fixture: Global Institute of Technology, Mumbai (Review Band Soft Alert)
        inst_global_mumbai = Institution(
            permanent_id="1-1099551122",
            name="Global Institute of Technology",
            normalized_name="global institute of technology",
            aliases=["GIT Mumbai", "Global Tech"],
            address="Kurla-Andheri Road, Sakinaka, Mumbai",
            city="Mumbai",
            state="Maharashtra",
            region="West",
            pincode="400072",
            institution_type="Engineering & Technology",
            risk_score=42.0,
            risk_breakdown={"complaint_volume": 12.0, "pending_ratio": 10.0, "severity": 10.0, "repeat_categories": 5.0, "unresolved_overlaps": 5.0}
        )
        db.add(inst_global_mumbai)
        institutions.append(inst_global_mumbai)

        # Scenario 1c Fixture: Imperial College of Engineering, Chennai (Negative Case - No Alert)
        inst_imperial_chennai = Institution(
            permanent_id="1-1099553344",
            name="Imperial College of Engineering",
            normalized_name="imperial college of engineering",
            aliases=["ICE Chennai", "Imperial Engg"],
            address="OMR IT Expressway, Sholinganallur, Chennai",
            city="Chennai",
            state="Tamil Nadu",
            region="South",
            pincode="600119",
            institution_type="Engineering & Technology",
            risk_score=20.0,
            risk_breakdown={"complaint_volume": 6.0, "pending_ratio": 6.0, "severity": 4.0, "repeat_categories": 0.0, "unresolved_overlaps": 0.0}
        )
        db.add(inst_imperial_chennai)
        institutions.append(inst_imperial_chennai)

        # Generate remaining ~141 institutions to reach exactly 150
        random.seed(42)
        perm_counter = 1099500000
        while len(institutions) < 150:
            perm_counter += 1
            prefix = random.choice(INST_PREFIXES)
            itype = random.choice(INST_TYPES)
            city_entry = random.choice(INDIAN_CITIES)
            city, state, region, pincode = city_entry
            inst_name = f"{prefix} {itype}"
            norm_name = inst_name.lower()
            perm_id = f"1-{perm_counter}"

            inst = Institution(
                permanent_id=perm_id,
                name=inst_name,
                normalized_name=norm_name,
                aliases=[f"{prefix} Tech", f"{prefix} Engg"],
                address=f"Plot No. {random.randint(10, 500)}, Knowledge Park, {city}",
                city=city,
                state=state,
                region=region,
                pincode=pincode,
                institution_type="Engineering & Technology" if "Engineering" in itype or "Technology" in itype else "Management",
                risk_score=round(random.uniform(10.0, 65.0), 1),
                risk_breakdown={"complaint_volume": random.randint(3, 18), "pending_ratio": random.randint(2, 12), "severity": random.randint(2, 12), "repeat_categories": 5, "unresolved_overlaps": 0}
            )
            db.add(inst)
            institutions.append(inst)

        db.flush()
        print(f"[OK] Seeded {len(institutions)} Institutions across all regions.")

        # ---------------------------------------------------------
        # 5. Seed Scripted Complaints for Demo Scenarios
        # ---------------------------------------------------------
        complaints = []
        now = utc_now()

        # SCENARIO 1: Strong Overlap (ABC Inst. of Tech, Pune)
        # Case A: PGRC Fee Grievance (Student voice)
        case_1a = Complaint(
            case_id="AICTE/PGRC/2026/00101",
            institution_id=inst_abc_pune.id,
            raw_institution_name="ABC Inst. of Tech., Pune",
            source="Portal",
            category="Fee Related",
            description="Student grievance against college for collecting Rs 25,000 unapproved caution money deposit and extra examination fees without receipt, refusing refund, and withholding hall ticket admit card.",
            complainant_type="Student",
            date_received=now - timedelta(days=33),
            status="Under Process",
            assigned_bureau_id=bureau_map["PGRC"].id,
            assigned_officer_id=officer_map["pgrc.officer@aicte.gov.in"].id,
            last_action="Notice dispatched to Principal seeking fee breakdown",
            next_action="Awaiting institutional explanation",
            last_action_date=now - timedelta(days=25),
            expected_disposal_date=now - timedelta(days=6),
            priority="High",
            is_overdue=True,
            is_escalated=False,
            match_confidence=0.96,
            needs_institution_review=False,
            candidate_institutions=[]
        )
        db.add(case_1a)
        db.flush()
        complaints.append(case_1a)

        # Case B: RB Regulatory Case (Official show-cause notice voice)
        case_1b = Complaint(
            case_id="AICTE/RB/2026/00204",
            institution_id=inst_abc_pune.id,
            raw_institution_name="ABC Institute of Technology, Pune",
            source="Letter",
            category="Approval/Affiliation Compliance",
            description="Show-cause notice to college regarding unauthorized collection of Rs 25,000 caution money deposit, charging extra examination fees without receipt, non-refund, and withholding student hall ticket admit card.",
            complainant_type="Faculty",
            date_received=now - timedelta(days=30),
            status="Under Process",
            assigned_bureau_id=bureau_map["RB"].id,
            assigned_officer_id=officer_map["rb.officer@aicte.gov.in"].id,
            last_action="Inspection report submitted by Expert Committee",
            next_action="Review response to Show-Cause Notice",
            last_action_date=now - timedelta(days=15),
            expected_disposal_date=now,
            priority="High",
            is_overdue=False,
            is_escalated=False,
            match_confidence=1.0,
            needs_institution_review=False,
            candidate_institutions=[]
        )
        db.add(case_1b)
        db.flush()
        complaints.append(case_1b)

        # Action history for Scenario 1 cases
        db.add(ActionHistory(complaint_id=case_1a.id, timestamp=case_1a.date_received, actor_name="SYSTEM", actor_role="Intake Portal", bureau_code="PGRC", action_type="received", remarks="Complaint registered via student portal", details={"source": "Portal"}))
        db.add(ActionHistory(complaint_id=case_1a.id, timestamp=now - timedelta(days=25), actor_name="Ms. Sunita Patil", actor_role="PGRC Officer", bureau_code="PGRC", action_type="assigned", remarks="Assigned to PGRC Desk 2", details={}))
        db.add(ActionHistory(complaint_id=case_1b.id, timestamp=case_1b.date_received, actor_name="SYSTEM", actor_role="Regulation Bureau", bureau_code="RB", action_type="received", remarks="Show-cause notice registered in RB", details={"source": "Letter"}))

        # Seed Overlap Record for Scenario 1
        case_link_1 = CaseLink(
            case_a_id=case_1a.id,
            case_b_id=case_1b.id,
            institution_id=inst_abc_pune.id,
            similarity_score=0.89,
            reasons=[
                "Same AICTE Permanent ID (1-1099238411)",
                "Active across different bureaus (PGRC and RB)",
                "High text similarity on Rs 25,000 caution money, unapproved exam charges, and admit card withholding",
                "Related categories: Fee Related and Approval/Affiliation Compliance",
                "Date proximity: Filed within 3 days of each other"
            ],
            suggested_lead_bureau_id=bureau_map["RB"].id,
            lead_suggestion_rule="RULE_STATUTORY_REGULATORY: Show-cause notice / statutory compliance inquiry in RB takes precedence -> RB Leads",
            status="suggested"
        )
        db.add(case_link_1)

        # SCENARIO 1b: Soft Overlap in Review Band (Global Institute of Technology, Mumbai)
        case_1b_a = Complaint(
            case_id="AICTE/PGRC/2026/00105",
            institution_id=inst_global_mumbai.id,
            raw_institution_name="Global Institute of Technology, Mumbai",
            source="Portal",
            category="Admission Irregularity",
            description="Student complains that college management demanded Rs 50,000 extra donation fee and unapproved development charges for management quota seat admission without issuing cash receipt.",
            complainant_type="Student",
            date_received=now - timedelta(days=20),
            status="Under Process",
            assigned_bureau_id=bureau_map["PGRC"].id,
            assigned_officer_id=officer_map["pgrc.officer@aicte.gov.in"].id,
            last_action="Grievance logged",
            next_action="Scrutiny of admission receipts",
            last_action_date=now - timedelta(days=18),
            expected_disposal_date=now + timedelta(days=10),
            priority="Medium",
            is_overdue=False,
            is_escalated=False,
            match_confidence=1.0,
            needs_institution_review=False,
            candidate_institutions=[]
        )
        case_1b_b = Complaint(
            case_id="AICTE/AB/2026/00205",
            institution_id=inst_global_mumbai.id,
            raw_institution_name="Global Institute of Technology, Mumbai",
            source="Letter",
            category="Approval/Affiliation Compliance",
            description="Inspection report regarding irregular admission seat allocation beyond sanctioned intake, collection of extra unapproved donation fee charges during quota admissions, and non-compliance with fee norms.",
            complainant_type="Citizen",
            date_received=now - timedelta(days=10),
            status="Under Process",
            assigned_bureau_id=bureau_map["AB"].id,
            assigned_officer_id=officer_map["ab.officer@aicte.gov.in"].id,
            last_action="Notice issued to verify admission lists against sanctioned intake",
            next_action="Awaiting intake ledger",
            last_action_date=now - timedelta(days=8),
            expected_disposal_date=now + timedelta(days=18),
            priority="Medium",
            is_overdue=False,
            is_escalated=False,
            match_confidence=1.0,
            needs_institution_review=False,
            candidate_institutions=[]
        )
        db.add(case_1b_a)
        db.add(case_1b_b)
        db.flush()
        complaints.extend([case_1b_a, case_1b_b])
        db.add(ActionHistory(complaint_id=case_1b_a.id, timestamp=case_1b_a.date_received, actor_name="SYSTEM", actor_role="Intake Portal", bureau_code="PGRC", action_type="received", remarks="Complaint registered via portal", details={}))
        db.add(ActionHistory(complaint_id=case_1b_b.id, timestamp=case_1b_b.date_received, actor_name="SYSTEM", actor_role="Approval Bureau", bureau_code="AB", action_type="received", remarks="Sanctioned intake scrutiny initiated", details={}))

        # Seed Overlap Record for Scenario 1b (Review Band)
        case_link_1b = CaseLink(
            case_a_id=case_1b_a.id,
            case_b_id=case_1b_b.id,
            institution_id=inst_global_mumbai.id,
            similarity_score=0.64,
            reasons=[
                "Same AICTE Permanent ID (1-1099551122)",
                "Active across different bureaus (PGRC and AB)",
                "Moderate text similarity on unapproved admission charges",
                "Related categories: Admission Irregularity and Approval/Affiliation Compliance",
                "Date proximity: Filed within 10 days of each other"
            ],
            suggested_lead_bureau_id=bureau_map["AB"].id,
            lead_suggestion_rule="RULE_INFRASTRUCTURE_APPROVAL: Admission quota norm violations governed by Approval Bureau -> AB Leads",
            status="suggested"
        )
        db.add(case_link_1b)

        # SCENARIO 1c: Negative Case - Unrelated Complaints (Imperial College of Engineering, Chennai)
        case_1c_a = Complaint(
            case_id="AICTE/PGRC/2026/00109",
            institution_id=inst_imperial_chennai.id,
            raw_institution_name="Imperial College of Engineering, Chennai",
            source="Portal",
            category="Harassment/Student Welfare",
            description="Hostel students complain regarding unhygienic mess food quality, water supply shortage in hostel blocks, and poor sanitation maintenance.",
            complainant_type="Student",
            date_received=now - timedelta(days=25),
            status="Under Process",
            assigned_bureau_id=bureau_map["PGRC"].id,
            assigned_officer_id=officer_map["pgrc.officer@aicte.gov.in"].id,
            last_action="Letter sent to hostel warden",
            next_action="Follow-up on mess committee",
            last_action_date=now - timedelta(days=15),
            expected_disposal_date=now + timedelta(days=5),
            priority="Medium",
            is_overdue=False,
            is_escalated=False,
            match_confidence=1.0,
            needs_institution_review=False,
            candidate_institutions=[]
        )
        case_1c_b = Complaint(
            case_id="AICTE/AB/2026/00209",
            institution_id=inst_imperial_chennai.id,
            raw_institution_name="Imperial College of Engineering, Chennai",
            source="Letter",
            category="Infrastructure",
            description="Notice issued for deficiency in mechanical engineering workshop machinery and laboratory safety certifications.",
            complainant_type="Citizen",
            date_received=now - timedelta(days=15),
            status="Under Process",
            assigned_bureau_id=bureau_map["AB"].id,
            assigned_officer_id=officer_map["ab.officer@aicte.gov.in"].id,
            last_action="Deficiency report noted",
            next_action="Compliance submission verification",
            last_action_date=now - timedelta(days=10),
            expected_disposal_date=now + timedelta(days=20),
            priority="Medium",
            is_overdue=False,
            is_escalated=False,
            match_confidence=1.0,
            needs_institution_review=False,
            candidate_institutions=[]
        )
        db.add(case_1c_a)
        db.add(case_1c_b)
        db.flush()
        complaints.extend([case_1c_a, case_1c_b])
        db.add(ActionHistory(complaint_id=case_1c_a.id, timestamp=case_1c_a.date_received, actor_name="SYSTEM", actor_role="Intake Portal", bureau_code="PGRC", action_type="received", remarks="Complaint registered via portal", details={}))
        db.add(ActionHistory(complaint_id=case_1c_b.id, timestamp=case_1c_b.date_received, actor_name="SYSTEM", actor_role="Approval Bureau", bureau_code="AB", action_type="received", remarks="Infrastructure notice registered", details={}))

        # Seed Alert for Scenario 1
        db.add(Alert(
            type="overlap",
            complaint_id=case_1a.id,
            institution_id=inst_abc_pune.id,
            message="Strong Overlap (88%) detected with Case AICTE/RB/2026/00204 across PGRC and RB. Coordination Required.",
            severity="critical",
            target_bureau_id=bureau_map["RB"].id,
            is_read=False
        ))

        # SCENARIO 2: False Match Avoidance (Jaipur vs Raipur)
        case_2a = Complaint(
            case_id="AICTE/AB/2026/00311",
            institution_id=inst_nat_jaipur.id,
            raw_institution_name="National College of Engineering, Jaipur",
            source="Portal",
            category="Infrastructure",
            description="Computer labs have insufficient terminal count and internet bandwidth below mandatory AICTE handbook specifications.",
            complainant_type="Student",
            date_received=now - timedelta(days=20),
            status="Under Process",
            assigned_bureau_id=bureau_map["AB"].id,
            assigned_officer_id=officer_map["ab.officer@aicte.gov.in"].id,
            last_action="Infrastructure checklist verified",
            next_action="Re-inspection scheduled",
            last_action_date=now - timedelta(days=10),
            expected_disposal_date=now + timedelta(days=25),
            priority="Medium",
            is_overdue=False,
            is_escalated=False,
            match_confidence=0.98,
            needs_institution_review=False,
            candidate_institutions=[]
        )
        case_2b = Complaint(
            case_id="AICTE/PGRC/2026/00312",
            institution_id=inst_nat_raipur.id,
            raw_institution_name="National College of Engineering, Raipur",
            source="Portal",
            category="Examination/Result",
            description="Withholding final year marksheet and degree transcript due to pending library fine controversy.",
            complainant_type="Student",
            date_received=now - timedelta(days=18),
            status="Under Process",
            assigned_bureau_id=bureau_map["PGRC"].id,
            assigned_officer_id=officer_map["pgrc.officer@aicte.gov.in"].id,
            last_action="Notice sent to COE",
            next_action="Awaiting response",
            last_action_date=now - timedelta(days=5),
            expected_disposal_date=now + timedelta(days=2),
            priority="Medium",
            is_overdue=False,
            is_escalated=False,
            match_confidence=0.98,
            needs_institution_review=False,
            candidate_institutions=[]
        )
        db.add(case_2a)
        db.add(case_2b)
        db.flush()
        complaints.extend([case_2a, case_2b])
        db.add(ActionHistory(complaint_id=case_2a.id, timestamp=case_2a.date_received, actor_name="SYSTEM", actor_role="Intake Portal", bureau_code="AB", action_type="received", remarks="Complaint registered via portal", details={}))
        db.add(ActionHistory(complaint_id=case_2b.id, timestamp=case_2b.date_received, actor_name="SYSTEM", actor_role="Intake Portal", bureau_code="PGRC", action_type="received", remarks="Complaint registered via portal", details={}))

        # SCENARIO 3: Human-Review Institution Match (Bengaluru Ambiguous)
        case_3 = Complaint(
            case_id="AICTE/PGRC/2026/00450",
            institution_id=None,  # Unresolved pending review
            raw_institution_name="Apex Tech College, Bengaluru",
            source="Email",
            category="Fee Related",
            description="College not refunding caution money deposit of Rs 25,000 even after issuing transfer certificate and completion of course.",
            complainant_type="Student",
            date_received=now - timedelta(days=12),
            status="Pending",
            assigned_bureau_id=bureau_map["PGRC"].id,
            assigned_officer_id=officer_map["pgrc.officer@aicte.gov.in"].id,
            last_action="Intake Scrutiny - Disambiguation Pending",
            next_action="Verify Institution identity from candidate list",
            last_action_date=now - timedelta(days=12),
            expected_disposal_date=now + timedelta(days=18),
            priority="Medium",
            is_overdue=False,
            is_escalated=False,
            match_confidence=0.73,
            needs_institution_review=True,
            candidate_institutions=[
                {"id": inst_apex_1.id, "name": inst_apex_1.name, "permanent_id": inst_apex_1.permanent_id, "city": "Bengaluru", "confidence": 0.73},
                {"id": inst_apex_2.id, "name": inst_apex_2.name, "permanent_id": inst_apex_2.permanent_id, "city": "Bengaluru", "confidence": 0.68},
                {"id": inst_apex_3.id, "name": inst_apex_3.name, "permanent_id": inst_apex_3.permanent_id, "city": "Bengaluru", "confidence": 0.62}
            ]
        )
        db.add(case_3)
        db.flush()
        complaints.append(case_3)
        db.add(ActionHistory(complaint_id=case_3.id, timestamp=case_3.date_received, actor_name="SYSTEM", actor_role="Intake Email", bureau_code="PGRC", action_type="received", remarks="Grievance received via email", details={}))

        # SCENARIO 4: Overdue Case Ready for Auto-Escalation
        case_4 = Complaint(
            case_id="AICTE/RB/2026/00045",
            institution_id=institutions[7].id,
            raw_institution_name=institutions[7].name,
            source="CPGRAMS",
            category="Faculty Shortage",
            description="Over 60 percent sanctioned faculty posts in Computer Science & Engineering department vacant for 3 academic sessions. Classes conducted by unqualified ad-hoc staff.",
            complainant_type="Faculty",
            date_received=now - timedelta(days=55),
            status="Under Process",
            assigned_bureau_id=bureau_map["RB"].id,
            assigned_officer_id=officer_map["rb.officer@aicte.gov.in"].id,
            last_action="Explanation letter sought from management",
            next_action="Review response",
            last_action_date=now - timedelta(days=35),
            expected_disposal_date=now - timedelta(days=23),  # 23 days overdue (> 7 days)
            priority="High",
            is_overdue=True,
            is_escalated=False,  # Ready to be auto-escalated live!
            match_confidence=1.0,
            needs_institution_review=False,
            candidate_institutions=[]
        )
        db.add(case_4)
        db.flush()
        complaints.append(case_4)
        db.add(ActionHistory(complaint_id=case_4.id, timestamp=case_4.date_received, actor_name="SYSTEM", actor_role="CPGRAMS Gateway", bureau_code="RB", action_type="received", remarks="CPGRAMS grievance forwarded to Regulation Bureau", details={}))

        # SCENARIO 6: Sunrise Institute of Technology (9 Complaints -> High Risk Score 82)
        sunrise_cats = [
            ("Fee Related", "High", "Under Process", 60),
            ("Fee Related", "Critical", "Pending", 45),
            ("Fee Related", "Medium", "Under Process", 30),
            ("Fee Related", "Low", "Disposed", 120),
            ("Faculty Shortage", "Critical", "Under Process", 40),
            ("Faculty Shortage", "High", "Under Process", 25),
            ("Faculty Shortage", "Medium", "Disposed", 90),
            ("Fake/Unapproved Courses", "High", "Under Process", 15),
            ("Harassment/Student Welfare", "Medium", "Under Process", 10)
        ]

        sunrise_cases = []
        for idx, (cat, prio, st, days_ago) in enumerate(sunrise_cats, start=1):
            s_case = Complaint(
                case_id=f"AICTE/RB/2026/0060{idx}",
                institution_id=inst_sunrise.id,
                raw_institution_name="Sunrise Institute of Technology & Management",
                source="Portal",
                category=cat,
                description=f"Serious issue regarding {cat.lower()} at Sunrise Institute campus affecting enrolled students.",
                complainant_type="Student" if idx % 2 == 0 else "Faculty",
                date_received=now - timedelta(days=days_ago),
                status=st,
                assigned_bureau_id=bureau_map["RB"].id if idx % 2 == 0 else bureau_map["PGRC"].id,
                assigned_officer_id=officer_map["rb.officer@aicte.gov.in"].id if idx % 2 == 0 else officer_map["pgrc.officer@aicte.gov.in"].id,
                last_action="Inquiry underway",
                next_action="Hearings scheduled",
                last_action_date=now - timedelta(days=max(1, days_ago - 5)),
                expected_disposal_date=now - timedelta(days=days_ago - 30),
                priority=prio,
                is_overdue=days_ago > 30 and st != "Disposed",
                is_escalated=False,
                match_confidence=1.0,
                needs_institution_review=False,
                candidate_institutions=[]
            )
            db.add(s_case)
            db.flush()
            sunrise_cases.append(s_case)
            complaints.append(s_case)
            db.add(ActionHistory(complaint_id=s_case.id, timestamp=s_case.date_received, actor_name="SYSTEM", actor_role="Intake Portal", bureau_code="RB" if idx % 2 == 0 else "PGRC", action_type="received", remarks=f"Complaint received for {cat}", details={}))

        # Seed 2 unresolved overlaps for Sunrise Institute
        link_s1 = CaseLink(
            case_a_id=sunrise_cases[0].id,
            case_b_id=sunrise_cases[1].id,
            institution_id=inst_sunrise.id,
            similarity_score=0.86,
            reasons=["Same AICTE Permanent ID", "High text similarity regarding illegal fee hikes", "Same category"],
            suggested_lead_bureau_id=bureau_map["PGRC"].id,
            lead_suggestion_rule="RULE_INDIVIDUAL_GRIEVANCE: Student fee dispute -> PGRC Leads",
            status="suggested"
        )
        link_s2 = CaseLink(
            case_a_id=sunrise_cases[4].id,
            case_b_id=sunrise_cases[7].id,
            institution_id=inst_sunrise.id,
            similarity_score=0.89,
            reasons=["Same AICTE Permanent ID", "Cross-bureau inquiry on unapproved faculty & course approval", "Related regulatory categories"],
            suggested_lead_bureau_id=bureau_map["RB"].id,
            lead_suggestion_rule="RULE_STATUTORY_REGULATORY: Unapproved course scrutiny -> RB Leads",
            status="suggested"
        )
        db.add(link_s1)
        db.add(link_s2)

        # ---------------------------------------------------------
        # 6. Generate Remaining Complaints to reach exactly 450
        # ---------------------------------------------------------
        # Filter out fixture institutions so scenario counts remain clean and isolated
        fixture_perm_ids = {
            "1-1099238411",  # ABC Pune (Scenario 1)
            "1-1099112233",  # NCE Jaipur (Scenario 2)
            "1-1099445566",  # NCE Raipur (Scenario 2)
            "1-1099334411",  # Apex Tech 1 (Scenario 3)
            "1-1099334422",  # Apex Tech 2 (Scenario 3)
            "1-1099334433",  # Apex Tech 3 (Scenario 3)
            "1-1099882233",  # Sunrise Lucknow (Scenario 6)
            "1-1099551122",  # Global Mumbai (Scenario 1b)
            "1-1099553344",  # Imperial Chennai (Scenario 1c)
        }
        general_institutions = [i for i in institutions if i.permanent_id not in fixture_perm_ids]

        bureaus_list = list(bureau_map.values())
        officers_list = list(officer_map.values())

        case_num = 1000
        while len(complaints) < 450:
            case_num += 1
            inst = random.choice(general_institutions)
            cat = random.choice(COMPLAINT_CATEGORIES)
            prio = random.choices(PRIORITIES, weights=[0.2, 0.5, 0.25, 0.05])[0]
            st = random.choices(STATUSES, weights=[0.25, 0.40, 0.25, 0.05, 0.05])[0]
            days_ago = random.randint(1, 400)
            date_rec = now - timedelta(days=days_ago)

            # Determine bureau assignment based on category realistically
            if cat in ["Approval/Affiliation Compliance", "Fake/Unapproved Courses"]:
                bureau = bureau_map["RB"]
            elif cat in ["Fee Related", "Harassment/Student Welfare", "Examination/Result"]:
                bureau = bureau_map["PGRC"]
            elif cat in ["Infrastructure", "Admission Irregularity"]:
                bureau = bureau_map["AB"]
            else:
                bureau = random.choice(bureaus_list)

            # Expected disposal calculation
            base_days = 30
            prio_mult = 1.0 if prio == "Medium" else (0.7 if prio == "High" else (0.4 if prio == "Critical" else 1.5))
            target_days = int(base_days * prio_mult)
            exp_date = date_rec + timedelta(days=target_days)
            is_od = (now > exp_date) and (st not in ["Disposed", "Transferred"])

            b_code = bureau.code
            case_id = f"AICTE/{b_code}/2025/{case_num:05d}" if days_ago > 90 else f"AICTE/{b_code}/2026/{case_num:05d}"

            complaint = Complaint(
                case_id=case_id,
                institution_id=inst.id,
                raw_institution_name=inst.name,
                source=random.choice(SOURCES),
                category=cat,
                description=f"Grievance filed regarding {cat.lower()} at {inst.name}. Complainant alleges non-compliance with AICTE regulations.",
                complainant_type=random.choice(COMPLAINANT_TYPES),
                date_received=date_rec,
                status=st,
                assigned_bureau_id=bureau.id,
                assigned_officer_id=random.choice(officers_list).id,
                last_action="Scrutiny note recorded",
                next_action="Awaiting institutional clarification" if st != "Disposed" else "Disposal letter issued",
                last_action_date=date_rec + timedelta(days=min(10, days_ago)),
                expected_disposal_date=exp_date,
                priority=prio,
                is_overdue=is_od,
                is_escalated=st == "Escalated",
                match_confidence=1.0,
                needs_institution_review=False,
                candidate_institutions=[]
            )
            db.add(complaint)
            db.flush()

            # Add ActionHistory entry for each complaint
            db.add(ActionHistory(
                complaint_id=complaint.id,
                timestamp=date_rec,
                actor_name="SYSTEM",
                actor_role="Intake Portal",
                bureau_code=bureau.code,
                action_type="received",
                remarks=f"Complaint received via {complaint.source}",
                details={"category": cat}
            ))
            complaints.append(complaint)

        db.commit()
        print(f"[OK] Seeded {len(complaints)} Complaints with ActionHistory audit logs.")
        print("[SUCCESS] Master synthetic database successfully initialized at data/aicte_portal.db")
        print("=" * 60)

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Failed to seed database: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
