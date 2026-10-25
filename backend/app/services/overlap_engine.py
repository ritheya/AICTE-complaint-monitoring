import re
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.orm import Session

from backend.app.config import (
    OVERLAP_WEIGHT_TEXT,
    OVERLAP_WEIGHT_CATEGORY,
    OVERLAP_WEIGHT_DATE,
    OVERLAP_STRONG_ALERT_THRESHOLD,
    OVERLAP_REVIEW_ALERT_THRESHOLD,
    CATEGORY_RELATIONSHIPS,
    CONCEPT_SYNONYMS,
    USE_EMBEDDINGS
)
from backend.app.models.complaint import Complaint


@dataclass
class OverlapResult:
    is_overlap: bool
    score: float
    band: str  # STRONG_OVERLAP, POSSIBLE_OVERLAP, BELOW_THRESHOLD, GATED_OUT
    gated_out: bool
    gate_reason: Optional[str]
    signals: Dict[str, float]
    reasons: List[str]


class ComplaintOverlapEngine:
    """
    Multi-Signal Complaint Overlap Engine.
    - Gate 1: Same resolved institution
    - Gate 2: Different bureaus handling the cases
    - Gate 3: Both cases open
    - Content Scoring: Text similarity (50%), Category relation (30%), Date proximity (20%)
    - Global reusable TF-IDF vectorizer fit on corpus with concept normalization
    """

    def __init__(self):
        self.vectorizer: Optional[TfidfVectorizer] = None
        self._is_fitted: bool = False

    @staticmethod
    def preprocess_text(text: str) -> str:
        """
        Normalizes complaint description:
        - Lowercases and removes special punctuation
        - Strips administrative noise stopwords
        - Applies semantic concept token substitution using CONCEPT_SYNONYMS
        """
        if not text:
            return ""
        cleaned = text.lower()
        cleaned = re.sub(r"[^\w\s]", " ", cleaned)
        tokens = cleaned.split()

        noise_words = {
            "the", "of", "and", "for", "in", "rs", "1", "5", "at", "by", "under", "to", "is",
            "a", "an", "my", "sir", "please", "kindly", "against", "about"
        }

        normalized_tokens = []
        for token in tokens:
            if token not in noise_words:
                concept = CONCEPT_SYNONYMS.get(token, token)
                normalized_tokens.append(concept)

        return " ".join(normalized_tokens)

    def fit_corpus(self, corpus: List[str]) -> None:
        """Fits the TF-IDF vectorizer on a corpus of complaint descriptions."""
        if not corpus:
            return
        preprocessed = [self.preprocess_text(doc) for doc in corpus if doc]
        if not preprocessed:
            return
        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 1),
            sublinear_tf=False,
            stop_words="english",
            min_df=1
        )
        self.vectorizer.fit(preprocessed)
        self._is_fitted = True

    def initialize_from_db(self, db: Session) -> None:
        """Ensures the vectorizer is fit on all complaints currently in the database."""
        if self._is_fitted:
            return
        descriptions = [row[0] for row in db.query(Complaint.description).filter(Complaint.description != None).all()]
        if descriptions:
            self.fit_corpus(descriptions)
        else:
            sample_corpus = [
                "fee refund caution deposit unapproved charges capitation fee",
                "faculty shortage teachers vacancies cadre professor adjunct",
                "infrastructure lab terminals computers bandwidth internet building",
                "affiliation approval compliance unapproved courses inspection norms",
                "examination result marksheet transcript withholding hall ticket"
            ]
            self.fit_corpus(sample_corpus)

    def compute_text_similarity(self, desc_a: str, desc_b: str, db: Optional[Session] = None) -> float:
        """
        Computes cosine similarity between two descriptions using the fitted TF-IDF model.
        """
        norm_a = self.preprocess_text(desc_a)
        norm_b = self.preprocess_text(desc_b)

        if not norm_a or not norm_b:
            return 0.0

        # Create or ensure vectorizer fit on global database corpus snapshot
        if not self._is_fitted:
            if db:
                self.initialize_from_db(db)
            else:
                try:
                    from backend.app.database import SessionLocal
                    temp_session = SessionLocal()
                    self.initialize_from_db(temp_session)
                    temp_session.close()
                except Exception:
                    self.fit_corpus([desc_a, desc_b])

        try:
            vecs = self.vectorizer.transform([norm_a, norm_b])
            sim = float(cosine_similarity(vecs[0:1], vecs[1:2])[0][0])
            return max(0.0, min(1.0, round(sim, 4)))
        except Exception:
            # Fallback pairwise vectorizer if global transform encounters edge case
            local_vec = TfidfVectorizer(ngram_range=(1, 1), stop_words="english")
            mat = local_vec.fit_transform([norm_a, norm_b])
            sim = float(cosine_similarity(mat[0:1], mat[1:2])[0][0])
            return max(0.0, min(1.0, round(sim, 4)))

    @staticmethod
    def compute_category_score(cat_a: str, cat_b: str) -> Tuple[float, str]:
        """
        Calculates category relationship score:
        - 1.0 for identical category
        - 0.80 for directly related category in CATEGORY_RELATIONSHIPS
        - 0.0 for unrelated category
        """
        if not cat_a or not cat_b:
            return 0.0, "Missing category"
        if cat_a == cat_b:
            return 1.0, f"Identical category: '{cat_a}'"

        related_to_a = CATEGORY_RELATIONSHIPS.get(cat_a, [])
        related_to_b = CATEGORY_RELATIONSHIPS.get(cat_b, [])

        if cat_b in related_to_a or cat_a in related_to_b:
            return 0.80, f"Related categories: '{cat_a}' and '{cat_b}'"

        return 0.0, f"Unrelated categories: '{cat_a}' and '{cat_b}'"

    @staticmethod
    def compute_date_score(date_a: datetime, date_b: datetime) -> Tuple[float, str]:
        """
        Calculates date proximity score linearly decaying over 180 days.
        """
        delta_days = abs((date_a - date_b).days)
        score = max(0.0, 1.0 - (delta_days / 180.0))
        return round(score, 4), f"Filed within {delta_days} day(s) of each other"

    def evaluate_overlap(
        self,
        complaint_a: Complaint,
        complaint_b: Complaint,
        db: Optional[Session] = None
    ) -> OverlapResult:
        """
        Evaluates overlap between two complaints:
        1. Gating verification (same inst, diff bureau, both open)
        2. Content scoring: Text (50%), Category (30%), Date (20%)
        """
        reasons = []

        # --- GATING CONDITION 1: Same Resolved Institution ---
        if complaint_a.institution_id is None or complaint_b.institution_id is None or complaint_a.institution_id != complaint_b.institution_id:
            return OverlapResult(
                is_overlap=False,
                score=0.0,
                band="GATED_OUT",
                gated_out=True,
                gate_reason="Complaints are not resolved to the same institution ID",
                signals={"text": 0.0, "category": 0.0, "date": 0.0},
                reasons=["Gate Failed: Complaints do not share the same institution ID"]
            )

        # --- GATING CONDITION 2: Different Assigned Bureaus ---
        if complaint_a.assigned_bureau_id == complaint_b.assigned_bureau_id:
            return OverlapResult(
                is_overlap=False,
                score=0.0,
                band="GATED_OUT",
                gated_out=True,
                gate_reason="Both complaints sit within the same bureau (internal duplicate, not cross-bureau coordination)",
                signals={"text": 0.0, "category": 0.0, "date": 0.0},
                reasons=["Gate Failed: Both cases are assigned to the same bureau"]
            )

        # --- GATING CONDITION 3: Both Cases Must Be Open ---
        closed_statuses = {"Disposed", "Transferred"}
        if complaint_a.status in closed_statuses or complaint_b.status in closed_statuses:
            return OverlapResult(
                is_overlap=False,
                score=0.0,
                band="GATED_OUT",
                gated_out=True,
                gate_reason=f"One or both cases are closed (Status A: {complaint_a.status}, Status B: {complaint_b.status})",
                signals={"text": 0.0, "category": 0.0, "date": 0.0},
                reasons=["Gate Failed: One or both cases are already Disposed or Transferred"]
            )

        # --- GATING CONDITION 4: Prior Rejected Overlap Decision (Never Re-Suggest) ---
        if db and complaint_a.id and complaint_b.id:
            from backend.app.models.case_link import CaseLink
            ca_id, cb_id = (complaint_a.id, complaint_b.id) if complaint_a.id < complaint_b.id else (complaint_b.id, complaint_a.id)
            existing_rejected = db.query(CaseLink).filter(
                CaseLink.case_a_id == ca_id,
                CaseLink.case_b_id == cb_id,
                CaseLink.status == "rejected"
            ).first()
            if existing_rejected:
                return OverlapResult(
                    is_overlap=False,
                    score=0.0,
                    band="GATED_OUT",
                    gated_out=True,
                    gate_reason="Prior officer adjudication rejected overlap linkage between these cases (never re-suggest)",
                    signals={"text": 0.0, "category": 0.0, "date": 0.0},
                    reasons=["Gate Failed: Prior officer adjudication rejected overlap linkage between these cases (never re-suggest)"]
                )

        # Gating Passed
        inst_name = complaint_a.institution.name if complaint_a.institution else "Institution"
        reasons.append(f"Gating Passed: Both cases active across distinct bureaus at '{inst_name}'")

        # --- CONTENT SIGNAL 1: Text Similarity (50%) ---
        s_text = self.compute_text_similarity(complaint_a.description, complaint_b.description, db=db)
        reasons.append(f"Text Similarity: {s_text * 100:.1f}% based on concept-normalized phrasing")

        # --- CONTENT SIGNAL 2: Category Relationship (30%) ---
        s_cat, cat_reason = self.compute_category_score(complaint_a.category, complaint_b.category)
        reasons.append(f"Category Relationship: {cat_reason} ({s_cat * 100:.0f}%)")

        # --- CONTENT SIGNAL 3: Date Proximity (20%) ---
        s_date, date_reason = self.compute_date_score(complaint_a.date_received, complaint_b.date_received)
        reasons.append(f"Date Proximity: {date_reason} ({s_date * 100:.1f}%)")

        # --- COMPOSITE SCORE CALCULATION ---
        raw_score = (
            OVERLAP_WEIGHT_TEXT * s_text +
            OVERLAP_WEIGHT_CATEGORY * s_cat +
            OVERLAP_WEIGHT_DATE * s_date
        )
        final_score = max(0.0, min(1.0, round(raw_score, 4)))

        # Determine threshold band
        if final_score >= OVERLAP_STRONG_ALERT_THRESHOLD:
            band = "STRONG_OVERLAP"
            is_overlap = True
            reasons.append(f"Strong Overlap Alert: Score {final_score:.2f} >= {OVERLAP_STRONG_ALERT_THRESHOLD}")
        elif final_score >= OVERLAP_REVIEW_ALERT_THRESHOLD:
            band = "POSSIBLE_OVERLAP"
            is_overlap = True
            reasons.append(f"Possible Overlap: Score {final_score:.2f} in coordination review band ({OVERLAP_REVIEW_ALERT_THRESHOLD} - {OVERLAP_STRONG_ALERT_THRESHOLD})")
        else:
            band = "BELOW_THRESHOLD"
            is_overlap = False
            reasons.append(f"Score {final_score:.2f} below minimum overlap threshold ({OVERLAP_REVIEW_ALERT_THRESHOLD})")

        return OverlapResult(
            is_overlap=is_overlap,
            score=final_score,
            band=band,
            gated_out=False,
            gate_reason=None,
            signals={
                "text_similarity": s_text,
                "category_relation": s_cat,
                "date_proximity": s_date
            },
            reasons=reasons
        )


# Global singleton instance
overlap_engine = ComplaintOverlapEngine()
