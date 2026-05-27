"""
wobsongo.core.pipeline
~~~~~~~~~~~~~~~~~~~~~~
PipelineController — top-level orchestrator for both pipelines:

  - verify(post) → VerificationResult   (Decompose → Retrieve → Judge)
  - ingest_document(markdown, id)       → list[VerifiedFact]

Constructs ClaimDecomposer, NLIJudge, DocumentIngestor internally.
Depends only on ports — no direct adapter imports.
"""

from __future__ import annotations

from uuid import UUID

from wobsongo.core.agents.decomposer import ClaimDecomposer
from wobsongo.core.agents.judge import NLIJudge
from wobsongo.core.domain import Post, VerificationResult, VerifiedFact
from wobsongo.core.ports import EmbeddingClientProtocol, LLMClientProtocol, RepositoryProtocol
from wobsongo.core.services.ingestion import DocumentIngestor


class PipelineController:
    """
    Orchestrates the full Decompose → Retrieve → Verify pipeline.

    Injected with port implementations at construction time.
    Agents are wired internally.
    """

    def __init__(
        self,
        repo: RepositoryProtocol,
        llm: LLMClientProtocol,
        embedder: EmbeddingClientProtocol,
    ) -> None:
        self._repo = repo
        self._embedder = embedder
        self._decomposer = ClaimDecomposer(llm=llm)
        self._judge = NLIJudge(llm=llm)
        self._ingestor = DocumentIngestor(llm=llm, embedder=embedder, repo=repo)

    async def verify(self, post: Post) -> VerificationResult:
        """
        Full verification pipeline for a Post.

        1. Decompose raw_text into atomic claims.
        2. For each claim: retrieve chunks (vector) + facts (subject match).
        3. Judge each claim → ClaimVerdict.
        4. Return aggregated VerificationResult.
        """
        claims = await self._decomposer.decompose(post.raw_text)

        verdicts = []
        for claim in claims:
            # embed claim for vector retrieval
            claim_vector = await self._embedder.embed_text(claim)

            # scoped retrieval — use post topic_tag if available
            topic_filter = post.topic_tag.path if post.topic_tag else ""

            chunks = await self._repo.get_chunks_by_vector(claim_vector, topic_filter)
            facts = await self._repo.get_facts_by_subject(claim)

            verdict = await self._judge.adjudicate(claim, chunks, facts)
            verdicts.append(verdict)

        return VerificationResult(
            post_id=post.id,
            claims=claims,
            verdicts=verdicts,
        )

    async def ingest_document(
        self,
        markdown_text: str,
        source_doc_id: UUID,
    ) -> list[VerifiedFact]:
        """Ingest a markdown document into the knowledge base."""
        return await self._ingestor.ingest_markdown(markdown_text, source_doc_id)
