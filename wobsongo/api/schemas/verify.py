from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VerifyRequest:
    text: str
    language: str = "en"


@dataclass
class VerdictItem:
    claim: str
    verdict: str
    confidence: float
    reasoning: str


@dataclass
class VerifyResponse:
    post_id: str
    overall_verdict: str
    verdicts: list[VerdictItem] = field(default_factory=list)
