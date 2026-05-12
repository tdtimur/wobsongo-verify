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


def _format_evidence(chunks: list[DocumentChunk]) -> str:
    if not chunks:
        return "(no evidence retrieved)"
    return "\n\n".join(f"[{i + 1}] {c.text}" for i, c in enumerate(chunks))


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
            return _insufficient(claim, "No verified facts found for this claim.")

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
