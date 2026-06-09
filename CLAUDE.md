# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands assume a devbox shell (`devbox shell`) or direct `uv run` invocations.

```bash
# Run tests
uv run pytest                        # all tests
uv run pytest tests/core/            # specific module
uv run pytest -v                     # verbose

# Lint / type-check
uv run ruff check wobsongo/ tests/   # lint
uv run mypy wobsongo/                # strict type-check

# Run dev server
uv run python main.py                # Litestar on 127.0.0.1:8000 with reload

# Devbox composite check (ruff + mypy + pytest)
devbox run check
```

Install optional extras as needed:
```bash
uv pip install -e ".[llm,embed,db,pdf]"
```

## Architecture

**Hexagonal (Ports & Adapters)** pattern — `wobsongo/core/` contains zero external imports.

```
wobsongo/core/
  domain.py        # Pure dataclasses: Post, DocumentChunk, VerifiedFact, ClaimVerdict, VerificationResult
  ports.py         # Protocol interfaces: RepositoryProtocol, LLMClientProtocol, EmbeddingClientProtocol
  pipeline.py      # PipelineController — orchestrates verify() and ingest_document()
  agents/
    decomposer.py  # ClaimDecomposer: splits post text into atomic verifiable claims via LLM
    judge.py       # NLIJudge: adjudicates claims against evidence, routing by truth tier
  services/
    ingestion.py   # DocumentIngestor: chunks markdown → embeds → extracts SPO facts → stores

wobsongo/adapters/
  llm_openai.py    # OpenAILLMClient (needs OPENAI_API_KEY; model via OPENAI_MODEL env var)
  llm_stub.py      # StubLLMClient — deterministic hardcoded responses for tests
  embed_bge.py     # BGEEmbedder using BAAI/bge-m3 (768-dim, multilingual)
  db_sqlite.py     # SQLiteRepository — WAL mode; vector search currently stubbed

wobsongo/api/
  app.py           # Litestar routes: POST /api/v1/verify, POST /api/v1/ingest
                   # Adapter selection via WOBSONGO_LLM, WOBSONGO_EMBEDDER, WOBSONGO_DB_PATH
```

### Verification pipeline
`Post` → `ClaimDecomposer` (LLM) → retrieve chunks/facts → `NLIJudge` (LLM) → `VerificationResult`

### Ingestion pipeline
Markdown → paragraph chunks → embed (BGE-M3) + extract SPO facts (LLM) → `SQLiteRepository`

### Truth tier routing in NLIJudge
Verdicts are evaluated differently based on `VerifiedFact.truth_tier`:
- **Tier 1**: Axiomatic/universal — strict evaluation
- **Tier 2**: Time-bound — checks `valid_from` date
- **Tier 3**: Conditional — checks conditions
- **Tier 4**: Expert opinion — checks attribution

### Testing approach
Tests use `StubLLMClient` (keyword-based deterministic responses), in-memory SQLite, and a `StubEmbedder`. All tests are async (`pytest-asyncio` with `asyncio_mode = "auto"`).

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | Required for OpenAI adapter |
| `OPENAI_MODEL` | `gpt-4o-mini` | LLM model |
| `OPENAI_BASE_URL` | — | Override API base (e.g. local proxy) |
| `WOBSONGO_LLM` | — | Adapter selection for API (`openai` / `stub`) |
| `WOBSONGO_EMBEDDER` | — | Adapter selection (`bge` / `stub`) |
| `WOBSONGO_DB_PATH` | — | SQLite database path |
| `TESSDATA_PREFIX` | `./tessdata` | Tesseract OCR data (set by devbox) |

## Notes

- `parser.py` is a standalone script for parsing PDFs with `liteparse`; it is not part of the main package.
- `sqlite-vec` vector search is installed as an optional extra (`[db]`) but the retrieval path in `db_sqlite.py` is currently stubbed (returns `[]`).
- Ruff ignores `B008` in `wobsongo/api/app.py` to accommodate Litestar's `Body()` dependency injection pattern.
