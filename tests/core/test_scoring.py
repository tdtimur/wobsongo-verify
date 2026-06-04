"""
Tests for wobsongo.core.scoring.factuality_score.

Two layers:
  1. Signal unit tests  — verify each heuristic fires independently.
  2. Annotated cases    — parametrized from tests/data/scoring_cases.json.
     Add entries there to extend coverage without touching this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wobsongo.core.scoring import factuality_score

# ---------------------------------------------------------------------------
# Annotated test cases
# ---------------------------------------------------------------------------

_CASES_PATH = Path(__file__).parent.parent / "data" / "scoring_cases.json"
_CASES = json.loads(_CASES_PATH.read_text()) if _CASES_PATH.exists() else []


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_annotated_cases(case: dict) -> None:
    score = factuality_score(case["text"])
    assert case["min_score"] <= score <= case["max_score"], (
        f"score={score:.2f} not in [{case['min_score']}, {case['max_score']}] "
        f"— {case['note']}"
    )


# ---------------------------------------------------------------------------
# Signal unit tests
# ---------------------------------------------------------------------------


def test_empty_returns_zero() -> None:
    assert factuality_score("") == 0.0


def test_whitespace_returns_zero() -> None:
    assert factuality_score("   \n  ") == 0.0


def test_units_signal() -> None:
    # A sentence long enough to also hit the length signal but no other signals
    base = "The patient received a dose of 50mg daily for treatment purposes here."
    score = factuality_score(base)
    assert score >= 0.25, "units signal should contribute at least 0.25"


def test_named_entity_signal() -> None:
    # Two multi-word capitalised names, long enough for length signal, no units/relational
    text = "According to World Health Organization guidelines, the United Nations report noted findings."
    score = factuality_score(text)
    assert score >= 0.20, "named entity signal should contribute at least 0.20"


def test_relational_signal() -> None:
    text = (
        "The intervention was associated with a reduction in symptoms "
        "and therefore considered effective by the committee."
    )
    score = factuality_score(text)
    assert score >= 0.20, "relational signal should contribute at least 0.20"


def test_length_sweet_spot() -> None:
    # Exactly 60 chars of content with no other signals
    text = "a" * 60
    score = factuality_score(text)
    assert score >= 0.20, "length signal (50-500 chars) should contribute 0.20"


def test_length_too_short() -> None:
    text = "a" * 20  # below 50-char threshold
    score = factuality_score(text)
    assert score < 0.20, "short text should not receive length bonus"


def test_numeral_signal() -> None:
    text = "The study enrolled 42 participants across three sites for evaluation."
    score = factuality_score(text)
    assert score >= 0.15, "numeral signal should contribute at least 0.15"


def test_score_capped_at_one() -> None:
    # All five signals fire: units, >=2 named entities, relational, length, numeral
    text = (
        "World Health Organization and Harvard Medical School recommend "
        "administering 500mg of letrozole daily for 7 days, as this is "
        "significantly more effective compared to clomiphene citrate in "
        "3 randomised controlled trials."
    )
    assert factuality_score(text) == 1.0


def test_high_score_implies_full_pipeline_threshold() -> None:
    clinical = (
        "Letrozole 2.5mg administered for 5 days is recommended over "
        "clomiphene citrate for ovulation induction in women with PCOS, "
        "based on 12 randomised trials showing significantly higher live "
        "birth rates."
    )
    assert factuality_score(clinical) >= 0.3, "clinical sentence should pass the fact-extraction threshold"


def test_low_score_implies_drop_threshold() -> None:
    noise = "iii"
    assert factuality_score(noise) < 0.1, "page number noise should fall below the drop threshold"
