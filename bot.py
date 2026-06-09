"""
Wobsongo fact-checking Telegram bot.

Users submit claims in plain text. The bot verifies each claim against
the pre-ingested knowledge base and returns a structured verdict.

PDF ingestion is done offline by operators — see parser.py and the
ingest_document() pipeline.

Setup:
  Add TELEGRAM_BOT_TOKEN to .env, then:
  uv run python bot.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# Wobsongo imports
# ---------------------------------------------------------------------------

from wobsongo.adapters.db_sqlite import SQLiteRepository
from wobsongo.adapters.embed_ollama import OllamaEmbedder
from wobsongo.adapters.llm_ollama import OllamaLLMClient
from wobsongo.core.domain import Post
from wobsongo.core.pipeline import PipelineController

# ---------------------------------------------------------------------------
# Telegram imports
# ---------------------------------------------------------------------------

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DB_PATH = os.environ.get("WOBSONGO_DB_PATH", "wobsongo.db")

_VERDICT_EMOJI = {
    "SUPPORTED": "✅",
    "REFUTED": "❌",
    "INSUFFICIENT_EVIDENCE": "❓",
}

# ---------------------------------------------------------------------------
# Shared resources
# ---------------------------------------------------------------------------

_pipeline = PipelineController(
    repo=SQLiteRepository(DB_PATH),
    llm=OllamaLLMClient(),
    embedder=OllamaEmbedder(),
)

# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _overall_verdict(verdicts: list) -> str:
    v_set = {v.verdict for v in verdicts}
    if "REFUTED" in v_set:
        return "REFUTED"
    if v_set == {"SUPPORTED"}:
        return "SUPPORTED"
    if "SUPPORTED" in v_set:
        return "MIXED"
    return "INSUFFICIENT_EVIDENCE"


def _esc(text: str) -> str:
    """Escape HTML special characters in LLM-generated text."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_result(result: object) -> str:
    from wobsongo.core.domain import VerificationResult

    assert isinstance(result, VerificationResult)

    if not result.verdicts:
        return "Could not decompose the claim into verifiable statements."

    overall = _overall_verdict(result.verdicts)
    emoji = _VERDICT_EMOJI.get(overall, "❓")
    n = len(result.verdicts)
    claim_word = "claim" if n == 1 else "claims"

    lines: list[str] = [
        f"{emoji} <b>{overall}</b> — {n} {claim_word} checked",
        "",
    ]

    for i, verdict in enumerate(result.verdicts, 1):
        ve = _VERDICT_EMOJI.get(verdict.verdict, "❓")
        lines.append(f"<b>{i}.</b> {ve} {verdict.verdict} ({verdict.confidence:.0%})")
        lines.append(f"<i>{_esc(verdict.claim)}</i>")
        lines.append(_esc(verdict.reasoning))
        lines.append("")

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


async def handle_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message and update.message.text

    claim_text = update.message.text.strip()
    await update.message.chat.send_action("typing")

    post = Post(
        id=uuid4(),
        raw_text=claim_text,
        source="telegram",
        language="en",
    )

    try:
        result = await _pipeline.verify(post)
        reply = _format_result(result)
    except Exception as exc:
        logging.exception("Verification failed")
        reply = f"Verification failed: {exc}"

    await update.message.reply_text(reply[:4096], parse_mode="HTML")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_claim))
    logging.getLogger(__name__).info("Bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
