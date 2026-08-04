"""Digital PDFs, via PyMuPDF.

Page numbers are preserved exactly, because a citation that says p.55 must
survive being checked against the printed sheet.

Headings are detected by font size relative to the document's body text rather
than by a fixed threshold — design documents are typeset inconsistently, and an
absolute cutoff misclassifies whole documents one way or the other.
"""

from __future__ import annotations

import re
import statistics
from pathlib import Path

import fitz  # PyMuPDF

from .base import Block, ParsedDocument, ParserError

# Section numbering as it appears in the office's documents: "4.2 Righting arm
# curve", "Part 3, Clause 12", "Annex D".
#
# The number must be followed by a capitalised word. Without that guard a
# wrapped body line such as "0.50 has proven satisfactory for a design speed of
# 28 knots." matches, and the section metadata on every following chunk becomes
# a fragment of a sentence. Technical prose is full of lines that begin with a
# figure, so this case is the rule rather than the exception.
_SECTION = re.compile(
    r"^(?:\d+(?:\.\d+){0,3}\s+[A-Z]|part\s+\d+|annex\s+[a-z]\b|appendix\s+[a-z]\b)",
    re.IGNORECASE,
)
_DOC_REF = re.compile(r"\b([A-Z]{2,}(?:[/-][A-Z0-9]{2,}){1,3})\b")
_REVISION = re.compile(r"\b(rev(?:ision)?\.?\s*[A-Z0-9]{1,3}|issue\s*\d+)\b", re.IGNORECASE)


def parse(path: Path) -> ParsedDocument:
    try:
        document = fitz.open(path)
    except Exception as exc:
        raise ParserError(f"Cannot open PDF: {exc}") from exc

    try:
        spans = _collect_spans(document)
        body_size = _body_size(spans)
        blocks = _to_blocks(spans, body_size)

        head = " ".join(block.text for block in blocks[:12])[:2000]
        doc_ref = _first(_DOC_REF, head)
        revision = _first(_REVISION, head)
        title = (document.metadata or {}).get("title") or _first_heading(blocks)

        return ParsedDocument(
            blocks=blocks,
            title=(title or path.stem).strip() or path.stem,
            doc_ref=doc_ref,
            revision=revision,
            pages=document.page_count,
            kind="text",
        )
    finally:
        document.close()


def _collect_spans(document: fitz.Document) -> list[tuple[int, float, bool, str]]:
    """(page, font size, bold, text) for every line, in reading order."""
    spans: list[tuple[int, float, bool, str]] = []

    for page_number, page in enumerate(document, start=1):
        layout = page.get_text("dict")
        for block in layout.get("blocks", []):
            if block.get("type") != 0:  # 0 = text; ignore images
                continue
            for line in block.get("lines", []):
                pieces = line.get("spans", [])
                text = "".join(piece.get("text", "") for piece in pieces).strip()
                if not text:
                    continue
                size = max((piece.get("size", 0.0) for piece in pieces), default=0.0)
                bold = any("bold" in piece.get("font", "").lower() for piece in pieces)
                spans.append((page_number, round(size, 1), bold, text))

    return spans


def _body_size(spans: list[tuple[int, float, bool, str]]) -> float:
    """Modal font size — whatever most of the document is set in."""
    sizes = [size for _, size, _, _ in spans if size > 0]
    if not sizes:
        return 0.0
    try:
        return statistics.mode(sizes)
    except statistics.StatisticsError:
        return statistics.median(sizes)


def _to_blocks(
    spans: list[tuple[int, float, bool, str]], body_size: float
) -> list[Block]:
    blocks: list[Block] = []
    current_section = ""

    for page, size, bold, text in spans:
        is_heading = _looks_like_heading(text, size, bold, body_size)

        if is_heading:
            current_section = text.strip()
            blocks.append(
                Block(text=text, page=page, section=current_section, heading_level=1)
            )
        else:
            blocks.append(Block(text=text, page=page, section=current_section))

    return blocks


def _looks_like_heading(text: str, size: float, bold: bool, body_size: float) -> bool:
    stripped = text.strip()

    if len(stripped) > 120:  # headings are short
        return False

    # Set larger than the body: that is a heading regardless of wording.
    if body_size and size >= body_size * 1.15:
        return True

    # Below that, only trust the numbering pattern — and not on anything
    # punctuated like a sentence.
    if stripped.endswith((".", ",", ";", ":")) and len(stripped.split()) > 6:
        return False

    return bool(_SECTION.match(stripped)) and (bold or len(stripped) < 80)


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def _first_heading(blocks: list[Block]) -> str | None:
    for block in blocks:
        if block.heading_level and len(block.text) > 4:
            return block.text
    return None
