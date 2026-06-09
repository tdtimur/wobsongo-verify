"""
wobsongo.core.scoring
~~~~~~~~~~~~~~~~~~~~~
Heuristic factuality scorer for document chunks.

factuality_score(text) -> float in [0.0, 1.0]

Signals are additive and domain-agnostic. The score estimates how
information-dense a chunk is — i.e. how likely it is to contain a
verifiable, specific fact worth storing and extracting SPO triples from.

Thresholds used by the ingestion pipeline:
  < 0.1   drop entirely — do not embed or store
  0.1-0.3 embed and store; skip LLM fact extraction
  >= 0.3  full pipeline — embed, store, extract facts
"""

from __future__ import annotations

import re

# Measurement units common in scientific/medical/legal documents
_UNITS = re.compile(
    r"\b\d+\.?\d*\s*"
    r"(%|mg|kg|g|mcg|µg|IU|mmol|mol|mL|dL|L|cm|mm|"
    r"days?|weeks?|months?|years?|hours?|minutes?|"
    r"cycles?|doses?|tablets?|units?)\b",
    re.IGNORECASE,
)

# Two or more title-cased words in a row → named entity proxy
_NAMED_ENTITIES = re.compile(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+")

# Language that signals relational or causal structure
_RELATIONAL = re.compile(
    r"\b("
    r"therefore|however|whereas|because|although|since|"
    r"compared\s+to|associated\s+with|significantly|"
    r"recommend(ed|s)?|suggest(ed|s)?|"
    r"indicates?|demonstrates?|shows?|"
    r"results?\s+in|leads?\s+to|reduces?|increases?"
    r")\b",
    re.IGNORECASE,
)

# Any standalone integer or decimal
_NUMERAL = re.compile(r"\b\d+(\.\d+)?\b")


def factuality_score(text: str) -> float:
    """Return a heuristic factuality score in [0.0, 1.0] for a text chunk."""
    s = text.strip()
    if not s:
        return 0.0

    score = 0.0

    if _UNITS.search(s):
        score += 0.25

    if len(_NAMED_ENTITIES.findall(s)) >= 2:
        score += 0.20

    if _RELATIONAL.search(s):
        score += 0.20

    n = len(s)
    if 50 <= n <= 500:
        score += 0.20
    elif 500 < n <= 1000:
        score += 0.10

    if _NUMERAL.search(s):
        score += 0.15

    return min(score, 1.0)
