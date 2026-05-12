# System Architecture: Data Flow & Design

## How Wobsongo Works

Two pipelines: **Ingestion** (build knowledge base) and **Verification** (check claims).

---

## Pipeline 1: Ingestion

**Goal:** Turn raw documents (PDFs) into structured, searchable knowledge.

```
PDF file
  → pymupdf4llm → Markdown text
  → LLM: "what topic is this?" → topic_path (e.g. "health.vaccines")
  → LLM: "extract facts as subject/predicate/object triples" → list[VerifiedFact]
  → EmbeddingClient: embed each text chunk → list[float]
  → SQLiteRepository: store DocumentChunk + VerifiedFact
```

Two things stored per document:
- **`DocumentChunk`** — raw text + vector embedding (for semantic search later)
- **`VerifiedFact`** — structured triple `(subject, predicate, object)` tagged with `truth_tier` + `topic_path` (for exact/filtered lookup later)

---

## Pipeline 2: Verification

**Goal:** Given a messy social media post, produce a verdict.

```
Post text ("Vaccines cause sterility and were made in 2 months")
  │
  ▼
[ClaimDecomposer]
  → LLM: "split into atomic verifiable claims"
  → ["Vaccines cause sterility", "Vaccine development took < 2 months"]
  │
  ▼ (for each claim)
[Hybrid Retriever — SQLiteRepository]
  → Vector search: DocumentChunk WHERE topic_path LIKE "health.vaccines%" AND cosine_distance < 0.3
  → Keyword search: VerifiedFact WHERE subject LIKE "vaccine%"
  → Returns: list[DocumentChunk] + list[VerifiedFact] as evidence
  │
  ▼
[NLIJudge]
  → Reads truth_tier from retrieved VerifiedFact
  → Routes to tier-specific logic:
      Tier 1 (axiomatic)     → strict binary prompt: "does evidence support or refute?"
      Tier 2 (temporal)      → date check: "is this still true given valid_from?"
      Tier 3 (probabilistic) → conditions check: "safe if dosage < 5mg — does claim omit that?"
      Tier 4 (subjective)    → attribution check: "is this presented as fact or opinion?"
  → LLM returns: {"verdict": "REFUTED", "confidence": 0.95, "reasoning": "..."}
  → Wraps into ClaimVerdict dataclass
  │
  ▼
[PipelineController]
  → Aggregates all ClaimVerdicts
  → Returns VerificationResult (post_id + all claims + all verdicts)
```

---

## Data Model Relationships

```
Post
 └── decomposed into → list[str] (atomic claims)

DocumentChunk
 ├── id, text, embedding (vector)
 ├── source_doc_id → links back to original PDF
 └── topic_path → scopes retrieval

VerifiedFact
 ├── subject / predicate / object → structured triple
 ├── truth_tier (1–4) → drives Judge routing
 ├── topic_path → scopes retrieval
 ├── valid_from → Tier 2 date logic
 ├── conditions → Tier 3 conditional logic
 └── source_chunk_id → links back to DocumentChunk

ClaimVerdict
 ├── claim (the atomic string)
 ├── verdict: SUPPORTED | REFUTED | INSUFFICIENT_EVIDENCE
 ├── confidence: 0.0–1.0
 ├── reasoning: LLM explanation
 ├── evidence_ids: which chunks/facts were used
 └── truth_tier: which tier was applied
```

---

## Hexagonal Architecture: Why It Matters

Core domain knows nothing about SQLite, OpenAI, or HTTP. It only speaks to **ports** (Protocols):

```
Core (pure Python)
  ↕ RepositoryProtocol      ← SQLiteRepository (or Postgres adapter later)
  ↕ LLMClientProtocol       ← StubLLMClient (dev) / OpenAI / Ollama / Gemma
  ↕ EmbeddingClientProtocol ← BGEEmbedder (or any other model)
```

Swap any adapter without touching business logic. Air-gapped deployment = just swap LLM + embedding adapters to local models. Scale to Postgres = new `db_postgres.py`, zero core changes.

---

## API Surface

| Endpoint | Input | What happens |
|---|---|---|
| `POST /api/v1/ingest` | PDF file (multipart) | Runs ingestion pipeline, returns `{facts_extracted, chunks_stored}` |
| `POST /api/v1/verify` | `{text, source, language}` | Runs verification pipeline, returns `VerificationResult` as JSON |
