"""wobsongo.core.services.verification_service"""

from __future__ import annotations

from uuid import uuid4

from wobsongo.core.domain import Post, VerificationResult
from wobsongo.core.pipeline import PipelineController


def compute_overall_verdict(verdicts: list[str]) -> str:
    if not verdicts:
        return "INSUFFICIENT_EVIDENCE"
    if all(v == "SUPPORTED" for v in verdicts):
        return "SUPPORTED"
    if any(v == "REFUTED" for v in verdicts):
        if all(v in ("REFUTED", "INSUFFICIENT_EVIDENCE") for v in verdicts):
            return "REFUTED"
        return "MIXED"
    return "INSUFFICIENT_EVIDENCE"


class VerificationService:
    def __init__(self, pipeline: PipelineController) -> None:
        self._pipeline = pipeline

    async def verify(self, text: str, language: str = "en") -> VerificationResult:
        post = Post(
            id=uuid4(),
            raw_text=text,
            source="api",
            language=language,
        )
        return await self._pipeline.verify(post)
