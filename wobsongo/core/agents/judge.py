"""
wobsongo.core.agents.judge
~~~~~~~~~~~~~~~~~~~~~~~~~~
NLIJudge — adjudicates a single atomic claim against retrieved evidence.

Routes verification logic based on the truth_tier of the best matching
VerifiedFact. Returns a ClaimVerdict with verdict, confidence, reasoning.

Zero external imports. Depends only on ports and domain.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from wobsongo.core.domain import ClaimVerdict, DocumentChunk, VerifiedFact
from wobsongo.core.ports import LLMClientProtocol

_VERDICT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["SUPPORTED", "REFUTED", "INSUFFICIENT_EVIDENCE"]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["verdict", "confidence", "reasoning"],
}

_TIER1_PROMPT = """\
You are a strict fact-checker. Evaluate the claim against the evidence below.

Claim: {claim}

Evidence:
{evidence}

Rules:
- Answer SUPPORTED only if evidence directly confirms the claim.
- Answer REFUTED if evidence directly contradicts the claim.
- Answer INSUFFICIENT_EVIDENCE if evidence does not clearly address the claim.
- Output valid JSON only.

Output format:
{{"verdict": "SUPPORTED|REFUTED|INSUFFICIENT_EVIDENCE", "confidence": 0.0-1.0, "reasoning": "..."}}
"""

_TIER2_PROMPT = """\
You are a fact-checker specialising in time-sensitive claims.

Claim: {claim}
This fact was valid from: {valid_from}

Evidence:
{evidence}

Rules:
- Check whether the claim is still accurate given the valid_from date.
- If the fact has expired or the claim omits temporal context, answer REFUTED.
- Output valid JSON only.

Output format:
{{"verdict": "SUPPORTED|REFUTED|INSUFFICIENT_EVIDENCE", "confidence": 0.0-1.0, "reasoning": "..."}}
"""

_TIER3_PROMPT = """\
You are a fact-checker specialising in conditional claims.

Claim: {claim}
Known conditions: {conditions}

Evidence:
{evidence}

Rules:
- The fact is only true under specific conditions listed above.
- If the claim omits or violates the conditions, answer REFUTED.
- Output valid JSON only.

Output format:
{{"verdict": "SUPPORTED|REFUTED|INSUFFICIENT_EVIDENCE", "confidence": 0.0-1.0, "reasoning": "..."}}
"""

_TIER4_PROMPT = """\
You are a fact-checker specialising in subjective and opinion-based claims.

Claim: {claim}

Evidence:
{evidence}

Rules:
- Check whether the claim is attributed to a credible expert or institution.
- If presented as universal fact but is actually expert opinion, answer REFUTED.
- Output valid JSON only.

Output format:
{{"verdict": "SUPPORTED|REFUTED|INSUFFICIENT_EVIDENCE", "confidence": 0.0-1.0, "reasoning": "..."}}
"""

_CHUNK_FALLBACK_PROMPT = """\
You are a strict fact-checker. Evaluate whether the following claim is supported \
by the document excerpts below.

Claim: {claim}

Document excerpts:
{evidence}

Rules:
- Answer SUPPORTED only if the excerpts directly and clearly confirm the claim.
- Answer REFUTED only if the excerpts directly and clearly contradict the claim.
- Answer INSUFFICIENT_EVIDENCE if the excerpts do not clearly address the claim, \
are only tangentially related, or if you are not fully confident. \
When in doubt, choose INSUFFICIENT_EVIDENCE — do not speculate or infer \
beyond what is explicitly stated in the excerpts.
- Output valid JSON only.

Output format:
{{"verdict": "SUPPORTED|REFUTED|INSUFFICIENT_EVIDENCE", "confidence": 0.0-1.0, "reasoning": "..."}}
"""


def _format_evidence(chunks: list[DocumentChunk]) -> str:
    if not chunks:
        return "(no evidence retrieved)"
    parts: list[str] = []
    seen_titles: dict[str, int] = {}
    for c in chunks:
        label = c.source_doc_title or str(c.source_doc_id)
        if label not in seen_titles:
            seen_titles[label] = len(seen_titles) + 1
        parts.append(f"[{label}, p.{c.page}] {c.text}")
    return "\n\n".join(parts)


def _insufficient(claim: str, reason: str) -> ClaimVerdict:
    return ClaimVerdict(
        claim=claim,
        verdict="INSUFFICIENT_EVIDENCE",
        confidence=0.0,
        reasoning=reason,
    )


def _parse_verdict(claim: str, raw: dict[str, object], tier: int | None, evidence_ids: Sequence[UUID]) -> ClaimVerdict:
    try:
        verdict = str(raw["verdict"])
        confidence = float(raw["confidence"])  # type: ignore[arg-type]
        reasoning = str(raw["reasoning"])
    except (KeyError, TypeError, ValueError):
        return _insufficient(claim, "LLM returned malformed response.")

    if verdict not in ("SUPPORTED", "REFUTED", "INSUFFICIENT_EVIDENCE"):
        verdict = "INSUFFICIENT_EVIDENCE"

    confidence = max(0.0, min(1.0, confidence))

    return ClaimVerdict(
        claim=claim,
        verdict=verdict,
        confidence=confidence,
        reasoning=reasoning,
        evidence_ids=list(evidence_ids),
        truth_tier=tier,
    )


class NLIJudge:
    """Routes claim adjudication logic by truth_tier of retrieved facts."""

    def __init__(self, llm: LLMClientProtocol) -> None:
        self._llm = llm

    async def adjudicate(
        self,
        claim: str,
        chunks: list[DocumentChunk],
        facts: list[VerifiedFact],
    ) -> ClaimVerdict:
        """Produce a ClaimVerdict for one atomic claim."""
        if not facts:
            if not chunks:
                return _insufficient(claim, "No relevant evidence found in the knowledge base.")
            # fall back to reasoning directly from retrieved chunks
            return await self._judge_from_chunks(claim, chunks)

        # use the first fact's tier — retrieval already scoped by topic
        best_fact = facts[0]
        evidence_ids = [c.id for c in chunks]

        return await self._route_by_tier(
            tier=best_fact.truth_tier,
            claim=claim,
            chunks=chunks,
            facts=facts,
            evidence_ids=list(evidence_ids),
        )

    async def _judge_from_chunks(
        self,
        claim: str,
        chunks: list[DocumentChunk],
    ) -> ClaimVerdict:
        """Assess a claim from raw chunks when no structured facts exist.

        The LLM is explicitly instructed to prefer INSUFFICIENT_EVIDENCE
        over speculation — this path must never manufacture confidence.
        """
        evidence_text = _format_evidence(chunks)
        prompt = _CHUNK_FALLBACK_PROMPT.format(claim=claim, evidence=evidence_text)
        raw = await self._llm.generate_json(prompt, _VERDICT_SCHEMA)
        evidence_ids = [c.id for c in chunks]
        return _parse_verdict(claim, raw, tier=None, evidence_ids=evidence_ids)

    async def _route_by_tier(
        self,
        tier: int,
        claim: str,
        chunks: list[DocumentChunk],
        facts: list[VerifiedFact],
        evidence_ids: Sequence[UUID],
    ) -> ClaimVerdict:
        evidence_text = _format_evidence(chunks)
        best_fact = facts[0]

        if tier == 1:
            prompt = _TIER1_PROMPT.format(claim=claim, evidence=evidence_text)

        elif tier == 2:
            valid_from = str(best_fact.valid_from) if best_fact.valid_from else "unknown"
            prompt = _TIER2_PROMPT.format(
                claim=claim,
                valid_from=valid_from,
                evidence=evidence_text,
            )

        elif tier == 3:
            conditions = best_fact.conditions or "none specified"
            prompt = _TIER3_PROMPT.format(
                claim=claim,
                conditions=conditions,
                evidence=evidence_text,
            )

        elif tier == 4:
            prompt = _TIER4_PROMPT.format(claim=claim, evidence=evidence_text)

        else:
            return _insufficient(claim, f"Unknown truth_tier: {tier}.")

        raw = await self._llm.generate_json(prompt, _VERDICT_SCHEMA)
        return _parse_verdict(claim, raw, tier, evidence_ids)
