#!/usr/bin/env python
"""Measure what the parser and chunker actually keep.

Ingestion quality is the ceiling on the whole system, and it is invisible: a
parser that silently drops half a document produces a working search over half
a document. This reports the loss so it can be seen.

    python scripts/ingest_report.py <file.pdf> [more...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdas.core.chunking import chunk_blocks  # noqa: E402
from pdas.core.ingest import parse_file  # noqa: E402


def raw_text_len(path: Path) -> tuple[int, int]:
    """Characters and pages according to the library, before our parsing."""
    if path.suffix.lower() != ".pdf":
        return 0, 0
    import fitz

    doc = fitz.open(path)
    try:
        return sum(len(p.get_text()) for p in doc), doc.page_count
    finally:
        doc.close()


def report(path: Path) -> None:
    raw_chars, raw_pages = raw_text_len(path)
    parsed = parse_file(path)
    chunks = chunk_blocks(parsed.blocks, kind=parsed.kind)

    block_chars = sum(len(b.text) for b in parsed.blocks)
    chunk_chars = sum(len(c.text) for c in chunks)

    print(f"\n{path.name}")
    print(f"  format          {parsed.kind}   doc_ref={parsed.doc_ref}   rev={parsed.revision}")
    if raw_pages:
        print(f"  pages           {raw_pages}")
        print(f"  raw text        {raw_chars:,} chars  (what the PDF library sees)")
        pct = 100 * block_chars / raw_chars if raw_chars else 0
        print(f"  after parsing   {block_chars:,} chars in {len(parsed.blocks):,} blocks  ({pct:.1f}% kept)")
    else:
        print(f"  after parsing   {block_chars:,} chars in {len(parsed.blocks):,} blocks")

    pct_chunk = 100 * chunk_chars / block_chars if block_chars else 0
    print(f"  after chunking  {chunk_chars:,} chars in {len(chunks):,} chunks  ({pct_chunk:.1f}% of blocks)")

    if raw_pages:
        pages_seen = {b.page for b in parsed.blocks if b.page}
        missing = sorted(set(range(1, raw_pages + 1)) - pages_seen)
        print(f"  pages with text {len(pages_seen)}/{raw_pages}"
              + (f"   MISSING: {missing[:12]}{'…' if len(missing) > 12 else ''}" if missing else ""))
        print(f"  chunks/page     {len(chunks) / raw_pages:.1f}")

    sizes = sorted(len(c.text) for c in chunks)
    if sizes:
        tiny = sum(1 for s in sizes if s < 120)
        print(f"  chunk size      min={sizes[0]}  median={sizes[len(sizes)//2]}  max={sizes[-1]}")
        if tiny:
            print(f"  fragments       {tiny} chunks under 120 chars ({100*tiny/len(sizes):.0f}%)")

    sections = [c.section for c in chunks if c.section]
    uniq = sorted(set(sections))
    print(f"  sections        {len(uniq)} distinct")
    for s in uniq[:6]:
        print(f"                    {s[:64]}")
    if len(uniq) > 6:
        print(f"                    … and {len(uniq)-6} more")

    print("\n  --- first chunk ---")
    if chunks:
        print("  " + chunks[0].text[:300].replace("\n", "\n  "))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", type=Path)
    args = ap.parse_args()
    for path in args.paths:
        try:
            report(path)
        except Exception as exc:
            print(f"\n{path.name}\n  FAILED: {exc}")


if __name__ == "__main__":
    main()
