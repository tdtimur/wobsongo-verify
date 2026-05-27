"""
wobsongo.adapters.llm_openai
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
OpenAILLMClient — satisfies LLMClientProtocol.

Uses openai>=1.0 async client. JSON mode enforced via response_format.
openai imported lazily — raises RuntimeError if absent.

Install: uv sync --extra llm

Environment variables:
  OPENAI_API_KEY   — required
  OPENAI_MODEL     — default "gpt-4o-mini"
  OPENAI_BASE_URL  — optional override (e.g. Azure, local proxy)
"""

from __future__ import annotations

import json
import os


class OpenAILLMClient:
    """OpenAI chat-completions adapter. Satisfies LLMClientProtocol."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self._client: object | None = None  # lazy

    def _get_client(self) -> object:
        if self._client is None:
            try:
                from openai import AsyncOpenAI  # type: ignore[import-not-found]
            except ImportError as e:
                raise RuntimeError(
                    "openai not installed. Run: uv sync --extra llm"
                ) from e
            kwargs: dict[str, object] = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    async def generate_json(
        self,
        prompt: str,
        json_schema: dict[str, object],
    ) -> dict[str, object]:
        from openai import AsyncOpenAI

        client = self._get_client()
        assert isinstance(client, AsyncOpenAI)
        system_msg = (
            "You are a precise fact-checking assistant. "
            "Always respond with valid JSON matching the provided schema. "
            f"Schema: {json.dumps(json_schema)}"
        )
        response = await client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        raw: str = response.choices[0].message.content or "{}"
        result: dict[str, object] = json.loads(raw)
        return result
