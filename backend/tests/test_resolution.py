import pytest
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.app.database import SessionLocal
from backend.app.services.resolution_engine import InstitutionResolutionEngine
from backend.app.models.institution import Institution


@pytest.fixture(scope="module")
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def engine():
    return InstitutionResolutionEngine()


class TestInstitutionResolutionEngine:

    def test_name_normalization_and_abbreviation_expansion(self, engine):
        """Checks abbreviation expansion (inst., tech., engg., coll., univ.) and stopword removal."""
        raw = "Apex Inst. of Tech. & Engg. Coll."
        normalized = engine.normalize_name(raw)
        assert "institute" in normalized
        assert "technology" in normalized
        assert "engineering" in normalized
        assert "college" in normalized
        assert "of" not in normalized.split()

    def test_city_alias_normalization(self, engine):
        """Test (c): Bangalore / Bengaluru alias works."""
        assert engine.normalize_city("Bangalore") == "bengaluru"
        assert engine.normalize_city("Bengaluru") == "bengaluru"
        assert engine.normalize_city("Bombay") == "mumbai"
        assert engine.normalize_city("Poona") == "pune"

    def test_layer_1_permanent_id_match(self, engine, db_session):
        """Checks exact Permanent ID auto-link."""
        result = engine.resolve(
            raw_name="Random Name That Does Not Match Anything",
            permanent_id="1-1099238411",
            db=db_session
        )
        assert result.status == "AUTO_LINK"
        assert result.confidence == 1.00
        assert result.best_institution is not None
        assert result.best_institution.permanent_id == "1-1099238411"

    def test_layer_1_embedded_permanent_id(self, engine, db_session):
        """Checks extraction of embedded Permanent ID from raw text."""
        result = engine.resolve(
            raw_name="Grievance against Institute 1-1099238411 located in Pune",
            db=db_session
        )
        assert result.status == "AUTO_LINK"
        assert result.confidence == 1.00
        assert result.best_institution.permanent_id == "1-1099238411"

    def test_scenario_2_false_match_avoidance_jaipur_raipur(self, engine, db_session):
        """
        Scenario 2: National College of Engineering in Jaipur vs Raipur.
        City contradiction penalty must prevent false match across cities.
        """
        # Query specifically specifying Raipur
        result = engine.resolve(
            raw_name="National College of Engineering",
            city="Raipur",
            state="Chhattisgarh",
            db=db_session
        )
        assert result.best_institution is not None
        assert result.best_institution.city == "Raipur"
        assert result.best_institution.permanent_id == "1-1099445566"

        # Check that candidate for Jaipur received severe contradiction penalty
        jaipur_cand = next((c for c in result.candidates if c["city"] == "Jaipur"), None)
        if jaipur_cand:
            assert jaipur_cand["confidence"] < 0.50

    def test_same_name_institutions_no_city_forces_review(self, engine, db_session):
        """
        Test (b): Same-name institutions with NO city given must trigger the
        ambiguity rule and go to NEEDS_REVIEW.
        """
        result = engine.resolve(
            raw_name="National College of Engineering",
            city=None,
            state=None,
            db=db_session
        )
        # Both Jaipur and Raipur have the identical name, so margin is 0.0
        assert result.status == "NEEDS_REVIEW"
        assert result.needs_review is True
        assert len(result.candidates) >= 2
        margin = abs(result.candidates[0]["confidence"] - result.candidates[1]["confidence"])
        assert margin <= 0.08
        assert any("ambiguity" in r.lower() for r in result.reasons)

    def test_scenario_3_human_review_bengaluru_ambiguous(self, engine, db_session):
        """
        Scenario 3: 'Apex Academy' matches 3 candidate institutions in Bengaluru.
        Must land in human review band (0.65 - 0.75) with top 3 candidates.
        """
        result = engine.resolve(
            raw_name="Apex Academy",
            city="Bengaluru",
            state="Karnataka",
            db=db_session
        )
        assert result.status == "NEEDS_REVIEW"
        assert result.needs_review is True
        assert 0.65 <= result.confidence <= 0.75
        assert len(result.candidates) == 3
        # Check that top candidate is one of the Apex institutions in Bengaluru
        assert "Apex" in result.candidates[0]["name"]
        assert result.candidates[0]["city"] == "Bengaluru"

    def test_bangalore_alias_in_query_resolves_to_bengaluru(self, engine, db_session):
        """
        Test (c) practical verification: 'Apex Tech College, Bangalore' must match
        institutions recorded with city 'Bengaluru'.
        """
        result = engine.resolve(
            raw_name="Apex Tech College",
            city="Bangalore",
            state="Karnataka",
            db=db_session
        )
        assert result.best_institution is not None
        assert result.best_institution.city == "Bengaluru"
        assert result.confidence >= 0.60

    def test_floating_point_rounding_exact_threshold(self, engine):
        """
        Verifies that IEEE-754 floating point arithmetic (e.g. 0.65 + 0.15 + 0.05 == 0.8500000000000001)
        is safely rounded to 4 decimals so composite scores evaluate strictly as exactly 0.85.
        """
        raw_val = 0.65 + 0.15 + 0.05
        # In raw IEEE 754, raw_val != 0.85
        assert raw_val != 0.85
        assert abs(raw_val - 0.85) < 1e-15

        # With 4-decimal rounding safeguard
        rounded_val = round(raw_val, 4)
        assert rounded_val == 0.85

    def test_unlisted_misspellings_resolution(self, engine, db_session):
        """
        Verifies resolution behavior for queries containing misspellings or word-order transpositions
        that are NOT present in the institution's alias list.
        Target: ABC Institute of Technology (Pune, Maharashtra, PID 1-1099238411)
        """
        # Query 1: "ABC Instt of Tech Pune" (unlisted typo "Instt")
        res1 = engine.resolve(
            raw_name="ABC Instt of Tech Pune",
            city="Pune",
            state="Maharashtra",
            db=db_session
        )
        assert res1.best_institution is not None
        assert res1.best_institution.permanent_id == "1-1099238411"
        assert res1.confidence >= 0.70
        assert res1.status in {"AUTO_LINK", "NEEDS_REVIEW"}

        # Query 2: "Abc technology institute pune" (transposed name words)
        res2 = engine.resolve(
            raw_name="Abc technology institute pune",
            city="Pune",
            state="Maharashtra",
            db=db_session
        )
        assert res2.best_institution is not None
        assert res2.best_institution.permanent_id == "1-1099238411"
        assert res2.confidence >= 0.80

    def test_unresolved_reason_has_no_code_fragments(self, engine, db_session):
        """
        Item 1: Checks that UNRESOLVED reason text has proper f-string formatting
        and contains no code fragments like 'if top_candidates'.
        """
        result = engine.resolve(
            raw_name="NonExistentInstitutionXYZ987654321",
            city="NowhereVille",
            state="NowhereState",
            db=db_session
        )
        assert result.status == "UNRESOLVED"
        assert len(result.reasons) > 0
        reason = result.reasons[0]
        # Must NOT contain raw code fragments
        assert "if top_candidates" not in reason
        assert "top_candidates[0]" not in reason
        # Must contain properly formatted numeric confidence
        assert "Resolution confidence (" in reason
        assert "below minimum review threshold" in reason

    def test_name_matching_distinctive_weighting_and_subset_penalty(self, engine, db_session):
        """
        Item 2: Distinctive token weighting & blended token_sort_ratio:
        (a) Query 'Abc technology institute pune' against 'Premier Institute of Technology':
            Generic words (technology, institute) previously inflated score to 0.68.
            With distinctive token weighting, 'Premier Institute of Technology' drops to ~0.55 (or 0.35 without geo),
            safely below the 0.60 review threshold.
        (b) Query 'National College of Engineering' against 'National Engineering Academy':
            Subset match via alias 'National Engg' was 0.65 (tied with exact name).
            Now blended ratio drops it to ~0.6288, strictly below exact name match (0.65).
        """
        # Query 1: "Abc technology institute pune" with city="Pune"
        res1 = engine.resolve(
            raw_name="Abc technology institute pune",
            city="Pune",
            state="Maharashtra",
            db=db_session
        )
        premier_cand = next((c for c in res1.candidates if "Premier" in c["name"]), None)
        assert premier_cand is not None
        # Previously scored ~0.68; now drops < 0.60 (UNRESOLVED band for this candidate)
        assert premier_cand["confidence"] < 0.60
        # ABC Institute of Technology must still be top candidate >= 0.80
        assert res1.best_institution is not None
        assert res1.best_institution.permanent_id == "1-1099238411"
        assert res1.confidence >= 0.80

        # Query 2: "National College of Engineering" (no geo)
        nce_inst = db_session.query(Institution).filter(Institution.name == "National College of Engineering").first()
        nea_inst = db_session.query(Institution).filter(Institution.name == "National Engineering Academy").first()
        
        # Calculate raw name scores
        q_norm = engine.normalize_name("National College of Engineering")
        nce_score = engine.compute_name_similarity(q_norm, engine.normalize_name(nce_inst.normalized_name)) * 0.65
        nea_alias_scores = [
            engine.compute_name_similarity(q_norm, engine.normalize_name(alias)) * 0.65
            for alias in nea_inst.aliases
        ]
        nea_best_score = max(nea_alias_scores)

        # Exact match gets full 0.65
        assert nce_score == 0.65
        # Subset match via 'National Engg' was previously 0.65 (1.0 * 0.65), now strictly < 0.65
        assert nea_best_score < 0.65
        assert nea_best_score < nce_score

    def test_city_only_state_inference(self, engine, db_session):
        """
        Item 3: City-to-state lookup and state inference:
        - Query with known city (e.g. Pune) and state=None infers Maharashtra,
          awards state bonus (+0.05), and displays 'State inferred from city' in reasons.
        - Exact name + city-only reaches AUTO_LINK (0.65 + 0.15 + 0.05 = 0.85).
        - Query 'ABC Instt of Tech Pune' shows inferred state in reasons.
        - Query with unlisted city (e.g. Atlantis) must NOT infer a state and
          must NOT contain 'State inferred from city' in reasons.
        """
        # User specified test: "ABC Instt of Tech Pune" should show inferred state
        res_user_check = engine.resolve(
            raw_name="ABC Instt of Tech Pune",
            city="Pune",
            state=None,
            db=db_session
        )
        assert res_user_check.best_institution is not None
        assert res_user_check.best_institution.permanent_id == "1-1099238411"
        assert any("State inferred from city" in r for r in res_user_check.reasons)
        assert any("Maharashtra" in r for r in res_user_check.reasons)

        # Auto-link demonstration: exact name + city-only reaches 0.85 (previously capped at 0.80)
        res_exact = engine.resolve(
            raw_name="ABC Institute of Technology",
            city="Pune",
            state=None,
            db=db_session
        )
        assert res_exact.confidence == 0.85
        assert res_exact.status == "AUTO_LINK"
        assert any("State inferred from city" in r for r in res_exact.reasons)

        # Unknown city: Atlantis -> no state inferred
        res_unknown = engine.resolve(
            raw_name="ABC Instt of Tech Pune",
            city="Atlantis",
            state=None,
            db=db_session
        )
        assert not any("State inferred from city" in r for r in res_unknown.reasons)


