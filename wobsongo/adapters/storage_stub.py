"""
wobsongo.adapters.storage_stub
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
StubStorage — in-memory ObjectStorageProtocol for tests.

Stores file content in a dict keyed by storage key.
generate_upload_url() returns a stub:// URL that tests can recognise.
download_file() writes the stored bytes to dest_path (empty bytes if key absent).
"""

from __future__ import annotations

from pathlib import Path


class StubStorage:
    """In-memory ObjectStorageProtocol for tests."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def generate_upload_url(self, key: str, expires_in: int = 3600) -> str:
        return f"stub://{key}"

    async def download_file(self, key: str, dest_path: Path) -> None:
        dest_path.write_bytes(self.store.get(key, b""))
