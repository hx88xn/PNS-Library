"""Digital PDFs, via PyMuPDF.

Ingestion quality is the ceiling on the whole system, and it fails silently: a
parser that mangles a document produces a working search over a mangled
document. Four things go wrong in real technical PDFs, and each is handled
explicitly below.

**Running headers and footers.** A rulebook repeats "TURK LLOYD — RULES FOR
CLASSIFICATION" and a page number on all 1,100 pages. Left in, that text lands
in every chunk, dominates BM25, and gets mistaken for a section heading —
measured on a synthetic rulebook, the detected section was "2016 Edition", the
footer. They are found by repetition at a stable vertical position and dropped.

**Tables.** Rules documents carry their numbers in tables. Read as flowing
text, a row becomes loose words and the association between "Bottom shell" and
"8.0 mm" is destroyed. Tables are extracted separately, rendered row-wise, and
their regions excluded from the body text so nothing is counted twice.

**Columns.** Two-column layouts interleave if lines are read by vertical
position alone, producing sentences spliced from both columns. Lines are
clustered into columns by horizontal position and read column by column.

**Clause numbering.** "2.6.1" at the start of a line is a section reference in
this kind of document, but a bare figure elsewhere is not. Headings are decided
on numbering *and* typography together.

Page numbers survive all of it: a citation that says p.55 must be checkable
against the printed sheet.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from .base import Block, ParsedDocument, ParserError

# Section numbering as technical documents write it: "4.2", "2.6.1",
# "Part 3, Clause 12", "Annex D", "SECTION 5". A trailing capital is not
# required — clause labels frequently stand alone on their own line.
_SECTION = re.compile(
    r"^(?:"
    r"\d+(?:\.\d+){0,3}\s*[.)]?\s*(?:[A-Z]|$)"      # 4.2 Title  |  2.6.1
    r"|(?:section|part|chapter|annex|appendix|table)\s+[A-Z0-9]"
    r")",
    re.IGNORECASE,
)
_DOC_REF = re.compile(r"\b([A-Z]{2,}(?:[/-][A-Z0-9]{2,}){1,3})\b")
_REVISION = re.compile(r"\b(rev(?:ision)?\.?\s*[A-Z0-9]{1,3}|issue\s*\d+|\d{4}\s+edition)\b", re.I)

HEADER_BAND = 0.08   # top 8% of the page
FOOTER_BAND = 0.92   # bottom 8%
REPEAT_RATIO = 0.35  # text on this fraction of pages in a band is furniture
MIN_PAGES_FOR_REPEAT = 4


@dataclass
class _Line:
    text: str
    page: int
    x0: float
    y0: float
    size: float
    bold: bool


def parse(path: Path) -> ParsedDocument:
    try:
        document = fitz.open(path)
    except Exception as exc:
        raise ParserError(f"Cannot open PDF: {exc}") from exc

    try:
        tables = _extract_tables(document)
        lines = _collect_lines(document, tables)

        if not lines and not tables:
            raise ParserError(
                "No extractable text — this looks like a scanned PDF. "
                "OCR it before ingesting."
            )

        furniture = _find_furniture(lines, document.page_count)
        lines = [ln for ln in lines if _key(ln.text) not in furniture]

        body_size = _body_size(lines)
        blocks = _to_blocks(lines, tables, body_size, document.page_count)

        # Coverage check. Two steps here can drop real text: a falsely detected
        # table excludes the body under it, and furniture detection could flag
        # a genuine repeated clause. Both are silent, and a search over a
        # document missing a third of its text still looks like it works.
        #
        # Compare what we kept against what the library saw, and if too much is
        # missing, fall back to plain extraction rather than index a hole.
        raw = "".join(page.get_text() for page in document)
        kept = sum(len(b.text) for b in blocks)
        coverage = _coverage(kept, raw)

        if coverage < MIN_COVERAGE:
            blocks = _fallback_blocks(document)
            kept = sum(len(b.text) for b in blocks)
            coverage = _coverage(kept, raw)

        head = " ".join(b.text for b in blocks[:25])[:3000]
        title = (document.metadata or {}).get("title") or _first_heading(blocks)

        return ParsedDocument(
            blocks=blocks,
            title=(title or path.stem).strip() or path.stem,
            doc_ref=_first(_DOC_REF, head),
            revision=_first(_REVISION, head),
            pages=document.page_count,
            kind="text",
            coverage=coverage,
            raw_text=raw,
        )
    finally:
        document.close()


MIN_COVERAGE = 0.90
"""Below this, the layout-aware path is assumed to have gone wrong.

Losing a tenth of a document is tolerable — it is mostly the furniture we
meant to drop. Losing a third means a false table detection swallowed real
content, and a search over the remainder still looks like it works, which is
the dangerous part.
"""


def _coverage(kept: int, raw: str) -> float:
    """Fraction of the library's own text that survived our parsing.

    Whitespace is ignored on both sides: line joining changes it legitimately,
    and counting it would make the ratio meaningless.
    """
    raw_chars = len(re.sub(r"\s+", "", raw))
    if raw_chars == 0:
        return 1.0
    return min(1.0, kept / raw_chars)


def _fallback_blocks(document: fitz.Document) -> list[Block]:
    """Plain page-by-page extraction, keeping page numbers.

    No column ordering, no table structure, no furniture removal — but nothing
    dropped either. Used when the layout-aware path loses too much: degraded
    structure beats missing content, because a citation to slightly muddled
    text is checkable and a citation to text that was never indexed does not
    exist at all.
    """
    blocks: list[Block] = []
    for page_number, page in enumerate(document, start=1):
        for raw in page.get_text().split("\n"):
            text = raw.strip()
            if text:
                blocks.append(Block(text=text, page=page_number, section=""))
    return blocks


# ── Tables ───────────────────────────────────────────────────────────────


def _extract_tables(document: fitz.Document) -> dict[int, list[tuple[fitz.Rect, str]]]:
    """Tables per page, as (region, rendered text).

    Rendered row-wise with a separator so a row survives chunking intact —
    "Bottom shell | 8.0 | AH36" keeps the number attached to the thing it
    describes, which flowing text does not.
    """
    found: dict[int, list[tuple[fitz.Rect, str]]] = defaultdict(list)

    for page_number, page in enumerate(document, start=1):
        try:
            finder = page.find_tables()
        except Exception:
            continue  # table detection is best-effort; never fail a document for it

        for table in getattr(finder, "tables", []):
            try:
                rows = table.extract()
            except Exception:
                continue
            if not rows or len(rows) < 2:
                continue

            rendered = []
            for row in rows:
                cells = [str(c).strip().replace("\n", " ") for c in row if c is not None]
                cells = [c for c in cells if c]
                if cells:
                    rendered.append(" | ".join(cells))

            if len(rendered) >= 2:
                found[page_number].append((fitz.Rect(table.bbox), "\n".join(rendered)))

    return found


# ── Lines ────────────────────────────────────────────────────────────────


def _collect_lines(
    document: fitz.Document, tables: dict[int, list[tuple[fitz.Rect, str]]]
) -> list[_Line]:
    """Every text line outside a table region, with position and typography."""
    lines: list[_Line] = []

    for page_number, page in enumerate(document, start=1):
        table_rects = [rect for rect, _ in tables.get(page_number, [])]
        layout = page.get_text("dict")

        for block in layout.get("blocks", []):
            if block.get("type") != 0:  # 0 = text
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(s.get("text", "") for s in spans).strip()
                if not text:
                    continue

                bbox = fitz.Rect(line["bbox"])
                # Skip anything inside a table — already captured, and counting
                # it twice would inflate the index with duplicate text.
                if any(rect.intersects(bbox) for rect in table_rects):
                    continue

                lines.append(
                    _Line(
                        text=text,
                        page=page_number,
                        x0=bbox.x0,
                        y0=bbox.y0,
                        size=round(max((s.get("size", 0.0) for s in spans), default=0.0), 1),
                        bold=any("bold" in s.get("font", "").lower() for s in spans),
                    )
                )

    return lines


def _key(text: str) -> str:
    """Normalised form for repetition detection: page numbers vary, the rest
    of a running header does not."""
    return re.sub(r"\d+", "#", text.strip().lower())[:80]


def _find_furniture(lines: list[_Line], page_count: int) -> set[str]:
    """Text repeated near the top or bottom of many pages — running headers,
    footers, page numbers, edition marks."""
    if page_count < MIN_PAGES_FOR_REPEAT:
        return set()

    page_heights: dict[int, float] = {}
    for line in lines:
        page_heights[line.page] = max(page_heights.get(line.page, 0.0), line.y0)

    seen: dict[str, set[int]] = defaultdict(set)
    for line in lines:
        height = page_heights.get(line.page, 842.0) or 842.0
        position = line.y0 / height
        if position <= HEADER_BAND or position >= FOOTER_BAND:
            seen[_key(line.text)].add(line.page)

    threshold = max(MIN_PAGES_FOR_REPEAT, int(page_count * REPEAT_RATIO))
    return {key for key, pages in seen.items() if len(pages) >= threshold}


# ── Reading order ────────────────────────────────────────────────────────


def _columns(lines: list[_Line], page_width: float = 595.0) -> list[list[_Line]]:
    """Split a page's lines into columns by horizontal position.

    Read by vertical position alone, a two-column page interleaves and produces
    sentences spliced from both columns — text that is individually valid and
    collectively meaningless, which is worse than dropping it.
    """
    if len(lines) < 6:
        return [sorted(lines, key=lambda ln: (ln.y0, ln.x0))]

    xs = sorted(ln.x0 for ln in lines)
    midpoint = page_width / 2

    left = [x for x in xs if x < midpoint]
    right = [x for x in xs if x >= midpoint]

    # Two columns only when both sides are substantially populated and there is
    # a clear gap between them. Otherwise treat the page as one flow.
    if len(left) < 3 or len(right) < 3:
        return [sorted(lines, key=lambda ln: (ln.y0, ln.x0))]

    gap = min(right) - max(left)
    if gap < 20:
        return [sorted(lines, key=lambda ln: (ln.y0, ln.x0))]

    split = (max(left) + min(right)) / 2
    return [
        sorted([ln for ln in lines if ln.x0 < split], key=lambda ln: (ln.y0, ln.x0)),
        sorted([ln for ln in lines if ln.x0 >= split], key=lambda ln: (ln.y0, ln.x0)),
    ]


def _body_size(lines: list[_Line]) -> float:
    """Modal font size — whatever most of the document is set in."""
    sizes = [ln.size for ln in lines if ln.size > 0]
    if not sizes:
        return 0.0
    try:
        return statistics.mode(sizes)
    except statistics.StatisticsError:
        return statistics.median(sizes)


def _to_blocks(
    lines: list[_Line],
    tables: dict[int, list[tuple[fitz.Rect, str]]],
    body_size: float,
    page_count: int,
) -> list[Block]:
    by_page: dict[int, list[_Line]] = defaultdict(list)
    for line in lines:
        by_page[line.page].append(line)

    blocks: list[Block] = []
    current_section = ""

    for page in range(1, page_count + 1):
        for _, rendered in tables.get(page, []):
            blocks.append(
                Block(text=rendered, page=page, section=current_section or "Table")
            )

        for column in _columns(by_page.get(page, [])):
            for line in column:
                if _is_heading(line, body_size):
                    current_section = line.text.strip()
                    blocks.append(
                        Block(text=line.text, page=page,
                              section=current_section, heading_level=1)
                    )
                else:
                    blocks.append(Block(text=line.text, page=page, section=current_section))

    return blocks


def _is_heading(line: _Line, body_size: float) -> bool:
    text = line.text.strip()

    if len(text) > 120:
        return False

    # Sentence-shaped text is body copy however it is numbered — a wrapped line
    # beginning "0.50 has proven satisfactory for…" must not become a section.
    if text.endswith((".", ",", ";", ":")) and len(text.split()) > 6:
        return False

    larger = body_size > 0 and line.size >= body_size * 1.15
    numbered = bool(_SECTION.match(text))

    if larger and (numbered or line.bold or text.isupper() or len(text.split()) <= 10):
        return True

    # Same size as the body: require numbering plus a typographic signal.
    return numbered and (line.bold or text.isupper()) and len(text) < 90


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1).strip() if match else None


# "SECTION 1", "Part 3", "Chapter 2" are position markers, not titles. Taking
# one as the document title puts "SECTION 1" in the library table where the
# name of the document should be.
_BARE_LABEL = re.compile(
    r"^(?:section|part|chapter|annex|appendix|table|figure)?\s*[\dIVXivx]+(?:\.\d+)*\s*[.)]?$",
    re.IGNORECASE,
)


def _first_heading(blocks: list[Block]) -> str | None:
    for block in blocks:
        text = block.text.strip()
        if not block.heading_level or len(text) <= 4:
            continue
        if _BARE_LABEL.match(text):
            continue
        return text
    return None
