"""
wobsongo.adapters.password
~~~~~~~~~~~~~~~~~~~~~~~~~~
bcrypt password hashing and verification.

Cost (rounds) is read from the WOBSONGO_BCRYPT_ROUNDS env var at call time
so that tests can override it without monkey-patching module-level state.

  Production:  WOBSONGO_BCRYPT_ROUNDS unset → default 12
  Tests:       WOBSONGO_BCRYPT_ROUNDS=4 (set in tests/conftest.py)
"""

from __future__ import annotations

import os

import bcrypt

_DEFAULT_ROUNDS = 12


def _rounds() -> int:
    return int(os.environ.get("WOBSONGO_BCRYPT_ROUNDS", _DEFAULT_ROUNDS))


def hash_password(password: str, *, rounds: int | None = None) -> str:
    """Return a bcrypt hash of *password*."""
    cost = rounds if rounds is not None else _rounds()
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(cost)).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Return True if *password* matches the stored bcrypt *hashed* string."""
    return bcrypt.checkpw(password.encode(), hashed.encode())
