# System Design: PDF → SQL + Vector Knowledge Base

## Overview

Two independent but complementary pipelines share one SQLite database.

- **Ingest**: PDF file → parse → score → embed → extract facts → store
- **Verify**: claim text → decompose → retrieve → judge → verdict

Architecture follows the existing hexagonal pattern: `wobsongo/core/` has zero
external imports. Adapters implement ports. `PipelineController` wires them.

---

## Data Flow

### Ingest

```
PDF file (bytes)
  │
  ▼  parse_document()                            parser.py
  │  • liteparse extracts text per page
  │  • heading detection (font-size heuristic + regex)
  │  • paragraph chunking (blank-line split)
  │  • cleaning: whitespace, dot leaders, page numbers, symbol noise, running headers
  │  • title: PDF /Title metadata → first-page heuristic → filename stem
  ▼
ParsedDocument { metadata: DocumentMetadata, chunks: list[ParsedChunk] }
  │
  ▼  content_hash = SHA-256(raw PDF bytes)
  │  check documents table — skip if hash already present (dedup)
  ▼
  │  factuality_score(chunk.text) per chunk          wobsongo/core/scoring.py (NEW)
  │  drop chunks with score < 0.1
  ▼
DocumentIngestor.ingest_pdf(doc: ParsedDocument)     wobsongo/core/services/ingestion.py
  │
  ├─ classify_topic(first_3_chunks) → topic_path     one LLM call per document
  │
  ├─ for each retained chunk:
  │    embed(chunk.text) → list[float]               EmbeddingClientProtocol
  │    save DocumentChunk                            RepositoryProtocol.save_chunk()
  │
  └─ for each chunk with score >= 0.3:
       extract_facts(chunk.text, chapter_context)    one LLM call per qualifying chunk
       for each fact:
         save VerifiedFact                           RepositoryProtocol.save_fact()
  │
  ▼
  save_document(SourceDocument)                      RepositoryProtocol.save_document()
```

### Verify

```
Post { id, raw_text, source, language, topic_tag? }
  │
  ▼  ClaimDecomposer.decompose(raw_text)             wobsongo/core/agents/decomposer.py
  │  LLM splits text into atomic verifiable claims
  ▼
list[str]  (atomic claims)
  │
  ▼  for each claim:
  │
  ├─ embed(claim) → vector                           EmbeddingClientProtocol
  │
  ├─ get_chunks_by_vector(vector, topic_filter)      RepositoryProtocol (sqlite-vec)
  │  returns top-k DocumentChunk, ordered by cosine similarity
  │  optional filter: topic_path prefix, factuality_score >= threshold
  │
  ├─ get_facts_by_chunk_ids([chunk.id, ...])         RepositoryProtocol (NEW)
  │  pull pre-extracted VerifiedFact rows for retrieved chunks
  │
  └─ NLIJudge.adjudicate(claim, chunks, facts)       wobsongo/core/agents/judge.py
       routes by truth_tier of best-matching fact:
         tier 1 (Axiomatic)    → strict entailment check
         tier 2 (Temporal)     → checks valid_from against claim date
         tier 3 (Probabilistic)→ checks conditions list
         tier 4 (Subjective)   → checks source attribution
       factuality_score passed as evidence weight signal
     → ClaimVerdict { verdict, confidence, reasoning, evidence_ids, truth_tier }
  │
  ▼
VerificationResult { post_id, claims, verdicts }
```

---

## Domain Models

### Existing (unchanged)

```python
# wobsongo/core/domain.py

@dataclass
class TaxonomyTag:
    path: str   # "health.infertility.treatment"
    label: str

@dataclass
class Post:
    id: UUID
    raw_text: str
    source: str
    language: str
    topic_tag: TaxonomyTag | None = None

@dataclass
class ClaimVerdict:
    claim: str
    verdict: str        # "SUPPORTED" | "REFUTED" | "INSUFFICIENT_EVIDENCE"
    confidence: float
    reasoning: str
    evidence_ids: list[UUID] = field(default_factory=list)
    truth_tier: int | None = None

@dataclass
class VerificationResult:
    post_id: UUID
    claims: list[str]
    verdicts: list[ClaimVerdict]
```

### Extended (fields added)

```python
@dataclass
class DocumentChunk:
    id: UUID
    source_doc_id: UUID
    text: str
    embedding: list[float]
    topic_path: str
    factuality_score: float   # NEW — 0.0-1.0 heuristic, assigned at parse time
    page: int                 # NEW — from ParsedChunk
    chapter: str | None       # NEW — from ParsedChunk

@dataclass
class VerifiedFact:
    id: UUID
    source_chunk_id: UUID
    source_doc_id: UUID       # NEW — denormalised for fast doc-level queries
    subject: str
    predicate: str
    object: str
    truth_tier: int           # 1=Axiomatic 2=Temporal 3=Probabilistic 4=Subjective
    topic_path: str
    valid_from: date | None = None
    conditions: str | None = None
```

### New

```python
@dataclass
class SourceDocument:         # NEW — wobsongo/core/domain.py
    id: UUID
    content_hash: str         # SHA-256 of raw PDF bytes — dedup key
    title: str
    filename: str
    file_type: str            # "pdf"
    file_size: int            # bytes
    num_pages: int
    created_at: str           # ISO 8601 from file stat
    modified_at: str          # ISO 8601 from file stat
    ingested_at: str          # ISO 8601 timestamp of ingest run
```

---

## SQL Schema

### New table: `documents`

```sql
CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,
    content_hash    TEXT NOT NULL UNIQUE,   -- SHA-256; dedup guard
    title           TEXT NOT NULL,
    filename        TEXT NOT NULL,
    file_type       TEXT NOT NULL,
    file_size       INTEGER NOT NULL,
    num_pages       INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    modified_at     TEXT NOT NULL,
    ingested_at     TEXT NOT NULL
);
```

### Altered table: `document_chunks`

```sql
-- Drop and recreate (migration required — existing data must be re-ingested)
CREATE TABLE IF NOT EXISTS document_chunks (
    id                  TEXT PRIMARY KEY,
    source_doc_id       TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    text                TEXT NOT NULL,
    embedding           BLOB,               -- struct-packed float32 array
    topic_path          TEXT NOT NULL,
    factuality_score    REAL NOT NULL DEFAULT 0.0,
    page                INTEGER NOT NULL,
    chapter             TEXT,               -- nullable
    line_start          INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_source_doc   ON document_chunks(source_doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_topic        ON document_chunks(topic_path);
CREATE INDEX IF NOT EXISTS idx_chunks_score        ON document_chunks(factuality_score);
```

### Altered table: `verified_facts`

```sql
CREATE TABLE IF NOT EXISTS verified_facts (
    id              TEXT PRIMARY KEY,
    source_chunk_id TEXT NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    source_doc_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    subject         TEXT NOT NULL,
    predicate       TEXT NOT NULL,
    object          TEXT NOT NULL,
    truth_tier      INTEGER NOT NULL CHECK (truth_tier BETWEEN 1 AND 4),
    topic_path      TEXT NOT NULL,
    valid_from      TEXT,                   -- ISO date string
    conditions      TEXT                    -- free-text condition description
);

CREATE INDEX IF NOT EXISTS idx_facts_subject    ON verified_facts(subject);
CREATE INDEX IF NOT EXISTS idx_facts_doc        ON verified_facts(source_doc_id);
CREATE INDEX IF NOT EXISTS idx_facts_topic      ON verified_facts(topic_path);
CREATE INDEX IF NOT EXISTS idx_facts_tier       ON verified_facts(truth_tier);
```

### sqlite-vec virtual table

```sql
-- Loaded at startup if sqlite-vec extension is present
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(
    chunk_id TEXT PRIMARY KEY,
    embedding FLOAT[768]      -- BGE-M3 output dimension
);
```

Queries against `chunk_vectors` use cosine distance and join back to
`document_chunks` for metadata filtering:

```sql
SELECT dc.*
FROM chunk_vectors cv
JOIN document_chunks dc ON dc.id = cv.chunk_id
WHERE cv.embedding MATCH ?            -- query vector blob
  AND dc.topic_path LIKE ?            -- optional topic prefix filter
  AND dc.factuality_score >= 0.3      -- optional quality floor
ORDER BY cv.distance
LIMIT 10;
```

---

## Port Contracts

### Existing (unchanged signatures)

```python
# wobsongo/core/ports.py

class RepositoryProtocol(Protocol):
    async def save_chunk(self, chunk: DocumentChunk) -> None: ...
    async def save_fact(self, fact: VerifiedFact) -> None: ...
    async def get_chunks_by_vector(
        self, vector: list[float], topic_filter: str
    ) -> list[DocumentChunk]: ...
    async def get_facts_by_subject(self, subject: str) -> list[VerifiedFact]: ...
```

### New methods

```python
    # document registry
    async def save_document(self, doc: SourceDocument) -> None: ...
    async def get_document_by_hash(self, content_hash: str) -> SourceDocument | None: ...

    # chunk-linked fact retrieval (used by verify pipeline)
    async def get_facts_by_chunk_ids(
        self, chunk_ids: list[UUID]
    ) -> list[VerifiedFact]: ...

    # taxonomy browsing (used by API / analysis tooling)
    async def get_facts_by_topic_path(
        self, topic_path: str                   # prefix match: "health" matches "health.x.y"
    ) -> list[VerifiedFact]: ...

    async def get_facts_by_truth_tier(
        self, truth_tier: int
    ) -> list[VerifiedFact]: ...
```

---

## Factuality Scorer

**Location**: `wobsongo/core/scoring.py` (new file)

Runs at parse time, before embedding. Pure function — no I/O, no LLM.

```python
def factuality_score(text: str) -> float:
    """
    Heuristic score 0.0-1.0 for information density of a text chunk.
    Used to:
      - drop near-zero chunks before storing (< 0.1)
      - skip LLM fact extraction for low-value chunks (< 0.3)
      - weight retrieved evidence in the judge prompt
    """
```

Signals (additive, capped at 1.0):

| Signal | Weight | Rationale |
|---|---|---|
| Measurement units present (`mg`, `%`, `mmol`, `IU`, `days`, …) | +0.25 | Clinical/scientific specificity |
| ≥2 capitalised multi-word names (named entity proxy) | +0.20 | Subject/object richness |
| Causal/comparative language (`therefore`, `compared to`, `significantly`, …) | +0.20 | Relational structure present |
| Length 50–500 chars | +0.20 | Sweet spot: not a fragment, not a wall of text |
| Any standalone numeral in context | +0.15 | Quantitative claim likely present |

Thresholds used downstream:

| Score | Action |
|---|---|
| < 0.1 | Drop entirely — do not embed or store |
| 0.1–0.29 | Embed and store chunk; skip LLM fact extraction |
| ≥ 0.3 | Full pipeline — embed, store, extract SPO facts |

---

## Ingestion Service Changes

**File**: `wobsongo/core/services/ingestion.py`

Current method `ingest_markdown(text: str, source_doc_id: UUID)` is replaced by:

```python
async def ingest_pdf(self, doc: ParsedDocument) -> list[VerifiedFact]:
    """
    Full ingest of a ParsedDocument produced by parser.parse_document().

    1. Dedup check via content_hash.
    2. Classify topic once for the document (LLM, first 3 chunks as sample).
    3. Score each chunk; drop score < 0.1.
    4. Embed and save all retained chunks as DocumentChunk.
    5. For chunks with score >= 0.3: extract SPO facts (LLM, per-chunk).
    6. Save SourceDocument record last (marks ingest as complete).
    """
```

Fact extraction prompt changes:
- Input was: full document text
- New input: single chunk text + `chapter` context string
- Rationale: chunk-level extraction gives precise `source_chunk_id` per fact,
  and the chapter string adds enough context for the LLM to produce
  better-scoped subject/predicate/object triples

---

## Pipeline Controller Changes

**File**: `wobsongo/core/pipeline.py`

```python
# replace:
async def ingest_document(self, markdown_text: str, source_doc_id: UUID) -> list[VerifiedFact]:

# with:
async def ingest_pdf(self, doc: ParsedDocument) -> list[VerifiedFact]:
    return await self._ingestor.ingest_pdf(doc)
```

Verify loop — add fact lookup by chunk IDs after vector retrieval:

```python
chunks = await self._repo.get_chunks_by_vector(claim_vector, topic_filter)
facts  = await self._repo.get_facts_by_chunk_ids([c.id for c in chunks])
#                         ^^^ replaces get_facts_by_subject(claim)
verdict = await self._judge.adjudicate(claim, chunks, facts)
```

---

## API Changes

**File**: `wobsongo/api/app.py`

```
POST /api/v1/ingest       multipart/form-data, field: file (PDF bytes)
                          calls parse_document() then pipeline.ingest_pdf()
                          returns: { document_id, num_chunks, num_facts }

GET  /api/v1/documents    list all ingested documents (from documents table)
GET  /api/v1/documents/{id}/facts   facts for one document, optional ?tier=1&topic=health
```

The existing `POST /api/v1/verify` is unchanged.

---

## Build Order

Each step is independently testable before the next begins.

| Step | What | Files touched |
|---|---|---|
| 1 | SQL schema migration — add `documents` table, new columns on chunks/facts, indexes | `db_sqlite.py` |
| 2 | `SourceDocument` domain model + `save_document` / `get_document_by_hash` port + adapter | `domain.py`, `ports.py`, `db_sqlite.py` |
| 3 | `factuality_score()` function + tests | `wobsongo/core/scoring.py` (new), `tests/core/test_scoring.py` (new) |
| 4 | Extend `DocumentChunk` with `factuality_score`, `page`, `chapter` — update adapter serialisation | `domain.py`, `db_sqlite.py` |
| 5 | `ingest_pdf()` replacing `ingest_markdown()` in `DocumentIngestor` | `ingestion.py` |
| 6 | `sqlite-vec` virtual table + `get_chunks_by_vector()` implementation | `db_sqlite.py` |
| 7 | `get_facts_by_chunk_ids()`, `get_facts_by_topic_path()`, `get_facts_by_truth_tier()` | `ports.py`, `db_sqlite.py` |
| 8 | `PipelineController` wiring — swap `ingest_document` → `ingest_pdf`, update verify loop | `pipeline.py` |
| 9 | API endpoint for PDF upload + document/facts browsing endpoints | `app.py` |

Steps 1–6 give a working end-to-end system (ingest a PDF, verify a claim against it).
Steps 7–9 add browsing, taxonomy queries, and the HTTP interface.
