"""
Quick connectivity check for Ollama Cloud.

Usage:
    uv run python scripts/verify_ollama.py

Reads credentials from .env in the project root if present.
Prints extracted facts from a sample clinical sentence and exits 0 on success.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")
sys.path.insert(0, str(_ROOT))

from wobsongo.adapters.factextract_ollama import OllamaFactExtractor  # noqa: E402

_SAMPLE = (
    "Letrozole 2.5mg administered daily for 5 days is recommended over "
    "clomiphene citrate for ovulation induction in women with PCOS, "
    "based on 12 randomised controlled trials showing significantly "
    "higher live birth rates."
)


async def main() -> None:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
    has_key = bool(os.environ.get("OLLAMA_API_KEY"))

    print(f"host  : {base_url}")
    print(f"model : {model}")
    print(f"auth  : {'yes' if has_key else 'no (local)'}")
    print(f"input : {_SAMPLE[:80]}...")
    print()

    extractor = OllamaFactExtractor()
    try:
        facts = await extractor.extract_facts(_SAMPLE)
    except Exception as exc:
        print(f"FAIL  : {exc}", file=sys.stderr)
        sys.exit(1)

    if not facts:
        print("WARN  : connected but no facts returned — check model name")
        sys.exit(1)

    print(f"OK    : {len(facts)} fact(s) extracted\n")
    for i, f in enumerate(facts, 1):
        print(f"  [{i}] subject  : {f.subject}")
        print(f"      predicate: {f.predicate}")
        print(f"      object   : {f.object}")
        print(f"      tier     : {f.truth_tier}")
        print()


asyncio.run(main())
