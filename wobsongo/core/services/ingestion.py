"""
wobsongo.core.services.ingestion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
DocumentIngestor — turns markdown text into stored DocumentChunks
and extracted VerifiedFacts.

Chunking strategy: split on double newline (paragraphs).
PDF ingestion deferred (requires pymupdf4llm — optional dep).

Zero external imports. Depends only on ports and domain.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from wobsongo.core.domain import DocumentChunk, VerifiedFact
from wobsongo.core.ports import EmbeddingClientProtocol, LLMClientProtocol, RepositoryProtocol

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


def _split_chunks(markdown: str) -> list[str]:
    """Split markdown into non-empty paragraph chunks."""
    return [p.strip() for p in markdown.split("\n\n") if p.strip()]


class DocumentIngestor:
    """Ingests markdown documents into the knowledge base."""

    def __init__(
        self,
        llm: LLMClientProtocol,
        embedder: EmbeddingClientProtocol,
        repo: RepositoryProtocol,
    ) -> None:
        self._llm = llm
        self._embedder = embedder
        self._repo = repo

    async def ingest_markdown(
        self,
        markdown: str,
        source_doc_id: UUID,
    ) -> list[VerifiedFact]:
        """
        Process markdown text into DocumentChunks + VerifiedFacts.
        Persists both to repo. Returns extracted facts.
        """
        paragraphs = _split_chunks(markdown)
        if not paragraphs:
            return []

        # classify topic for whole document using first 3 paragraphs as sample
        sample = "\n\n".join(paragraphs[:3])
        topic_raw = await self._llm.generate_json(
            _TOPIC_PROMPT.format(text=sample), _TOPIC_SCHEMA
        )
        topic_path = str(topic_raw.get("topic_path", "general"))

        # embed + store each chunk
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

        # extract facts from full document
        full_text = "\n\n".join(paragraphs)
        facts_raw = await self._llm.generate_json(
            _EXTRACT_PROMPT.format(text=full_text), _EXTRACT_SCHEMA
        )

        facts: list[VerifiedFact] = []
        raw_facts = facts_raw.get("facts", [])
        if not isinstance(raw_facts, list):
            return facts

        # pair each fact with the first chunk id as source (best effort)
        source_chunk_id = chunk_ids[0] if chunk_ids else uuid4()

        for raw in raw_facts:
            if not isinstance(raw, dict):
                continue
            try:
                fact = VerifiedFact(
                    id=uuid4(),
                    subject=str(raw["subject"]),
                    predicate=str(raw["predicate"]),
                    object=str(raw["object"]),
                    truth_tier=int(raw["truth_tier"]),
                    topic_path=topic_path,
                    source_chunk_id=source_chunk_id,
                )
            except (KeyError, TypeError, ValueError):
                continue  # skip malformed LLM output gracefully

            await self._repo.save_fact(fact)
            facts.append(fact)

        return facts
