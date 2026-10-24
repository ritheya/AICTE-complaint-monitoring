from typing import Dict, Any, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from backend.app.config import RISK_WEIGHTS
from backend.app.utils import utc_now
from backend.app.models.complaint import Complaint
from backend.app.models.case_link import CaseLink
from backend.app.models.institution import Institution


class InstitutionalRiskScorer:
    """
    Calculates explainable 0-100 Institutional Risk Score dynamically
    from database complaints, priority severity, repeat categories, and overlaps.
    """

    @staticmethod
    def calculate_risk(institution_id: int, db: Session) -> Tuple[float, Dict[str, Any]]:
        """
        Dynamically computes the 5-component risk score:
        1. Complaint Volume (last 24m) [max 30]
        2. Pending Ratio [max 20]
        3. Priority Severity Penalty [max 20]
        4. Repeat Categories Recidivism [max 15]
        5. Unresolved Inter-Bureau Overlaps [max 15]
        """
        now = utc_now()
        two_years_ago = now - timedelta(days=730)

        # 1. Total complaints in last 24m
        complaints_24m = db.query(Complaint).filter(
            Complaint.institution_id == institution_id,
            Complaint.date_received >= two_years_ago
        ).all()
        n_24 = len(complaints_24m)
        c_vol = min(RISK_WEIGHTS["volume_max_pts"], n_24 * RISK_WEIGHTS["volume_pts_per_case"])

        # 2. Pending ratio
        open_complaints = [c for c in complaints_24m if c.status not in ["Disposed", "Transferred"]]
        n_open = len(open_complaints)
        pending_ratio = (n_open / n_24) if n_24 > 0 else 0.0
        c_pen = round(pending_ratio * RISK_WEIGHTS["pending_ratio_max_pts"], 2)

        # 3. Severity penalty
        n_crit = sum(1 for c in complaints_24m if c.priority == "Critical")
        n_high = sum(1 for c in complaints_24m if c.priority == "High")
        sev_raw = (n_crit * RISK_WEIGHTS["severity_crit_pts"]) + (n_high * RISK_WEIGHTS["severity_high_pts"])
        c_sev = min(RISK_WEIGHTS["severity_max_pts"], sev_raw)

        # 4. Repeat categories (recidivism)
        cat_counts: Dict[str, int] = {}
        for c in complaints_24m:
            cat_counts[c.category] = cat_counts.get(c.category, 0) + 1

        repeat_cats = [cat for cat, cnt in cat_counts.items() if cnt >= RISK_WEIGHTS["repeat_cat_threshold"]]
        c_rep = min(RISK_WEIGHTS["repeat_cat_max_pts"], len(repeat_cats) * RISK_WEIGHTS["repeat_cat_pts_per_cat"])

        # 5. Unresolved overlaps
        unresolved_overlaps = db.query(CaseLink).filter(
            CaseLink.institution_id == institution_id,
            CaseLink.status.in_(["suggested", "needs_discussion"])
        ).count()
        c_ovl = min(RISK_WEIGHTS["unresolved_overlaps_max_pts"], unresolved_overlaps * RISK_WEIGHTS["unresolved_overlap_pts"])

        # Total composite score clamped to [0.0, 100.0]
        total_raw = c_vol + c_pen + c_sev + c_rep + c_ovl
        final_score = max(0.0, min(100.0, round(total_raw, 2)))

        # Risk band
        if final_score >= 70.0:
            band = "High Risk"
        elif final_score >= 40.0:
            band = "Medium Risk"
        else:
            band = "Low Risk"

        breakdown = {
            "total_score": final_score,
            "band": band,
            "components": {
                "complaint_volume": {
                    "count": n_24,
                    "points": c_vol,
                    "max_points": RISK_WEIGHTS["volume_max_pts"]
                },
                "pending_ratio": {
                    "open_count": n_open,
                    "total_count": n_24,
                    "ratio": round(pending_ratio, 2),
                    "points": c_pen,
                    "max_points": RISK_WEIGHTS["pending_ratio_max_pts"]
                },
                "severity_penalty": {
                    "critical_count": n_crit,
                    "high_count": n_high,
                    "points": c_sev,
                    "max_points": RISK_WEIGHTS["severity_max_pts"]
                },
                "repeat_categories": {
                    "repeat_categories_list": repeat_cats,
                    "points": c_rep,
                    "max_points": RISK_WEIGHTS["repeat_cat_max_pts"]
                },
                "unresolved_overlaps": {
                    "count": unresolved_overlaps,
                    "points": c_ovl,
                    "max_points": RISK_WEIGHTS["unresolved_overlaps_max_pts"]
                }
            }
        }

        return final_score, breakdown


risk_scorer = InstitutionalRiskScorer()
