"""
wobsongo.core.services.ingestion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
DocumentIngestor — turns parsed documents into stored DocumentChunks
and extracted VerifiedFacts.

Two entry points:
  ingest_document(doc)   — primary path; accepts ParsedDocument from parser.py.
                           Applies factuality routing, per-chunk fact extraction,
                           and deduplication by content_hash.
  ingest_markdown(text)  — legacy path; kept for backward compatibility.

Factuality routing:
  < 0.1   drop — neither embed nor store
  0.1-0.3 embed and store; skip fact extraction
  >= 0.3  full pipeline — embed, store, extract facts

Zero external imports. Depends only on ports and domain.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from wobsongo.core.domain import (
    DocumentChunk,
    ParsedChunk,
    ParsedDocument,
    SourceDocument,
    VerifiedFact,
)
from wobsongo.core.ports import (
    EmbeddingClientProtocol,
    FactExtractorProtocol,
    LLMClientProtocol,
    RepositoryProtocol,
)
from wobsongo.core.scoring import factuality_score

_TOPIC_PROMPT = """\
You are a document classifier. Given the following text, assign it to the most \
specific topic path using dot notation (e.g. "health.vaccines.mrna").

Text:
{text}

Output valid JSON only.

Output format:
{{"topic_path": "category.subcategory"}}
"""

_EXTRACT_PROMPT = """\
You are a knowledge extraction assistant. Extract all factual claims from the \
following text as subject-predicate-object triples.

Text:
{text}

Rules:
- Each fact must be atomic and independently verifiable.
- Assign a truth_tier: 1=universal fact, 2=time-bound, 3=conditional, 4=expert opinion.
- Output valid JSON only.

Output format:
{{"facts": [{{"subject": "...", "predicate": "...", "object": "...", "truth_tier": 1}}]}}
"""

_TOPIC_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"topic_path": {"type": "string"}},
    "required": ["topic_path"],
}

_EXTRACT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "predicate": {"type": "string"},
                    "object": {"type": "string"},
                    "truth_tier": {"type": "integer"},
                },
                "required": ["subject", "predicate", "object", "truth_tier"],
            },
        }
    },
    "required": ["facts"],
}

_FACT_EXTRACTION_THRESHOLD = 0.3
_DROP_THRESHOLD = 0.1

_TOPIC_PATH_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _sanitize_topic_path(value: str) -> str:
    cleaned = value.strip().lower()
    return cleaned if _TOPIC_PATH_RE.match(cleaned) else "general"


def _split_chunks(markdown: str) -> list[str]:
    """Split markdown into non-empty paragraph chunks."""
    return [p.strip() for p in markdown.split("\n\n") if p.strip()]


class DocumentIngestor:
    """Ingests documents into the knowledge base."""

    def __init__(
        self,
        llm: LLMClientProtocol,
        embedder: EmbeddingClientProtocol,
        repo: RepositoryProtocol,
        fact_extractor: FactExtractorProtocol | None = None,
    ) -> None:
        self._llm = llm
        self._embedder = embedder
        self._repo = repo
        self._fact_extractor = fact_extractor

    async def ingest_document(self, doc: ParsedDocument) -> list[VerifiedFact]:
        """
        Ingest a ParsedDocument into the knowledge base.

        Deduplicates by content_hash — returns [] if the document was already ingested.
        Applies factuality routing per chunk. Extracts facts only for chunks
        scoring >= 0.3 and only if a fact_extractor was provided.
        """
        existing = await self._repo.get_document_by_hash(doc.metadata.content_hash)
        if existing is not None:
            return []

        now = datetime.now(UTC).isoformat()
        source_doc = SourceDocument(
            id=uuid4(),
            content_hash=doc.metadata.content_hash,
            title=doc.metadata.title,
            filename=doc.metadata.filename,
            file_type=doc.metadata.file_type,
            file_size=doc.metadata.file_size,
            num_pages=doc.metadata.num_pages,
            created_at=doc.metadata.created_at,
            modified_at=doc.metadata.modified_at,
            ingested_at=now,
        )
        await self._repo.save_document(source_doc)

        scoreable = [c for c in doc.chunks if factuality_score(c.text) >= _DROP_THRESHOLD]
        topic_path = await self._classify_topic(scoreable[:3])

        facts: list[VerifiedFact] = []
        for parsed_chunk in doc.chunks:
            score = factuality_score(parsed_chunk.text)
            if score < _DROP_THRESHOLD:
                continue

            embedding = await self._embedder.embed_text(parsed_chunk.text)
            chunk = DocumentChunk(
                id=uuid4(),
                source_doc_id=source_doc.id,
                text=parsed_chunk.text,
                embedding=embedding,
                topic_path=topic_path,
                factuality_score=score,
                page=parsed_chunk.page,
                chapter=parsed_chunk.chapter,
                line_start=parsed_chunk.line_start,
            )
            await self._repo.save_chunk(chunk)

            if score >= _FACT_EXTRACTION_THRESHOLD and self._fact_extractor is not None:
                extracted = await self._fact_extractor.extract_facts(parsed_chunk.text)
                for ef in extracted:
                    if not 1 <= ef.truth_tier <= 4:
                        continue
                    fact = VerifiedFact(
                        id=uuid4(),
                        subject=ef.subject,
                        predicate=ef.predicate,
                        object=ef.object,
                        truth_tier=ef.truth_tier,
                        topic_path=topic_path,
                        source_chunk_id=chunk.id,
                        source_doc_id=source_doc.id,
                    )
                    await self._repo.save_fact(fact)
                    facts.append(fact)

        return facts

    async def ingest_markdown(
        self,
        markdown: str,
        source_doc_id: UUID,
    ) -> list[VerifiedFact]:
        """
        Legacy entry point: process raw markdown into DocumentChunks + VerifiedFacts.
        No factuality filtering; all paragraphs are embedded and stored.
        """
        paragraphs = _split_chunks(markdown)
        if not paragraphs:
            return []

        sample = "\n\n".join(paragraphs[:3])
        topic_raw = await self._llm.generate_json(
            _TOPIC_PROMPT.format(text=sample), _TOPIC_SCHEMA
        )
        topic_path = _sanitize_topic_path(str(topic_raw.get("topic_path", "general")))

        chunk_ids: list[UUID] = []
        for paragraph in paragraphs:
            embedding = await self._embedder.embed_text(paragraph)
            chunk = DocumentChunk(
                id=uuid4(),
                text=paragraph,
                embedding=embedding,
                source_doc_id=source_doc_id,
                topic_path=topic_path,
            )
            await self._repo.save_chunk(chunk)
            chunk_ids.append(chunk.id)

        full_text = "\n\n".join(paragraphs)
        facts_raw = await self._llm.generate_json(
            _EXTRACT_PROMPT.format(text=full_text), _EXTRACT_SCHEMA
        )

        facts: list[VerifiedFact] = []
        raw_facts = facts_raw.get("facts", [])
        if not isinstance(raw_facts, list):
            return facts

        source_chunk_id = chunk_ids[0] if chunk_ids else uuid4()

        for raw in raw_facts:
            if not isinstance(raw, dict):
                continue
            try:
                tier = int(raw["truth_tier"])
                if not 1 <= tier <= 4:
                    continue
                fact = VerifiedFact(
                    id=uuid4(),
                    subject=str(raw["subject"]),
                    predicate=str(raw["predicate"]),
                    object=str(raw["object"]),
                    truth_tier=tier,
                    topic_path=topic_path,
                    source_chunk_id=source_chunk_id,
                )
            except (KeyError, TypeError, ValueError):
                continue

            await self._repo.save_fact(fact)
            facts.append(fact)

        return facts

    async def _classify_topic(self, chunks: list[ParsedChunk]) -> str:
        if not chunks:
            return "general"
        sample = "\n\n".join(c.text for c in chunks)
        result = await self._llm.generate_json(_TOPIC_PROMPT.format(text=sample), _TOPIC_SCHEMA)
        return _sanitize_topic_path(str(result.get("topic_path", "general")))
