from typing import Tuple
from dataclasses import dataclass
from backend.app.models.complaint import Complaint
from backend.app.models.bureau import Bureau


@dataclass
class LeadBureauRecommendation:
    lead_bureau_id: int
    lead_bureau_code: str
    rule_id: str
    rule_description: str
    is_joint_review_recommended: bool


class LeadBureauEngine:
    """
    Deterministic rule engine that recommends a Lead Bureau for an overlapping case pair.
    CONSTRAINT: The recommended lead bureau MUST be one of the two bureaus involved in the pair.
    """

    @staticmethod
    def suggest_lead(
        complaint_a: Complaint,
        complaint_b: Complaint
    ) -> LeadBureauRecommendation:
        """
        Evaluates rule hierarchy in strict precedence:
        1. Regulatory / Statutory Compliance -> RB (if RB is involved)
        2. Infrastructure / Approval Process Handbook -> AB (if AB is involved)
        3. Student / Faculty Grievance / Fee Refund -> PGRC (if PGRC is involved)
        4. Default / Tie -> Bureau of the earliest filed complaint (with Joint Review flag)
        """
        bur_a = complaint_a.assigned_bureau
        bur_b = complaint_b.assigned_bureau
        code_a = bur_a.code if bur_a else ""
        code_b = bur_b.code if bur_b else ""

        cat_a = complaint_a.category
        cat_b = complaint_b.category

        # Rule 1: Statutory / Affiliation / Regulatory Action / Show-Cause -> RB takes precedence
        statutory_cats = {"Approval/Affiliation Compliance", "Fake/Unapproved Courses"}
        regulatory_indicators = {"inspection", "show-cause", "regulatory", "inquiry", "statutory", "audit"}
        
        desc_a = (complaint_a.description or "").lower()
        desc_b = (complaint_b.description or "").lower()
        has_regulatory = (
            cat_a in statutory_cats or cat_b in statutory_cats or
            any(ind in desc_a for ind in regulatory_indicators) or
            any(ind in desc_b for ind in regulatory_indicators)
        )

        if has_regulatory:
            if code_a == "RB":
                return LeadBureauRecommendation(
                    lead_bureau_id=complaint_a.assigned_bureau_id,
                    lead_bureau_code="RB",
                    rule_id="RULE_STATUTORY_REGULATORY",
                    rule_description="Regulatory action or statutory compliance scrutiny in Regulation Bureau takes legal precedence -> RB Leads",
                    is_joint_review_recommended=False
                )
            elif code_b == "RB":
                return LeadBureauRecommendation(
                    lead_bureau_id=complaint_b.assigned_bureau_id,
                    lead_bureau_code="RB",
                    rule_id="RULE_STATUTORY_REGULATORY",
                    rule_description="Regulatory action or statutory compliance scrutiny in Regulation Bureau takes legal precedence -> RB Leads",
                    is_joint_review_recommended=False
                )

        # Rule 2: Infrastructure & Sanctioned Intake Norms -> AB takes precedence
        approval_cats = {"Infrastructure", "Admission Irregularity"}
        if (cat_a in approval_cats or cat_b in approval_cats):
            if code_a == "AB":
                return LeadBureauRecommendation(
                    lead_bureau_id=complaint_a.assigned_bureau_id,
                    lead_bureau_code="AB",
                    rule_id="RULE_INFRASTRUCTURE_APPROVAL",
                    rule_description="Infrastructure, lab terminal deficit, or admission quota norm violations governed by Approval Bureau -> AB Leads",
                    is_joint_review_recommended=False
                )
            elif code_b == "AB":
                return LeadBureauRecommendation(
                    lead_bureau_id=complaint_b.assigned_bureau_id,
                    lead_bureau_code="AB",
                    rule_id="RULE_INFRASTRUCTURE_APPROVAL",
                    rule_description="Infrastructure, lab terminal deficit, or admission quota norm violations governed by Approval Bureau -> AB Leads",
                    is_joint_review_recommended=False
                )

        # Rule 3: Individual Grievance / Fee Refund / Welfare -> PGRC takes precedence
        grievance_cats = {"Fee Related", "Harassment/Student Welfare", "Examination/Result"}
        if (cat_a in grievance_cats or cat_b in grievance_cats):
            if code_a == "PGRC":
                return LeadBureauRecommendation(
                    lead_bureau_id=complaint_a.assigned_bureau_id,
                    lead_bureau_code="PGRC",
                    rule_id="RULE_INDIVIDUAL_GRIEVANCE",
                    rule_description="Individual student/faculty grievance regarding fee refund or welfare falls under specialized PGRC mandate -> PGRC Leads",
                    is_joint_review_recommended=False
                )
            elif code_b == "PGRC":
                return LeadBureauRecommendation(
                    lead_bureau_id=complaint_b.assigned_bureau_id,
                    lead_bureau_code="PGRC",
                    rule_id="RULE_INDIVIDUAL_GRIEVANCE",
                    rule_description="Individual student/faculty grievance regarding fee refund or welfare falls under specialized PGRC mandate -> PGRC Leads",
                    is_joint_review_recommended=False
                )

        # Rule 4: Tie-breaking / Default: Earliest active inquiry anchor + Joint Review
        if complaint_a.date_received <= complaint_b.date_received:
            lead_id = complaint_a.assigned_bureau_id
            lead_code = code_a
            anchor_case = complaint_a.case_id
        else:
            lead_id = complaint_b.assigned_bureau_id
            lead_code = code_b
            anchor_case = complaint_b.case_id

        return LeadBureauRecommendation(
            lead_bureau_id=lead_id,
            lead_bureau_code=lead_code,
            rule_id="RULE_HISTORICAL_INQUIRY_EARLIEST",
            rule_description=f"Multiple cross-bureau violations detected; earliest inquiry case ({anchor_case}) nominated as lead with Joint Review Recommended",
            is_joint_review_recommended=True
        )


lead_bureau_engine = LeadBureauEngine()
