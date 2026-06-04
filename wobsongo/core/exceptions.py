"""wobsongo.core.exceptions — domain-level exceptions raised by services."""

from __future__ import annotations


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass
