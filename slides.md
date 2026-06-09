---
title: Wobsongo Verify
author: ImpactScope
---

# Wobsongo Verify

Automated claim verification against trusted documents

Stack: Python · SQLite · sqlite-vec · Ollama · Telegram

Pattern: Hexagonal (Ports & Adapters)

---

## The Problem

Social media users share health claims —
many are inaccurate, misattributed, or out of context.

**Goal:** given a claim like

> "Letrozole is better than clomiphene for PCOS infertility"

automatically check it against authoritative sources
and return a verdict.

---

## Two Pipelines

**Ingestion** (offline, operator-run)

```
PDF → parse → score → embed → store chunks + facts
```

**Verification** (real-time, user-triggered)

```
Claim → decompose → retrieve → judge → verdict
```

---

## Ingestion Pipeline

```
PDF file
  └─ liteparse
       └─ ParsedDocument
            └─ DocumentIngestor
                 ├─ factuality score
                 ├─ OllamaEmbedder
                 │    └─► document_chunks + vec_chunks
                 └─ OllamaFactExtractor
                      └─► verified_facts
```

---

## Verification Pipeline

```
User claim (Telegram)
  └─ PipelineController
       ├─ ClaimDecomposer (LLM)
       │    └─► atomic sub-claims
       ├─ vector search
       │    └─► top-10 relevant chunks
       └─ NLIJudge
            ├─ facts found  → tier-routed prompt
            └─ no facts     → chunk fallback prompt
```

---

## Step 1 — PDF Parsing

`liteparse` extracts per-page structure.

Output: `ParsedDocument` — metadata + list of `ParsedChunk`

| Field        | Source                        |
|--------------|-------------------------------|
| `text`       | paragraph text                |
| `page`       | page number (1-indexed)       |
| `chapter`    | font-size heuristic + regex   |
| `line_start` | newline count within page     |

---

## Step 2 — Factuality Scoring

Each chunk is scored before storing anything.

| Signal                         | Weight |
|--------------------------------|--------|
| Contains units (mg, %, mmHg…) | +0.25  |
| Named entities (WHO, PCOS…)    | +0.20  |
| Relational verbs (causes, …)   | +0.20  |
| Length ≥ 40 words              | +0.20  |
| Contains numerals              | +0.15  |

---

## Step 2 — Routing by Score

| Score     | Action                  |
|-----------|-------------------------|
| `< 0.1`   | dropped (noise)         |
| `0.1–0.3` | embed only              |
| `≥ 0.3`   | embed + extract facts   |

This avoids wasting LLM calls on headers,
page numbers, and whitespace.

---

## Step 3 — Embedding

**Model:** `embeddinggemma:300m` via local Ollama

**Dimensions:** 768

```python
response = client.embed(model="embeddinggemma:300m", input=text)
vector = response.embeddings[0]  # list[float], len=768
```

Each chunk gets a 768-dim vector stored as a BLOB
alongside the text in `document_chunks`.

---

## Step 3 — Vector Index

sqlite-vec creates an ANN index as a virtual table:

```sql
CREATE VIRTUAL TABLE vec_chunks
USING vec0(chunk_id TEXT PRIMARY KEY, embedding float[768]);
```

Retrieval at query time:

```sql
SELECT dc.*, d.title AS doc_title
FROM vec_chunks vc
JOIN document_chunks dc ON dc.id = vc.chunk_id
LEFT JOIN documents d ON d.id = dc.source_doc_id
WHERE vc.embedding MATCH ? AND vc.k = 10
ORDER BY vc.distance
```

---

## Step 4 — Fact Extraction

High-scoring chunks (≥ 0.3) → `OllamaFactExtractor`

**Model:** `gemma4:31b-cloud` via Ollama Cloud

Output: schema-constrained JSON (SPO triples)

```json
{
  "subject": "letrozole",
  "predicate": "recommended over clomiphene citrate",
  "object": "women with PCOS-related infertility",
  "truth_tier": 1
}
```

---

## Step 4 — Truth Tiers

Facts are tagged with a tier that controls how the
judge evaluates claims against them.

| Tier | Type          | Example                          |
|------|---------------|----------------------------------|
| 1    | Axiomatic     | drug A is more effective than B  |
| 2    | Time-bound    | guideline valid since 2023       |
| 3    | Conditional   | safe if dosage < 5mg             |
| 4    | Expert opinion| WHO recommends…                  |

---

## Step 5 — Verdict

**Per claim:** `SUPPORTED` / `REFUTED` / `INSUFFICIENT_EVIDENCE`

```
❓ INSUFFICIENT_EVIDENCE — 3 claims checked

1. ✅ SUPPORTED (82%)
   Letrozole is recommended over clomiphene for PCOS
   According to WHO Infertility Guideline, p.47…

2. ❓ INSUFFICIENT_EVIDENCE (0%)
   The retrieved excerpts do not clearly address…
```

---

## Data Model

```
documents
  id, title, content_hash, filename, num_pages

document_chunks
  id, source_doc_id → documents
  text, embedding (BLOB)
  topic_path, factuality_score, page, chapter

vec_chunks  (virtual, ANN index)
  chunk_id → document_chunks, embedding float[768]

verified_facts
  id, source_chunk_id → document_chunks
  subject, predicate, object, truth_tier, topic_path
```

---

## Key Design Choices

| Decision                 | Reason                                       |
|--------------------------|----------------------------------------------|
| Hexagonal architecture   | core/ has zero external deps                 |
| Factuality routing       | skip LLM on boilerplate chunks               |
| sqlite-vec               | single-file DB, no infra, fits 500 PDFs      |
| Chunk fallback in judge  | never manufacture confidence without evidence|
| Ollama daemon            | cloud auth via `ollama login`                |
| SHA-256 content_hash     | idempotent re-ingestion, doc-level dedup     |

---

## Current Status

**Documents ingested:** 1 (WHO Infertility Guideline, 262 pages)

**Chunks embedded:** 1,671 of 1,871

**Facts extracted:** 0 — full run pending

**Verdict path:** chunk fallback active and working

**Bot:** live on Telegram

**Next:** overnight ingestion with fact extraction enabled
