# **Wobsongo Core: Technical Specifications**

**Project:** Wobsongo Open Source Core

**Version:** 1.1.0 (MVP \- Zero Dependency Core)

**Status:** Approved for Development

**Architecture:** Modular Monolith with Hexagonal (Ports & Adapters) Design

## **1\. Executive Summary**

The Wobsongo Core is a **generic, language-agnostic misinformation detection engine**. It is designed to be a Digital Public Good (DPG) that allows any organization to spin up a fact-checking system using their own local data and models.

To ensure rapid delivery, low barrier to entry, and decade-long maintainability, the system enforces a strict **minimal-dependency rule**. The Core Domain uses pure standard-library Python. It abstracts the database and AI providers, running locally on SQLite \+ Open Models for the MVP, with seamless scalability to PostgreSQL \+ Commercial APIs via configuration.

## **2\. System Architecture**

### **2.1 Design Pattern: Hexagonal Architecture**

We strictly separate the **Core Domain** (Business Logic) from the **Infrastructure** (Databases, APIs). We utilize Python's typing.Protocol (Structural Subtyping) to define our Ports. This ensures that the Adapters are completely decoupled from the Core Domain, allowing developers to write custom adapters without importing any Core classes.

- **Core Domain (/core):** Pure Python entities (dataclasses) and logic. No external imports (no SQL, no HTTP calls, no Pydantic).
- **Ports (/core/ports.py):** typing.Protocol definitions defining _what_ the system needs (e.g., RepositoryProtocol, LLMClientProtocol).
- **Adapters (/adapters):** Concrete implementations of the protocols (e.g., SQLiteRepository, LitestarAPI). They "quack like a duck" and fulfill the protocol contract implicitly.

### **2.2 Component Diagram**

graph TD  
 User\[User/Admin\] \--\> API\[Litestar API (Primary Adapter)\]  
 API \--\> Controller\[Pipeline Controller\]

    subgraph "Core Domain (Standard Lib Python)"
        Controller \--\> Decomposer\[Claim Decomposer\]
        Controller \--\> Judge\[NLI Judge\]
        Controller \--\> Ingestor\[Document Ingestor\]
    end

    Controller \-. "typing.Protocol\\n(RepositoryProtocol)" .-\> DB\_Adapter\[SQLite Adapter\]
    Controller \-. "typing.Protocol\\n(LLMClientProtocol)" .-\> AI\_Adapter\[LLM Adapter\]

    DB\_Adapter \--\> SQLite\[(SQLite \+ sqlite-vec)\]
    AI\_Adapter \--\> LLM\[External/Local Model\]

## **3\. Core Domain Logic (The "IP")**

The system implements a **Decompose-Retrieve-Verify** pipeline.

### **3.1 Step 1: Ingestion & Extraction (The Knowledge Builder)**

Raw documents are processed into structured facts.

1. **Read:** Convert PDF to Markdown.
2. **Classify:** Auto-tag document with Topic Taxonomy (e.g., health.vaccines).
3. **Extract:** LLM extracts atomic Subject-Predicate-Object triples and outputs raw JSON, which is parsed safely into Python dataclasses.

### **3.2 Step 2: Claim Decomposition**

- **Input:** "The new vaccine was rushed in 2 months and causes infertility."
- **Action:** Break complex posts into atomic, verifiable statements.
- **Output:** \["Vaccine X development time \< 2 months", "Vaccine X causes infertility"\]

### **3.3 Step 3: Scoped Hybrid Retrieval**

For each atomic claim, execute a scoped search:

1. **Vector Search:** Query document_chunks for semantic context, filtered by topic.
2. **Structured Search:** Query verified_facts for exact keyword/subject matches.

### **3.4 Step 4: Logic-Based Verification (The Judge)**

The Judge applies different logic based on the **Truth Tier** of the retrieved evidence:

- **Tier 1 (Axiomatic):** Strict Binary Check.
- **Tier 2 (Temporal):** Date Check.
- **Tier 3 (Probabilistic):** Condition Check (e.g., "safe _if dosage \< 5mg_").
- **Tier 4 (Subjective):** Attribution Check.

## **4\. Data Architecture**

### **4.1 Taxonomy Models**

#### **4.1.1 The Topic Taxonomy (Ontological)**

Used for **Retrieval Scoping**. Implemented via Path Enumeration (e.g., health.reproductive.contraception).

#### **4.1.2 The Truth Taxonomy (Epistemological)**

Used for **Verification Logic**.

- **Tier 1 (Axiomatic):** Universal truths.
- **Tier 2 (Temporal):** Time-bound facts.
- **Tier 3 (Probabilistic):** General consensus with exceptions.
- **Tier 4 (Subjective):** Expert opinions.

### **4.2 Entity Definitions (Standard Library Dataclasses)**

**1\. VerifiedFact (The Structured Knowledge)**

from dataclasses import dataclass  
from typing import Optional  
from datetime import date  
from uuid import UUID

@dataclass  
class VerifiedFact:  
 id: UUID  
 subject: str  
 predicate: str  
 object: str  
 truth_tier: int \# 1-4  
 topic_path: str  
 valid_from: Optional\[date\]  
 conditions: Optional\[str\]  
 source_chunk_id: UUID

**2\. DocumentChunk (The Unstructured Context)**

@dataclass  
class DocumentChunk:  
 id: UUID  
 text: str  
 embedding: list\[float\]  
 source_doc_id: UUID

## **5\. Technology Stack (MVP)**

| Component         | Choice                   | Rationale                                                                                                                                                                |
| :---------------- | :----------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Language**      | Python 3.11+             | Ecosystem standard. Uses standard @dataclass (No Pydantic).                                                                                                              |
| **Web Framework** | **Litestar**             | Modern, high-performance ASGI framework. Stable (v2+), community-governed, and natively supports standard library dataclasses for validation without requiring Pydantic. |
| **Persistence**   | **SQLite \+ sqlite-vec** | Single-file, no-setup, supports vectors natively via C-extension.                                                                                                        |
| **Embeddings**    | **BAAI/bge-m3**          | Open Source (Apache 2.0), Multilingual SOTA.                                                                                                                             |
| **PDF Parser**    | pymupdf4llm              | Converts PDF to Markdown (preserves layout).                                                                                                                             |
| **LLM Interface** | Native SDKs / HTTP       | Uses OpenAI/Ollama native JSON modes. No instructor or Langchain.                                                                                                        |

## **6\. Detailed Development Roadmap**

### **Step 1: Core Domain & Abstractions (Week 1, Days 1-2)**

_Goal: Define the system's shape using pure Python without external dependencies._

1. **Initialize Project:** Set up pyproject.toml, pytest, and folder structure (/core, /adapters, /api). Set up mypy with \--strict to enforce Protocol adherence.
2. **Define Entities (core/domain.py):** Create Post, DocumentChunk, VerifiedFact, and TaxonomyTag using standard @dataclass.
3. **Define Interfaces (core/ports.py):**
   - RepositoryProtocol(Protocol): Methods: save_fact(self, fact: VerifiedFact) \-\> None, get_chunks_by_vector(self, vector: list\[float\], topic_filter: str) \-\> list\[DocumentChunk\].
   - LLMClientProtocol(Protocol): Method: generate_json(self, prompt: str, json_schema: dict) \-\> dict.
   - EmbeddingClientProtocol(Protocol): Method: embed_text(self, text: str) \-\> list\[float\].

### **Step 2: Infrastructure Adapters (Week 1, Days 3-5)**

_Goal: Implement the ports using lightweight libraries._

1. **SQLite Adapter (adapters/db_sqlite.py):**
   - Write initialization script to load sqlite-vec.
   - Create tables matching the dataclass attributes.
   - Implement manual row-to-dataclass mapping in the fetch methods. Ensure it satisfies RepositoryProtocol.
   - Enable PRAGMA journal_mode \= WAL;.
2. **Embedding Adapter (adapters/embed_bge.py):**
   - Implement a class satisfying EmbeddingClientProtocol using sentence-transformers.
3. **LLM Adapter (adapters/llm_openai.py):**
   - Implement a class satisfying LLMClientProtocol using the official SDK.
   - Utilize response_format={"type": "json_object"}.
   - Write internal validation to ensure the returned dict contains the expected keys before passing it back to the Core.

### **Step 3: The Ingestion Pipeline (Week 2\)**

_Goal: Turn PDFs into searchable facts and vectors._

1. **PDF Parser Service (core/services/ingestion.py):** Integrate pymupdf4llm to extract Markdown.
2. **Topic Classifier Agent:** Prompt the LLM to output a JSON dictionary like {"topic_path": "health.vaccines"}.
3. **Fact Extractor Agent:** Prompt the LLM with a strict JSON schema. Parse the returned JSON into a list of VerifiedFact dataclasses. Handle KeyError gracefully if the LLM hallucinates.
4. **Database Commit:** Persist DocumentChunk and VerifiedFact entities via an injected instance of RepositoryProtocol.

### **Step 4: The Verification Pipeline (Week 3\)**

_Goal: Build the core Decompose-Retrieve-Verify engine._

1. **Decomposer Agent (core/agents/decomposer.py):** Prompt LLM to split a post. Expect JSON output: {"claims": \["claim 1", "claim 2"\]}.
2. **Hybrid Retriever (adapters/db_sqlite.py):** Write the SQLite query combining vector distance with taxonomy filtering: SELECT text FROM document_chunks WHERE topic_path LIKE ? AND vec_distance_cosine(embedding, ?) \< 0.3.
3. **NLI Judge Agent (core/agents/judge.py):** Route logic based on truth_tier.
   - If Tier 1: Prompt for strict binary evaluation.
   - If Tier 3: Inject conditions into the prompt to check for omitted context.
   - Output: {"verdict": "FALSE", "confidence": 0.9, "reasoning": "..."}

### **Step 5: API & Dashboard MVP (Week 4\)**

_Goal: Expose the system for human interaction and testing._

1. **Litestar API (api/app.py):**
   - POST /api/v1/ingest: Accepts PDF upload.
   - POST /api/v1/verify: Accepts claim text, returns JSON verdict.
2. **Streamlit Admin UI (frontend/app.py):**
   - **Knowledge Base View:** Upload PDFs, view/edit extracted facts.
   - **Sandbox View:** Paste a claim, see step-by-step processing (Decomposition \-\> Evidence \-\> Verdict).

### **Step 6: Automated Data Collection (Phase 2 \- Weeks 5-6)**

_Goal: Continuous monitoring._

1. **Scraper Adapters:** Integration with Apify for TikTok/X.
2. **Task Queue:** Implement a standard library queue.Queue background thread or simple database polling table for background processing.
3. **Triage Dashboard:** UI for Admins to review auto-flagged content.

### **Step 7: Localization & DPG Release (Phase 3 \- Weeks 7+)**

1. **The Pivot Interface:** Implement TranslatorProtocol.
2. **Language Adapters:** Integrate Meta NLLB for Dioula/Moorè to French translation.
3. **Documentation:** Finalize deployment docs for the "Zero Dependency Core" ensuring it can run in air-gapped environments.

## **7\. Quality Assurance Strategy**

### **7.1 Golden Dataset**

A manually curated CSV (/tests/golden_dataset.csv) containing 50 claims mapped to:

1. Expected Verdict.
2. Expected Evidence Source.
3. Expected Taxonomy Path.

### **7.2 Automated Evaluation (promptfoo)**

Every PR modifying prompts or logic must pass the promptfoo CLI suite to prevent regressions. Example configuration:

tests:  
 \- vars:  
 claim: "Vaccines cause sterility."  
 assert:  
 \- type: contains  
 value: "FALSE"  
 \- type: llm-rubric  
 value: "Mentions that sterility is a myth based on WHO guidelines."
