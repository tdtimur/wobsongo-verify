"""
wobsongo.core.domain
~~~~~~~~~~~~~~~~~~~~
Pure stdlib dataclasses. Zero external imports.
All entities used across the Wobsongo pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID


@dataclass
class TaxonomyTag:
    """Ontological topic tag using path enumeration."""

    path: str   # e.g. "health.vaccines.mrna"
    label: str  # human-readable label


@dataclass
class Post:
    """A raw social media post pending verification."""

    id: UUID
    raw_text: str
    source: str    # e.g. "twitter", "tiktok", "manual"
    language: str  # ISO 639-1, e.g. "en", "fr"
    topic_tag: TaxonomyTag | None = None


@dataclass
class DocumentChunk:
    """A chunk of a source document with its vector embedding."""

    id: UUID
    text: str
    embedding: list[float]
    source_doc_id: UUID
    topic_path: str  # e.g. "health.vaccines"


@dataclass
class VerifiedFact:
    """A structured, verified fact extracted from a trusted source document."""

    id: UUID
    subject: str
    predicate: str
    object: str
    truth_tier: int       # 1=Axiomatic, 2=Temporal, 3=Probabilistic, 4=Subjective
    topic_path: str       # e.g. "health.vaccines"
    source_chunk_id: UUID
    valid_from: date | None = None
    conditions: str | None = None  # e.g. "safe if dosage < 5mg"


@dataclass
class ClaimVerdict:
    """The judge's verdict on a single atomic claim."""

    claim: str
    verdict: str        # "SUPPORTED" | "REFUTED" | "INSUFFICIENT_EVIDENCE"
    confidence: float   # 0.0-1.0
    reasoning: str
    evidence_ids: list[UUID] = field(default_factory=list)
    truth_tier: int | None = None


@dataclass
class VerificationResult:
    """Aggregated result of verifying all claims in a Post."""

    post_id: UUID
    claims: list[str]
    verdicts: list[ClaimVerdict]
