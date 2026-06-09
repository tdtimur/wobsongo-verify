"""
PDF parser CLI — thin wrapper over wobsongo.adapters.pdf_parser.

Usage:
  uv run python parser.py <pdf_path> [--output FILE] [--no-clean]

Outputs a preview to stdout. Use --output to write .json or .csv.
"""

import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from liteparse import LiteParse

from wobsongo.adapters.pdf_parser import parse_document

if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(description="Parse a PDF into structured chunks.")
    arg_parser.add_argument("pdf_path", help="Path to the PDF file")
    arg_parser.add_argument("--output", "-o", help="Output file (.json or .csv); omit to print a preview")
    arg_parser.add_argument("--no-clean", action="store_true", help="Skip noise filtering and text cleaning")
    args = arg_parser.parse_args()

    # Write raw text (kept for compatibility)
    raw_result = LiteParse(quiet=True).parse(args.pdf_path)
    with open("parsed_output.txt", "w") as f:
        f.write(raw_result.text)

    doc = parse_document(args.pdf_path, clean=not args.no_clean)
    print(f"Title:  {doc.metadata.title}")
    print(f"Pages:  {doc.metadata.num_pages}")
    print(f"Chunks: {len(doc.chunks)}")

    if args.output:
        if args.output.endswith(".csv"):
            with open(args.output, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=["page", "chapter", "line_start", "text"])
                writer.writeheader()
                writer.writerows(asdict(c) for c in doc.chunks)
        else:
            with open(args.output, "w", encoding="utf-8") as fh:
                json.dump(asdict(doc), fh, ensure_ascii=False, indent=2)
        print(f"Written to {args.output}")
    else:
        print()
        for chunk in doc.chunks[:10]:
            chapter_label = chunk.chapter or "(none)"
            print(f"[page={chunk.page}, line={chunk.line_start}, chapter={chapter_label!r}]")
            preview = chunk.text[:120].replace("\n", " ")
            print(f"  {preview}")
            print()
