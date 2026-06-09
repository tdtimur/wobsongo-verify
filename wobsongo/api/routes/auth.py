"""POST /api/v3/auth/token"""

from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime, timedelta

import jwt
from litestar import post
from litestar.exceptions import HTTPException

from wobsongo.api.schemas.auth import TokenRequest, TokenResponse


@post("/api/v3/auth/token", status_code=200)
async def login_handler(data: TokenRequest) -> TokenResponse:
    admin_password = os.environ.get("WOBSONGO_ADMIN_PASSWORD", "")
    if not admin_password or not hmac.compare_digest(data.password, admin_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    secret = os.environ.get("WOBSONGO_JWT_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="Server misconfiguration: JWT secret not set")
    ttl_hours = int(os.environ.get("WOBSONGO_JWT_TTL_HOURS", "24"))
    now = datetime.now(UTC)
    exp = now + timedelta(hours=ttl_hours)
    token: str = jwt.encode(
        {"sub": "admin", "iat": int(now.timestamp()), "exp": int(exp.timestamp())},
        secret,
        algorithm="HS256",
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=ttl_hours * 3600,
    )
