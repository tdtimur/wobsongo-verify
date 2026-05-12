"""
wobsongo.adapters.llm_stub
~~~~~~~~~~~~~~~~~~~~~~~~~~
StubLLMClient — satisfies LLMClientProtocol. Dev/testing only.

No network calls. Returns deterministic hardcoded JSON keyed on
prompt keywords. Covers all prompt types used by core agents.
"""

from __future__ import annotations


class StubLLMClient:
    """Deterministic fake LLM for testing. Zero external deps."""

    async def generate_json(
        self,
        prompt: str,
        json_schema: dict[str, object],
    ) -> dict[str, object]:
        lowered = prompt.lower()

        if "decompose" in lowered or "split" in lowered or "atomic" in lowered:
            return {
                "claims": [
                    "Stub claim one.",
                    "Stub claim two.",
                ]
            }

        if "verdict" in lowered or "refute" in lowered or "support" in lowered or "adjudicate" in lowered:
            return {
                "verdict": "REFUTED",
                "confidence": 0.9,
                "reasoning": "Stub reasoning: evidence does not support the claim.",
            }

        if "topic" in lowered or "classify" in lowered or "taxonomy" in lowered:
            return {"topic_path": "health.vaccines"}

        if "extract" in lowered or "triple" in lowered or "subject" in lowered:
            return {
                "facts": [
                    {
                        "subject": "stub subject",
                        "predicate": "stub predicate",
                        "object": "stub object",
                    }
                ]
            }

        # fallback — return empty dict; caller must handle gracefully
        return {}
