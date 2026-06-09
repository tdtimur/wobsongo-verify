"""POST /api/v3/verify"""

from __future__ import annotations

from litestar import post
from litestar.exceptions import HTTPException

from wobsongo.api.schemas.verify import VerdictItem, VerifyRequest, VerifyResponse
from wobsongo.core.services.verification_service import (
    VerificationService,
    compute_overall_verdict,
)


@post("/api/v3/verify")
async def verify_handler(
    data: VerifyRequest,
    verification_service: VerificationService,
) -> VerifyResponse:
    try:
        result = await verification_service.verify(text=data.text, language=data.language)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Verification pipeline failed") from exc
    verdicts = [
        VerdictItem(
            claim=v.claim,
            verdict=v.verdict,
            confidence=v.confidence,
            reasoning=v.reasoning,
        )
        for v in result.verdicts
    ]
    overall = compute_overall_verdict([v.verdict for v in result.verdicts])
    return VerifyResponse(
        post_id=str(result.post_id),
        overall_verdict=overall,
        verdicts=verdicts,
    )
