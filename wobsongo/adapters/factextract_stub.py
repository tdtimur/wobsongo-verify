"""
wobsongo.adapters.factextract_stub
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
StubFactExtractor — FactExtractorProtocol for dev/testing only.

Returns deterministic facts without any network calls.
Two facts are always returned so tests can assert on list length and structure.
"""

from __future__ import annotations

from wobsongo.core.domain import ExtractedFact


class StubFactExtractor:
    """Deterministic fake fact extractor. Zero external deps."""

    async def extract_facts(self, text: str) -> list[ExtractedFact]:
        return [
            ExtractedFact(
                subject="stub subject",
                predicate="stub predicate",
                object="stub object",
                truth_tier=1,
            ),
            ExtractedFact(
                subject="stub entity",
                predicate="stub relation",
                object="stub value",
                truth_tier=4,
            ),
        ]
