"""CAD drawings (DXF), via ezdxf.

A drawing is not prose. Chunking its annotations like body text produces noise:
disconnected dimension callouts and part labels that embed to nothing and match
everything.

So a drawing is indexed as a **record**: title block first (drawing number,
sheet title, revision, scale, drawn/checked), then the annotation text grouped
by layer. What a naval architect searches for is "which drawing covers the
transverse bulkhead at frame 62" — a metadata question.

DWG cannot be read directly; no open library parses it. Convert to DXF or plot
to PDF before ingestion.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .base import Block, ParsedDocument, ParserError

if TYPE_CHECKING:
    from ezdxf.document import Drawing

# Title block attributes vary by template, so match on common tag names rather
# than assuming one house standard.
TITLE_TAGS = {
    "drawing_no": {"DWG_NO", "DRAWING_NO", "DWGNO", "NUMBER", "DRAWING_NUMBER"},
    "title": {"TITLE", "DWG_TITLE", "SHEET_TITLE", "DESCRIPTION"},
    "revision": {"REV", "REVISION", "REV_NO", "ISSUE"},
    "scale": {"SCALE"},
    "sheet": {"SHEET", "SHEET_NO"},
    "drawn_by": {"DRAWN", "DRAWN_BY", "AUTHOR"},
    "checked_by": {"CHECKED", "CHECKED_BY", "APPROVED"},
}

MAX_ANNOTATIONS = 400
"""Past this, a drawing's text is dimension noise rather than description."""


def parse(path: Path) -> ParsedDocument:
    # Imported here, not at module scope. ezdxf reads a user config file at
    # import time, which raises PermissionError under a hardened systemd
    # sandbox — and at module scope that takes down the entire API before it
    # starts. A parser for one format should only be able to fail that format.
    import ezdxf

    try:
        document = ezdxf.readfile(str(path))
    except IOError as exc:
        raise ParserError(f"Cannot open DXF: {exc}") from exc
    except ezdxf.DXFStructureError as exc:
        raise ParserError(f"Invalid or corrupt DXF: {exc}") from exc

    fields = _title_block(document)
    annotations = _annotations(document)

    blocks: list[Block] = []

    summary = "; ".join(f"{key.replace('_', ' ')}: {value}" for key, value in fields.items())
    if summary:
        blocks.append(Block(text=f"Drawing record — {summary}", section="Title block"))

    if annotations:
        # Group by layer: layer names in a ship drawing are meaningful
        # ("STRUCTURE", "PIPING", "NOTES") and give the annotations context.
        for layer, texts in annotations.items():
            joined = "; ".join(texts)
            blocks.append(Block(text=f"{layer}: {joined}", section=f"Layer {layer}"))

    if not blocks:
        raise ParserError("Drawing contains no title block or annotation text")

    return ParsedDocument(
        blocks=blocks,
        title=fields.get("title") or path.stem,
        doc_ref=fields.get("drawing_no"),
        revision=fields.get("revision"),
        kind="drawing",
    )


def _title_block(document: Drawing) -> dict[str, str]:
    """Pull attributes off block INSERTs — where title blocks live."""
    found: dict[str, str] = {}

    for insert in document.modelspace().query("INSERT"):
        for attribute in getattr(insert, "attribs", []):
            tag = (attribute.dxf.tag or "").strip().upper()
            value = (attribute.dxf.text or "").strip()
            if not value:
                continue
            for field, aliases in TITLE_TAGS.items():
                if tag in aliases and field not in found:
                    found[field] = value

    return found


def _annotations(document: Drawing) -> dict[str, list[str]]:
    by_layer: dict[str, list[str]] = {}
    seen: set[str] = set()
    total = 0

    for entity in document.modelspace().query("TEXT MTEXT"):
        if total >= MAX_ANNOTATIONS:
            break

        raw = entity.plain_text() if entity.dxftype() == "MTEXT" else entity.dxf.text
        text = (raw or "").strip()
        # Skip bare dimensions and single glyphs: they carry no retrievable meaning.
        if len(text) < 3 or text in seen:
            continue

        seen.add(text)
        layer = (entity.dxf.layer or "0").strip() or "0"
        by_layer.setdefault(layer, []).append(text)
        total += 1

    return by_layer
