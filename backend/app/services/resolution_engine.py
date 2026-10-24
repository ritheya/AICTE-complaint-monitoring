import re
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from backend.app.config import (
    RESOLUTION_AUTO_LINK_THRESHOLD,
    RESOLUTION_REVIEW_THRESHOLD,
    RESOLUTION_AMBIGUITY_MARGIN,
    NAME_ABBREVIATIONS,
    CITY_ALIASES,
    GEO_PINCODE_EXACT_BONUS,
    GEO_PINCODE_ZONAL_BONUS,
    GEO_PINCODE_MISMATCH_PENALTY,
    GEO_CITY_EXACT_BONUS,
    GEO_CITY_CONTRADICTION_PENALTY,
    GEO_STATE_EXACT_BONUS,
    GEO_STATE_CONTRADICTION_PENALTY,
    NAME_WEIGHT_IN_RESOLUTION,
    GENERIC_INSTITUTION_WORDS,
    CITY_TO_STATE_LOOKUP
)
from backend.app.models.institution import Institution


@dataclass
class ResolutionCandidate:
    id: int
    name: str
    permanent_id: str
    city: str
    state: str
    confidence: float


@dataclass
class ResolutionResult:
    best_institution: Optional[Institution]
    confidence: float
    status: str  # AUTO_LINK, NEEDS_REVIEW, UNRESOLVED
    needs_review: bool
    candidates: List[Dict[str, Any]]
    reasons: List[str]


class InstitutionResolutionEngine:
    """
    3-Layer Institution Resolution Engine with geographic disambiguation
    and ambiguity-margin enforcement.
    """

    @staticmethod
    def normalize_name(text: str) -> str:
        """
        Normalize institution name:
        - lowercase
        - strip punctuation
        - expand standard educational abbreviations
        - remove generic stopwords (the, of, and, for)
        """
        if not text:
            return ""
        cleaned = text.lower()
        cleaned = re.sub(r"[^\w\s]", " ", cleaned)
        tokens = cleaned.split()

        expanded = []
        for token in tokens:
            # Check abbreviations
            expanded_token = NAME_ABBREVIATIONS.get(token, token)
            # Remove filler words
            if expanded_token not in {"the", "of", "and", "for", "in"}:
                expanded.append(expanded_token)

        return " ".join(expanded)

    @staticmethod
    def normalize_city(city: Optional[str]) -> str:
        """Normalize city name and resolve historical/regional aliases."""
        if not city:
            return ""
        norm = city.lower().strip()
        norm = re.sub(r"[^\w\s]", "", norm)
        return CITY_ALIASES.get(norm, norm)

    @staticmethod
    def normalize_state(state: Optional[str]) -> str:
        """Normalize state name."""
        if not state:
            return ""
        norm = state.lower().strip()
        return CITY_ALIASES.get(norm, norm)

    @classmethod
    def extract_permanent_id(cls, text: str) -> Optional[str]:
        """Detect AICTE Permanent ID pattern (e.g. 1-1099238411) in raw text."""
        if not text:
            return None
        match = re.search(r"\b1-[0-9]{8,11}\b", text)
        return match.group(0) if match else None

    @classmethod
    def compute_name_similarity(cls, query_name: str, target_name: str) -> float:
        """
        Computes robust name similarity:
        1. Blends token_set_ratio (handles word reordering) with token_sort_ratio (penalizes unmatched tokens)
           so subset matches do not equal exact matches.
        2. Weights distinctive brand tokens higher than generic institutional descriptor words (e.g. institute,
           technology, engineering, college).
        """
        if not query_name or not target_name:
            return 0.0

        q_norm = query_name.lower().strip()
        t_norm = target_name.lower().strip()

        if q_norm == t_norm:
            return 1.0

        # Base blended ratio (RapidFuzz)
        set_sim = fuzz.token_set_ratio(q_norm, t_norm) / 100.0
        sort_sim = fuzz.token_sort_ratio(q_norm, t_norm) / 100.0
        blended = 0.50 * set_sim + 0.50 * sort_sim

        # Distinctive token analysis
        q_tokens = [t for t in q_norm.split() if t not in GENERIC_INSTITUTION_WORDS]
        t_tokens = [t for t in t_norm.split() if t not in GENERIC_INSTITUTION_WORDS]

        if q_tokens and t_tokens:
            q_distinct = set(q_tokens)
            t_distinct = set(t_tokens)
            common = q_distinct & t_distinct

            if common:
                distinctive_score = len(common) / max(len(q_distinct), len(t_distinct))
            else:
                max_typo = 0.0
                for qd in q_distinct:
                    for td in t_distinct:
                        max_typo = max(max_typo, fuzz.ratio(qd, td) / 100.0)
                distinctive_score = max_typo

            final_sim = (0.60 * distinctive_score) + (0.40 * blended)
        else:
            final_sim = blended

        return max(0.0, min(1.0, round(final_sim, 4)))

    def resolve(
        self,
        raw_name: str,
        city: Optional[str] = None,
        state: Optional[str] = None,
        pincode: Optional[str] = None,
        permanent_id: Optional[str] = None,
        db: Optional[Session] = None
    ) -> ResolutionResult:
        """
        Executes the 3-layer institution resolution pipeline:
        - Layer 1: Permanent ID exact lookup
        - Layer 2: RapidFuzz token matching on name + aliases
        - Layer 3: Geographic verification & contradiction penalties
        - Ambiguity check: Margin between top 2 candidates
        """
        reasons = []

        # Layer 1: Check for explicit or embedded Permanent ID
        pid_query = permanent_id or self.extract_permanent_id(raw_name)
        if pid_query and db:
            inst = db.query(Institution).filter(Institution.permanent_id == pid_query.strip()).first()
            if inst:
                return ResolutionResult(
                    best_institution=inst,
                    confidence=1.00,
                    status="AUTO_LINK",
                    needs_review=False,
                    candidates=[{
                        "id": inst.id,
                        "name": inst.name,
                        "permanent_id": inst.permanent_id,
                        "city": inst.city,
                        "confidence": 1.00
                    }],
                    reasons=[f"Layer 1: Exact AICTE Permanent ID match ({inst.permanent_id})"]
                )

        if not db:
            return ResolutionResult(
                best_institution=None,
                confidence=0.0,
                status="UNRESOLVED",
                needs_review=False,
                candidates=[],
                reasons=["No database session provided for resolution"]
            )

        # Normalize query inputs
        norm_query_name = self.normalize_name(raw_name)
        norm_query_city = self.normalize_city(city)
        norm_query_state = self.normalize_state(state)
        clean_pincode = pincode.strip() if pincode else ""

        # Geographic inference: infer state from city if not explicitly provided
        if not norm_query_state and norm_query_city:
            if norm_query_city in CITY_TO_STATE_LOOKUP:
                inferred_state = CITY_TO_STATE_LOOKUP[norm_query_city]
                norm_query_state = inferred_state
                reasons.append(f"State inferred from city: '{inferred_state.title()}' from '{norm_query_city.title()}'")

        # Fetch all candidate institutions from database
        all_institutions = db.query(Institution).all()
        scored_candidates = []

        for inst in all_institutions:
            # Layer 2: Name & Alias similarity with distinctive weighting & blended ratio
            name_sim = self.compute_name_similarity(norm_query_name, self.normalize_name(inst.normalized_name))
            alias_sims = [self.compute_name_similarity(norm_query_name, self.normalize_name(alias)) for alias in inst.aliases] if inst.aliases else []
            best_name_score = max([name_sim] + alias_sims) if alias_sims else name_sim

            # Layer 3: Geographic confirmation & contradiction penalties
            geo_score = 0.0
            inst_norm_city = self.normalize_city(inst.city)
            inst_norm_state = self.normalize_state(inst.state)
            inst_pincode = inst.pincode.strip() if inst.pincode else ""

            # City evaluation
            if norm_query_city and inst_norm_city:
                if norm_query_city == inst_norm_city:
                    geo_score += GEO_CITY_EXACT_BONUS
                else:
                    geo_score -= GEO_CITY_CONTRADICTION_PENALTY

            # State evaluation
            if norm_query_state and inst_norm_state:
                if norm_query_state == inst_norm_state:
                    geo_score += GEO_STATE_EXACT_BONUS
                else:
                    geo_score -= GEO_STATE_CONTRADICTION_PENALTY

            # Pincode evaluation
            if clean_pincode and inst_pincode:
                if clean_pincode == inst_pincode:
                    geo_score += GEO_PINCODE_EXACT_BONUS
                elif clean_pincode[:3] == inst_pincode[:3]:
                    geo_score += GEO_PINCODE_ZONAL_BONUS
                else:
                    geo_score -= GEO_PINCODE_MISMATCH_PENALTY

            # Composite confidence calculation clamped strictly to [0.0, 1.0]
            raw_confidence = (best_name_score * NAME_WEIGHT_IN_RESOLUTION) + geo_score
            composite_confidence = max(0.0, min(1.0, round(raw_confidence, 4)))

            scored_candidates.append(ResolutionCandidate(
                id=inst.id,
                name=inst.name,
                permanent_id=inst.permanent_id,
                city=inst.city,
                state=inst.state,
                confidence=composite_confidence
            ))

        # Sort candidates descending by confidence
        scored_candidates.sort(key=lambda c: c.confidence, reverse=True)
        top_candidates = scored_candidates[:3]

        if not top_candidates or top_candidates[0].confidence < RESOLUTION_REVIEW_THRESHOLD:
            conf_val = top_candidates[0].confidence if top_candidates else 0.0
            return ResolutionResult(
                best_institution=None,
                confidence=conf_val,
                status="UNRESOLVED",
                needs_review=False,
                candidates=[{
                    "id": c.id, "name": c.name, "permanent_id": c.permanent_id, "city": c.city, "confidence": c.confidence
                } for c in top_candidates],
                reasons=[f"Resolution confidence ({conf_val:.2f}) below minimum review threshold ({RESOLUTION_REVIEW_THRESHOLD})"]
            )

        top_cand = top_candidates[0]
        best_inst = db.query(Institution).filter(Institution.id == top_cand.id).first()
        is_ambiguous = False

        # Ambiguity Rule: If margin between top two candidates is <= RESOLUTION_AMBIGUITY_MARGIN
        if len(top_candidates) >= 2:
            second_cand = top_candidates[1]
            margin = round(top_cand.confidence - second_cand.confidence, 4)
            if margin <= RESOLUTION_AMBIGUITY_MARGIN:
                is_ambiguous = True
                reasons.append(
                    f"Ambiguity detected: Top candidates ('{top_cand.name}' @ {top_cand.confidence:.2f} and '{second_cand.name}' @ {second_cand.confidence:.2f}) are within ambiguity margin ({RESOLUTION_AMBIGUITY_MARGIN}). Human review required."
                )

        # Status determination
        if is_ambiguous:
            status = "NEEDS_REVIEW"
            needs_review = True
        elif top_cand.confidence >= RESOLUTION_AUTO_LINK_THRESHOLD:
            status = "AUTO_LINK"
            needs_review = False
            reasons.append(f"High resolution confidence ({top_cand.confidence:.2f} >= {RESOLUTION_AUTO_LINK_THRESHOLD}) with unambiguous geographic match")
        else:
            status = "NEEDS_REVIEW"
            needs_review = True
            reasons.append(f"Moderate resolution confidence ({top_cand.confidence:.2f}) in human review band ({RESOLUTION_REVIEW_THRESHOLD} - {RESOLUTION_AUTO_LINK_THRESHOLD})")

        return ResolutionResult(
            best_institution=best_inst,
            confidence=top_cand.confidence,
            status=status,
            needs_review=needs_review,
            candidates=[{
                "id": c.id, "name": c.name, "permanent_id": c.permanent_id, "city": c.city, "confidence": c.confidence
            } for c in top_candidates],
            reasons=reasons
        )
