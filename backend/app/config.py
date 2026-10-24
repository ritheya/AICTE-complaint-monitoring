"""
AICTE Complaint Monitor - Central Engine Configuration
Every parameter, weight, threshold, dictionary, and SLA matrix is declared here.
"""

# ==============================================================================
# 1. INSTITUTION RESOLUTION THRESHOLDS & GEOGRAPHIC RULES
# ==============================================================================
RESOLUTION_AUTO_LINK_THRESHOLD = 0.85      # >= 0.85: Auto-link to institution
RESOLUTION_REVIEW_THRESHOLD = 0.60         # 0.60 - 0.84: Flag for manual one-click review
                                           # < 0.60: Treat as Unresolved

# If the confidence difference between the top candidate and runner-up is <= margin,
# force human review (NEEDS_REVIEW) even if top candidate >= 0.85
RESOLUTION_AMBIGUITY_MARGIN = 0.15

# Standard technical education abbreviations
NAME_ABBREVIATIONS = {
    "inst.": "institute", "inst": "institute",
    "tech.": "technology", "tech": "technology",
    "engg.": "engineering", "engg": "engineering",
    "coll.": "college", "coll": "college",
    "univ.": "university", "univ": "university",
    "dept.": "department", "dept": "department",
    "mgmt.": "management", "mgmt": "management",
    "poly.": "polytechnic", "poly": "polytechnic",
    "acad.": "academy", "acad": "academy"
}

# Major Indian city synonyms / historical aliases
CITY_ALIASES = {
    "bangalore": "bengaluru",
    "bombay": "mumbai",
    "madras": "chennai",
    "calcutta": "kolkata",
    "poona": "pune",
    "gurgaon": "gurugram",
    "orissa": "odisha",
    "baroda": "vadodara",
    "trivandrum": "thiruvananthapuram",
    "cochin": "kochi"
}

# Generic education institutional descriptor words (weighted lower than distinctive brand names)
GENERIC_INSTITUTION_WORDS = {
    "institute", "institution", "technology", "tech", "college", "engineering",
    "engg", "polytechnic", "poly", "academy", "acad", "university", "univ",
    "management", "mgmt", "department", "dept", "school", "center", "centre",
    "of", "and", "&", "for", "in"
}

# Deterministic city-to-state lookup for technical education hubs in seed database
# Enables state inference when queries specify only the city, allowing legitimate auto-link
CITY_TO_STATE_LOOKUP = {
    "mumbai": "maharashtra", "bombay": "maharashtra",
    "pune": "maharashtra", "poona": "maharashtra",
    "nagpur": "maharashtra",
    "ahmedabad": "gujarat", "baroda": "gujarat", "vadodara": "gujarat",
    "bengaluru": "karnataka", "bangalore": "karnataka",
    "mysuru": "karnataka", "mysore": "karnataka",
    "chennai": "tamil nadu", "madras": "tamil nadu",
    "coimbatore": "tamil nadu",
    "hyderabad": "telangana",
    "kolkata": "west bengal", "calcutta": "west bengal",
    "bhubaneswar": "odisha", "orissa": "odisha",
    "patna": "bihar",
    "ranchi": "jharkhand",
    "new delhi": "delhi", "delhi": "delhi",
    "jaipur": "rajasthan",
    "lucknow": "uttar pradesh",
    "kanpur": "uttar pradesh",
    "chandigarh": "punjab",
    "bhopal": "madhya pradesh",
    "indore": "madhya pradesh",
    "raipur": "chhattisgarh",
    "guwahati": "assam",
    "shillong": "meghalaya",
    "thiruvananthapuram": "kerala", "trivandrum": "kerala",
    "kochi": "kerala", "cochin": "kerala",
    "gurugram": "haryana", "gurgaon": "haryana",
    "dehradun": "uttarakhand"
}

# Geographic verification weights
GEO_PINCODE_EXACT_BONUS = 0.20
GEO_PINCODE_ZONAL_BONUS = 0.10
GEO_PINCODE_MISMATCH_PENALTY = 0.25

GEO_CITY_EXACT_BONUS = 0.15
GEO_CITY_CONTRADICTION_PENALTY = 0.40

GEO_STATE_EXACT_BONUS = 0.05
GEO_STATE_CONTRADICTION_PENALTY = 0.30

# Name weight in composite resolution formula
NAME_WEIGHT_IN_RESOLUTION = 0.65


# ==============================================================================
# 2. OVERLAP SCORING WEIGHTS & CONTENT SIGNALS
# ==============================================================================
# GATING CONDITIONS:
# 1. Same institution (case_a.institution_id == case_b.institution_id)
# 2. Different bureaus (case_a.assigned_bureau_id != case_b.assigned_bureau_id)
# 3. Both cases open (statuses not in ['Disposed', 'Transferred'])
# If any gating condition fails -> Overlap score is strictly 0.0 (No overlap).

# Content Weights (Must sum to 1.00)
OVERLAP_WEIGHT_TEXT = 0.50          # Text cosine similarity on concept-normalized descriptions
OVERLAP_WEIGHT_CATEGORY = 0.30      # Exact or related category match
OVERLAP_WEIGHT_DATE = 0.20          # Closeness of receipt dates (linear decay over 180 days)

# Overlap Alert Thresholds
OVERLAP_STRONG_ALERT_THRESHOLD = 0.85      # >= 0.85: Red strong alert + suggested link
OVERLAP_REVIEW_ALERT_THRESHOLD = 0.60      # 0.60 - 0.84: Amber alert ("Possible overlap, review")
                                           # < 0.60: No alert generated

# Flag for deep semantic embeddings (sentence-transformers), defaults to False for offline speed
USE_EMBEDDINGS = False

# Category Relatedness Scores
CATEGORY_SCORE_SAME = 1.0

# Configurable relatedness value set by the design team, to be reviewed by AICTE domain experts.
# Indicates semantic and operational adjacency between categories (e.g. fee collection issues
# and institutional compliance oversight).
CATEGORY_SCORE_RELATED = 0.80
CATEGORY_SCORE_UNRELATED = 0.0

# Category Relatedness Matrix (Pairwise semantic relatedness in AICTE governance)
CATEGORY_RELATIONSHIPS = {
    "Fee Related": ["Admission Irregularity", "Harassment/Student Welfare", "Approval/Affiliation Compliance"],
    "Admission Irregularity": ["Fee Related", "Fake/Unapproved Courses", "Placement Misrepresentation", "Approval/Affiliation Compliance"],
    "Faculty Shortage": ["Approval/Affiliation Compliance", "Infrastructure"],
    "Approval/Affiliation Compliance": ["Faculty Shortage", "Infrastructure", "Fake/Unapproved Courses", "Fee Related", "Admission Irregularity"],
    "Infrastructure": ["Faculty Shortage", "Approval/Affiliation Compliance"],
    "Placement Misrepresentation": ["Admission Irregularity"],
    "Examination/Result": ["Harassment/Student Welfare"],
    "Harassment/Student Welfare": ["Fee Related", "Examination/Result"],
    "Fake/Unapproved Courses": ["Approval/Affiliation Compliance", "Admission Irregularity"],
    "Other": []
}

# Semantic Concept Normalization Dictionary for Grievance Text
# Words in each group are mapped to a canonical concept token before TF-IDF vectorization
CONCEPT_SYNONYMS = {
    # Fee & Money Concept
    "capitation": "fee_concept",
    "caution": "fee_concept",
    "deposit": "fee_concept",
    "refund": "fee_concept",
    "refunding": "fee_concept",
    "fees": "fee_concept",
    "fee": "fee_concept",
    "charges": "fee_concept",
    "charge": "fee_concept",
    "payment": "fee_concept",
    "money": "fee_concept",
    "receipt": "fee_concept",
    "levy": "fee_concept",
    "levies": "fee_concept",
    "development": "fee_concept",
    "extortion": "fee_concept",

    # Collection & Demands Concept
    "collected": "levy_concept",
    "collection": "levy_concept",
    "collecting": "levy_concept",
    "charging": "levy_concept",
    "charged": "levy_concept",
    "demanding": "levy_concept",
    "demanded": "levy_concept",
    "hikes": "levy_concept",
    "hike": "levy_concept",

    # Violation & Norms Concept
    "unauthorized": "violation_concept",
    "unapproved": "violation_concept",
    "illegally": "violation_concept",
    "illegal": "violation_concept",
    "violating": "violation_concept",
    "violation": "violation_concept",
    "violations": "violation_concept",
    "scrutiny": "violation_concept",
    "inspection": "violation_concept",
    "inquiry": "violation_concept",
    "investigation": "violation_concept",
    "deficiency": "violation_concept",
    "noncompliance": "violation_concept",

    # Coercion & Withholding Concept
    "withholding": "withhold_concept",
    "withheld": "withhold_concept",
    "withhold": "withhold_concept",
    "threat": "withhold_concept",
    "harassing": "withhold_concept",

    # Academic & Examination Concept
    "marksheet": "exam_concept",
    "transcript": "exam_concept",
    "hallticket": "exam_concept",
    "halltickets": "exam_concept",
    "admitcard": "exam_concept",
    "admit": "exam_concept",
    "card": "exam_concept",
    "cards": "exam_concept",
    "ticket": "exam_concept",
    "tickets": "exam_concept",
    "exam": "exam_concept",
    "examination": "exam_concept",
    "result": "exam_concept",
    "results": "exam_concept",

    # Faculty & Staff Concept
    "faculty": "faculty_concept",
    "teachers": "faculty_concept",
    "teacher": "faculty_concept",
    "professors": "faculty_concept",
    "professor": "faculty_concept",
    "lecturers": "faculty_concept",
    "lecturer": "faculty_concept",
    "adjunct": "faculty_concept",
    "vacancies": "faculty_concept",
    "vacancy": "faculty_concept",
    "vacant": "faculty_concept",
    "shortage": "faculty_concept",
    "cadre": "faculty_concept",
    "unqualified": "faculty_concept",

    # Infrastructure & Lab Concept
    "infrastructure": "infra_concept",
    "labs": "infra_concept",
    "lab": "infra_concept",
    "laboratory": "infra_concept",
    "terminals": "infra_concept",
    "computers": "infra_concept",
    "bandwidth": "infra_concept",
    "internet": "infra_concept",
    "equipment": "infra_concept",
    "building": "infra_concept",
    "campus": "infra_concept",
    "library": "infra_concept"
}


# ==============================================================================
# 3. INSTITUTIONAL RISK SCORE WEIGHTS (0 to 100)
# ==============================================================================
RISK_WEIGHTS = {
    "volume_max_pts": 30.0,         # Up to 30 pts based on complaint volume (>= 10 complaints)
    "volume_pts_per_case": 3.0,
    "pending_ratio_max_pts": 20.0,   # Up to 20 pts based on unclosed percentage
    "severity_max_pts": 20.0,        # Up to 20 pts (Critical: 5 pts, High: 3 pts)
    "severity_crit_pts": 5.0,
    "severity_high_pts": 3.0,
    "repeat_cat_max_pts": 15.0,      # Up to 15 pts (>= 3 complaints in same category = 5 pts per category)
    "repeat_cat_pts_per_cat": 5.0,
    "repeat_cat_threshold": 3,
    "unresolved_overlaps_max_pts": 15.0, # Up to 15 pts (5 pts per active unapproved overlap)
    "unresolved_overlap_pts": 5.0
}


# ==============================================================================
# 4. SLA MATRICES & ESCALATION RULES
# ==============================================================================
SLA_DAYS_BY_CATEGORY = {
    "Harassment/Student Welfare": 15,
    "Fake/Unapproved Courses": 20,
    "Examination/Result": 20,
    "Fee Related": 30,
    "Approval/Affiliation Compliance": 30,
    "Admission Irregularity": 30,
    "Placement Misrepresentation": 40,
    "Faculty Shortage": 45,
    "Infrastructure": 45,
    "Other": 30
}

SLA_PRIORITY_MULTIPLIERS = {
    "Critical": 0.4,
    "High": 0.7,
    "Medium": 1.0,
    "Low": 1.5
}

SLA_DUE_SOON_PERCENTAGE = 0.20             # Alert when <= 20% of SLA time remains
SLA_AUTO_ESCALATE_OVERDUE_DAYS = 7         # Auto-escalate to Senior Management if > 7 days overdue


# ==============================================================================
# 5. SECURITY, AUTHENTICATION & CORS CONFIGURATION
# ==============================================================================
import os

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "aicte-secret-key-super-secure-change-in-prod-2026")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))  # 8 hours

# Frontend origin for restricted CORS
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
CORS_ORIGINS = [
    FRONTEND_URL,
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000"
]

# Basic in-memory rate limiting configuration for login attempts
LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 5
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 60

# Canonical Role Names
ROLE_ADMIN = "Admin"
ROLE_SENIOR_MGMT = "Senior Management"
ROLE_RB_OFFICER = "RB Officer"
ROLE_PGRC_OFFICER = "PGRC Officer"
ROLE_AB_OFFICER = "AB Officer"
ROLE_AFB_OFFICER = "AFB Officer"
ROLE_REGIONAL_OFFICER = "Regional Officer"

ALL_ROLES = [
    ROLE_ADMIN,
    ROLE_SENIOR_MGMT,
    ROLE_RB_OFFICER,
    ROLE_PGRC_OFFICER,
    ROLE_AB_OFFICER,
    ROLE_AFB_OFFICER,
    ROLE_REGIONAL_OFFICER
]

