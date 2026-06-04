from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenRequest:
    password: str


@dataclass
class TokenResponse:
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400
