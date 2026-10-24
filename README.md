# AICTE Integrated Institution Complaint Monitoring and Coordination Portal
**Smart India Hackathon (SIH) Project**

## Overview
An AI-powered integrated grievance monitoring, inter-bureau coordination, and institutional risk intelligence portal for the All India Council for Technical Education (AICTE).

The system continuously tracks grievances across distinct administrative bureaus (Regulation Bureau, Public Grievance Redressal Cell, Approval Bureau, Affiliation Bureau), detects multi-signal complaint overlaps, resolves informal institutional names via a 3-layer disambiguation engine, dynamically scores institutional risk, and automates SLA escalation.

---

## Scripted Demonstration Scenarios

| Scenario | Objective | Input / Context | Engine Execution & Result |
| :--- | :--- | :--- | :--- |
| **Scenario 1** | **Strong Inter-Bureau Overlap Alert** | AICTE/PGRC/2026/00101 (Student fee grievance) vs. AICTE/RB/2026/00204 (Show-cause notice) at ABC Institute of Technology, Pune. | **Gating Passed**; Text Cosine: 91.6%, Category Rel: 80%, Date Gap (3 days): 98.3%. **Composite Score: 0.8946** (>= 0.85). **Red Strong Alert**, suggested lead: **RB** (`RULE_STATUTORY_REGULATORY`). |
| **Scenario 1b** | **Possible Overlap in Review Band** | AICTE/PGRC/2026/00105 vs. AICTE/AB/2026/00205 at Global Institute of Technology. | **Gating Passed**; Text Cosine: 54.7%, Category Rel: 80%, Date Gap (10 days): 94.4%. **Composite Score: 0.7024** (0.60 - 0.84). **Amber Possible Overlap Alert**, suggested lead: **AB**. |
| **Scenario 1c** | **Negative Case (Unrelated Complaints)** | AICTE/PGRC/2026/00109 (Hostel mess food) vs. AICTE/AB/2026/00209 (Mechanical lab machinery) at Imperial College of Engineering. | **Gating Passed**; Text Cosine: 0.0%, Category Rel: 0.0%. **Composite Score: 0.1889** (< 0.60). **BELOW_THRESHOLD: No Alert, No Lead**. |
| **Scenario 2** | **False Match Avoidance (Cross-City Isolation)** | "National College of Engineering, Jaipur" vs. "National College of Engineering, Raipur". | Layer 3 Geographic Verification applies city contradiction (-0.40) & state contradiction (-0.30). Strictly isolates both institutions into distinct entities. |
| **Scenario 3** | **Human Review Band & Ambiguity Enforcement** | Query: `"Apex Academy"` (City: Bengaluru, State: Karnataka). | Resolves with **Confidence: 0.70** (in 0.65 - 0.75 band). Top 2 candidates tie within margin 0.002 (<= 0.15 threshold), triggering the Ambiguity Rule (`NEEDS_REVIEW`) and surfacing all 3 Bengaluru Apex campuses for one-click verification. |
| **Scenario 4** | **SLA Auto-Escalation** | Case AICTE/RB/2026/00045 (Faculty Shortage, High Priority). | Evaluates priority-adjusted SLA target. Case is overdue by > 7 days; auto-escalates to `Escalated`, sets `is_escalated = True`, logs audit history, and raises Critical Alert for Senior Management. |
| **Scenario 5** | **Live Complaint Intake Pre-Check** | Complainant enters unformatted complaint text referencing Rs 25,000 caution money without receipt at ABC Tech Pune. | Real-time intake pre-check resolves canonical institution (`1-1099238411`) and detects active overlap (**0.9041 STRONG_OVERLAP**) with open case `AICTE/RB/2026/00204` **before** database persistence. |
| **Scenario 6** | **Institutional Risk Leaderboard** | Sunrise Institute of Technology & Management (`1-1099882233`). | Dynamic closed-form calculation: Volume (27.0) + Pending Ratio (15.56) + Severity (19.0) + Repeat Categories (10.0) + Unresolved Overlaps (10.0) = **81.56** (High Risk Band). |

---

## Technical Stack
- **Backend**: FastAPI, SQLAlchemy, SQLite, PyJWT, Bcrypt, Scikit-learn (TF-IDF), RapidFuzz, APScheduler.
- **Frontend**: React (Vite), TailwindCSS, Lucide-React, Recharts.
- **Python Version**: >= 3.10
