# Project Scaffold Plan: `project-scaffold`

**Branch:** `project-scaffold`
**Source:** `tech-spec.md` v1.1.0
**Scope:** Steps 1–2 of roadmap only (Core Domain + Infrastructure Stubs). No pipeline logic yet.

---

## 1. Guiding Constraints

| Rule | Detail |
|---|---|
| `core/` = zero external imports | Pure stdlib: `dataclasses`, `typing`, `uuid`, `datetime`, `json` only |
| Ports via `typing.Protocol` | Structural subtyping — adapters never import core classes |
| Heavy deps = optional groups | `sentence-transformers`, `sqlite-vec`, `pymupdf4llm`, `openai` not required to import core |
| `mypy --strict` from day 1 | Enforces Protocol adherence at CI level |
| Python 3.14+ | Keep existing `.python-version` lock |
| Flat package layout | `wobsongo/` at project root (not `src/`) |
| Dev environment | **devbox** manages tooling (Python 3.14.2, uv 0.9.21, ruff 0.14.9). Enter shell: `devbox shell` |
| Package manager | **uv** exclusively. `uv sync` to install, `uv run` to execute, `uv add` to add deps |

---

## 2. Directory Structure

```
wobsongo-verify/
│
├── wobsongo/                          # Main package
│   ├── __init__.py
│   │
│   ├── core/                          # ZERO external imports
│   │   ├── __init__.py
│   │   ├── domain.py                  # All dataclasses
│   │   ├── ports.py                   # All Protocol definitions
│   │   ├── pipeline.py                # PipelineController (orchestrator)
│   │   │
│   │   ├── agents/                    # Core logic units (stubs for now)
│   │   │   ├── __init__.py
│   │   │   ├── decomposer.py          # ClaimDecomposer
│   │   │   └── judge.py               # NLIJudge (tier-based routing)
│   │   │
│   │   └── services/                  # Side-effect-free services (stubs)
│   │       ├── __init__.py
│   │       └── ingestion.py           # DocumentIngestor
│   │
│   ├── adapters/                      # Concrete port implementations
│   │   ├── __init__.py
│   │   ├── db_sqlite.py               # SQLiteRepository (satisfies RepositoryProtocol)
│   │   ├── embed_bge.py               # BGEEmbedder (satisfies EmbeddingClientProtocol)
│   │   └── llm_stub.py                # StubLLMClient (satisfies LLMClientProtocol — dev only)
│   │
│   └── api/                           # Primary adapter (Litestar)
│       ├── __init__.py
│       └── app.py                     # POST /api/v1/ingest, POST /api/v1/verify
│
├── tests/
│   ├── __init__.py
│   ├── golden_dataset.csv             # Header + 3 seed rows (50 to fill later)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── test_domain.py             # Dataclass construction + field types
│   │   ├── test_decomposer.py         # Decomposer with StubLLMClient
│   │   └── test_judge.py              # Judge tier routing logic
│   └── adapters/
│       ├── __init__.py
│       └── test_db_sqlite.py          # SQLite adapter round-trip (in-memory DB)
│
├── specs/
│   └── project-scaffold/
│       └── PLAN.md                    # This file
│
├── pyproject.toml                     # Updated (see Section 4)
├── main.py                            # Dev launcher (runs Litestar dev server)
└── ...existing files unchanged...
```

---

## 3. File-by-File Spec

### 3.1 `wobsongo/core/domain.py`

Four dataclasses. All stdlib. All fields typed.

```python
@dataclass
class TaxonomyTag:
    path: str          # e.g. "health.vaccines.mrna"
    label: str

@dataclass
class Post:
    id: UUID
    raw_text: str
    source: str        # e.g. "twitter", "tiktok"
    language: str      # ISO 639-1
    topic_tag: TaxonomyTag | None

@dataclass
class DocumentChunk:
    id: UUID
    text: str
    embedding: list[float]
    source_doc_id: UUID
    topic_path: str

@dataclass
class VerifiedFact:
    id: UUID
    subject: str
    predicate: str
    object: str
    truth_tier: int                # 1–4
    topic_path: str
    valid_from: date | None
    conditions: str | None
    source_chunk_id: UUID
```

### 3.2 `wobsongo/core/ports.py`

Three Protocols. **Async-first.** No imports from `wobsongo.core.domain` — uses `TYPE_CHECKING` guard only.

All protocol methods are `async`. Sync adapters satisfy the protocol by wrapping blocking calls in `asyncio.to_thread()` internally — the protocol contract is unchanged.

```python
class RepositoryProtocol(Protocol):
    async def save_fact(self, fact: VerifiedFact) -> None: ...
    async def save_chunk(self, chunk: DocumentChunk) -> None: ...
    async def get_chunks_by_vector(self, vector: list[float], topic_filter: str) -> list[DocumentChunk]: ...
    async def get_facts_by_subject(self, subject: str) -> list[VerifiedFact]: ...

class LLMClientProtocol(Protocol):
    async def generate_json(self, prompt: str, json_schema: dict[str, object]) -> dict[str, object]: ...

class EmbeddingClientProtocol(Protocol):
    async def embed_text(self, text: str) -> list[float]: ...
```

### 3.4 `wobsongo/core/agents/decomposer.py`

`ClaimDecomposer` — takes `LLMClientProtocol`. Prompt template defined, parses JSON response.

```python
class ClaimDecomposer:
    def __init__(self, llm: LLMClientProtocol) -> None: ...
    async def decompose(self, text: str) -> list[str]: ...  # returns atomic claims
```

### 3.5 `wobsongo/core/agents/judge.py`

`NLIJudge` — takes `LLMClientProtocol` only. `PipelineController` passes both chunks and facts.

```python
class NLIJudge:
    def __init__(self, llm: LLMClientProtocol) -> None: ...
    async def adjudicate(
        self,
        claim: str,
        chunks: list[DocumentChunk],
        facts: list[VerifiedFact],
    ) -> ClaimVerdict: ...
    async def _route_by_tier(
        self,
        tier: int,
        claim: str,
        chunks: list[DocumentChunk],
        facts: list[VerifiedFact],
    ) -> ClaimVerdict: ...
```

Tier routing:
- Tier 1 (Axiomatic): strict binary prompt
- Tier 2 (Temporal): inject `valid_from` into prompt
- Tier 3 (Probabilistic): inject `conditions` into prompt
- Tier 4 (Subjective): attribution check prompt
- No facts / unknown tier: `INSUFFICIENT_EVIDENCE`

### 3.6 `wobsongo/core/services/ingestion.py`

`DocumentIngestor` — takes all three ports. PDF parsing deferred.

Markdown chunking: split on double newline (`\n\n`), skip empty/whitespace-only chunks.

```python
class DocumentIngestor:
    def __init__(self, llm: LLMClientProtocol, embedder: EmbeddingClientProtocol, repo: RepositoryProtocol) -> None: ...
    async def ingest_markdown(self, markdown: str, source_doc_id: UUID) -> list[VerifiedFact]: ...
    # ingest_pdf() deferred to Step 3
```

### 3.3 `wobsongo/core/pipeline.py`

`PipelineController` — instantiates agents internally. Orchestrates full pipelines.

```python
class PipelineController:
    def __init__(
        self,
        repo: RepositoryProtocol,
        llm: LLMClientProtocol,
        embedder: EmbeddingClientProtocol,
    ) -> None:
        # internally constructs ClaimDecomposer, NLIJudge, DocumentIngestor
        ...

    async def verify(self, post: Post) -> VerificationResult:
        # 1. decompose post.raw_text into atomic claims
        # 2. for each claim: retrieve chunks (vector) + facts (subject match)
        # 3. judge each claim with chunks + facts
        # 4. return VerificationResult
        ...

    async def ingest_document(self, markdown_text: str, source_doc_id: UUID) -> list[VerifiedFact]:
        # delegates to DocumentIngestor.ingest_markdown
        ...
```

### 3.7 `wobsongo/adapters/db_sqlite.py`

`SQLiteRepository` — satisfies `RepositoryProtocol`.

- Uses stdlib `sqlite3` only
- `__init__` takes `db_path: str | Path`
- Creates schema on init
- WAL mode enabled: `PRAGMA journal_mode = WAL`
- `sqlite-vec` loading deferred (guarded `try/except ImportError` — vector search returns `[]` stub if ext absent)
- Manual row→dataclass mapping (no ORM)
- All public methods are `async` — blocking `sqlite3` calls wrapped via `asyncio.to_thread()`

```python
class SQLiteRepository:
    async def save_fact(self, fact: VerifiedFact) -> None:
        await asyncio.to_thread(self._save_fact_sync, fact)

    def _save_fact_sync(self, fact: VerifiedFact) -> None:
        # actual blocking sqlite3 call
        ...
```

Schema:
```sql
CREATE TABLE IF NOT EXISTS document_chunks (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    embedding BLOB,          -- struct.pack('Nf', *floats); sqlite-vec takes over later
    source_doc_id TEXT NOT NULL,
    topic_path TEXT NOT NULL
);
```

### 3.9 `wobsongo/adapters/llm_stub.py`

`StubLLMClient` — satisfies `LLMClientProtocol`. For dev/testing only.

- `generate_json` is `async` — returns deterministic hardcoded JSON keyed on prompt keywords
- No network calls
- Used in all tests — no real LLM needed to run test suite
- Must return valid shapes for all prompt types used by agents:
  - Decomposer prompt → `{"claims": ["claim 1", "claim 2"]}`
  - Judge prompt → `{"verdict": "REFUTED", "confidence": 0.9, "reasoning": "stub reasoning"}`
  - Topic classifier prompt → `{"topic_path": "health.vaccines"}`
  - Fact extractor prompt → `{"facts": [{"subject": "...", "predicate": "...", "object": "..."}]}`
- Detection: inspect `prompt` string for keywords (`"decompose"`, `"verdict"`, `"topic"`, `"extract"`)

```python
class StubLLMClient:
    async def generate_json(self, prompt: str, json_schema: dict[str, object]) -> dict[str, object]:
        # Returns minimal valid JSON matching expected schema shapes
        ...
```

### 3.8 `wobsongo/adapters/embed_bge.py`

`BGEEmbedder` — satisfies `EmbeddingClientProtocol`.

- Import `sentence_transformers` inside method body (lazy), guarded by `ImportError` with clear message
- Model: `BAAI/bge-m3`
- `embed_text` is `async` — model inference wrapped via `asyncio.to_thread()`
- Stub mode: if `sentence-transformers` absent, raises `RuntimeError("Install wobsongo[embed] to use BGEEmbedder")`

### 3.9 `wobsongo/adapters/llm_stub.py`

`StubLLMClient` — satisfies `LLMClientProtocol`. For dev/testing only.

- `generate_json` is `async` — returns deterministic hardcoded JSON based on prompt content keywords
- No network calls
- Used in all tests — no real LLM needed to run test suite

```python
class StubLLMClient:
    async def generate_json(self, prompt: str, json_schema: dict[str, object]) -> dict[str, object]:
        # Returns minimal valid JSON matching expected schema shapes
        ...
```

### 3.10 `wobsongo/api/app.py`

Litestar app. Two routes.

```python
# POST /api/v1/verify
# Body: {"text": str, "source": str, "language": str}
# Response: VerificationResult as JSON

# POST /api/v1/ingest
# Body: multipart/form-data with PDF file
# Response: {"facts_extracted": int, "chunks_stored": int}
```

- Controller wired at app startup via dependency injection
- `PipelineController` injected via Litestar's `Provide` mechanism

### 3.11 `tests/golden_dataset.csv`

```csv
claim,expected_verdict,expected_evidence_source,expected_taxonomy_path
"Vaccines cause sterility.",REFUTED,WHO guidelines,health.vaccines
"The earth is flat.",REFUTED,NASA/ESA data,science.astronomy
"Lemon water cures cancer.",REFUTED,CDC oncology database,health.oncology
```

---

## 4. `pyproject.toml` Changes

Managed via `uv`. Add deps with `uv add <pkg>`, optional groups with `uv add --optional <group> <pkg>`.

Notes:
- `mkdocs` + `mkdocs-material` moved from core deps → `docs` optional group (not deleted)
- `uvicorn` added to `dev` group (used by `main.py` launcher)
- `ruff` managed by devbox — not in `pyproject.toml`
- `all` group uses explicit dep list (self-referencing `wobsongo-verify[...]` not valid PEP 508 across all tools); use `[dependency-groups]` (PEP 735, supported by uv) instead

```toml
[project]
name = "wobsongo-verify"
version = "0.1.2"
requires-python = ">=3.14"
dependencies = [
    "litestar>=2.0",        # API framework
]

[project.optional-dependencies]
embed = ["sentence-transformers>=3.0"]
db    = ["sqlite-vec>=0.1"]
pdf   = ["pymupdf4llm>=0.0.17"]
llm   = ["openai>=1.0"]
docs  = ["mkdocs>=1.6.1", "mkdocs-material>=9.7.1"]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "mypy>=1.10",
    "pytest-asyncio>=0.23",
    "uvicorn>=0.30",
]

[tool.mypy]
strict = true
packages = ["wobsongo"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

---

## 5. `main.py` Update

```python
# Dev launcher — runs Litestar dev server
# Usage: uv run main.py
import uvicorn
from wobsongo.api.app import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)
```

Run via: `devbox shell` → `uv run main.py`

---

## 6. Execution Order

| # | File | Reason for order |
|---|---|---|
| 1 | `pyproject.toml` | Deps first — needed to install before anything runs |
| 2 | `wobsongo/core/domain.py` | Everything depends on entities |
| 3 | `wobsongo/core/ports.py` | Protocols depend on domain types |
| 4 | `wobsongo/core/agents/decomposer.py` | Depends on ports only |
| 5 | `wobsongo/core/agents/judge.py` | Depends on ports + domain |
| 6 | `wobsongo/core/services/ingestion.py` | Depends on ports + domain |
| 7 | `wobsongo/core/pipeline.py` | Depends on agents + services |
| 8 | `wobsongo/adapters/llm_stub.py` | No deps — needed for tests |
| 9 | `wobsongo/adapters/db_sqlite.py` | Stdlib sqlite3 only |
| 10 | `wobsongo/adapters/embed_bge.py` | Lazy import — safe without heavy dep |
| 11 | `wobsongo/api/app.py` | Depends on pipeline + litestar |
| 12 | `tests/` | Written alongside each module |
| 13 | `main.py` | Last — ties everything together |

---

## 7. Out of Scope (Deferred)

- Streamlit frontend
- Real LLM adapter (OpenAI / Ollama / Gemma 4)
- `sqlite-vec` vector search (guarded stub only)
- PDF ingestion (`pymupdf4llm`)
- Scraper adapters (Phase 2)
- Translation / localization (Phase 3)
- `promptfoo` CI integration
