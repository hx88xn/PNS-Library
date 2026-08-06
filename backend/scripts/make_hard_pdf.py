#!/usr/bin/env python
"""Generate a PDF that behaves like a real classification-society rulebook.

The synthetic sample documents parse cleanly because I wrote them to. Real
rules documents do not: they are two-column, tabular, and carry running
headers and footers on every page. This produces those conditions so parser
changes can be measured rather than guessed at.

    python scripts/make_hard_pdf.py [--out hard-sample.pdf] [--pages 40]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import fitz

PAGE_W, PAGE_H = 595, 842          # A4 points
MARGIN = 54
COL_GAP = 18
HEADER_Y = 34
FOOTER_Y = PAGE_H - 30

SECTIONS = [
    ("1", "General Requirements"),
    ("2", "Hull Structural Design"),
    ("3", "Materials and Welding"),
    ("4", "Machinery Installations"),
    ("5", "Electrical Installations"),
    ("6", "Fire Protection"),
]

BODY = (
    "The scantlings of the structural members shall be determined in accordance "
    "with the requirements of this Section, taking into account the design loads "
    "specified in Chapter 3 and the material factor k defined in 2.1.4. Where the "
    "arrangement differs from that assumed, direct calculation shall be submitted "
    "for approval. The thickness of plating shall in no case be less than the "
    "minimum values given in Table {t}. Corrosion additions shall be applied in "
    "accordance with 2.6 and are additional to the calculated net thickness. "
)

TABLES = [
    (
        "Minimum plating thickness",
        ["Location", "t_min (mm)", "Grade", "Remarks"],
        [
            ["Keel", "9.0", "AH36", "Amidships 0.4L"],
            ["Bottom shell", "8.0", "AH36", "Outside 0.4L: 7.0"],
            ["Side shell", "7.5", "AH32", "Above DWL: 6.5"],
            ["Strength deck", "8.5", "AH36", "Within line of hatch"],
            ["Tank boundary", "7.0", "A", "Oil-tight"],
        ],
    ),
    (
        "Section modulus factors",
        ["Frame spacing (mm)", "Factor k1", "Factor k2", "Applies to"],
        [
            ["600", "1.00", "0.85", "Machinery spaces"],
            ["700", "1.08", "0.91", "Cargo spaces"],
            ["750", "1.13", "0.95", "Fore peak"],
            ["800", "1.19", "1.00", "Aft peak"],
        ],
    ),
]


def draw_header_footer(page, section_no, section_title, page_no) -> None:
    """Running header and footer, repeated on every page — the kind of text that
    pollutes every chunk if the parser does not strip it."""
    page.insert_text((MARGIN, HEADER_Y), "TURK LLOYD — RULES FOR CLASSIFICATION",
                     fontsize=7.5, fontname="helv", color=(0.35, 0.35, 0.35))
    page.insert_text((PAGE_W - MARGIN - 120, HEADER_Y),
                     f"Section {section_no} — {section_title}"[:40],
                     fontsize=7.5, fontname="helv", color=(0.35, 0.35, 0.35))
    page.draw_line((MARGIN, HEADER_Y + 6), (PAGE_W - MARGIN, HEADER_Y + 6),
                   color=(0.7, 0.7, 0.7), width=0.5)
    page.insert_text((MARGIN, FOOTER_Y), "2016 Edition", fontsize=7.5,
                     fontname="helv", color=(0.35, 0.35, 0.35))
    page.insert_text((PAGE_W / 2 - 10, FOOTER_Y), str(page_no), fontsize=8,
                     fontname="helv", color=(0.35, 0.35, 0.35))


def draw_table(page, x, y, width, title, headers, rows) -> float:
    """A real ruled table. Rows must survive as rows, not become loose words."""
    row_h = 15
    col_w = width / len(headers)

    page.insert_text((x, y), title, fontsize=8.5, fontname="hebo")
    y += 10

    top = y
    for r, cells in enumerate([headers, *rows]):
        for c, cell in enumerate(cells):
            page.insert_text((x + c * col_w + 3, y + 10), str(cell),
                             fontsize=7.5,
                             fontname="hebo" if r == 0 else "helv")
        y += row_h

    # Ruling — find_tables() keys off these lines.
    for i in range(len(rows) + 2):
        page.draw_line((x, top + i * row_h), (x + width, top + i * row_h),
                       color=(0.4, 0.4, 0.4), width=0.4)
    for c in range(len(headers) + 1):
        page.draw_line((x + c * col_w, top), (x + c * col_w, y),
                       color=(0.4, 0.4, 0.4), width=0.4)

    return y + 12


def build(out: Path, pages: int) -> None:
    doc = fitz.open()
    col_w = (PAGE_W - 2 * MARGIN - COL_GAP) / 2
    clause = 0

    for page_no in range(1, pages + 1):
        section_no, section_title = SECTIONS[(page_no - 1) * len(SECTIONS) // pages]
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        draw_header_footer(page, section_no, section_title, page_no)

        y_start = HEADER_Y + 28

        # Section heading, once per section
        if page_no == 1 or SECTIONS[(page_no - 2) * len(SECTIONS) // pages][0] != section_no:
            page.insert_text((MARGIN, y_start), f"SECTION {section_no}",
                             fontsize=14, fontname="hebo")
            page.insert_text((MARGIN, y_start + 18), section_title,
                             fontsize=12, fontname="hebo")
            y_start += 40

        # Every third page carries a table spanning both columns.
        if page_no % 3 == 0:
            title, headers, rows = TABLES[page_no // 3 % len(TABLES)]
            y_start = draw_table(page, MARGIN, y_start,
                                 PAGE_W - 2 * MARGIN, title, headers, rows)

        # Two columns of numbered clauses.
        for col in range(2):
            x = MARGIN + col * (col_w + COL_GAP)
            y = y_start
            while y < FOOTER_Y - 60:
                clause += 1
                label = f"{section_no}.{clause % 9 + 1}.{clause % 5 + 1}"
                page.insert_text((x, y), label, fontsize=8.5, fontname="hebo")
                y += 11
                text = BODY.format(t=(clause % 4) + 1)
                used = page.insert_textbox(
                    fitz.Rect(x, y, x + col_w, FOOTER_Y - 40),
                    text, fontsize=8, fontname="helv", align=3,
                )
                if used < 0:            # did not fit
                    break
                y += (len(text) / (col_w / 3.6)) * 9 + 10

    doc.save(str(out))
    doc.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).parent.parent / "hard-sample.pdf")
    parser.add_argument("--pages", type=int, default=40)
    args = parser.parse_args()

    build(args.out, args.pages)
    doc = fitz.open(args.out)
    chars = sum(len(p.get_text()) for p in doc)
    print(f"Wrote {args.out}")
    print(f"  {doc.page_count} pages, {chars:,} characters of text")
    doc.close()


if __name__ == "__main__":
    main()
