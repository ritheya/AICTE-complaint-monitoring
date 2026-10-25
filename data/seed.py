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
from backend.app.services.overlap_engine import ComplaintOverlapEngine
from backend.app.services.lead_bureau_rules import LeadBureauEngine


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

CATEGORY_DESCRIPTION_TEMPLATES = {
    "Fee Related": [
        "Dispute over unapproved exam re-evaluation fee charged per subject without official receipt.",
        "College management withholding original educational certificates over pending library charges.",
        "Tuition fee increased mid-year by 25 percent without university fee committee notification.",
        "Refund of admission cancellation charges withheld beyond 30 days statutory window.",
        "Mandatory extra development fees demanded for unutilized transport and laboratory facilities.",
        "Demand for non-refundable caution deposit during second semester registration."
    ],
    "Faculty Shortage": [
        "No regular faculty appointed for specialized artificial intelligence elective courses.",
        "Cadre ratio severely skewed with zero professors in electronics and communications department.",
        "Guest lecturers conducting mandatory core subjects without AICTE requisite qualifications.",
        "Dean and department head positions vacant for over six months affecting course delivery.",
        "Assistant professors engaged on ad-hoc ten-month contracts with delayed salary disbursement."
    ],
    "Infrastructure": [
        "Computer laboratory internet bandwidth insufficient for mandatory online coursework.",
        "Central library lacks prescribed syllabus reference textbooks for mechanical engineering.",
        "Fire safety clearance certificate expired and no operational extinguishers in hostel block.",
        "Boys hostel drinking water filtration plant non-functional for past two months.",
        "Machine tool workshop equipment outdated and non-operational for practical examinations."
    ],
    "Approval/Affiliation Compliance": [
        "Institution operating from temporary premises exceeding five year permissible tenure.",
        "Mandatory disclosure link missing on official college website in violation of AICTE norms.",
        "Land and built-up instructional area deficiency observed during university affiliation review.",
        "Running unapproved post-graduate diploma tracks without regulatory council sanction."
    ],
    "Admission Irregularity": [
        "Management quota seat allotment executed without publishing merit list on public portal.",
        "Cutoff marks lowered for direct spot admission in violation of state counseling guidelines.",
        "Admissions conducted beyond sanctioned student intake cap for computer science branch."
    ],
    "Placement Misrepresentation": [
        "Admission brochure claims 100 percent placement assistance but no campus drives conducted.",
        "Placement statistics inflated by including off-campus non-technical telecalling roles."
    ],
    "Examination/Result": [
        "Internal assessment marks withheld due to attendance calculation dispute in third year.",
        "Semester marksheet issuance delayed by over 90 days preventing placement onboarding.",
        "Discrepancy in practical examination grading not addressed by controller of examinations."
    ],
    "Harassment/Student Welfare": [
        "Internal complaints committee not constituted as per AICTE gender sensitization regulations.",
        "Grievance redressal cell portal non-functional and written student complaints ignored.",
        "Hostel curfew hours and punitive fines imposed arbitrarily without warden hearing."
    ],
    "Fake/Unapproved Courses": [
        "Institution advertising technical diploma program without AICTE extension of approval letter.",
        "Autonomous certificate course marketed as an AICTE recognized degree program."
    ],
    "Other": [
        "Administrative office staff refusing to issue bonafide certificate for education loan processing.",
        "Delay in processing duplicate student identity card request submitted two months ago."
    ]
}

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

GENERATED_INST_PREFIXES = [
    "Vanguard", "Metropolitan", "Universal", "Modern", "Beacon", "Pioneer",
    "Silicon", "Zenith", "Horizon", "Sterling", "Elite", "Premier",
    "Pinnacle", "Paramount", "Summit", "Galaxy", "Nova", "Heritage",
    "Trinity", "Loyola", "St. Xavier's", "Oxford", "Cambridge", "Vidya",
    "Pratibha", "Aryabhatta", "Chanakya", "Vivekananda", "Tagore", "Ramanujan",
    "Visvesvaraya", "Bhabha", "Kalam", "Sarabhai", "Bose", "Drona",
    "Acharya", "Sigma", "Matrix", "Kaveri", "Godavari", "Ganga",
    "Himalaya", "Vindhya", "Sahyadri", "Nilgiri", "Saraswati", "Nalanda",
    "Takshashila", "Indus"
]
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

    # Reset in-memory rate limiter so no accounts are blocked on fresh seed
    from backend.app.auth.security import login_rate_limiter
    login_rate_limiter._attempts.clear()

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

        # Explicit fixtures for resolution tests
        inst_premier_pune = Institution(
            permanent_id="1-1099667788",
            name="Premier Institute of Technology",
            normalized_name="premier institute of technology",
            aliases=["Premier Tech Pune", "PIT Pune"],
            address="Paud Road, Kothrud, Pune",
            city="Pune",
            state="Maharashtra",
            region="West",
            pincode="411038",
            institution_type="Engineering & Technology",
            risk_score=22.0,
            risk_breakdown={"complaint_volume": 5.0, "pending_ratio": 4.0, "severity": 4.0, "repeat_categories": 0.0, "unresolved_overlaps": 0.0}
        )
        inst_nea_delhi = Institution(
            permanent_id="1-1099667799",
            name="National Engineering Academy",
            normalized_name="national engineering academy",
            aliases=["NEA Delhi", "National Engg"],
            address="Pusa Road, Karol Bagh, New Delhi",
            city="New Delhi",
            state="Delhi",
            region="North",
            pincode="110005",
            institution_type="Engineering & Technology",
            risk_score=26.0,
            risk_breakdown={"complaint_volume": 7.0, "pending_ratio": 5.0, "severity": 5.0, "repeat_categories": 0.0, "unresolved_overlaps": 0.0}
        )
        db.add(inst_premier_pune)
        db.add(inst_nea_delhi)
        institutions.extend([inst_premier_pune, inst_nea_delhi])

        # Generate remaining institutions to reach exactly 150
        random.seed(42)
        perm_counter = 1099500000

        used_institution_names = set(inst.name.lower() for inst in institutions)
        used_aliases = set(alias.lower() for inst in institutions for alias in (inst.aliases or []))

        while len(institutions) < 150:
            perm_counter += 1
            city_entry = random.choice(INDIAN_CITIES)
            city, state, region, pincode = city_entry

            # Select unique institution name
            candidate_name = None
            for _ in range(50):
                prefix = random.choice(GENERATED_INST_PREFIXES)
                itype = random.choice(INST_TYPES)
                trial_name = f"{prefix} {itype}"
                if trial_name.lower() in used_institution_names:
                    trial_name = f"{prefix} {itype} of {city}"
                if trial_name.lower() in used_institution_names:
                    trial_name = f"{prefix} Regional {itype} ({city})"
                if trial_name.lower() not in used_institution_names:
                    candidate_name = trial_name
                    break

            if not candidate_name:
                candidate_name = f"Institute of Technical Sciences {city} {perm_counter % 1000}"

            used_institution_names.add(candidate_name.lower())
            norm_name = candidate_name.lower()
            perm_id = f"1-{perm_counter}"

            # Generate strictly unique aliases per institution
            inst_aliases = []
            alias_1 = f"{prefix} Tech ({city})"
            alias_2 = f"{prefix} Engg ({city})"
            if alias_1.lower() not in used_aliases:
                inst_aliases.append(alias_1)
                used_aliases.add(alias_1.lower())
            if alias_2.lower() not in used_aliases:
                inst_aliases.append(alias_2)
                used_aliases.add(alias_2.lower())
            if not inst_aliases:
                fallback_alias = f"{prefix}-{city[:3].upper()}-{perm_counter % 1000}"
                inst_aliases.append(fallback_alias)
                used_aliases.add(fallback_alias.lower())

            inst = Institution(
                permanent_id=perm_id,
                name=candidate_name,
                normalized_name=norm_name,
                aliases=inst_aliases,
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

        # Note: CaseLinks and Overlap Alerts are generated dynamically via ComplaintOverlapEngine below

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

        # Note: CaseLink for Scenario 1b generated dynamically via ComplaintOverlapEngine below

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

        # SCENARIO 6: Sunrise Institute of Technology (9 Complaints -> Genuine Cross-Bureau Overlaps & High Risk)
        sunrise_cases_data = [
            # Case 1 (idx=1): Overdue by 12 days, High priority, Under Process, Fee Related (Overlap Pair 1)
            {
                "case_id": "AICTE/PGRC/2026/00601",
                "bureau_code": "PGRC",
                "officer_email": "pgrc.officer@aicte.gov.in",
                "category": "Fee Related",
                "priority": "High",
                "status": "Under Process",
                "days_ago": 48,
                "complainant": "Student",
                "desc": "Student grievance regarding unauthorized annual development fee of Rs 40,000 charged without official receipts and refusal to refund caution deposit upon discontinuation.",
                "last_act": "Explanation letter sought from management",
                "next_act": "Hearings scheduled",
                "is_overdue": True,
                "exp_date": now - timedelta(days=12)
            },
            # Case 2 (idx=2): Overdue by 4 days, Critical priority, Pending, Approval/Affiliation Compliance (Overlap Pair 1)
            {
                "case_id": "AICTE/RB/2026/00602",
                "bureau_code": "RB",
                "officer_email": "rb.officer@aicte.gov.in",
                "category": "Approval/Affiliation Compliance",
                "priority": "Critical",
                "status": "Pending",
                "days_ago": 45,
                "complainant": "Citizen",
                "desc": "Regulatory show-cause inquiry into unauthorized tuition and development fee levy of Rs 40,000 beyond approved fee regulatory committee caps and non-refund of security deposits.",
                "last_act": "Show-cause notice served to governing body",
                "next_act": "Awaiting response",
                "is_overdue": True,
                "exp_date": now - timedelta(days=4)
            },
            # Case 3 (idx=3): Within SLA, Medium priority, Under Process, Fee Related
            {
                "case_id": "AICTE/PGRC/2026/00603",
                "bureau_code": "PGRC",
                "officer_email": "pgrc.officer@aicte.gov.in",
                "category": "Fee Related",
                "priority": "Medium",
                "status": "Under Process",
                "days_ago": 30,
                "complainant": "Student",
                "desc": "Grievance from M.Tech student regarding delay in stipend disbursement under AICTE PG scholarship scheme.",
                "last_act": "Verification with finance division",
                "next_act": "Fund reconciliation",
                "is_overdue": False,
                "exp_date": now + timedelta(days=5)
            },
            # Case 4 (idx=4): Disposed, Low priority, Fee Related
            {
                "case_id": "AICTE/RB/2026/00604",
                "bureau_code": "RB",
                "officer_email": "rb.officer@aicte.gov.in",
                "category": "Fee Related",
                "priority": "Low",
                "status": "Disposed",
                "days_ago": 120,
                "complainant": "Parent",
                "desc": "Disposed inquiry concerning delayed refund of hostel caution money for 2024 academic batch.",
                "last_act": "Compliance verified and refund order executed",
                "next_act": "Case closed",
                "is_overdue": False,
                "exp_date": now - timedelta(days=90)
            },
            # Case 5 (idx=5): Overdue by 3 days, Critical priority, Under Process, Faculty Shortage (Overlap Pair 2)
            {
                "case_id": "AICTE/PGRC/2026/00605",
                "bureau_code": "PGRC",
                "officer_email": "pgrc.officer@aicte.gov.in",
                "category": "Faculty Shortage",
                "priority": "Critical",
                "status": "Under Process",
                "days_ago": 22,
                "complainant": "Faculty",
                "desc": "Faculty and student complaint that Computer Science department is operating with 70 percent unqualified ad-hoc staff and severe cadre ratio deficiency for AICTE approved programs.",
                "last_act": "Staff verification inspection deputed",
                "next_act": "Scrutiny of faculty register",
                "is_overdue": True,
                "exp_date": now - timedelta(days=3)
            },
            # Case 6 (idx=6): Within SLA, High priority, Under Process, Faculty Shortage
            {
                "case_id": "AICTE/RB/2026/00606",
                "bureau_code": "RB",
                "officer_email": "rb.officer@aicte.gov.in",
                "category": "Faculty Shortage",
                "priority": "High",
                "status": "Under Process",
                "days_ago": 25,
                "complainant": "Citizen",
                "desc": "Notice issued regarding non-submission of annual biometric attendance records for Electrical engineering department.",
                "last_act": "Compliance sought from principal",
                "next_act": "Review biometric report",
                "is_overdue": False,
                "exp_date": now + timedelta(days=10)
            },
            # Case 7 (idx=7): Disposed, Medium priority, Faculty Shortage
            {
                "case_id": "AICTE/PGRC/2026/00607",
                "bureau_code": "PGRC",
                "officer_email": "pgrc.officer@aicte.gov.in",
                "category": "Faculty Shortage",
                "priority": "Medium",
                "status": "Disposed",
                "days_ago": 90,
                "complainant": "Faculty",
                "desc": "Resolved grievance regarding guest lecture honorarium in Civil engineering department.",
                "last_act": "Payment disbursed by college bursar",
                "next_act": "Case closed",
                "is_overdue": False,
                "exp_date": now - timedelta(days=60)
            },
            # Case 8 (idx=8): Within SLA, High priority, Under Process, Approval/Affiliation Compliance (Overlap Pair 2)
            {
                "case_id": "AICTE/AB/2026/00608",
                "bureau_code": "AB",
                "officer_email": "ab.officer@aicte.gov.in",
                "category": "Approval/Affiliation Compliance",
                "priority": "High",
                "status": "Under Process",
                "days_ago": 20,
                "complainant": "Citizen",
                "desc": "Approval Bureau inspection regarding cadre ratio deficiencies, severe faculty vacancy exceeding 70 percent in technical courses, and violation of sanctioned intake approval norms.",
                "last_act": "Approval Bureau team inspection conducted",
                "next_act": "Preparation of deficiency notice",
                "is_overdue": False,
                "exp_date": now + timedelta(days=15)
            },
            # Case 9 (idx=9): Within SLA, Medium priority, Under Process, Harassment/Student Welfare
            {
                "case_id": "AICTE/PGRC/2026/00609",
                "bureau_code": "PGRC",
                "officer_email": "pgrc.officer@aicte.gov.in",
                "category": "Harassment/Student Welfare",
                "priority": "Medium",
                "status": "Under Process",
                "days_ago": 10,
                "complainant": "Student",
                "desc": "Student representation regarding hostel mess hygiene and lack of clean drinking water facilities.",
                "last_act": "Warden response requested",
                "next_act": "Health inspection check",
                "is_overdue": False,
                "exp_date": now + timedelta(days=25)
            }
        ]

        sunrise_cases = []
        for cdata in sunrise_cases_data:
            s_case = Complaint(
                case_id=cdata["case_id"],
                institution_id=inst_sunrise.id,
                raw_institution_name="Sunrise Institute of Technology & Management",
                source="Portal",
                category=cdata["category"],
                description=cdata["desc"],
                complainant_type=cdata["complainant"],
                date_received=now - timedelta(days=cdata["days_ago"]),
                status=cdata["status"],
                assigned_bureau_id=bureau_map[cdata["bureau_code"]].id,
                assigned_officer_id=officer_map[cdata["officer_email"]].id,
                last_action=cdata["last_act"],
                next_action=cdata["next_act"],
                last_action_date=now - timedelta(days=max(1, cdata["days_ago"] - 5)),
                expected_disposal_date=cdata["exp_date"],
                priority=cdata["priority"],
                is_overdue=cdata["is_overdue"],
                is_escalated=False,
                match_confidence=1.0,
                needs_institution_review=False,
                candidate_institutions=[]
            )
            db.add(s_case)
            db.flush()
            sunrise_cases.append(s_case)
            complaints.append(s_case)
            db.add(ActionHistory(
                complaint_id=s_case.id,
                timestamp=s_case.date_received,
                actor_name="SYSTEM",
                actor_role="Intake Portal",
                bureau_code=cdata["bureau_code"],
                action_type="received",
                remarks=f"Complaint received for {cdata['category']}",
                details={}
            ))

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
            "1-1099667788",  # Premier Pune (Resolution test fixture)
            "1-1099667799",  # NEA Delhi (Resolution test fixture)
        }
        general_institutions = [i for i in institutions if i.permanent_id not in fixture_perm_ids]

        bureaus_list = list(bureau_map.values())
        officers_list = list(officer_map.values())

        # Deterministic seed for reproducible dataset metrics
        random.seed(42)

        # Realistic distribution for remaining 432 complaints:
        # - 210 Disposed (~48.6%) -> Disposed cases NEVER overdue
        # - 105 Pending (~24.3%)
        # - 105 Under Process (~24.3%)
        # - 6 Escalated (~1.4%)
        # - 6 Transferred (~1.4%)
        planned_statuses = (
            ["Disposed"] * 209 +
            ["Pending"] * 105 +
            ["Under Process"] * 105 +
            ["Escalated"] * 6 +
            ["Transferred"] * 6
        )
        random.shuffle(planned_statuses)

        # Out of open cases (210), partition into realistic operational categories:
        # - 5 deeply overdue (8-18 days overdue >= 7), un-escalated -> will auto-escalate on first SLA run
        # - 23 moderate overdue (1-6 days overdue < 7) -> overdue but will NOT auto-escalate
        # - 15 due soon (due in 1-4 days)
        # - Remaining open cases well within SLA
        open_pending_under_process = [idx for idx, st in enumerate(planned_statuses) if st in ["Pending", "Under Process"]]
        deeply_overdue_indices = set(random.sample(open_pending_under_process, 5))
        rem_open = [idx for idx in open_pending_under_process if idx not in deeply_overdue_indices]
        moderate_overdue_indices = set(random.sample(rem_open, 23))
        rem_open2 = [idx for idx in rem_open if idx not in moderate_overdue_indices]
        due_soon_indices = set(random.sample(rem_open2, 15))

        case_num = 1000
        for i, st in enumerate(planned_statuses):
            case_num += 1
            inst = random.choice(general_institutions)
            cat = random.choice(COMPLAINT_CATEGORIES)
            prio = random.choices(PRIORITIES, weights=[0.15, 0.55, 0.25, 0.05])[0]

            # Calculate base SLA target
            base_days = 30
            prio_mult = 1.0 if prio == "Medium" else (0.7 if prio == "High" else (0.4 if prio == "Critical" else 1.5))
            target_days = int(base_days * prio_mult)

            # Determine bureau assignment based on category realistically
            if cat in ["Approval/Affiliation Compliance", "Fake/Unapproved Courses"]:
                bureau = bureau_map["RB"]
            elif cat in ["Fee Related", "Harassment/Student Welfare", "Examination/Result"]:
                bureau = bureau_map["PGRC"]
            elif cat in ["Infrastructure", "Admission Irregularity"]:
                bureau = bureau_map["AB"]
            else:
                bureau = random.choice(bureaus_list)

            # Assign dates based on status and overdue designation
            if st == "Disposed":
                days_ago = random.randint(30, 360)
                date_rec = now - timedelta(days=days_ago)
                resolution_days = min(days_ago - 2, random.randint(12, 35))
                last_act_date = date_rec + timedelta(days=resolution_days)
                exp_date = date_rec + timedelta(days=target_days)
                is_od = False  # Disposed cases must NEVER count as overdue
                is_esc = False
                last_act = "Grievance resolved and formal disposal order issued"
                next_act = "Case closed - archiving records"
            elif st == "Transferred":
                days_ago = random.randint(10, 45)
                date_rec = now - timedelta(days=days_ago)
                last_act_date = date_rec + timedelta(days=4)
                exp_date = date_rec + timedelta(days=target_days)
                is_od = False
                is_esc = False
                last_act = "Case jurisdiction transferred to State Technical Directorate"
                next_act = "Awaiting state action report"
            elif st == "Escalated":
                # Seeded as already escalated in historical records
                days_ago = random.randint(40, 75)
                date_rec = now - timedelta(days=days_ago)
                exp_date = date_rec + timedelta(days=target_days)
                last_act_date = date_rec + timedelta(days=random.randint(20, 35))
                is_od = True
                is_esc = True
                last_act = "Escalated to Senior Management"
                next_act = "Senior Management hearing scheduled"
            elif i in deeply_overdue_indices:
                # 5 cases deeply overdue (8 to 18 days overdue >= 7), un-escalated
                # Ready to be auto-escalated on first SLA run!
                days_overdue = random.randint(8, 18)
                days_ago = target_days + days_overdue
                date_rec = now - timedelta(days=days_ago)
                exp_date = date_rec + timedelta(days=target_days)
                last_act_date = date_rec + timedelta(days=random.randint(5, target_days))
                is_od = True
                is_esc = False
                last_act = "Hearing notice issued - prolonged compliance overdue"
                next_act = "Pending statutory escalation review"
            elif i in moderate_overdue_indices:
                # 23 cases 1 to 6 days overdue (< 7 threshold)
                # Overdue, but NOT auto-escalated by SLA run!
                days_overdue = random.randint(1, 6)
                days_ago = target_days + days_overdue
                date_rec = now - timedelta(days=days_ago)
                exp_date = date_rec + timedelta(days=target_days)
                last_act_date = date_rec + timedelta(days=random.randint(3, target_days))
                is_od = True
                is_esc = False
                last_act = "First SLA breach reminder dispatched"
                next_act = "Awaiting compliance within grace period"
            elif i in due_soon_indices:
                # 15 cases due soon (in 1 to 4 days)
                days_left = random.randint(1, 4)
                days_ago = max(2, target_days - days_left)
                date_rec = now - timedelta(days=days_ago)
                exp_date = date_rec + timedelta(days=target_days)
                last_act_date = date_rec + timedelta(days=min(3, days_ago))
                is_od = False
                is_esc = False
                last_act = "Drafting disposal recommendation"
                next_act = "Final disposal review due soon"
            else:
                # Regular open non-overdue complaint: received recently, well within SLA
                days_ago = random.randint(2, max(3, target_days - 8))
                date_rec = now - timedelta(days=days_ago)
                exp_date = date_rec + timedelta(days=target_days)
                last_act_date = date_rec + timedelta(days=min(3, days_ago))
                is_od = False
                is_esc = False
                last_act = "Scrutiny note recorded"
                next_act = "Awaiting institutional clarification"

            b_code = bureau.code
            case_id = f"AICTE/{b_code}/2025/{case_num:05d}" if days_ago > 90 else f"AICTE/{b_code}/2026/{case_num:05d}"

            cat_desc_list = CATEGORY_DESCRIPTION_TEMPLATES.get(cat, ["Grievance filed alleging non-compliance with regulations."])
            desc_text = random.choice(cat_desc_list)

            complaint = Complaint(
                case_id=case_id,
                institution_id=inst.id,
                raw_institution_name=inst.name,
                source=random.choice(SOURCES),
                category=cat,
                description=desc_text,
                complainant_type=random.choice(COMPLAINANT_TYPES),
                date_received=date_rec,
                status=st,
                assigned_bureau_id=bureau.id,
                assigned_officer_id=random.choice(officers_list).id,
                last_action=last_act,
                next_action=next_act,
                last_action_date=last_act_date,
                expected_disposal_date=exp_date,
                priority=prio,
                is_overdue=is_od,
                is_escalated=is_esc,
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

        # ---------------------------------------------------------
        # 7. Generate CaseLinks Dynamically via ComplaintOverlapEngine
        # ---------------------------------------------------------
        print("[*] Running ComplaintOverlapEngine to dynamically generate all CaseLinks...")
        overlap_engine = ComplaintOverlapEngine()
        overlap_engine.initialize_from_db(db)
        lead_bureau_engine = LeadBureauEngine()

        open_statuses = ["Pending", "Under Process", "Escalated"]
        open_complaints = db.query(Complaint).filter(Complaint.status.in_(open_statuses)).all()
        by_inst = {}
        for c in open_complaints:
            if c.institution_id:
                by_inst.setdefault(c.institution_id, []).append(c)

        created_links_count = 0
        for inst_id, c_list in by_inst.items():
            n = len(c_list)
            for i in range(n):
                for j in range(i + 1, n):
                    c1 = c_list[i]
                    c2 = c_list[j]
                    if c1.assigned_bureau_id == c2.assigned_bureau_id:
                        continue
                    ca, cb = (c1, c2) if c1.id < c2.id else (c2, c1)
                    res = overlap_engine.evaluate_overlap(ca, cb, db=db)
                    if res.is_overlap and res.score >= 0.60:
                        lead_rec = lead_bureau_engine.suggest_lead(ca, cb)
                        new_link = CaseLink(
                            case_a_id=ca.id,
                            case_b_id=cb.id,
                            institution_id=inst_id,
                            similarity_score=res.score,
                            signals=res.signals,
                            reasons=res.reasons,
                            suggested_lead_bureau_id=lead_rec.lead_bureau_id,
                            lead_suggestion_rule=f"{lead_rec.rule_id}: {lead_rec.rule_description}",
                            status="suggested"
                        )
                        db.add(new_link)
                        db.flush()
                        created_links_count += 1

                        band_label = "Strong" if res.band == "STRONG_OVERLAP" else "Possible"
                        severity = "critical" if res.band == "STRONG_OVERLAP" else "warning"
                        alert_msg = (
                            f"{band_label} Inter-Bureau Overlap detected between {ca.case_id} "
                            f"({ca.assigned_bureau.code if ca.assigned_bureau else 'Bureau'}) and "
                            f"{cb.case_id} ({cb.assigned_bureau.code if cb.assigned_bureau else 'Bureau'}) "
                            f"at '{ca.institution.name if ca.institution else 'Institution'}' "
                            f"(Score: {res.score:.2f}). Suggested Lead: {lead_rec.lead_bureau_code}."
                        )
                        created_time = max(ca.date_received, cb.date_received)
                        db.add(Alert(
                            type="overlap",
                            complaint_id=ca.id,
                            institution_id=inst_id,
                            message=alert_msg,
                            severity=severity,
                            target_bureau_id=ca.assigned_bureau_id,
                            is_read=False,
                            created_at=created_time
                        ))
                        db.add(Alert(
                            type="overlap",
                            complaint_id=cb.id,
                            institution_id=inst_id,
                            message=alert_msg,
                            severity=severity,
                            target_bureau_id=cb.assigned_bureau_id,
                            is_read=False,
                            created_at=created_time
                        ))

        db.commit()
        print(f"[OK] Dynamically generated {created_links_count} genuine CaseLink linkages with real signals and explainable reasons.")
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
