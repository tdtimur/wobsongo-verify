"""
wobsongo.core.agents.decomposer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
ClaimDecomposer — splits a raw social media post into atomic,
verifiable claims using an LLM.

Zero external imports. Depends only on ports and domain.
"""

from __future__ import annotations

from wobsongo.core.ports import LLMClientProtocol

_DECOMPOSE_PROMPT = """\
You are a fact-checking assistant. Your task is to decompose the following \
social media post into a list of atomic, independently verifiable claims.

Rules:
- Each claim must be a single, self-contained statement.
- Remove opinions, emotions, and filler. Keep only verifiable assertions.
- Output valid JSON only. No explanation outside the JSON.

Post:
{text}

Output format:
{{"claims": ["claim 1", "claim 2", ...]}}
"""

_DECOMPOSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["claims"],
}


class ClaimDecomposer:
    """Breaks compound posts into atomic verifiable claims."""

    def __init__(self, llm: LLMClientProtocol) -> None:
        self._llm = llm

    async def decompose(self, text: str) -> list[str]:
        """Return list of atomic claims extracted from text."""
        prompt = _DECOMPOSE_PROMPT.format(text=text.strip())
        result = await self._llm.generate_json(prompt, _DECOMPOSE_SCHEMA)

        try:
            claims = result["claims"]
            if not isinstance(claims, list):
                return []
            return [str(c) for c in claims if str(c).strip()]
        except (KeyError, TypeError):
            return []
