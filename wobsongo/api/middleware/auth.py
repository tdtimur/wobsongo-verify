"""wobsongo.api.middleware.auth — JWT Bearer auth for all /api/v3/* routes."""

from __future__ import annotations

import json
import os

import jwt
from litestar.types import ASGIApp, Receive, Scope, Send

_EXCLUDED_PREFIXES = ("/api/v3/auth/token", "/schema")


class JWTAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if any(path == p or path.startswith(p) for p in _EXCLUDED_PREFIXES):
            await self.app(scope, receive, send)
            return

        auth = ""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                auth = value.decode()
                break

        if not auth.startswith("Bearer "):
            await _reject(scope, send, "Missing or invalid Authorization header")
            return

        token = auth[len("Bearer "):]
        secret = os.environ.get("WOBSONGO_JWT_SECRET")
        if not secret:
            await _reject(scope, send, "Server misconfiguration: JWT secret not set")
            return
        try:
            jwt.decode(token, secret, algorithms=["HS256"])
        except jwt.PyJWTError:
            await _reject(scope, send, "Invalid or expired token")
            return

        await self.app(scope, receive, send)


async def _reject(scope: Scope, send: Send, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})
