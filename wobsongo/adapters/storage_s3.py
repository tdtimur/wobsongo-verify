"""
wobsongo.adapters.storage_s3
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
S3Storage — ObjectStorageProtocol backed by boto3.

Supports AWS S3, MinIO, and Cloudflare R2 via the S3_ENDPOINT_URL env var.
All blocking boto3 calls are wrapped in asyncio.to_thread().

Environment variables:
  S3_BUCKET           Bucket name (required)
  S3_ENDPOINT_URL     Override endpoint — omit for AWS, set for MinIO / R2
  AWS_ACCESS_KEY_ID
  AWS_SECRET_ACCESS_KEY
  AWS_DEFAULT_REGION  (default: us-east-1)
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import boto3

_BUCKET = os.getenv("S3_BUCKET", "")
_ENDPOINT = os.getenv("S3_ENDPOINT_URL")
_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")


class S3Storage:
    """ObjectStorageProtocol implementation using boto3."""

    def __init__(
        self,
        bucket: str = _BUCKET,
        endpoint_url: str | None = _ENDPOINT,
        region_name: str = _REGION,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
        )

    def generate_upload_url(self, key: str, expires_in: int = 3600) -> str:
        return self._client.generate_presigned_url(  # type: ignore[no-any-return]
            "put_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    async def download_file(self, key: str, dest_path: Path) -> None:
        await asyncio.to_thread(
            self._client.download_file, self._bucket, key, str(dest_path)
        )
