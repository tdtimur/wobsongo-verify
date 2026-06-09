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
class DocumentMetadata:
    """File-level metadata produced by the parser before ingestion."""

    content_hash: str   # SHA-256 of raw file bytes — dedup key
    title: str
    filename: str
    file_type: str      # e.g. "pdf"
    file_size: int      # bytes
    num_pages: int
    created_at: str     # ISO 8601 (st_ctime)
    modified_at: str    # ISO 8601 (st_mtime)


@dataclass
class ParsedChunk:
    """A paragraph-sized chunk produced by the parser with positional metadata."""

    text: str
    page: int
    chapter: str | None
    line_start: int


@dataclass
class ParsedDocument:
    """Parser output: document metadata + ordered list of text chunks."""

    metadata: DocumentMetadata
    chunks: list[ParsedChunk]


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
class SourceDocument:
    """A source document ingested into the knowledge base."""

    id: UUID
    content_hash: str    # SHA-256 of raw file bytes — dedup key
    title: str
    filename: str
    file_type: str       # e.g. "pdf"
    file_size: int       # bytes
    num_pages: int
    created_at: str      # ISO 8601 from file stat (st_ctime)
    modified_at: str     # ISO 8601 from file stat (st_mtime)
    ingested_at: str     # ISO 8601 timestamp of ingest run


@dataclass
class DocumentChunk:
    """A chunk of a source document with its vector embedding."""

    id: UUID
    source_doc_id: UUID
    text: str
    embedding: list[float]
    topic_path: str         # e.g. "health.vaccines"
    factuality_score: float = 0.0
    page: int = 0
    chapter: str | None = None
    line_start: int = 0
    source_doc_title: str | None = None  # populated on retrieval via JOIN


@dataclass
class ExtractedFact:
    """Raw SPO triple returned by a FactExtractor before provenance is attached."""

    subject: str
    predicate: str
    object: str
    truth_tier: int   # 1=Axiomatic, 2=Temporal, 3=Probabilistic, 4=Subjective


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
    source_doc_id: UUID | None = None  # denormalised FK for fast doc-level queries
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


@dataclass
class User:
    """An authenticated user of the API."""

    id: UUID
    email: str
    password_hash: str
    role: str           # admin | viewer
    created_at: str     # ISO 8601
    updated_at: str     # ISO 8601
    is_active: bool = True
    is_email_verified: bool = False
    last_login_at: str | None = None


@dataclass
class IngestionJob:
    """Tracks the lifecycle of a single PDF ingestion request."""

    id: UUID
    status: str        # pending | processing | done | failed
    title: str
    filename: str
    storage_key: str   # object storage key (S3 / MinIO)
    created_at: str    # ISO 8601
    content_hash: str | None = None
    chunks_stored: int | None = None
    facts_extracted: int | None = None
    error_message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
