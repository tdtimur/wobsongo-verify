"""
wobsongo.adapters.pdf_parser
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
parse_document(pdf_path, clean=True) -> ParsedDocument

Converts a PDF file into a list of structured ParsedChunk objects using
liteparse for extraction and pypdf for metadata. Lives in adapters (not core)
because it depends on external libraries.

See parser.py at the project root for the standalone CLI wrapper.
"""

import hashlib
import itertools
import os
import re
import statistics
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import overload

import pypdf
from liteparse import LiteParse, ParseResult
from liteparse.types import ParsedPage, TextItem

from wobsongo.core.domain import DocumentMetadata, ParsedChunk, ParsedDocument

_MULTI_SPACE = re.compile(r" {2,}")
_ROMAN = re.compile(
    r"^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$",
    re.IGNORECASE,
)
_DOT_LEADER_LINE = re.compile(r"^[\s.]*(\.\s*){4,}[\s.\d]*$")
_INLINE_DOT_RUN = re.compile(r"(\s*\.\s*){4,}")


@overload
def clean_whitespace(text: str) -> str: ...
@overload
def clean_whitespace(text: list[str]) -> list[str]: ...
def clean_whitespace(text: str | list[str]) -> str | list[str]:
    def _clean(t: str) -> str:
        lines = [_MULTI_SPACE.sub(" ", line.strip()) for line in t.split("\n")]
        return "\n".join(lines).strip()

    if isinstance(text, list):
        return [_clean(t) for t in text]
    return _clean(text)


@overload
def remove_dot_leaders(text: str) -> str: ...
@overload
def remove_dot_leaders(text: list[str]) -> list[str]: ...
def remove_dot_leaders(text: str | list[str]) -> str | list[str]:
    def _remove(t: str) -> str:
        cleaned: list[str] = []
        for line in t.split("\n"):
            if _DOT_LEADER_LINE.match(line):
                continue
            line = _INLINE_DOT_RUN.sub(" ", line).strip()
            if line:
                cleaned.append(line)
        return "\n".join(cleaned).strip()

    if isinstance(text, list):
        return [_remove(t) for t in text]
    return _remove(text)


@overload
def is_page_number(text: str) -> bool: ...
@overload
def is_page_number(text: list[str]) -> list[bool]: ...
def is_page_number(text: str | list[str]) -> bool | list[bool]:
    def _check(t: str) -> bool:
        s = t.strip()
        if not s or len(s) > 8:
            return False
        if s.isdigit():
            return True
        m = _ROMAN.fullmatch(s)
        return m is not None and bool(m.group(0))

    if isinstance(text, list):
        return [_check(t) for t in text]
    return _check(text)


@overload
def is_symbol_noise(text: str) -> bool: ...
@overload
def is_symbol_noise(text: list[str]) -> list[bool]: ...
def is_symbol_noise(text: str | list[str]) -> bool | list[bool]:
    def _check(t: str) -> bool:
        s = t.strip()
        if not s:
            return True
        alpha_ratio = sum(c.isalpha() for c in s) / len(s)
        return alpha_ratio < 0.4 and len(s) < 30

    if isinstance(text, list):
        return [_check(t) for t in text]
    return _check(text)


def detect_running_headers(
    texts: list[str],
    min_count: int = 3,
    threshold: float = 0.05,
) -> set[str]:
    norm_to_original: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for t in texts:
        norm = _MULTI_SPACE.sub(" ", t.strip().lower())
        norm_to_original.setdefault(norm, t)
        counts[norm] += 1

    cutoff = max(min_count, int(len(texts) * threshold))
    return {norm_to_original[norm] for norm, n in counts.items() if n >= cutoff}


def _pdf_metadata_title(pdf_path: str) -> str:
    try:
        reader = pypdf.PdfReader(pdf_path)
        meta = reader.metadata
        if meta is None:
            return ""
        return (meta.title or "").strip()
    except Exception:
        return ""


def _first_page_title(result: ParseResult) -> str:
    if not result.pages:
        return ""
    for para in result.pages[0].text.split("\n\n"):
        text = " ".join(para.split())
        if len(text) > 10 and len(text) < 200 and sum(c.isalpha() for c in text) / len(text) > 0.5:
            return text
    return ""


def _build_metadata(pdf_path: str, result: ParseResult, title: str | None = None) -> DocumentMetadata:
    p = Path(pdf_path)
    stat = os.stat(pdf_path)

    def _iso(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=UTC).isoformat()

    resolved_title = title or _pdf_metadata_title(pdf_path) or _first_page_title(result) or p.stem
    content_hash = hashlib.sha256(p.read_bytes()).hexdigest()

    return DocumentMetadata(
        content_hash=content_hash,
        title=resolved_title,
        filename=p.name,
        file_type=p.suffix.lstrip(".").lower(),
        file_size=stat.st_size,
        num_pages=result.num_pages,
        created_at=_iso(stat.st_ctime),
        modified_at=_iso(stat.st_mtime),
    )


def _column_boundary(items: list[TextItem]) -> float | None:
    xs = sorted(item.x for item in items if item.text.strip())
    if len(xs) < 6:
        return None

    x_min, x_max = xs[0], xs[-1]
    x_range = x_max - x_min
    if x_range < 10:
        return None

    mid_lo = x_min + x_range * 0.25
    mid_hi = x_min + x_range * 0.75

    best_gap = 0.0
    boundary: float | None = None
    for a, b in itertools.pairwise(xs):
        if b < mid_lo or a > mid_hi:
            continue
        gap = b - a
        if gap > best_gap and gap > x_range * 0.15:
            best_gap = gap
            boundary = (a + b) / 2

    return boundary


def _page_to_text(page: ParsedPage) -> str:
    items = [i for i in page.text_items if i.text.strip()]
    if not items:
        return ""

    boundary = _column_boundary(items)
    if boundary is not None:
        groups = [
            sorted((i for i in items if i.x < boundary), key=lambda i: (i.y, i.x)),
            sorted((i for i in items if i.x >= boundary), key=lambda i: (i.y, i.x)),
        ]
    else:
        groups = [sorted(items, key=lambda i: (i.y, i.x))]

    column_texts: list[str] = []
    for group in groups:
        lines: list[str] = []
        current_line: list[str] = []
        prev_y: float | None = None

        for item in group:
            y = item.y
            if prev_y is None or y - prev_y < 0.8:
                current_line.append(item.text.strip())
            else:
                if current_line:
                    lines.append(" ".join(t for t in current_line if t))
                if y - prev_y > 1.5:
                    lines.append("")
                current_line = [item.text.strip()]
            prev_y = y

        if current_line:
            lines.append(" ".join(t for t in current_line if t))
        column_texts.append("\n".join(lines))

    return "\n\n".join(column_texts)


def _collect_heading_texts(result: ParseResult) -> dict[int, set[str]]:
    all_sizes = [
        item.font_size
        for page in result.pages
        for item in page.text_items
        if item.font_size is not None
    ]
    median_size = statistics.median(all_sizes) if all_sizes else 0.0
    size_threshold = median_size * 1.5

    heading_pattern = re.compile(
        r"^(\d+\.)+\s+\w"
        r"|^[A-Z][A-Z\s]{4,}$"
        r"|^(Chapter|Section|CHAPTER|SECTION)\b",
        re.MULTILINE,
    )

    per_page: dict[int, set[str]] = {}
    for page in result.pages:
        headings: set[str] = set()
        for item in page.text_items:
            stripped = item.text.strip()
            if len(stripped) < 3 or len(stripped) >= 120:
                continue
            is_large = item.font_size is not None and item.font_size >= size_threshold and len(stripped) >= 5
            is_pattern = bool(heading_pattern.match(stripped))
            if is_large or is_pattern:
                headings.add(stripped)
        per_page[page.page_num] = headings
    return per_page


def _flush_chunk(
    chunk_lines: list[str],
    page_num: int,
    line_start: int,
    page_headings: set[str],
    current_chapter: str | None,
    chunks: list[ParsedChunk],
) -> str | None:
    text = "\n".join(chunk_lines).strip()
    if not text:
        return current_chapter
    first_line = chunk_lines[0].strip()
    if first_line in page_headings:
        return first_line
    chunks.append(ParsedChunk(text=text, page=page_num, chapter=current_chapter, line_start=line_start))
    return current_chapter


def parse_document(
    pdf_path: str | Path,
    *,
    clean: bool = True,
    title: str | None = None,
) -> ParsedDocument:
    """Parse a PDF into a structured ParsedDocument.

    Args:
        pdf_path: path to the PDF file.
        clean: strip noise (page numbers, dot leaders, running headers).
        title: override the title instead of extracting it from PDF metadata.
    """
    path = str(pdf_path)
    result = LiteParse(quiet=True).parse(path)
    metadata = _build_metadata(path, result, title=title)
    heading_texts = _collect_heading_texts(result)

    raw: list[ParsedChunk] = []
    current_chapter: str | None = None

    for page in result.pages:
        page_headings = heading_texts.get(page.page_num, set())
        lines = _page_to_text(page).split("\n")
        chunk_lines: list[str] = []
        chunk_line_start = 0

        for i, line in enumerate(lines):
            if line.strip() == "":
                if chunk_lines:
                    current_chapter = _flush_chunk(
                        chunk_lines, page.page_num, chunk_line_start,
                        page_headings, current_chapter, raw,
                    )
                    chunk_lines = []
                    chunk_line_start = i + 1
            else:
                if not chunk_lines:
                    chunk_line_start = i
                chunk_lines.append(line)

        if chunk_lines:
            current_chapter = _flush_chunk(
                chunk_lines, page.page_num, chunk_line_start,
                page_headings, current_chapter, raw,
            )

    if not clean:
        return ParsedDocument(metadata=metadata, chunks=raw)

    headers = detect_running_headers([c.text for c in raw])

    chunks: list[ParsedChunk] = []
    for chunk in raw:
        if is_page_number(chunk.text) or is_symbol_noise(chunk.text):
            continue
        if chunk.text in headers:
            continue
        text = remove_dot_leaders(clean_whitespace(chunk.text))
        if text:
            chunks.append(ParsedChunk(
                text=text, page=chunk.page,
                chapter=chunk.chapter, line_start=chunk.line_start,
            ))

    return ParsedDocument(metadata=metadata, chunks=chunks)
